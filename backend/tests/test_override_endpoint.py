"""HTTP-layer tests for POST /overrides/, driven by override_endpoint_test_cases.json.

Distinct from test_apply_override.py (the applyOverride SERVICE method) — here we
assert the endpoint contract: status codes, error envelopes, the response body,
idempotency (replay / conflict / expiry), and validation normalization.

Wiring notes from the sweep:
  - PKs are unpinned: the JSON's severity_id/intake_id are join keys; rows are
    seeded with autoincrement and the real severity_id is substituted into the
    request body before POSTing. `body_intake_id` is asserted against the real id.
  - Idempotency keys are made unique per run (uuid) so the persistent _test DB
    can't collide on a re-run; the same unique key is used for the seeded row and
    the request header.
  - request_hash for the replay row is computed with the real hash_payload over
    the (substituted) body so check_idempotency matches; the conflict row uses a
    deliberately different hash.
  - The endpoint reaches the queue via Depends(get_queue); `override_queue` swaps
    a fresh queue onto overrides_app and the target intake is inserted for cases
    that actually run applyOverride (else updatePatientPosition raises).
  - Success/replay bodies are wrapped under "payload" by MedicalDisclaimerResponse.
"""
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.dependencies import get_queue
from app.main import overrides_app
from app.models.event_log import EventLog
from app.models.idempotency_key import IdempotencyKey
from app.models.intake_record import IntakeRecord
from app.models.override import Override
from app.models.patient import Patient
from app.models.patient_severity import PatientSeverity
from app.models.triage_queue import TriageQueue
from app.schemas.override_create import OverrideCreate
from app.services.idempotency import hash_payload
from app.services.priority_queue import PriorityQueue
from app.services.triage_service import EventType

UNIT_CASES = Path(__file__).parent / "unit_cases"
CASES = json.loads((UNIT_CASES / "override_endpoint_test_cases.json").read_text(encoding="utf-8"))["cases"]

DIFFERENT_HASH = "0" * 64  # never equals a real sha256 hex of a valid body


def _at(hhmm: str) -> datetime:
    return datetime.strptime(hhmm, "%H:%M").replace(tzinfo=timezone.utc)


@pytest.fixture
def override_queue():
    """Swap the endpoint's queue for a fresh one, scoped to this test."""
    queue = PriorityQueue()
    overrides_app.dependency_overrides[get_queue] = lambda: queue
    yield queue
    overrides_app.dependency_overrides.pop(get_queue, None)


def _seed_rows(db_session, seed):
    """Seed patient + intake + patient_severity when present. Returns (severity, intake)."""
    if not seed or "patient_severity" not in seed:
        return None, None

    patient = Patient(name="Override EP", date_of_birth=date(1970, 1, 1), sex="M")
    db_session.add(patient)
    db_session.flush()

    ir = seed["intake_record"]
    intake = IntakeRecord(
        patient_id=patient.patient_id,
        chief_complaint=ir.get("chief_complaint", "cardiac"),
    )
    db_session.add(intake)
    db_session.flush()

    ps = seed["patient_severity"]
    severity = PatientSeverity(
        intake_id=intake.intake_id,
        severity_score=ps["severity_score"],
        system_ESI=ps["system_ESI"],
        clinician_ESI=ps["clinician_ESI"],
        score_reason="seed",
        confidence="HIGH",
        red_flags=[],
        red_flag_fired=False,
        flag_tier=ps["flag_tier"],
    )
    db_session.add(severity)
    db_session.commit()
    return severity, intake


def _seed_idempotency(db_session, idem_row, key, body):
    """Seed a pre-existing idempotency_key row for replay / conflict / expiry."""
    created = idem_row["created_at"]
    if "past" in created or "25" in created:
        created_at = datetime.now(timezone.utc) - timedelta(hours=25)
    else:
        created_at = datetime.now(timezone.utc) - timedelta(hours=1)

    if idem_row["request_hash"] == "<hash of the body below>":
        request_hash = hash_payload(OverrideCreate(**body))  # must match the endpoint
    else:
        request_hash = DIFFERENT_HASH

    db_session.add(
        IdempotencyKey(
            idempotency_key=key,
            request_hash=request_hash,
            response_body=idem_row["response_body"],
            status_code=idem_row["status_code"],
            created_at=created_at,
        )
    )
    db_session.commit()


