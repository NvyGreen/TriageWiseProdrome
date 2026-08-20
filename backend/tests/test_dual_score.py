"""Dual-score rendering tests, driven by dual_score_test_cases.json (req R2).

_render_dual_score(severity, explanation) -> (dual_score_line, xai_line) reads only
attributes off a PatientSeverity + AIExplanation (no DB access), so each case builds
UNPERSISTED ORM objects and calls the renderer directly — no seeding, no commit. The
service still needs a db to construct, so db_session is passed but never queried.

Pure function: assert the returned tuple equals the case's two expected strings exactly.
"""
import json
from datetime import date
from pathlib import Path

import pytest

from app.models.ai_explanation import AIExplanation
from app.models.intake_record import IntakeRecord
from app.models.override import Override
from app.models.patient import Patient
from app.models.patient_severity import PatientSeverity
from app.services.triage_service import TriageService

UNIT_CASES = Path(__file__).parent / "unit_cases"
CASES = json.loads((UNIT_CASES / "dual_score_test_cases.json").read_text(encoding="utf-8"))["cases"]


def _severity(inputs):
    return PatientSeverity(
        system_ESI=inputs["system_ESI"],
        clinician_ESI=inputs["clinician_ESI"],
    )


def _explanation(inputs):
    return AIExplanation(factor_breakdown=inputs["factor_breakdown"])


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["_name"])
def test_render_dual_score(case, db_session):
    inputs = case["inputs"]
    severity = _severity(inputs)
    explanation = _explanation(inputs)

    service = TriageService(db_session)  # db is unused by _render_dual_score
    dual_score_line, xai_line = service._render_dual_score(severity, explanation)

    assert dual_score_line == case["expect"]["dual_score_line"]
    assert xai_line == case["expect"]["xai_line"]


def test_dual_score_appends_override_note(db_session):
    """A persisted override carrying a note surfaces it in the score line. Needs
    real rows (the renderer queries Override by severity_id), unlike the pure cases."""
    patient = Patient(name="Note Case", date_of_birth=date(1980, 1, 1), sex="M")
    db_session.add(patient)
    db_session.flush()
    intake = IntakeRecord(patient_id=patient.patient_id, chief_complaint="cardiac")
    db_session.add(intake)
    db_session.flush()
    severity = PatientSeverity(
        intake_id=intake.intake_id, severity_score=6, system_ESI="ESI-2",
        clinician_ESI="ESI-1", score_reason="seed", confidence="HIGH",
        red_flags=[], red_flag_fired=False, flag_tier=3,
    )
    db_session.add(severity)
    db_session.flush()
    db_session.add(Override(
        intake_id=intake.intake_id, severity_id=severity.severity_id,
        system_ESI="ESI-2", clinician_ESI="ESI-1", reason_code="Other", note="Clear STEMI",
    ))
    db_session.commit()

    explanation = AIExplanation(factor_breakdown=[], data_completeness="5 of 5", gaps={})
    score_line, _ = TriageService(db_session)._render_dual_score(severity, explanation)

    assert "Override reason: Other" in score_line
    assert "Clear STEMI" in score_line
