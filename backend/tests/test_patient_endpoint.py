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
    "Malformed body, wrong types, missing required field "
    "(e.g. no chief complaint), out-of-range vital"
)


def test_valid_intake_passes_validation(client, api_examples):
    """A well-formed contract body clears validation (does NOT hit the 400 path).

    Storage/scoring isn't built yet, so we only assert it isn't rejected as
    malformed. This also guards against the contract body drifting out of sync
    with the IntakeCreate schema.
    """
    body = api_examples["POST /patients"]["valid_201"]["request"]["body"]
    resp = client.post("/patients/", json=body)

    assert resp.status_code != 400


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
