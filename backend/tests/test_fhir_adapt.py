"""Unit tests for epic_fhir_adapter — the Epic FHIR R4 -> intake draft mapper.

Pure function tests: hand-built (synthetic) FHIR resources in, an intake draft
dict out. No network, no real sandbox data, no DB.
"""
import pytest

from app.services import epic_fhir_adapter as adapt
from app.services.epic_fhir_adapter import build_intake, extract_arrival

# --- synthetic FHIR fixtures -------------------------------------------------

PATIENT = {
    "resourceType": "Patient",
    "id": "abc123",
    "name": [{"text": "Jane Doe", "family": "Doe", "given": ["Jane"]}],
    "gender": "female",
    "birthDate": "1980-05-17",
}

VITALS = {
    "resourceType": "Bundle",
    "entry": [
        {"resource": {"resourceType": "OperationOutcome"}},  # must be skipped
        # two heart-rate readings — the later effectiveDateTime must win
        {"resource": {"resourceType": "Observation", "effectiveDateTime": "2020-01-01",
                      "code": {"coding": [{"code": "8867-4"}]}, "valueQuantity": {"value": 70}}},
        {"resource": {"resourceType": "Observation", "effectiveDateTime": "2021-01-01",
                      "code": {"coding": [{"code": "8867-4"}]}, "valueQuantity": {"value": 88}}},
        # temperature in Celsius -> converted to F
        {"resource": {"resourceType": "Observation", "effectiveDateTime": "2021-01-01",
                      "code": {"coding": [{"code": "8310-5"}]}, "valueQuantity": {"value": 37.0}}},
        {"resource": {"resourceType": "Observation", "effectiveDateTime": "2021-01-01",
                      "code": {"coding": [{"code": "2708-6"}]}, "valueQuantity": {"value": 98}}},
        {"resource": {"resourceType": "Observation", "effectiveDateTime": "2021-01-01",
                      "code": {"coding": [{"code": "72514-3"}]}, "valueQuantity": {"value": 4}}},
        # height (8302-2) must NOT be read as temperature
        {"resource": {"resourceType": "Observation", "effectiveDateTime": "2021-01-01",
                      "code": {"coding": [{"code": "8302-2"}]}, "valueQuantity": {"value": 180}}},
        # blood pressure as a component panel
        {"resource": {"resourceType": "Observation", "effectiveDateTime": "2021-01-01",
                      "code": {"coding": [{"code": "85354-9"}]},
                      "component": [
                          {"code": {"coding": [{"code": "8480-6"}]}, "valueQuantity": {"value": 120}},
                          {"code": {"coding": [{"code": "8462-4"}]}, "valueQuantity": {"value": 78}},
                      ]}},
    ],
}

CONDITION_UNMAPPED = {
    "resourceType": "Bundle",
    "entry": [{"resource": {"resourceType": "Condition",
                            "code": {"coding": [{"system": "http://snomed.info/sct", "code": "69878008"}]}}}],
}


def test_build_intake_happy():
    rec = build_intake(patient=PATIENT, vitals=VITALS, condition=CONDITION_UNMAPPED)

    # identity fields
    assert rec["name"] == "Jane Doe"
    assert rec["date_of_birth"] == "1980-05-17"
    assert rec["external_patient_id"] == "abc123"
    assert rec["source"] == "fhir"

    # vitals: most-recent HR wins, C->F, BP panel, height excluded from temperature
    assert rec["heart_rate"] == 88
    assert rec["temperature"] == 98.6
    assert rec["oxygen_saturation"] == 98
    assert rec["pain_level"] == 4
    assert rec["blood_pressure_systolic"] == 120
    assert rec["blood_pressure_diastolic"] == 78

    # unmapped condition -> no chief complaint, flagged in missing_fields
    assert rec["chief_complaint"] is None
    assert "chief_complaint" in rec["missing_fields"]


def test_chief_complaint_mapped(monkeypatch):
    monkeypatch.setattr(adapt, "SNOMED_CC_TO_KEY", {"22298006": "cardiac"})
    condition = {
        "resourceType": "Bundle",
        "entry": [{"resource": {"resourceType": "Condition",
                                "code": {"coding": [{"system": "http://snomed.info/sct", "code": "22298006"}]}}}],
    }
    rec = build_intake(patient=PATIENT, vitals=VITALS, condition=condition)
    assert rec["chief_complaint"] == "cardiac"
    assert "chief_complaint" not in rec["missing_fields"]


def test_sanity_drops_out_of_range():
    vitals = {
        "resourceType": "Bundle",
        "entry": [{"resource": {"resourceType": "Observation", "effectiveDateTime": "2021-01-01",
                                "code": {"coding": [{"code": "8867-4"}]}, "valueQuantity": {"value": 500}}}],
    }
    rec = build_intake(patient=PATIENT, vitals=vitals)
    assert rec["heart_rate"] is None
    assert "heart_rate" in rec["missing_fields"]


def test_empty_inputs_all_none():
    rec = build_intake()
    assert rec["name"] is None
    assert rec["date_of_birth"] is None
    assert rec["chief_complaint"] is None
    # every vital plus chief_complaint is missing
    assert "chief_complaint" in rec["missing_fields"]
    assert rec["heart_rate"] is None and rec["blood_pressure_systolic"] is None


@pytest.mark.parametrize("cls_code,expected", [("EMER", True), ("AMB", None)])
def test_extract_arrival(cls_code, expected):
    encounter = {
        "resourceType": "Bundle",
        "entry": [{"resource": {"resourceType": "Encounter", "class": {"code": cls_code}}}],
    }
    assert extract_arrival(encounter) is expected
