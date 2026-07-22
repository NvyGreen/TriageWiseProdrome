"""Service-level tests for TriageService.getQueue.

Unlike test_queue.py (pure PriorityQueue, no DB), getQueue joins IntakeRecord ->
Patient -> PatientSeverity -> ESIBand, so these need the test database.

Each test builds its own rows and a FRESH PriorityQueue (not the singleton from
app.dependencies), so tests can't bleed into each other. getQueue only returns
what's in the queue it's handed, so leftover rows in the persistent test DB
can't leak into results either.

Deferred until scoring exists: populated esi_level / priority_label /
severity_score, and clinician_ESI taking precedence over system_ESI.
Not asserted: `status` (hardcoded "WAITING") and `entered_at` (placeholder).
"""
from datetime import date

import pytest
from fastapi.exceptions import HTTPException

from app.models.intake_record import IntakeRecord
from app.models.patient import Patient
from app.services.priority_queue import PriorityQueue
from app.services.triage_service import TriageService
from app.utils.dates import age_from_dob

TIME_FORMAT = "%H:%M"


def _make_intake(db_session, name, dob=date(1980, 5, 17)):
    """Insert a Patient + IntakeRecord, returning both."""
    patient = Patient(name=name, date_of_birth=dob, sex="M")
    db_session.add(patient)
    db_session.flush()

    intake = IntakeRecord(patient_id=patient.patient_id, chief_complaint="cardiac")
    db_session.add(intake)
    db_session.commit()
    return patient, intake


def test_empty_queue_returns_no_entries(db_session):
    assert TriageService.getQueue(PriorityQueue(), db_session) == []


def test_single_entry_has_patient_details(db_session):
    dob = date(1975, 3, 14)
    patient, intake = _make_intake(db_session, "Solo Patient", dob=dob)

    queue = PriorityQueue()
    queue.insert(3, 3, "10:00", intake.intake_id, TIME_FORMAT)

    entries = TriageService.getQueue(queue, db_session)

    assert len(entries) == 1
    entry = entries[0]
    assert entry.position == 1
    assert entry.patient_id == patient.patient_id
    assert entry.name == "Solo Patient"
    # Computed, never hardcoded — a literal would rot on the patient's birthday.
    assert entry.age == age_from_dob(dob)


def test_entries_follow_queue_order(db_session):
    _, first = _make_intake(db_session, "Band Three")
    _, second = _make_intake(db_session, "Band One")
    _, third = _make_intake(db_session, "Band Two")

    # Insert in an order that does NOT match the expected output, so the test
    # fails if getQueue returned insertion order instead of queue order.
    queue = PriorityQueue()
    queue.insert(3, 3, "10:00", first.intake_id, TIME_FORMAT)
    queue.insert(1, 3, "10:01", second.intake_id, TIME_FORMAT)
    queue.insert(2, 3, "10:02", third.intake_id, TIME_FORMAT)

    entries = TriageService.getQueue(queue, db_session)

    assert [e.patient_id for e in entries] == [
        second.patient_id,
        third.patient_id,
        first.patient_id,
    ]
    assert [e.position for e in entries] == [1, 2, 3]


def test_no_severity_row_yields_none_fields(db_session):
    """The live path today: submitIntake writes no PatientSeverity row."""
    _, intake = _make_intake(db_session, "Unscored Patient")

    queue = PriorityQueue()
    queue.insert(3, 3, "10:00", intake.intake_id, TIME_FORMAT)

    entry = TriageService.getQueue(queue, db_session)[0]
    assert entry.esi_level is None
    assert entry.priority_label is None
    assert entry.severity_score is None


def test_missing_intake_raises_500(db_session):
    queue = PriorityQueue()
    queue.insert(3, 3, "10:00", 999_999_999, TIME_FORMAT)  # no such intake row

    with pytest.raises(HTTPException) as e:
        TriageService.getQueue(queue, db_session)
    assert e.value.status_code == 500
