"""Validate the scoring engine against the MC-MED-derived datasets.

Runs balanced.json and representative.json through the engine and reports, per file:
  - agreement: predicted ESI band == true_esi (exact match)
  - under-triage: predicted LESS acute than true (the dangerous direction)
  - over-triage: predicted MORE acute than true (for context)
  - AUC: rank-based (Mann-Whitney) of the continuous severity_score against the
    real outcome (admit = admitted|icu vs discharged) — does higher predicted
    acuity actually predict admission?

Writes a markdown report to docs/validation/scoring_validation.md.

Safety: points at the *_test* database (reusing the reference tables the test
suite loads) and never commits — every record is scored inside a savepoint that
is rolled back, so nothing persists. Run `pytest` once first if the _test DB
hasn't been built yet.

    python scripts/evaluate_scoring.py
"""
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

# `import app` when run as a bare script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Repoint to the _test DB BEFORE any app.* import builds the engine (mirrors the
# test suite's conftest).
from app.config import get_settings

_base = get_settings().DB_NAME
_test_db = _base if _base.endswith("_test") else f"{_base}_test"
os.environ["DB_NAME"] = _test_db
get_settings.cache_clear()

from sqlalchemy import func, select

from app.dependencies import SessionLocal
from app.models.intake_record import IntakeRecord
from app.models.patient import Patient
from app.models.scoring_rule import ScoringRule
from app.services.red_flag_layer import RedFlagLayer
from app.services.scoring_engine import ScoringEngine, CannotScoreException

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
REPORT = ROOT / "docs" / "validation" / "scoring_validation.md"
DATASETS = ["balanced.json", "representative.json"]

ADMIT_OUTCOMES = {"admitted", "icu"}
VITAL_FIELDS = [
    "heart_rate", "blood_pressure_systolic", "blood_pressure_diastolic",
    "temperature", "oxygen_saturation", "respiration_rate", "pain_level", "blood_sugar",
]


def _score_record(rec, engine, layer, db):
    """Score one record inside a savepoint; return (predicted, true, score, admit) or None."""
    nested = db.begin_nested()
    try:
        patient = Patient(
            name="eval", date_of_birth=date.fromisoformat(rec["date_of_birth"]), sex="unknown"
        )
        db.add(patient)
        db.flush()

        intake = IntakeRecord(
            patient_id=patient.patient_id,
            chief_complaint=rec["chief_complaint"],
            symptoms=rec.get("symptoms", []),
            pre_existing_conditions=rec.get("pre_existing_conditions", []),
            pregnancy_status=rec.get("pregnancy_status"),
            **{f: rec.get(f) for f in VITAL_FIELDS},
        )
        db.add(intake)
        db.flush()

        _, result = engine.score(intake, layer, db)
        return (
            int(result.esi_level[-1]),
            int(rec["true_esi"]),
            float(result.severity_score),
            1 if rec["actual_outcome"] in ADMIT_OUTCOMES else 0,
        )
    except CannotScoreException:
        return None
    finally:
        nested.rollback()


