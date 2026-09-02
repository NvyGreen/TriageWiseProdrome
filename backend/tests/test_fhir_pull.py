"""Unit tests for epic_fhir_pull's reusable pieces.

No network and no real credentials: the HTTP layer (get_access_token / fhir_get /
fetch_bundle) is monkeypatched, so these exercise fetch_patient_fhir's
orchestration + error wrapping, _client_id, and read_kid. The CLI/signing/network
functions are excluded from coverage via `# pragma: no cover` in the module.
"""
import json
from types import SimpleNamespace

import pytest
import requests

from app.services import epic_fhir_pull as pull


def test_fetch_patient_fhir_happy(monkeypatch):
    def fake_fhir_get(token, url, params=None):
        return {"resourceType": "Patient", "_url": url}

    def fake_fetch_bundle(token, rtype, pid, extra=None):
        return {"resourceType": "Bundle", "_rtype": rtype, "_pid": pid, "_extra": extra}

    monkeypatch.setattr(pull, "get_access_token", lambda: "tok")
    monkeypatch.setattr(pull, "fhir_get", fake_fhir_get)
    monkeypatch.setattr(pull, "fetch_bundle", fake_fetch_bundle)

    out = pull.fetch_patient_fhir("PID")

    assert set(out) == {"patient", "vitals", "condition", "encounter"}
    assert out["patient"]["_url"].endswith("/Patient/PID")
    assert out["vitals"]["_rtype"] == "Observation"
    assert out["vitals"]["_extra"] == {"category": "vital-signs"}
    assert out["condition"]["_rtype"] == "Condition"
    assert out["encounter"]["_rtype"] == "Encounter"
    assert out["vitals"]["_pid"] == "PID"


def test_fetch_wraps_runtime_error(monkeypatch):
    def boom():
        raise RuntimeError("token failed")

    monkeypatch.setattr(pull, "get_access_token", boom)
    with pytest.raises(pull.FHIRRetrievalException):
        pull.fetch_patient_fhir("PID")


def test_fetch_wraps_http_error(monkeypatch):
    def raise_http(*args, **kwargs):
        raise requests.HTTPError("404 Not Found")

    monkeypatch.setattr(pull, "get_access_token", lambda: "tok")
    monkeypatch.setattr(pull, "fhir_get", raise_http)
    with pytest.raises(pull.FHIRRetrievalException):
        pull.fetch_patient_fhir("PID")


def test_client_id_reads_settings(monkeypatch):
    monkeypatch.setattr("app.config.get_settings", lambda: SimpleNamespace(FHIR_CLIENT_ID="cid-123"))
    assert pull._client_id() == "cid-123"


def test_read_kid_present(monkeypatch, tmp_path):
    jwks = tmp_path / "jwks.json"
    jwks.write_text(json.dumps({"keys": [{"kid": "k1"}]}), encoding="utf-8")
    monkeypatch.setattr(pull, "JWKS_PATH", str(jwks))
    assert pull.read_kid() == "k1"


def test_read_kid_empty_keys(monkeypatch, tmp_path):
    jwks = tmp_path / "jwks.json"
    jwks.write_text(json.dumps({"keys": []}), encoding="utf-8")
    monkeypatch.setattr(pull, "JWKS_PATH", str(jwks))
    assert pull.read_kid() is None


def test_read_kid_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(pull, "JWKS_PATH", str(tmp_path / "nope.json"))
    assert pull.read_kid() is None
