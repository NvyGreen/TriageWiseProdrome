"""HTTP tests for POST /demo/simulation, driven by the same simulation_test_cases.json
as the unit suite — so the endpoint and the service stay in lock-step.

Unlike the unit suite, these send each case's `call` as the raw JSON body (string
keys and all, exactly as a real client would). That exercises the full path,
including the service-side int-key normalization for custom bands/flags.
"""
import json
from pathlib import Path

import pytest

from app.services.epic_fhir_pull import FHIRRetrievalException
from app.services.simulation import PRESETS

CASES = json.loads(
    (Path(__file__).parent / "unit_cases" / "simulation_test_cases.json").read_text(
        encoding="utf-8"
    )
)["cases"]

SUCCESS_CASES = [c for c in CASES if "expect" in c]
ERROR_CASES = [c for c in CASES if "expect_error" in c]

URL = "/demo/simulation"


def test_demo_health(client):
    resp = client.get("/demo/test")
    assert resp.status_code == 200
    assert resp.json()["payload"] == {"message": "Demo API is running"}


def test_get_presets(client):
    resp = client.get("/demo/presets")

    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["disclaimer"]

    payload = body["payload"]
    assert set(payload) == set(PRESETS)  # the named presets, all present
    # JSON stringifies the int band/flag keys, so compare against the same
    # round-trip rather than the raw (int-keyed) PRESETS dict.
    assert payload == json.loads(json.dumps(PRESETS))


@pytest.mark.parametrize("case", SUCCESS_CASES, ids=[c["_name"] for c in SUCCESS_CASES])
def test_simulate_success(client, case):
    resp = client.post(URL, json=case["call"])

    assert resp.status_code == 200
    body = resp.json()
    # Ordered rows come back under the disclaimer envelope, matching run_simulation.
    assert body["payload"] == case["expect"]
    assert body["meta"]["disclaimer"]


@pytest.mark.parametrize("case", ERROR_CASES, ids=[c["_name"] for c in ERROR_CASES])
def test_simulate_bad_request(client, case):
    # unknown preset / neither field -> ValueError -> 400 invalid_input.
    resp = client.post(URL, json=case["call"])

    assert resp.status_code == 400
    error = resp.json()["error"]
    assert error["code"] == "invalid_input"
    assert isinstance(error["details"], list) and error["details"]


# --- POST /demo/fhir/{fhir_id} ----------------------------------------------
# fetch_patient_fhir is patched where the router looks it up, so no network runs.
# build_intake stays real, so the endpoint's mapping is exercised end to end.

_PATIENT = {
    "resourceType": "Patient",
    "id": "abc123",
    "name": [{"text": "Jane Doe"}],
    "gender": "female",
    "birthDate": "1980-05-17",
}


def test_fhir_endpoint_returns_draft(client, monkeypatch):
    monkeypatch.setattr(
        "app.routers.demo.fetch_patient_fhir",
        lambda fhir_id: {"patient": _PATIENT, "vitals": None, "condition": None, "encounter": None},
    )

    resp = client.post("/demo/fhir/abc123")

    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["disclaimer"]
    payload = body["payload"]
    assert payload["name"] == "Jane Doe"
    assert payload["date_of_birth"] == "1980-05-17"
    assert payload["source"] == "fhir"
    # no condition -> chief_complaint is left None (unsubmittable draft, by design)
    assert payload["chief_complaint"] is None


def test_fhir_endpoint_retrieval_error(client, monkeypatch):
    def boom(fhir_id):
        raise FHIRRetrievalException("sandbox down")

    monkeypatch.setattr("app.routers.demo.fetch_patient_fhir", boom)

    resp = client.post("/demo/fhir/badid")

    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "internal_error"
