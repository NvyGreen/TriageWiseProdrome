"""Service-layer tests for TriageService.getPatientDetail composition.

Layer A of patient_detail_test_cases.json (`service_cases`): assert on the
PatientDetail DOMAIN OBJECT — domain types (Driver / TriggerInfo instances),
domain attr casing (system_ESI), missing_fields present, override None when
absent. No status_code and no event here — the service alone logs nothing (the
route fires explanation_viewed). The emitted-JSON layer lives in
test_intake_endpoint.py.

PKs are NOT pinned: the JSON's patient_id/intake_id are only join keys; rows are
inserted with autoincrement and the real generated intake_id is threaded through,
so the persistent _test DB can't duplicate-key on a re-run.

band_name and age aren't fields on the bundle — derived here from system_ESI
(via LABEL_MAP) and date_of_birth, which the bundle does expose.
"""
import json
from datetime import date
from pathlib import Path

import pytest

from app.models.ai_explanation import AIExplanation
from app.models.intake_record import IntakeRecord
from app.models.patient import Patient
from app.models.patient_severity import PatientSeverity
from app.schemas.trigger_info import TriggerInfo
from app.services.triage_service import LABEL_MAP, TriageService
from app.utils.dates import age_in_years
from app.utils.driver import Driver

UNIT_CASES = Path(__file__).parent / "unit_cases"
SERVICE_CASES = json.loads(
    (UNIT_CASES / "patient_detail_test_cases.json").read_text(encoding="utf-8")
)["service_cases"]

# Override composition isn't built yet (PatientDetail.override is hardcoded None),
# so the override case can't pass — xfailed until the override route lands.
OVERRIDE_CASE = "svc_override_present"


def _param(case):
    marks = (
        [pytest.mark.xfail(reason="override composition not implemented; PatientDetail.override is hardcoded None")]
        if case["_name"] == OVERRIDE_CASE
        else []
    )
    return pytest.param(case, id=case["_name"], marks=marks)


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
        # IntakeInfo.pregnancy_status is a required enum; a real intake always
        # stores "none" (IntakeCreate defaults it), so mirror that here.
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


@pytest.mark.parametrize("case", [_param(c) for c in SERVICE_CASES])
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

    # Red-flag rehydration into TriggerInfo objects (joined from red_flag_rule).
    if expect.get("red_flags_empty"):
        assert detail.red_flags == []
    if "red_flags_count" in expect:
        assert len(detail.red_flags) == expect["red_flags_count"]
    if expect.get("red_flags_are_Trigger_objects"):
        assert all(isinstance(t, TriggerInfo) for t in detail.red_flags)
    if "red_flag_flag_tier" in expect:
        assert detail.red_flags[0].flag_tier == expect["red_flag_flag_tier"]

    # override is None until the override route exists.
    if "override_is_none" in expect:
        assert (detail.override is None) == expect["override_is_none"]
    if "override_reason_code" in expect:
        assert detail.override is not None
        assert detail.override.reason_code == expect["override_reason_code"]

    if expect.get("lede_present"):
        assert isinstance(detail.lede, str) and detail.lede

    # age is derived from date_of_birth, never a stored column.
    if expect.get("age_is_derived"):
        assert detail.patient.date_of_birth == date.fromisoformat(case["seed"]["patient"]["date_of_birth"])
        assert age_in_years(detail.patient.date_of_birth) >= 0
