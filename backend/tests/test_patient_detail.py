"""Integration tests for TriageService.getPatientDetail composition (D1 surface).

These assert how the STORED rows compose into a PatientDetail bundle — NOT the
lede text (see test_lede_renderer.py) or the Explanation values (see
test_explanation_builder.py). Each case pre-seeds patient / intake_record /
patient_severity / ai_explanation and calls getPatientDetail.

Two deliberate choices from the sweep:
  - PKs are NOT pinned. The JSON's patient_id/intake_id (100/5001...) are only
    join keys; we insert with autoincrement and thread the REAL generated ids,
    so the persistent _test DB can't duplicate-key on a second run.
  - Object-identity assertions (Driver/Trigger instances, gap dict) run at the
    SERVICE level. Those types are lost once serialized to JSON, so only the
    200/404 status + error code go through GET /intakes/{id}.

band_name and age aren't fields on the bundle — they're derived here from
system_ESI and date_of_birth, which the bundle does expose.
"""
import json
from datetime import date
from pathlib import Path

import pytest

from app.models.ai_explanation import AIExplanation
from app.models.event_log import EventLog
from app.models.intake_record import IntakeRecord
from app.models.patient import Patient
from app.models.patient_severity import PatientSeverity
from app.services.triage_service import LABEL_MAP, EventType, TriageService
from app.utils.dates import age_in_years
from app.utils.driver import Driver
from app.schemas.trigger_info import TriggerInfo

UNIT_CASES = Path(__file__).parent / "unit_cases"
CASES = json.loads((UNIT_CASES / "patient_detail_test_cases.json").read_text(encoding="utf-8"))["cases"]
BY_NAME = {c["_name"]: c for c in CASES}

# Override composition isn't built yet (PatientDetail.override is hardcoded null),
# so the dual-score case can't pass — xfailed until the override route lands.
OVERRIDE_CASE = "bundle_with_override_dual_score"
ENDPOINT_CASE = "unknown_intake_id_404"
SERVICE_CASES = [c for c in CASES if c["_name"] not in {OVERRIDE_CASE, ENDPOINT_CASE}]


def _seed(db_session, seed):
    """Insert the case's rows with autoincrement PKs; return the real intake."""
    p = seed["patient"]
    patient = Patient(
        name=p["name"],
        date_of_birth=date.fromisoformat(p["date_of_birth"]),
        sex=p["sex"],
    )
    db_session.add(patient)
    db_session.flush()

    ir = seed["intake_record"]
    intake = IntakeRecord(
        patient_id=patient.patient_id,
        chief_complaint=ir["chief_complaint"],
        missing_fields=ir["missing_fields"],
        # A real intake always stores "none" (IntakeCreate defaults it); the DB
        # column is nullable but the API never writes NULL, so mirror that here.
        pregnancy_status="none",
    )
    db_session.add(intake)
    db_session.flush()

    ps = seed["patient_severity"]
    severity = PatientSeverity(
        intake_id=intake.intake_id,
        severity_score=ps["severity_score"],
        system_ESI=ps["system_ESI"],
        clinician_ESI=ps["clinician_ESI"],
        score_reason="seed",  # nonnull; real reason is produced by scoring
        confidence=ps["confidence"],
        red_flags=ps["red_flags"],
        red_flag_fired=ps["red_flag_fired"],
        flag_tier=ps["flag_tier"],
    )
    db_session.add(severity)
    db_session.flush()

    ax = seed["ai_explanation"]
    explanation = AIExplanation(
        severity_id=severity.severity_id,
        intake_id=intake.intake_id,
        explanation_text="seed",  # nonnull; real text is asserted elsewhere
        factor_breakdown=ax["factor_breakdown"],
        data_completeness=ax["data_completeness"],
        gaps=ax["gaps"],
    )
    db_session.add(explanation)
    db_session.commit()
    return intake


