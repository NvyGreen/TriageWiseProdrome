"""Dual-score rendering tests, driven by dual_score_test_cases.json (req R2).

_render_dual_score(severity, explanation) -> (dual_score_line, xai_line) reads only
attributes off a PatientSeverity + AIExplanation (no DB access), so each case builds
UNPERSISTED ORM objects and calls the renderer directly — no seeding, no commit. The
service still needs a db to construct, so db_session is passed but never queried.

Pure function: assert the returned tuple equals the case's two expected strings exactly.
"""
import json
from pathlib import Path

import pytest

from app.models.ai_explanation import AIExplanation
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
