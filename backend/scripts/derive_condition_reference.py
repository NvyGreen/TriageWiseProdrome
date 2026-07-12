"""
derive_condition_reference.py

Derives per-condition emergency-department admission rates from the raw
NHAMCS 2022 ED public-use file (Stata .dta) and emits the seed rows for the
`condition_reference` table.

WHY THIS EXISTS
---------------
The admit rates in `condition_reference` (e.g. chest pain 13.7%) are not
hand-typed — they are computed here from the real NHAMCS microdata so they are
reproducible and auditable. Re-running this script against the same .dta
reproduces the same numbers.

TWO KINDS OF ROWS
-----------------
- "complaint" rows  -> matched at intake via the patient's chief_complaint
                       (mapped through NHAMCS Reason-for-Visit / RFV codes).
- "diagnosis" rows  -> context-only, NOT known at intake; derived via ICD-10
                       diagnosis prefixes (DIAG1-3 / hospital discharge dx).
                       Cited by a complaint row's context_condition, never
                       matched directly.

ADMIT FLAG
----------
`ADMITHOS` (0/1) = admitted to this hospital. Overall NHAMCS 2022 baseline
admit rate is ~13.2%, which this script prints as a sanity check.

USAGE
-----
    python scripts/derive_condition_reference.py \
        --dta raw_data/ed2022-stata.dta \
        --out reference_data/condition_reference.csv

NOTE ON DATA HANDLING
---------------------
The raw .dta is public-use (NHAMCS), but keep large/raw data out of git
(raw_data/ is gitignored). Only the derived CSV (aggregate rates) in
reference_data/ and this script are committed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Configuration: complaint groups mapped to NHAMCS Reason-for-Visit (RFV) codes.
# A visit counts for a group if ANY of RFV1-RFV3 falls in the group's code set.
# These code sets were validated against top RFV frequencies so each group
# catches a correctly-sized population.
# ---------------------------------------------------------------------------
RFV_COLS = ["RFV1", "RFV2", "RFV3"]

COMPLAINT_GROUPS: dict[str, dict] = {
    "chest_pain": {
        "label": "Chest pain (all causes)",
        "rfv_codes": [10500, 10501, 10502, 10503, 10550, 10551, 10552],
    },
    "stroke_symptoms": {
        "label": "Stroke / TIA (FAST-positive)",
        "rfv_codes": [10850, 10855, 15250, 15251, 15252, 15253,
                      15350, 15351, 15352],
    },
    "shortness_of_breath": {
        "label": "Shortness of breath",
        "rfv_codes": [14150, 14151, 14152, 14153],
    },
    "abdominal_pain": {
        "label": "Abdominal pain (all causes)",
        "rfv_codes": [15450, 15451, 15452, 15453, 15454,
                      15455, 15456, 15457, 15458, 15459],
    },
    "syncope": {
        "label": "Syncope (fainting)",
        "rfv_codes": [10250, 10251],
    },
}
# NOTE: severe_headache is intentionally NOT a condition_reference row.
# It is part of scoring_rule and the intake UI, but its NHAMCS chief-complaint
# mapping lacks a reliable admit rate (headache is high-volume / low-admit and
# scatters across RFV codes), so it is excluded here by design — leaving 11 rows
# (5 complaint + 6 diagnosis). See project notes.

# ---------------------------------------------------------------------------
# Diagnosis (context-only) groups mapped to ICD-10 prefixes.
# These are derived from hospital-discharge / ED diagnosis fields, NOT RFV,
# because they are not known at triage. They provide context for a complaint
# row (e.g. "Acute MI" contextualizes "Chest pain").
# ---------------------------------------------------------------------------
DIAG_COLS = ["DIAG1", "DIAG2", "DIAG3"]

DIAGNOSIS_GROUPS: dict[str, dict] = {
    "acute_mi": {
        "label": "Acute MI",
        "icd10_prefixes": ["I21", "I22"],
    },
    "chest_pain_cardiac": {
        "label": "Chest pain + cardiac dx",
        "icd10_prefixes": ["I20", "I21", "I22", "I23", "I24", "I25"],
    },
    "sepsis": {
        "label": "Sepsis / severe infection",
        "icd10_prefixes": ["A40", "A41", "R65"],
    },
    "pneumonia": {
        "label": "Pneumonia",
        "icd10_prefixes": ["J12", "J13", "J14", "J15", "J16", "J17", "J18"],
    },
    "preeclampsia": {
        "label": "Pre-eclampsia / eclampsia",
        "icd10_prefixes": ["O11", "O12", "O13", "O14", "O15", "O16"],
    },
    "postpartum_hemorrhage": {
        "label": "Postpartum hemorrhage",
        "icd10_prefixes": ["O72"],
    },
}

LOW_N_THRESHOLD = 30  # below this, mark the rate unreliable ("low-n")
ADMIT_FLAG = "ADMITHOS"


def _rate_for_rfv(df: pd.DataFrame, codes: list[int]) -> tuple[int, int]:
    """Return (n_visits, n_admitted) for visits whose RFV1-3 hit any code."""
    codeset = set(codes)
    mask = pd.Series(False, index=df.index)
    for col in RFV_COLS:
        if col in df.columns:
            mask |= df[col].isin(codeset)
    sub = df[mask]
    return len(sub), int(sub[ADMIT_FLAG].sum())


def _rate_for_icd(df: pd.DataFrame, prefixes: list[str]) -> tuple[int, int]:
    """Return (n_visits, n_admitted) for visits whose DIAG1-3 start with any prefix."""
    mask = pd.Series(False, index=df.index)
    for col in DIAG_COLS:
        if col in df.columns:
            col_str = df[col].astype(str).str.upper()
            for pfx in prefixes:
                mask |= col_str.str.startswith(pfx.upper())
    sub = df[mask]
    return len(sub), int(sub[ADMIT_FLAG].sum())


def _reliable(n: int) -> str:
    return "yes" if n >= LOW_N_THRESHOLD else "low-n (<30)"


def derive(dta_path: Path) -> pd.DataFrame:
    """Read the NHAMCS .dta and build the condition_reference rows."""
    df = pd.read_stata(dta_path, convert_categoricals=False)

    if ADMIT_FLAG not in df.columns:
        raise KeyError(
            f"Expected admit flag '{ADMIT_FLAG}' not found in {dta_path.name}. "
            f"Available disposition-like cols: "
            f"{[c for c in df.columns if 'ADMIT' in c.upper() or 'DISP' in c.upper()]}"
        )

    baseline = round(df[ADMIT_FLAG].mean() * 100, 1)
    print(f"NHAMCS baseline admit rate: {baseline}%  (n={len(df)})", file=sys.stderr)

    rows = []
    cid = 1

    # Complaint rows (matched at intake via complaint_key)
    for key, cfg in COMPLAINT_GROUPS.items():
        n, admitted = _rate_for_rfv(df, cfg["rfv_codes"])
        rate = round(admitted / n * 100, 1) if n else None
        rows.append({
            "condition_reference_id": cid,
            "condition": cfg["label"],
            "match_type": "complaint",
            "complaint_key": key,
            "context_condition": None,
            "icd10_prefixes": None,
            "visits": n,
            "admitted": admitted,
            "admit_rate": f"{rate}%" if rate is not None else None,
            "reliable": _reliable(n),
            "triage_note": "matches intake chief complaint",
            "source_label": "NHAMCS 2022",
        })
        cid += 1

    # Diagnosis rows (context-only, via ICD-10)
    for key, cfg in DIAGNOSIS_GROUPS.items():
        n, admitted = _rate_for_icd(df, cfg["icd10_prefixes"])
        rate = round(admitted / n * 100, 1) if n else None
        rows.append({
            "condition_reference_id": cid,
            "condition": cfg["label"],
            "match_type": "diagnosis",
            "complaint_key": None,
            "context_condition": None,
            "icd10_prefixes": ";".join(cfg["icd10_prefixes"]),
            "visits": n,
            "admitted": admitted,
            "admit_rate": f"{rate}%" if rate is not None else None,
            "reliable": _reliable(n),
            "triage_note": "context only — not known at intake",
            "source_label": "NHAMCS 2022",
        })
        cid += 1

    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dta", required=True, type=Path,
                    help="Path to NHAMCS 2022 ED .dta file")
    ap.add_argument("--out", required=True, type=Path,
                    help="Output CSV path for condition_reference seed")
    args = ap.parse_args()

    if not args.dta.exists():
        sys.exit(f"ERROR: .dta not found at {args.dta}")

    out = derive(args.dta)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)
    print(f"Wrote {len(out)} rows -> {args.out}", file=sys.stderr)
    # Also echo to stdout for quick inspection
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()