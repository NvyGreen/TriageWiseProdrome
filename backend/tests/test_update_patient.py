"""Service-level tests for TriageService.updatePatient (req 1.7).

Tests the service directly rather than through PATCH /intakes/{id}, which isn't
built yet — same approach as test_triage_service.py.

updatePatient only flushes; the route will own the commit. These tests commit
themselves so the rows are queryable.

Row counts are always filtered by intake_id: the test DB persists across tests
and across runs, so table-wide counts would be meaningless.

Deferred: `status_now` (status isn't persisted yet — see the triage_queue TODO),
anything re-scored (req 1.4), `actual_outcome` (nothing writes it), and the
unscoreable case (needs exclude_unset so an explicit null can clear a vital).
"""
from datetime import date

import pytest
from pydantic import ValidationError

from app.models.case_update import CaseUpdate
from app.models.event_log import EventLog
from app.models.intake_record import IntakeRecord
from app.models.patient import Patient
from app.schemas.intake_update import IntakeUpdate, Status
from app.services.priority_queue import PriorityQueue
from app.services.triage_service import EventType, TriageService, IntakeNotFoundError

TIME_FORMAT = "%H:%M"


@pytest.fixture
def queue():
    """A fresh queue per test — never the app's singleton."""
    return PriorityQueue()


def _seed(db_session, name="Update Patient", **vitals):
    """Insert a Patient + IntakeRecord with known vitals. Returns (patient_id, intake_id)."""
    patient = Patient(name=name, date_of_birth=date(1980, 5, 17), sex="M")
    db_session.add(patient)
    db_session.flush()

    intake = IntakeRecord(
        patient_id=patient.patient_id,
        chief_complaint="chest_pain",
        **vitals,
    )
    db_session.add(intake)
    db_session.commit()
    return patient.patient_id, intake.intake_id


def _case_updates(db_session, intake_id):
    return db_session.query(CaseUpdate).filter(CaseUpdate.intake_id == intake_id).all()


def _events(db_session, intake_id, event_type):
    return (
        db_session.query(EventLog)
        .filter(EventLog.intake_id == intake_id, EventLog.event_type == event_type)
        .all()
    )


def test_partial_update_changes_only_sent_fields(db_session, queue):
    _, intake_id = _seed(
        db_session, "Partial Update",
        heart_rate=100, pain_level=4, respiration_rate=18,
    )

    TriageService.updatePatient(intake_id, IntakeUpdate(pain_level=8), queue, db_session)
    db_session.commit()

    intake = db_session.get(IntakeRecord, intake_id)
    assert intake.pain_level == 8
    assert intake.heart_rate == 100        # untouched
    assert intake.respiration_rate == 18   # untouched


def test_case_update_records_only_sent_vitals(db_session, queue):
    patient_id, intake_id = _seed(
        db_session, "Case Update Row", heart_rate=100, pain_level=4,
    )

    TriageService.updatePatient(intake_id, IntakeUpdate(pain_level=8), queue, db_session)
    db_session.commit()

    rows = _case_updates(db_session, intake_id)
    assert len(rows) == 1
    assert rows[0].patient_id == patient_id
    assert rows[0].updated_vitals == {"pain_level": 8}


def test_clinical_update_fires_case_updated_event(db_session, queue):
    _, intake_id = _seed(db_session, "Event Patient", heart_rate=100)

    TriageService.updatePatient(intake_id, IntakeUpdate(heart_rate=120), queue, db_session)
    db_session.commit()

    assert len(_events(db_session, intake_id, EventType.CASE_UPDATED)) == 1


def test_empty_patch_is_rejected():
    """No fields sent -> rejected at validation, so the service is never reached.

    Previously an empty body was a silent no-op; IntakeUpdate.at_least_one_field
    now makes it a 400 instead.
    """
    with pytest.raises(ValidationError) as e:
        IntakeUpdate()

    assert "at least one vital" in str(e.value)


def test_unchanged_values_write_nothing(db_session, queue):
    """Values identical to what's stored are a no-op, not an update."""
    _, intake_id = _seed(db_session, "Same Values", heart_rate=100, pain_level=4)

    TriageService.updatePatient(
        intake_id, IntakeUpdate(heart_rate=100, pain_level=4), queue, db_session
    )
    db_session.commit()

    assert _case_updates(db_session, intake_id) == []
    assert _events(db_session, intake_id, EventType.CASE_UPDATED) == []


def test_disposition_removes_from_queue(db_session, queue):
    _, first = _seed(db_session, "Stays First")
    _, target = _seed(db_session, "Gets Dispositioned")
    _, last = _seed(db_session, "Stays Last")

    queue.insert(1, 3, "10:00", first, TIME_FORMAT)
    queue.insert(2, 3, "10:01", target, TIME_FORMAT)
    queue.insert(3, 3, "10:02", last, TIME_FORMAT)

    TriageService.updatePatient(
        target, IntakeUpdate(status=Status.DISPOSITIONED), queue, db_session
    )
    db_session.commit()

    # Target gone; the others keep their relative order.
    assert queue.orderedIntakeIds() == [first, last]


def test_status_change_fires_status_changed_event(db_session, queue):
    _, intake_id = _seed(db_session, "Status Patient")
    queue.insert(3, 3, "10:00", intake_id, TIME_FORMAT)

    TriageService.updatePatient(
        intake_id, IntakeUpdate(status=Status.IN_ROOM), queue, db_session
    )
    db_session.commit()

    assert len(_events(db_session, intake_id, EventType.STATUS_CHANGED)) == 1
    # No re-score on the status path.
    assert _case_updates(db_session, intake_id) == []


def test_unknown_intake_clinical_path_raises_404(db_session, queue):
    with pytest.raises(IntakeNotFoundError) as e:
        TriageService.updatePatient(
            999_999_999, IntakeUpdate(pain_level=5), queue, db_session
        )
    assert e.value.intake_id == 999_999_999


def test_unknown_intake_status_path_raises_404(db_session, queue):
    """The status path has its own lookup, so it needs its own 404 test."""
    with pytest.raises(IntakeNotFoundError) as e:
        TriageService.updatePatient(
            999_999_999, IntakeUpdate(status=Status.IN_ROOM), queue, db_session
        )
    assert e.value.intake_id == 999_999_999
