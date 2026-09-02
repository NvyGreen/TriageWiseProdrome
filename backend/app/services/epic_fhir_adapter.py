"""
Epic FHIR R4 -> intake_record adapter.

Reads Epic FHIR resource bundles (Patient, Observation vital-signs, Condition,
Encounter) and maps them into your intake schema.

Built and verified against the Epic sandbox patients Camila Lopez, Derrick Lin,
and Desiree Powell. Handles Epic's real response shapes: component-style blood
pressure, OperationOutcome warning entries, empty/among suppressed bundles.

DESIGN CHOICE (per your decision): when no chief complaint can be derived, the
field is left None and flagged in `missing_fields`. This is TRUTHFUL output —
note it will NOT satisfy a NOT NULL chief_complaint constraint. Inject a value
downstream (or switch to placeholder mode) before persisting.

Usage:
    python epic_fhir_adapter.py --patient Patient.json --vitals Observation_vitals.json \
        --condition Condition.json --encounter Encounter.json
    # -> prints one intake record as JSON

    # or import and call:
    #   rec = build_intake(patient=..., vitals=..., condition=..., encounter=...)
"""

import json, argparse, re
from datetime import date, datetime

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

# LOINC -> your intake vital field
VITAL_LOINC = {
    "8867-4":  "heart_rate",
    "9279-1":  "respiration_rate",
    "2708-6":  "oxygen_saturation",
    "59408-5": "oxygen_saturation",
    "8480-6":  "blood_pressure_systolic",
    "8462-4":  "blood_pressure_diastolic",
    "8310-5":  "temperature",
    "8302-2":  "temperature",   # NOTE: 8302-2 is body HEIGHT in Epic data, filtered below
    "72514-3": "pain_level",
    "2339-0":  "blood_sugar",
}
# Epic reuses 8310-5 for temperature; 8302-2 is height (NOT temperature) in the
# sandbox data. Exclude height explicitly so it never lands in temperature.
HEIGHT_LOINC = {"8302-2"}
for h in HEIGHT_LOINC:
    VITAL_LOINC.pop(h, None)

TEMPERATURE_LOINC = {"8310-5"}

# SNOMED Condition code -> your ChiefComplaint enum.  # <-- REVIEW
# Only genuine presenting complaints should map. Problem-list RISK factors and
# chronic problems are NOT chief complaints -> leave unmapped (None).
# (Sandbox codes seen: 69878008 PCOS, 315016007 'at risk of CHD' — neither is a
#  presenting complaint, so both intentionally absent here.)
SNOMED_CC_TO_KEY = {
    # add real presenting-complaint SNOMED codes here as you encounter them
    # e.g. "22298006": "cardiac",
}

VITAL_FIELDS = ["heart_rate","blood_pressure_systolic","blood_pressure_diastolic",
                "temperature","oxygen_saturation","respiration_rate",
                "pain_level","blood_sugar"]

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _iter_resources(bundle, rtype=None):
    """Yield resources from a FHIR Bundle, skipping OperationOutcome entries."""
    if not isinstance(bundle, dict):
        return
    if bundle.get("resourceType") == "Bundle":
        for e in bundle.get("entry", []):
            r = e.get("resource", {})
            if r.get("resourceType") == "OperationOutcome":
                continue
            if rtype is None or r.get("resourceType") == rtype:
                yield r
    elif bundle.get("resourceType") == rtype or rtype is None:
        yield bundle  # a bare resource, not wrapped in a bundle

def c_to_f(c):
    try: return round(float(c) * 9 / 5 + 32, 1)
    except (TypeError, ValueError): return None

def to_int(x):
    try: return int(round(float(x)))
    except (TypeError, ValueError): return None