def _explanation_viewed_count(db_session, intake_id):
    return (
        db_session.query(EventLog)
        .filter(
            EventLog.intake_id == intake_id,
            EventLog.event_type == EventType.EXPLANATION_VIEWED,
        )
        .count()
    )


@pytest.mark.parametrize("case", SERVICE_CASES, ids=lambda c: c["_name"])
def test_get_patient_detail_composition(case, db_session):
    expect = case["expect"]
    intake = _seed(db_session, case["seed"])

    detail = TriageService(db_session).getPatientDetail(intake.intake_id)

    if "patient_name" in expect:
        assert detail.patient.name == expect["patient_name"]
    if "severity_score" in expect:
        assert float(detail.severity.severity_score) == float(expect["severity_score"])
    if "system_ESI" in expect:
        assert detail.severity.system_ESI == expect["system_ESI"]
    if "clinician_ESI" in expect:
        assert detail.severity.clinician_ESI == expect["clinician_ESI"]
    # band_name isn't stored — derived from system_ESI via LABEL_MAP.
    if "band_name" in expect:
        assert LABEL_MAP[detail.severity.system_ESI] == expect["band_name"]
    if "confidence" in expect:
        assert detail.severity.confidence == expect["confidence"]

    # Explanation rehydration.
    if "driver_count" in expect:
        assert len(detail.explanation.named_drivers) == expect["driver_count"]
    if expect.get("drivers_are_Driver_objects"):
        assert all(isinstance(d, Driver) for d in detail.explanation.named_drivers)
    if "gap_keys_present" in expect:
        assert set(detail.explanation.gap_acknowledgement.keys()) == set(expect["gap_keys_present"])
    if "gap_not_provided" in expect:
        assert detail.explanation.gap_acknowledgement["not_provided"] == expect["gap_not_provided"]
    if "gap_assumed" in expect:
        assert detail.explanation.gap_acknowledgement["assumed"] == expect["gap_assumed"]

    if "missing_fields" in expect:
        assert detail.missing_fields == expect["missing_fields"]

    # Red-flag rehydration into Trigger objects (joined from red_flag_rule).
    if "red_flags" in expect:
        assert detail.red_flags == expect["red_flags"]
    if "red_flags_count" in expect:
        assert len(detail.red_flags) == expect["red_flags_count"]
    if expect.get("red_flags_are_Trigger_objects"):
        assert all(isinstance(t, TriggerInfo) for t in detail.red_flags)
    if "red_flag_flag_tier" in expect:
        assert detail.red_flags[0].flag_tier == expect["red_flag_flag_tier"]

    # override is stubbed null until the override route exists.
    if "override" in expect:
        assert detail.override == expect["override"]

    if expect.get("lede_present"):
        assert isinstance(detail.lede, str) and detail.lede

    # age is derived from date_of_birth, never a stored column.
    if expect.get("age_is_derived"):
        assert detail.patient.date_of_birth == date.fromisoformat(case["seed"]["patient"]["date_of_birth"])
        assert age_in_years(detail.patient.date_of_birth) >= 0

    # explanation_viewed fires exactly once for this (fresh) intake.
    if expect.get("event_logged") == "explanation_viewed":
        assert _explanation_viewed_count(db_session, intake.intake_id) == 1


def test_unknown_intake_id_returns_404(client, db_session):
    case = BY_NAME[ENDPOINT_CASE]
    intake_id = case["call"]["intake_id"]

    resp = client.get(f"/intakes/{intake_id}")

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
    # No bundle assembled -> no explanation_viewed event.
    assert _explanation_viewed_count(db_session, intake_id) == 0


@pytest.mark.xfail(reason="override composition not implemented; PatientDetail.override is hardcoded null")
def test_override_dual_score(db_session):
    case = BY_NAME[OVERRIDE_CASE]
    intake = _seed(db_session, case["seed"])

    detail = TriageService(db_session).getPatientDetail(intake.intake_id)

    assert detail.override is not None
    assert detail.override.reason_code == case["expect"]["override_reason_code"]
