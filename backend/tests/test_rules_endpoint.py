"""HTTP tests for the /rules endpoints (the Scoring & Rules page's API).

Endpoint-level only: routing, the MedicalDisclaimerResponse envelope, and that the
service output passes through. RulesInfoService's logic is covered in depth by
test_rules_info_service.py, so these just spot-check a value or two per route plus
the error handler.
"""
import pytest
from fastapi import HTTPException

from app.services.rules_info_service import RulesInfoService


def test_rules_health(client):
    resp = client.get("/rules/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["payload"] == {"message": "Rules API is running"}
    assert body["meta"]["disclaimer"]


def test_scoring_rules_endpoint(client):
    resp = client.get("/rules/scoring-rules")
    assert resp.status_code == 200
    payload = resp.json()["payload"]
    assert set(payload) == {"complaint", "vital", "age", "total_rules", "active_rules"}
    by_complaint = {r["complaint_group"]: r for r in payload["complaint"]}
    assert by_complaint["cardiac"]["weight"] == 6


def test_esi_bands_endpoint(client):
    resp = client.get("/rules/esi-bands")
    assert resp.status_code == 200
    payload = resp.json()["payload"]
    assert len(payload) == 5
    assert {b["esi_level"] for b in payload} == {"ESI-1", "ESI-2", "ESI-3", "ESI-4", "ESI-5"}


def test_red_flags_endpoint(client):
    resp = client.get("/rules/red-flags")
    assert resp.status_code == 200
    payload = resp.json()["payload"]
    assert set(payload) == {"Tier 1", "Tier 2"}
    assert len(payload["Tier 1"] + payload["Tier 2"]) == 11


def test_complaint_esi_endpoint(client):
    resp = client.get("/rules/complaint-esi")
    assert resp.status_code == 200
    payload = resp.json()["payload"]
    by_complaint = {r["complaint"]: r for r in payload}
    assert by_complaint["cardiac"]["esi"] == "ESI-2"


def test_rules_endpoint_error_returns_500(client, monkeypatch):
    def boom(self):
        raise HTTPException(status_code=500)

    monkeypatch.setattr(RulesInfoService, "scoring_rules", boom)
    resp = client.get("/rules/scoring-rules")
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "internal_error"