def calc_age(birthdate_str):
    try:
        b = datetime.strptime(birthdate_str, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    t = date.today()
    return t.year - b.year - ((t.month, t.day) < (b.month, b.day))

def _eff(obs):
    return obs.get("effectiveDateTime") or ""

# ---------------------------------------------------------------------------
# EXTRACTORS
# ---------------------------------------------------------------------------

def extract_patient(patient_json):
    p = next(_iter_resources(patient_json, "Patient"), None) or {}
    names = p.get("name", [])
    name = names[0].get("text") if names else None
    return {
        "external_patient_id": p.get("id"),
        "name": name,
        "sex": p.get("gender"),
        "age": calc_age(p.get("birthDate")),
        "_birthDate": p.get("birthDate"),
    }

def extract_vitals(vitals_json):
    """Return {field: most_recent_value} from vital-sign Observations."""
    timed = {}  # field -> (effectiveDateTime, value)

    def consider(field, value, eff):
        if value is None:
            return
        prev = timed.get(field)
        if prev is None or eff > prev[0]:
            timed[field] = (eff, value)

    for obs in _iter_resources(vitals_json, "Observation"):
        eff = _eff(obs)
        # top-level coded value
        for c in obs.get("code", {}).get("coding", []):
            code = c.get("code")
            if code in TEMPERATURE_LOINC:
                consider("temperature", obs.get("valueQuantity", {}).get("value"), eff)
            elif code in VITAL_LOINC:
                consider(VITAL_LOINC[code], obs.get("valueQuantity", {}).get("value"), eff)
        # component values (blood pressure panel)
        for comp in obs.get("component", []):
            for c in comp.get("code", {}).get("coding", []):
                code = c.get("code")
                if code in VITAL_LOINC:
                    consider(VITAL_LOINC[code], comp.get("valueQuantity", {}).get("value"), eff)

    out = {f: None for f in VITAL_FIELDS}
    for field, (_, value) in timed.items():
        out[field] = c_to_f(value) if field == "temperature" else to_int(value)
    return _sanity(out)

# plausibility caps — drop impossible/sentinel values (e.g. sandbox BP 300)
_RANGES = {
    "heart_rate": (10, 300),
    "respiration_rate": (3, 80),
    "oxygen_saturation": (50, 100),
    "blood_pressure_systolic": (40, 250),
    "blood_pressure_diastolic": (20, 200),
    "temperature": (86.0, 113.0),   # F
    "pain_level": (0, 10),
    "blood_sugar": (10, 800),
}
def _sanity(vitals):
    for f, (lo, hi) in _RANGES.items():
        v = vitals.get(f)
        if v is not None and not (lo <= v <= hi):
            vitals[f] = None
    return vitals

def extract_chief_complaint(condition_json):
    """Return an enum key ONLY if a Condition maps to a real presenting complaint.
    Problem-list / risk conditions do not qualify -> None (flagged upstream)."""
    for cond in _iter_resources(condition_json, "Condition"):
        for c in cond.get("code", {}).get("coding", []):
            if "snomed" in c.get("system", ""):
                key = SNOMED_CC_TO_KEY.get(c.get("code"))
                if key:
                    return key
    return None

def extract_arrival(encounter_json):
    """Epic sandbox rarely authorizes Encounter; return None gracefully."""
    for enc in _iter_resources(encounter_json, "Encounter"):
        # class EMER etc. would go here if present; sandbox returns none
        cls = enc.get("class", {}).get("code")
        if cls == "EMER":
            return True
    return None

# ---------------------------------------------------------------------------
# BUILD
# ---------------------------------------------------------------------------

def build_intake(patient=None, vitals=None, condition=None, encounter=None):
    pat = extract_patient(patient) if patient else {"external_patient_id": None, "name": None, "sex": None, "age": None, "_birthDate": None}
    vit = extract_vitals(vitals) if vitals else {f: None for f in VITAL_FIELDS}
    cc  = extract_chief_complaint(condition) if condition else None

    missing = [f for f in VITAL_FIELDS if vit.get(f) is None]
    if cc is None:
        missing = ["chief_complaint"] + missing

    rec = {
        "name": pat.get("name"),
        "date_of_birth": pat.get("_birthDate"),   # FHIR birthDate, ISO YYYY-MM-DD
        "chief_complaint": cc,                    # None when no real complaint (per your choice)
        "heart_rate": vit["heart_rate"],
        "blood_pressure_systolic": vit["blood_pressure_systolic"],
        "blood_pressure_diastolic": vit["blood_pressure_diastolic"],
        "temperature": vit["temperature"],
        "oxygen_saturation": vit["oxygen_saturation"],
        "respiration_rate": vit["respiration_rate"],
        "pain_level": vit["pain_level"],
        "blood_sugar": vit["blood_sugar"],
        "symptoms": [],
        "missing_fields": missing,
        "source": "fhir",
        "external_patient_id": pat["external_patient_id"],
        "pregnancy_status": None,
        "pre_existing_conditions": None,
        "arrival_by_ambulance": None,
        "recent_ed_visit_72h": None,
        "injury_related": None,
        "actual_outcome": None,     # N/A — Epic sandbox has no ED outcome
        "outcome_source": None,     # N/A
        # helper (not an intake field): age/sex for your patient row
        "_age": pat["age"],
        "_sex": pat["sex"],
    }
    return rec

def _load(path):  # pragma: no cover - CLI file read
    if not path: return None
    with open(path) as f: return json.load(f)

def main():  # pragma: no cover - CLI entrypoint
    ap = argparse.ArgumentParser()
    ap.add_argument("--patient")
    ap.add_argument("--vitals")
    ap.add_argument("--condition")
    ap.add_argument("--encounter")
    args = ap.parse_args()
    rec = build_intake(
        patient=_load(args.patient),
        vitals=_load(args.vitals),
        condition=_load(args.condition),
        encounter=_load(args.encounter),
    )
    print(json.dumps(rec, indent=2))

if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    main()