def _auc(scores, labels):
    """Rank-based AUC (Mann-Whitney U with tie-averaged ranks)."""
    n_pos = sum(labels)
    n_neg = len(labels) - n_pos
    if n_pos == 0 or n_neg == 0:
        return None

    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j < len(order) and scores[order[j]] == scores[order[i]]:
            j += 1
        avg_rank = (i + j - 1) / 2 + 1  # 1-based, averaged over ties
        for k in range(i, j):
            ranks[order[k]] = avg_rank
        i = j

    pos_rank_sum = sum(ranks[i] for i in range(len(labels)) if labels[i] == 1)
    return (pos_rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def _metrics(rows):
    n = len(rows)
    agree = sum(1 for p, t, _, _ in rows if p == t)
    under = sum(1 for p, t, _, _ in rows if p > t)   # predicted less acute -> higher number
    over = sum(1 for p, t, _, _ in rows if p < t)
    auc = _auc([s for _, _, s, _ in rows], [a for _, _, _, a in rows])
    return {
        "scored": n,
        "agreement": agree / n,
        "under_triage": under / n,
        "over_triage": over / n,
        "auc": auc,
    }


def _pct(x):
    return f"{x:.1%}"


def main():
    db = SessionLocal()
    try:
        if db.scalar(select(func.count()).select_from(ScoringRule)) == 0:
            sys.exit(f"No reference data in {_test_db}. Run `pytest` once to build it.")

        engine = ScoringEngine(db)
        layer = RedFlagLayer(db)

        results = {}
        for name in DATASETS:
            records = json.loads((BACKEND / name).read_text(encoding="utf-8"))
            scored = [r for r in (_score_record(rec, engine, layer, db) for rec in records) if r is not None]
            results[name] = {
                "total": len(records),
                "unscoreable": len(records) - len(scored),
                **_metrics(scored),
            }
    finally:
        db.rollback()
        db.close()

    _write_report(results)
    for name, m in results.items():
        print(
            f"{name}: agreement {_pct(m['agreement'])}, under-triage {_pct(m['under_triage'])}, "
            f"AUC {m['auc']:.3f} ({m['scored']}/{m['total']} scored, {m['unscoreable']} unscoreable)"
        )
    print(f"Report written to {REPORT}")


def _write_report(results):
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Scoring Engine Validation",
        "",
        f"_Generated {datetime.now():%Y-%m-%d %H:%M}. Source: MC-MED-derived datasets "
        f"(500 records each). Scored against the `{_test_db}` database; all writes rolled back._",
        "",
        "## Metrics",
        "",
        "| Dataset | Scored | Agreement (exact ESI) | Under-triage | Over-triage | AUC (severity_score → admit) |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, m in results.items():
        auc = f"{m['auc']:.3f}" if m["auc"] is not None else "n/a"
        lines.append(
            f"| `{name}` | {m['scored']}/{m['total']} | {_pct(m['agreement'])} | "
            f"{_pct(m['under_triage'])} | {_pct(m['over_triage'])} | {auc} |"
        )

    lines += [
        "",
        "- **Agreement** — predicted ESI band equals `true_esi` exactly.",
        "- **Under-triage** — engine scored *less* acute than the real ESI (higher ESI number). The dangerous direction.",
        "- **Over-triage** — engine scored *more* acute than the real ESI. Shown for context.",
        "- **AUC** — rank-based (Mann-Whitney) of the continuous `severity_score` against the real "
        "outcome (admit = `admitted` ∪ `icu`, vs `discharged`). 0.5 = chance, 1.0 = perfect separation.",
        "",
        "## Limitations",
        "",
        "- **Chief-complaint mapping noise.** Free-text ED complaints were mapped down to the engine's "
        "nine complaint groups; that mapping is lossy, so a record's complaint may not match what a real "
        "intake form would produce — and the complaint drives most of the score.",
        "- **Psychiatric cases out of scope.** The engine does not triage psychiatric or behavioral "
        "presentations; the extractor filters them out (suicidal, self-harm, anxiety, panic, agitation) "
        "before scoring, so they are absent from these datasets by design. Toxicology (overdose, "
        "intoxication) is treated as medical and retained.",
        "- **Neonate / age precision.** The source only provides age in years, so `date_of_birth` is "
        "reconstructed as `YYYY-01-01`. Day-level age is lost, so the febrile-neonate red flag (8–60 days) "
        "and any day-precision age logic cannot fire.",
        "- **Unscoreable records excluded.** Records whose (mapped) complaint has no scoring rule are dropped "
        "from the metrics: "
        + ", ".join(f"{m['unscoreable']} from `{name}`" for name, m in results.items())
        + ".",
        "- **Single-center source.** MC-MED is one academic ED; agreement and outcome relationships may not "
        "generalize to other settings.",
        "- **AUC predictor.** Uses the continuous `severity_score` (raw points), not the discretized 1–5 band, "
        "so it reflects the underlying ranking rather than the banded output clinicians see.",
        "",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
