"""Endpoint tests for GET /queue.

get_queue now reads the persisted queue from triage_queue (joined to patient /
patient_severity / esi_band), so these seed real triage_queue rows and assert the
plumbing: the values seeded come back on the right patient, correctly typed and
ordered. Severity values are INVENTED — these test shape, not clinical accuracy.

The endpoint uses its own get_db session, so seeds are committed. The test DB
persists across tests and get_queue reads the whole table, so the autouse fixture
clears triage_queue first.
"""
from datetime import date, datetime, timezone

import pytest

from app.models.intake_record import IntakeRecord
from app.models.patient import Patient
from app.models.patient_severity import PatientSeverity
from app.models.triage_queue import TriageQueue
from app.utils.dates import age_in_years


def _at(hhmm: str) -> datetime:
    return datetime.strptime(hhmm, "%H:%M").replace(tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clear_queue(db_session):
    """Isolate the persisted queue — the test DB accumulates rows across tests."""
    db_session.query(TriageQueue).delete()
    db_session.commit()
    yield


def _seed_queued(db_session, name, esi_band, *, dob=date(1980, 5, 17),
                 system_esi=None, clinician_esi=None, severity_score=5,
                 flag_tier=3, arrival="10:00", status="WAITING"):
    """Seed a queued patient (patient + intake + severity + triage_queue row).
    Committed so the endpoint's own session sees it. Returns (patient_id, intake_id)."""
    patient = Patient(name=name, date_of_birth=dob, sex="M")
    db_session.add(patient)
    db_session.flush()

    intake = IntakeRecord(patient_id=patient.patient_id, chief_complaint="cardiac")
    db_session.add(intake)
    db_session.flush()

    severity = PatientSeverity(
        intake_id=intake.intake_id, severity_score=severity_score,
        system_ESI=system_esi or f"ESI-{esi_band}", clinician_ESI=clinician_esi,
        flag_tier=flag_tier,
    )
    db_session.add(severity)
    db_session.flush()

    db_session.add(TriageQueue(
        patient_id=patient.patient_id, intake_id=intake.intake_id,
        severity_id=severity.severity_id, esi_band=esi_band, flag_tier=flag_tier,
        arrival_time=_at(arrival), status=status,
    ))
    db_session.commit()
    return patient.patient_id, intake.intake_id


def _entries(client):
    resp = client.get("/queue/")
    assert resp.status_code == 200
    return resp.json()["payload"]["entries"]


def test_empty_queue_returns_no_entries(client):
    assert _entries(client) == []


def test_entries_follow_queue_order(client, db_session):
    third_pid, _ = _seed_queued(db_session, "Band Three", 3, arrival="10:00")
    first_pid, _ = _seed_queued(db_session, "Band One", 1, arrival="10:01")
    second_pid, _ = _seed_queued(db_session, "Band Two", 2, arrival="10:02")

    entries = _entries(client)
    assert [e["patient_id"] for e in entries] == [first_pid, second_pid, third_pid]
    assert [e["position"] for e in entries] == [1, 2, 3]


def test_entry_includes_patient_details(client, db_session):
    dob = date(1975, 3, 14)
    patient_id, intake_id = _seed_queued(db_session, "Detail Patient", 3, dob=dob)

    entry = _entries(client)[0]
    assert entry["patient_id"] == patient_id
    assert entry["intake_id"] == intake_id
    assert entry["name"] == "Detail Patient"
    assert entry["sex"] == "M"
    # Computed, never hardcoded — a literal would rot on the patient's birthday.
    assert entry["age"] == age_in_years(dob)


def test_severity_fields_populated_when_severity_row_exists(client, db_session):
    """esi_level must match the esi_band reference values ("ESI-2", not 2)."""
    _seed_queued(db_session, "Scored Patient", 2, system_esi="ESI-2", severity_score=6)

    entry = _entries(client)[0]
    assert entry["esi_level"] == "ESI-2"
    assert entry["priority_label"] == "High"  # joined from esi_band
    # Numeric(5,1) serializes as a float, not an int.
    assert float(entry["severity_score"]) == 6.0
    assert entry["flag_tier"] == 3


def test_clinician_esi_takes_precedence(client, db_session):
    _seed_queued(
        db_session, "Overridden Patient", 1,
        system_esi="ESI-4", clinician_esi="ESI-1", severity_score=3,
    )

    entry = _entries(client)[0]
    assert entry["esi_level"] == "ESI-1"
    assert entry["priority_label"] == "Highest"


def test_dispositioned_excluded_from_queue(client, db_session):
    waiting_pid, _ = _seed_queued(db_session, "Still Waiting", 2)
    _seed_queued(db_session, "Gone", 1, status="DISPOSITIONED")

    entries = _entries(client)
    assert [e["patient_id"] for e in entries] == [waiting_pid]
