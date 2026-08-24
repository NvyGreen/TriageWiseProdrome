"""Service-level tests for TriageService.getQueue.

getQueue now reads the persisted queue from triage_queue, joined to Patient ->
PatientSeverity -> ESIBand, ordered by (esi_band, flag_tier, arrival_time,
intake_id) and excluding dispositioned patients. So these seed real triage_queue
rows (not the in-memory heap).

The test DB persists across tests, and getQueue counts the whole table, so the
autouse fixture clears triage_queue first — otherwise leftover rows leak into
order/empty assertions.
"""
from datetime import date, datetime, timezone

import pytest

from app.models.intake_record import IntakeRecord
from app.models.patient import Patient
from app.models.patient_severity import PatientSeverity
from app.models.triage_queue import TriageQueue
from app.services.priority_queue import PriorityQueue
from app.services.triage_service import TriageService
from app.utils.dates import age_in_years

# getQueue ignores the PriorityQueue arg now (reads the DB), but the signature
# still takes one, so hand it a throwaway.
_UNUSED_QUEUE = PriorityQueue()


def _at(hhmm: str) -> datetime:
    return datetime.strptime(hhmm, "%H:%M").replace(tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clear_queue(db_session):
    """Isolate the persisted queue — the test DB accumulates rows across tests."""
    db_session.query(TriageQueue).delete()
    db_session.commit()
    yield


def _make_queued(db_session, name, esi_band=3, flag_tier=3, arrival="10:00",
                 dob=date(1980, 5, 17), clinician_esi=None, status="WAITING"):
    """Seed a queued (scored + enqueued) patient. Returns (patient, intake)."""
    patient = Patient(name=name, date_of_birth=dob, sex="M")
    db_session.add(patient)
    db_session.flush()

    intake = IntakeRecord(patient_id=patient.patient_id, chief_complaint="cardiac")
    db_session.add(intake)
    db_session.flush()

    severity = PatientSeverity(
        intake_id=intake.intake_id, severity_score=5,
        system_ESI=f"ESI-{esi_band}", clinician_ESI=clinician_esi, flag_tier=flag_tier,
    )
    db_session.add(severity)
    db_session.flush()

    db_session.add(TriageQueue(
        patient_id=patient.patient_id, intake_id=intake.intake_id,
        severity_id=severity.severity_id, esi_band=esi_band, flag_tier=flag_tier,
        arrival_time=_at(arrival), status=status,
    ))
    db_session.commit()
    return patient, intake


def test_empty_queue_returns_no_entries(db_session):
    assert TriageService(db_session).getQueue() == []


def test_single_entry_has_patient_details(db_session):
    dob = date(1975, 3, 14)
    patient, intake = _make_queued(db_session, "Solo Patient", esi_band=3, dob=dob)

    entries = TriageService(db_session).getQueue()

    assert len(entries) == 1
    entry = entries[0]
    assert entry.position == 1
    assert entry.patient_id == patient.patient_id
    assert entry.intake_id == intake.intake_id
    assert entry.name == "Solo Patient"
    assert entry.sex == "M"
    # Computed, never hardcoded — a literal would rot on the patient's birthday.
    assert entry.age == age_in_years(dob)


def test_severity_fields_populated(db_session):
    """A queued intake is always scored, so severity-derived fields are present."""
    _make_queued(db_session, "Scored Patient", esi_band=2, flag_tier=1)

    entry = TriageService(db_session).getQueue()[0]
    assert entry.esi_level == "ESI-2"
    assert entry.priority_label is not None
    assert entry.severity_score == 5
    assert entry.flag_tier == 1


def test_clinician_esi_takes_precedence_in_display(db_session):
    """esi_level shows the clinician override when present (coalesce)."""
    _make_queued(db_session, "Overridden", esi_band=1, clinician_esi="ESI-1")

    entry = TriageService(db_session).getQueue()[0]
    assert entry.esi_level == "ESI-1"


def test_entries_follow_queue_order(db_session):
    _, first = _make_queued(db_session, "Band Three", esi_band=3, arrival="10:00")
    _, second = _make_queued(db_session, "Band One", esi_band=1, arrival="10:01")
    _, third = _make_queued(db_session, "Band Two", esi_band=2, arrival="10:02")

    entries = TriageService(db_session).getQueue()

    assert [e.intake_id for e in entries] == [
        second.intake_id, third.intake_id, first.intake_id,
    ]
    assert [e.position for e in entries] == [1, 2, 3]


def test_dispositioned_excluded(db_session):
    _, waiting = _make_queued(db_session, "Still Waiting", esi_band=2)
    _make_queued(db_session, "Gone", esi_band=1, status="DISPOSITIONED")

    entries = TriageService(db_session).getQueue()

    assert [e.intake_id for e in entries] == [waiting.intake_id]
