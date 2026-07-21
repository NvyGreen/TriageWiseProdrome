"""Endpoint tests for POST /patients, driven by the API contract.

Inputs come from tests/contracts/api_examples.json; response assertions follow
API_Reference_v30.md (the source of truth). Where api_examples.json's guessed
values disagree with v30, v30 wins.

Readiness of POST /patients today:
  - 400 validation  -> implemented (app/main.py patients_validation_handler)   -> real test
  - 400 no key      -> implemented (Idempotency-Key is required, req 1.1b)      -> real test
  - 409 duplicate   -> implemented (idempotency: same key, different body)      -> real test
  - 201 success     -> persists, but full v30 Result body not built             -> interim + xfail
  - 422 unscoreable -> handler exists but trigger not wired up                  -> skip

Idempotency-Key is REQUIRED, so every POST /patients test must send one. Keys
must be UNIQUE per test: the session-scoped test DB persists rows across tests
and across runs, and a stored key dedups within its 24h window — a hardcoded
key would collide on the second run. Use _unique_key().

Note: the router route is "/" mounted at "/patients", so the path is "/patients/".
"""
import copy
from uuid import uuid4

import pytest

# v30 canonical error messages (source of truth: API_Reference_v30.md).
INVALID_INPUT_MESSAGE = "One or more fields are invalid."


def _unique_key() -> str:
    """A fresh Idempotency-Key so tests never collide in the persistent test DB."""
    return uuid4().hex


def test_intake_saves_patient_and_returns_201(client, api_examples):
    """TEMPORARY: interim check that a valid intake persists and returns 201.

    Confirms the intake is stored (patient + intake_record rows) and the status
    is 201 — the real behavior available today. Delete once the full v30 Result
    body is implemented; test_valid_intake_returns_201 (currently xfail)
    supersedes this. Also guards against the contract body drifting out of sync
    with the IntakeCreate schema.
    """
    body = api_examples["POST /patients"]["valid_201"]["request"]["body"]
    resp = client.post("/patients/", json=body, headers={"Idempotency-Key": _unique_key()})

    assert resp.status_code == 201
    intake_id = resp.json()["payload"]["intake_id"]
    assert isinstance(intake_id, int)

    # Confirm it actually landed in the DB — not just echoed in the response.
    # The response only carries intake_id, so reach the patient via its FK.
    from app.dependencies import SessionLocal
    from app.models.patient import Patient
    from app.models.intake_record import IntakeRecord

    session = SessionLocal()
    try:
        saved_intake = session.get(IntakeRecord, intake_id)
        assert saved_intake is not None
        assert saved_intake.chief_complaint == body["chief_complaint"]

        saved_patient = session.get(Patient, saved_intake.patient_id)
        assert saved_patient is not None
        assert saved_patient.name == body["name"]
    finally:
        session.close()


@pytest.mark.xfail(
    reason="severity scoring + queue placement not implemented; Result returns None placeholders",
    strict=False,
)
def test_valid_intake_returns_201(client, api_examples):
    """v30: POST /patients -> 201 Created with the full Result (id + severity + queue placement).

    NOTE: v30 names the id `patient_id`, but the implementation returns
    `intake_id`. Reconcile before treating this as the contract test.
    """
    body = api_examples["POST /patients"]["valid_201"]["request"]["body"]
    resp = client.post("/patients/", json=body, headers={"Idempotency-Key": _unique_key()})

    assert resp.status_code == 201
    payload = resp.json()["payload"]
    assert "intake_id" in payload

    # Both are None placeholders today (see utils/result.py); this flips to XPASS
    # once TriageService actually scores and queues the intake.
    assert payload["severity_score"] is not None
    assert payload["queue_placement"] is not None


def test_malformed_intake_returns_400(client, api_examples):
    """v30: malformed body -> 400 invalid_input with the consistent error envelope.

    No Idempotency-Key needed: body validation fires during request parsing,
    before the handler's idempotency check runs.
    """
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