def _events(db_session, intake_id, event_type):
    return (
        db_session.query(EventLog)
        .filter(EventLog.intake_id == intake_id, EventLog.event_type == event_type)
        .all()
    )


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["_name"])
def test_override_endpoint(case, client, db_session, override_queue):
    seed = case["seed"]
    expect = case["expect"]
    severity, intake = _seed_rows(db_session, seed)

    real_sev_id = severity.severity_id if severity else None
    real_intake_id = intake.intake_id if intake else None

    # Substitute the real severity id into the request body.
    body = dict(case["request"]["body"])
    if severity is not None and "severity_id" in body:
        body["severity_id"] = real_sev_id
    elif "severity_id" in body:
        real_sev_id = body["severity_id"]  # e.g. the 404's 999999

    # Unique key per run for both the seeded row and the header.
    send_key = uuid4().hex if "Idempotency-Key" in case["request"]["headers"] else None

    idem_row = seed.get("idempotency_key_row") if seed else None
    if idem_row:
        _seed_idempotency(db_session, idem_row, send_key, body)

    for entry in (seed.get("queue_seed", []) if seed else []):
        band = int(entry["esi"][-1])
        override_queue.insert(band, entry["flag_tier"], _at("10:00"), real_intake_id)
        # applyOverride reads the queue row from triage_queue; commit it so the
        # endpoint's own session sees it.
        db_session.add(TriageQueue(
            patient_id=intake.patient_id, intake_id=real_intake_id,
            severity_id=real_sev_id, esi_band=band, flag_tier=entry["flag_tier"],
            arrival_time=_at("10:00"),
        ))
    if seed and seed.get("queue_seed"):
        db_session.commit()

    headers = {"Idempotency-Key": send_key} if send_key else {}
    resp = client.post("/overrides/", json=body, headers=headers)

    assert resp.status_code == expect["status_code"]

    if "error_code" in expect:
        assert resp.json()["error"]["code"] == expect["error_code"]
    if "error_detail_field" in expect:
        fields = {d["field"] for d in resp.json()["error"]["details"]}
        assert expect["error_detail_field"] in fields
    if "error_message" in expect:
        assert resp.json()["error"]["message"] == expect["error_message"]

    db_session.expire_all()  # see the endpoint's committed writes

    if resp.status_code == 201:
        payload = resp.json()["payload"]
        if "body_keys" in expect:
            assert set(expect["body_keys"]) <= set(payload.keys())
        if "body_message" in expect:
            assert payload["message"] == expect["body_message"]
        if "body_intake_id" in expect:
            assert payload["intake_id"] == real_intake_id
        if "body_severity_score" in expect:
            assert payload["severity_score"] == expect["body_severity_score"]
        if expect.get("body_equals_stored"):
            assert payload == idem_row["response_body"]

    # Override row.
    if expect.get("override_persisted"):
        assert db_session.scalar(select(Override).where(Override.severity_id == real_sev_id)) is not None
    if (expect.get("no_override_row") or expect.get("no_new_override_row")) and real_sev_id is not None:
        assert db_session.scalars(select(Override).where(Override.severity_id == real_sev_id)).all() == []

    # clinician_ESI mutation / non-mutation.
    if "clinician_ESI_set_to" in expect:
        assert db_session.get(PatientSeverity, real_sev_id).clinician_ESI == expect["clinician_ESI_set_to"]
    if expect.get("clinician_ESI_unchanged"):
        assert db_session.get(PatientSeverity, real_sev_id).clinician_ESI == seed["patient_severity"]["clinician_ESI"]

    # No duplicate work on replay.
    if expect.get("no_new_events"):
        assert _events(db_session, real_intake_id, EventType.OVERRIDE_APPLIED) == []

    # Idempotency row persistence / upsert.
    if expect.get("idempotency_key_stored"):
        assert db_session.get(IdempotencyKey, send_key) is not None
    if expect.get("idempotency_row_upserted") or expect.get("created_at_reset"):
        row = db_session.get(IdempotencyKey, send_key)
        assert row is not None
        # created_at reset to ~now by the upsert (was seeded 25h ago).
        assert row.created_at > datetime.now(timezone.utc) - timedelta(minutes=5)
