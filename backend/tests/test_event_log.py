"""Event-log integration tests, driven by event_log_test_cases.json (req 1.20).

Each case performs an action through the API (POST /patients or PATCH
/intakes/{id}) and asserts the EXACT set of event_log rows it produced — extra
events are a failure too. Skips override_applied / explanation_viewed (those
paths aren't built).

Notes:
  - The JSON `intake` dicts are scoring-format (complaint + vitals); submit adds
    name/date_of_birth/sex to make a valid IntakeCreate body.
  - get_queue is overridden on all three sub-apps with ONE instance, so a POST
    inserts into and a PATCH reprioritizes the same queue.
  - The clinical case seeds a filler ahead of the target so the re-score produces
    a real move (reprioritized fires only on movement). The filler is enqueued at
    its stated ESI rather than scored — the endpoint only re-scores the target.
  - Update cases seed the intake directly (no submit), so the only events are the
    ones the PATCH produces.
"""
import json
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import update

from app.dependencies import get_queue
from app.main import intakes_app, patients_app, queue_app
from app.models.event_log import EventLog
from app.models.intake_record import IntakeRecord
from app.models.patient import Patient
from app.models.patient_severity import PatientSeverity
from app.models.scoring_rule import ScoringRule
from app.models.triage_queue import TriageQueue
from app.services.priority_queue import PriorityQueue

UNIT_CASES = Path(__file__).parent / "unit_cases"
CASES = json.loads((UNIT_CASES / "event_log_test_cases.json").read_text(encoding="utf-8"))["cases"]
BY_NAME = {c["_name"]: c for c in CASES}

IDENTITY = {"name": "Event Patient", "date_of_birth": "1980-01-01", "sex": "M"}


def _at(hhmm: str) -> datetime:
    return datetime.strptime(hhmm, "%H:%M").replace(tzinfo=timezone.utc)


@pytest.fixture
def event_queue():
    """One fresh queue shared across the sub-apps that touch it."""
    queue = PriorityQueue()
    apps = (patients_app, intakes_app, queue_app)
    for sub_app in apps:
        sub_app.dependency_overrides[get_queue] = lambda: queue
    yield queue
    for sub_app in apps:
        sub_app.dependency_overrides.pop(get_queue, None)


def _rows(db_session, intake_id):
    return db_session.query(EventLog).filter(EventLog.intake_id == intake_id).all()


def _types(rows):
    return {r.event_type for r in rows}


def _expected_types(case):
    return {e["event_type"] for e in case["expect_events"]}


def _submit(client, case):
    body = {**case["action"]["intake"], **IDENTITY}
    return client.post("/patients/", json=body, headers={"Idempotency-Key": uuid4().hex})


def _seed_queued(db_session, queue, chief_complaint, esi_band, arrival, **vitals):
    """Seed a scored + queued intake (no submit -> no submit events). Returns intake_id."""
    patient = Patient(name="Seeded", date_of_birth=date(1980, 1, 1), sex="M")
    db_session.add(patient)
    db_session.flush()
    intake = IntakeRecord(patient_id=patient.patient_id, chief_complaint=chief_complaint, **vitals)
    db_session.add(intake)
    db_session.flush()
    severity = PatientSeverity(intake_id=intake.intake_id, severity_score=1, system_ESI=f"ESI-{esi_band}")
    db_session.add(severity)
    db_session.flush()
    # A queued intake also has a triage_queue row — updatePatient reads/updates it.
    db_session.add(TriageQueue(
        patient_id=patient.patient_id, intake_id=intake.intake_id,
        severity_id=severity.severity_id, esi_band=esi_band, flag_tier=3,
        arrival_time=arrival,
    ))
    db_session.commit()
    queue.insert(esi_band, 3, arrival, intake.intake_id)
    return intake.intake_id


# --- submit path ---

