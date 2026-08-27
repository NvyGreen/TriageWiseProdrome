"""Integration tests for TriageService.apply_override, driven by override_test_cases.json.

Each case seeds a scored patient (patient + intake_record + patient_severity) and a
pre-populated triage_queue with fillers, calls apply_override, and asserts the full
effect: Result, clinician_ESI mutation, the persisted override row, events
(override_applied always; reprioritized only on real movement), and queue position.

PKs are NOT pinned — the JSON's patient/intake/severity ids are join keys; rows are
inserted with autoincrement and the real ids threaded through. Arrival labels map to
distinct times so tie-breaks are deterministic.
"""
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.event_log import EventLog
from app.models.intake_record import IntakeRecord
from app.models.override import Override
from app.models.patient import Patient
from app.models.patient_severity import PatientSeverity
from app.models.triage_queue import TriageQueue
from app.services.triage_service import (
    EventType,
    ReasonCode,
    SeverityNotFoundError,
    TriageService,
)

UNIT_CASES = Path(__file__).parent / "unit_cases"
CASES = json.loads((UNIT_CASES / "override_test_cases.json").read_text(encoding="utf-8"))["cases"]
BY_NAME = {c["_name"]: c for c in CASES}

SUCCESS_CASES = [c for c in CASES if "raises" not in c["expect"]]

# Arrival labels -> distinct times so same-band tie-breaks are deterministic.
ARRIVAL = {"earlier": "09:00", "later": "10:00", "only": "10:00"}


def _at(hhmm: str) -> datetime:
    return datetime.strptime(hhmm, "%H:%M").replace(tzinfo=timezone.utc)


def _seed(db_session, seed):
    """Insert patient + intake + patient_severity; return (intake, severity)."""
    p = seed["patient"]
    patient = Patient(
        name=p["name"], date_of_birth=date.fromisoformat(p["date_of_birth"]), sex=p["sex"]
    )
    db_session.add(patient)
    db_session.flush()

    ir = seed["intake_record"]
    intake = IntakeRecord(patient_id=patient.patient_id, chief_complaint=ir["chief_complaint"])
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
        red_flags=ps["red_flags"],
        red_flag_fired=False,
        flag_tier=ps["flag_tier"],
    )
    db_session.add(severity)
    db_session.commit()
    return intake, severity


def _seed_queue(db_session, queue_seed, target_json_id, target_intake, target_severity):
    """Insert each queue entry into triage_queue.

    The target reuses its seeded rows; fillers get a minimal patient/intake/
    severity chain so they exist in the DB — apply_override reads positions
    from triage_queue.

    The _test DB accumulates triage_queue rows across tests, so clear the table
    first: position math counts the whole table, and cases like "alone in the
    queue" are only true against an isolated queue.
    """
    db_session.query(TriageQueue).delete()
    db_session.flush()
    for entry in queue_seed:
        band = int(entry["esi"][-1])
        arrival = _at(ARRIVAL[entry["arrival"]])
        if entry["intake_id"] == target_json_id:
            patient_id, intake_id, severity_id = (
                target_intake.patient_id, target_intake.intake_id, target_severity.severity_id
            )
        else:
            patient = Patient(name="Filler", date_of_birth=date(1980, 1, 1), sex="M")
            db_session.add(patient)
            db_session.flush()
            fill_intake = IntakeRecord(patient_id=patient.patient_id, chief_complaint="cardiac")
            db_session.add(fill_intake)
            db_session.flush()
            fill_sev = PatientSeverity(
                intake_id=fill_intake.intake_id, severity_score=1,
                system_ESI=entry["esi"], flag_tier=entry["flag_tier"],
            )
            db_session.add(fill_sev)
            db_session.flush()
            patient_id, intake_id, severity_id = (
                patient.patient_id, fill_intake.intake_id, fill_sev.severity_id
            )
        db_session.add(TriageQueue(
            patient_id=patient_id, intake_id=intake_id, severity_id=severity_id,
            esi_band=band, flag_tier=entry["flag_tier"], arrival_time=arrival,
        ))
    db_session.commit()


def _events(db_session, intake_id, event_type):
    return (
        db_session.query(EventLog)
        .filter(EventLog.intake_id == intake_id, EventLog.event_type == event_type)
        .all()
    )


@pytest.mark.parametrize("case", SUCCESS_CASES, ids=lambda c: c["_name"])
def test_apply_override(case, db_session):
    seed = case["seed"]
    expect = case["expect"]
    intake, severity = _seed(db_session, seed)

    _seed_queue(db_session, seed["queue_seed"], seed["intake_record"]["intake_id"], intake, severity)

    call = case["call"]
    result = TriageService(db_session).apply_override(
        severity.severity_id,
        call["clinician_esi"],
        ReasonCode(call["reason_code"]),
        call["note"],
    )
    db_session.commit()

    # --- Result ---
    assert result is not None
    if "result_intake_id" in expect:
        assert result.intake_id == intake.intake_id
    if "result_severity_score" in expect:
        assert result.severity_score == expect["result_severity_score"]

    # --- clinician_ESI mutated on the severity row ---
    assert severity.clinician_ESI == expect["clinician_ESI_set_to"]

    # --- override row persisted (system_ESI always the ORIGINAL system value) ---
    override = db_session.scalar(select(Override).where(Override.severity_id == severity.severity_id))
    assert override is not None
    if "override_system_ESI" in expect:
        assert override.system_ESI == expect["override_system_ESI"]
    if "override_clinician_esi" in expect:
        assert override.clinician_ESI == expect["override_clinician_esi"]
    if "override_reason_code" in expect:
        assert override.reason_code == expect["override_reason_code"]
    if "override_note" in expect:
        assert override.note == expect["override_note"]

    # --- events ---
    for event_name in expect.get("events_logged", []):
        assert len(_events(db_session, intake.intake_id, EventType(event_name))) == 1, event_name
    if "event_NOT_logged" in expect:
        assert _events(db_session, intake.intake_id, EventType(expect["event_NOT_logged"])) == []

    if "override_applied_details" in expect:
        applied = _events(db_session, intake.intake_id, EventType.OVERRIDE_APPLIED)[0]
        assert applied.details == expect["override_applied_details"]
    if "reprioritized_details" in expect:
        reprio = _events(db_session, intake.intake_id, EventType.REPRIORITIZED)[0]
        assert reprio.details == expect["reprioritized_details"]
    if "reprioritized_old_esi" in expect:
        reprio = _events(db_session, intake.intake_id, EventType.REPRIORITIZED)[0]
        assert reprio.details["old_esi"] == expect["reprioritized_old_esi"]

    # reprioritized fires iff the position actually changed.
    reprioritized = _events(db_session, intake.intake_id, EventType.REPRIORITIZED)
    assert bool(reprioritized) == expect["position_changed"]


def test_severity_not_found_raises(db_session):
    case = BY_NAME["severity_not_found_raises"]
    call = case["call"]

    with pytest.raises(SeverityNotFoundError):
        TriageService(db_session).apply_override(
            call["severity_id"],
            call["clinician_esi"],
            ReasonCode(call["reason_code"]),
            call["note"],
        )

    # Nothing written: no override row for the unknown severity id.
    assert db_session.scalar(
        select(Override).where(Override.severity_id == call["severity_id"])
    ) is None
