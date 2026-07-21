"""Endpoint tests for GET /queue.

Bypasses scoring entirely: entries are hand-inserted into the queue and matching
rows are seeded in the DB, so the join is testable before req 1.4 lands. The
severity values here are INVENTED — these tests assert plumbing (the value I
seeded came back on the right patient, correctly typed and shaped), never that
an ESI is clinically right. Scoring won't invalidate them.

Isolation: the endpoint resolves its queue via Depends(get_queue), which returns
the module-level singleton. `queue_override` swaps in a fresh queue per test —
otherwise entries would pile up across the whole pytest process.

Note the override goes on `queue_app`, NOT `app`. dependency_overrides is
per-app-instance and this route is registered on the mounted sub-app; putting it
on the root app is silently ignored.
"""
from datetime import date

import pytest

from app.dependencies import get_queue
from app.main import queue_app
from app.models.intake_record import IntakeRecord
from app.models.patient import Patient
from app.models.patient_severity import PatientSeverity
from app.services.priority_queue import PriorityQueue
from app.utils.dates import age_from_dob

TIME_FORMAT = "%H:%M"


@pytest.fixture
def queue_override():
    """Swap the endpoint's queue for a fresh one, scoped to this test."""
    queue = PriorityQueue()
    queue_app.dependency_overrides[get_queue] = lambda: queue
    yield queue
    queue_app.dependency_overrides.pop(get_queue, None)


def _seed(db_session, name, dob=date(1980, 5, 17), system_esi=None,
          clinician_esi=None, severity_score=None):
    """Insert a Patient + IntakeRecord (+ PatientSeverity if asked). Returns both ids."""
    patient = Patient(name=name, date_of_birth=dob, sex="M")
    db_session.add(patient)
    db_session.flush()

    intake = IntakeRecord(patient_id=patient.patient_id, chief_complaint="chest_pain")
    db_session.add(intake)
    db_session.flush()

    if severity_score is not None:
        db_session.add(
            PatientSeverity(
                intake_id=intake.intake_id,
                severity_score=severity_score,
                system_ESI=system_esi,
                clinician_ESI=clinician_esi,
            )
        )

    # Commit so the endpoint's own session (a separate get_db session) sees these.
    db_session.commit()
    return patient.patient_id, intake.intake_id


def _entries(client):
    resp = client.get("/queue/")
    assert resp.status_code == 200
    return resp.json()["payload"]["entries"]


def test_empty_queue_returns_no_entries(client, queue_override):
    assert _entries(client) == []


def test_entries_follow_queue_order(client, db_session, queue_override):
    third_pid, third_iid = _seed(db_session, "Band Three")
    first_pid, first_iid = _seed(db_session, "Band One")
    second_pid, second_iid = _seed(db_session, "Band Two")

    # Insert in an order that does NOT match the expected output.
    queue_override.insert(3, 3, "10:00", third_iid, TIME_FORMAT)
    queue_override.insert(1, 3, "10:01", first_iid, TIME_FORMAT)
    queue_override.insert(2, 3, "10:02", second_iid, TIME_FORMAT)

    entries = _entries(client)
    assert [e["patient_id"] for e in entries] == [first_pid, second_pid, third_pid]
    assert [e["position"] for e in entries] == [1, 2, 3]


def test_entry_includes_patient_details(client, db_session, queue_override):
    dob = date(1975, 3, 14)
    patient_id, intake_id = _seed(db_session, "Detail Patient", dob=dob)
    queue_override.insert(3, 3, "10:00", intake_id, TIME_FORMAT)

    entry = _entries(client)[0]
    assert entry["patient_id"] == patient_id
    assert entry["name"] == "Detail Patient"
    # Computed, never hardcoded — a literal would rot on the patient's birthday.
    assert entry["age"] == age_from_dob(dob)


def test_severity_fields_populated_when_severity_row_exists(client, db_session, queue_override):
    """esi_level must match the esi_band reference values ("ESI-2", not 2)."""
    _, intake_id = _seed(db_session, "Scored Patient", system_esi="ESI-2", severity_score=6)
    queue_override.insert(2, 3, "10:00", intake_id, TIME_FORMAT)

    entry = _entries(client)[0]
    assert entry["esi_level"] == "ESI-2"
    assert entry["priority_label"] == "High"  # joined from esi_band
    # Numeric(5,1) serializes as a float, not an int.
    assert float(entry["severity_score"]) == 6.0


def test_clinician_esi_takes_precedence(client, db_session, queue_override):
    _, intake_id = _seed(
        db_session, "Overridden Patient",
        system_esi="ESI-4", clinician_esi="ESI-1", severity_score=3,
    )
    queue_override.insert(1, 3, "10:00", intake_id, TIME_FORMAT)

    entry = _entries(client)[0]
    assert entry["esi_level"] == "ESI-1"
    assert entry["priority_label"] == "Highest"


def test_unknown_intake_returns_500(client, queue_override):
    """Queue references an intake_id with no DB row -> 500 in the error envelope."""
    queue_override.insert(3, 3, "10:00", 999_999_999, TIME_FORMAT)

    resp = client.get("/queue/")
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "internal_error"