@pytest.mark.parametrize("name", [
    "submit_intake_logs_created_scored_queued",
    "submit_intake_with_red_flag_logs_flag_fired",
    "submit_intake_no_flag_omits_flag_fired",
])
def test_submit_logs_expected_events(client, db_session, event_queue, name):
    case = BY_NAME[name]
    resp = _submit(client, case)
    assert resp.status_code == 201
    intake_id = resp.json()["payload"]["intake_id"]

    # Scoring is out-of-band now (separate process); drive it so the score/queued
    # (and red-flag) events are written, the same path the poll loop uses.
    from app.dependencies import SessionLocal
    from app import scorer
    session = SessionLocal()
    try:
        scorer.score_claimed(session, intake_id)
    finally:
        session.close()
    db_session.expire_all()

    rows = _rows(db_session, intake_id)
    assert _types(rows) == _expected_types(case)  # exactly these — no extras
    for r in rows:
        assert r.intake_id is not None
        assert r.patient_id is not None


def test_unscoreable_submit_logs_nothing(client, db_session, event_queue):
    """An unscoreable submit is accepted (201, pending); out-of-band scoring rolls
    back, so no score_calculated / queued events are written (only intake_created)."""
    case = BY_NAME["unscoreable_submit_does_not_log_scored_or_queued"]
    (rule_id,) = case["action"]["setup"]["deactivate_rules"]

    db_session.execute(
        update(ScoringRule).where(ScoringRule.rule_id == rule_id).values(is_active=False)
    )
    db_session.commit()
    try:
        resp = _submit(client, case)
        assert resp.status_code == 201
        intake_id = resp.json()["payload"]["intake_id"]
        db_session.expire_all()  # see the background task's committed writes
        types = _types(_rows(db_session, intake_id))
        assert "score_calculated" not in types
        assert "queued" not in types
    finally:
        db_session.execute(
            update(ScoringRule).where(ScoringRule.rule_id == rule_id).values(is_active=True)
        )
        db_session.commit()


def test_every_row_has_event_type_and_ids(client, db_session, event_queue):
    case = BY_NAME["every_row_has_event_type_and_ids"]
    resp = _submit(client, case)
    assert resp.status_code == 201
    intake_id = resp.json()["payload"]["intake_id"]

    rows = _rows(db_session, intake_id)
    assert rows
    for r in rows:
        assert r.event_type
        assert r.intake_id is not None
        assert r.patient_id is not None
    assert not hasattr(EventLog, "performed_by")


# --- update path ---

def test_clinical_update_logs_events(client, db_session, event_queue):
    case = BY_NAME["clinical_update_logs_case_updated_and_scored"]

    # Filler ahead (earlier arrival), target behind; both ESI-3.
    filler = _seed_queued(db_session, event_queue, "abdominal", 3, _at("09:00"))
    target = _seed_queued(
        db_session, event_queue, "respiratory", 3, _at("10:00"),
        oxygen_saturation=98, heart_rate=80, respiration_rate=16,
        blood_pressure_systolic=120, pain_level=2,
    )

    resp = client.patch(f"/intakes/{target}", json=case["action"]["patch"])
    assert resp.status_code == 200

    assert _types(_rows(db_session, target)) == _expected_types(case)
    # reprioritized fired because the target crossed the filler in the persisted queue.
    entries = client.get("/queue/").json()["payload"]["entries"]
    got = [e["intake_id"] for e in entries if e["intake_id"] in {target, filler}]
    assert got == [target, filler]


def test_status_only_update_logs_status_changed(client, db_session, event_queue):
    case = BY_NAME["status_only_update_logs_status_changed_only"]
    intake_id = _seed_queued(db_session, event_queue, "cardiac", 2, _at("10:00"))

    resp = client.patch(f"/intakes/{intake_id}", json=case["action"]["patch"])
    assert resp.status_code == 200

    assert _types(_rows(db_session, intake_id)) == _expected_types(case)


def test_disposition_logs_status_changed(client, db_session, event_queue):
    case = BY_NAME["disposition_logs_status_changed"]
    intake_id = _seed_queued(db_session, event_queue, "cardiac", 2, _at("10:00"))

    resp = client.patch(f"/intakes/{intake_id}", json=case["action"]["patch"])
    assert resp.status_code == 200

    assert _types(_rows(db_session, intake_id)) == _expected_types(case)
