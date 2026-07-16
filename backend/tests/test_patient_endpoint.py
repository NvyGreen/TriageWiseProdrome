"""Endpoint tests for POST /patients, driven by the API contract.

Inputs come from tests/contracts/api_examples.json; response assertions follow
API_Reference_v30.md (the source of truth). Where api_examples.json's guessed
values disagree with v30, v30 wins.

Readiness of POST /patients today:
  - 400 validation  -> implemented (app/main.py patients_validation_handler)  -> real test
  - 201 success     -> NOT implemented (returns a 200 placeholder)            -> xfail
  - 409 / 422       -> handlers exist but triggers are commented out          -> skip

Note: the router route is "/" mounted at "/patients", so the path is "/patients/".
"""
import pytest

# v30 canonical error messages (source of truth: API_Reference_v30.md).
INVALID_INPUT_MESSAGE = (
    "One or more fields are invalid."
)


def test_intake_saves_patient_and_returns_201(client, api_examples):
    """TEMPORARY: interim check that a valid intake persists and returns 201.

    Confirms the intake is stored (patient + intake_record rows) and the status
    is 201 — the real behavior available today. Delete once the full v30 Result
    body is implemented; test_valid_intake_returns_201 (currently xfail)
    supersedes this. Also guards against the contract body drifting out of sync
    with the IntakeCreate schema.
    """
    body = api_examples["POST /patients"]["valid_201"]["request"]["body"]
    resp = client.post("/patients/", json=body)

    assert resp.status_code == 201
    patient_id = resp.json()["payload"]["patient_id"]
    assert isinstance(patient_id, int)

    # Confirm it actually landed in the DB — not just echoed in the response.
    from app.database import SessionLocal
    from app.models.patient import Patient
    from app.models.intake_record import IntakeRecord

    session = SessionLocal()
    try:
        saved_patient = session.get(Patient, patient_id)
        assert saved_patient is not None
        assert saved_patient.name == body["name"]

        saved_intake = (
            session.query(IntakeRecord)
            .filter(IntakeRecord.patient_id == patient_id)
            .first()
        )
        assert saved_intake is not None
        assert saved_intake.chief_complaint == body["chief_complaint"]
    finally:
        session.close()


@pytest.mark.xfail(
    reason="submitIntake storage + scoring not implemented; endpoint returns a 200 placeholder",
    strict=False,
)
def test_valid_intake_returns_201(client, api_examples):
    """v30: POST /patients -> 201 Created with new patient_id + severity + queue placement."""
    body = api_examples["POST /patients"]["valid_201"]["request"]["body"]
    resp = client.post("/patients/", json=body)

    assert resp.status_code == 201
    payload = resp.json()
    assert "patient_id" in payload
    assert "severity" in payload
    assert "queue_placement" in payload


def test_malformed_intake_returns_400(client, api_examples):
    """v30: malformed body -> 400 invalid_input with the consistent error envelope."""
    body = api_examples["POST /patients"]["invalid_400"]["request"]["body"]
    resp = client.post("/patients/", json=body)

    assert resp.status_code == 400
    err = resp.json()["error"]

    # Envelope shape + message are pinned by v30.
    assert err["code"] == "invalid_input"
    assert err["message"] == INVALID_INPUT_MESSAGE
    assert "request_id" in err

    # The malformed body has bad heart_rate / oxygen_saturation / pain_level.
    # Per-field `issue` wording is NOT pinned by v30, and the handler may also
    # flag the omitted required fields, so assert on a SUBSET of fields.
    fields = {d["field"] for d in err["details"]}
    assert {"heart_rate", "oxygen_saturation", "pain_level"} <= fields


@pytest.mark.skip(
    reason="idempotency/dedup not wired up (409 trigger commented out in routers/patients.py)"
)
def test_duplicate_intake_returns_409(client, api_examples):
    """v30: same Idempotency-Key (or identical intake in the dedup window) -> 409 duplicate_request."""
    key = api_examples["POST /patients"]["conflict_409"]["request"]["headers"]["Idempotency-Key"]
    body = api_examples["POST /patients"]["valid_201"]["request"]["body"]

    first = client.post("/patients/", json=body, headers={"Idempotency-Key": key})
    assert first.status_code == 201

    second = client.post("/patients/", json=body, headers={"Idempotency-Key": key})
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "duplicate_request"


@pytest.mark.skip(
    reason="scoreability check not wired up (422 trigger commented out in routers/patients.py)"
)
def test_unscoreable_intake_returns_422(client, api_examples):
    """v30: well-formed but unscoreable body -> 422 unscoreable."""
    body = api_examples["POST /patients"]["unscoreable_422"]["request"]["body"]
    resp = client.post("/patients/", json=body)

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "unscoreable"