def test_missing_idempotency_key_returns_400(client, api_examples):
    """req 1.1b: Idempotency-Key is required; absent header -> 400 invalid_input."""
    body = api_examples["POST /patients"]["valid_201"]["request"]["body"]
    resp = client.post("/patients/", json=body)  # no Idempotency-Key header

    assert resp.status_code == 400
    err = resp.json()["error"]
    assert err["code"] == "invalid_input"
    fields = {d["field"] for d in err["details"]}
    assert "Idempotency-Key" in fields


def test_same_key_same_body_replays(client, api_examples):
    """req 1.1b: same key + same body is a safe retry -> replay original, don't re-process."""
    body = api_examples["POST /patients"]["valid_201"]["request"]["body"]
    key = _unique_key()

    first = client.post("/patients/", json=body, headers={"Idempotency-Key": key})
    assert first.status_code == 201
    first_id = first.json()["payload"]["intake_id"]

    second = client.post("/patients/", json=body, headers={"Idempotency-Key": key})
    assert second.status_code == 201
    # The original response is replayed verbatim — same intake_id, no new record.
    assert second.json()["payload"]["intake_id"] == first_id

    from app.dependencies import SessionLocal
    from app.models.intake_record import IntakeRecord

    session = SessionLocal()
    try:
        # Replay must not re-process: the patient behind that intake still has
        # exactly one intake row.
        patient_id = session.get(IntakeRecord, first_id).patient_id
        count = (
            session.query(IntakeRecord)
            .filter(IntakeRecord.patient_id == patient_id)
            .count()
        )
        assert count == 1
    finally:
        session.close()


def test_same_key_different_body_returns_409(client, api_examples):
    """req 1.1b: same key + different body -> 409 duplicate_request."""
    body = api_examples["POST /patients"]["valid_201"]["request"]["body"]
    key = _unique_key()

    first = client.post("/patients/", json=body, headers={"Idempotency-Key": key})
    assert first.status_code == 201

    different = copy.deepcopy(body)
    different["name"] = "Totally Different Person"  # still valid, changes the payload hash
    second = client.post("/patients/", json=different, headers={"Idempotency-Key": key})

    assert second.status_code == 409
    assert second.json()["error"]["code"] == "duplicate_request"


def test_expired_key_reprocesses(client, api_examples):
    """req 1.1b: a key older than the TTL window is treated as fresh.

    Can't wait out the 24h window, so backdate the stored row's created_at past
    it. The reused key must then reprocess (new patient) and upsert the stale
    row — NOT 409, and NOT a primary-key crash.
    """
    from datetime import timedelta

    from app.dependencies import SessionLocal
    from app.models.idempotency_key import IdempotencyKey
    from app.services.idempotency import IDEMPOTENCY_TTL

    body = api_examples["POST /patients"]["valid_201"]["request"]["body"]
    key = _unique_key()

    first = client.post("/patients/", json=body, headers={"Idempotency-Key": key})
    assert first.status_code == 201
    first_id = first.json()["payload"]["intake_id"]

    # Age the stored key past the TTL window.
    session = SessionLocal()
    try:
        row = session.get(IdempotencyKey, key)
        row.created_at = row.created_at - (IDEMPOTENCY_TTL + timedelta(hours=1))
        session.commit()
    finally:
        session.close()

    # Same key + different body, now expired -> reprocessed, upserted, not 409.
    different = copy.deepcopy(body)
    different["name"] = "After Expiry"
    second = client.post("/patients/", json=different, headers={"Idempotency-Key": key})
    assert second.status_code == 201
    assert second.json()["payload"]["intake_id"] != first_id


@pytest.mark.skip(
    reason="scoreability check not wired up (422 trigger commented out in routers/patients.py)"
)
def test_unscoreable_intake_returns_422(client, api_examples):
    """v30: well-formed but unscoreable body -> 422 unscoreable."""
    body = api_examples["POST /patients"]["unscoreable_422"]["request"]["body"]
    resp = client.post("/patients/", json=body, headers={"Idempotency-Key": _unique_key()})

    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "unscoreable"
