"""Lede rendering tests, driven by lede_test_cases.json (req 1.9).

_render_lede reads only attributes off a PatientSeverity + AIExplanation (no DB
access), so each case builds UNPERSISTED ORM objects and calls the renderer
directly — no seeding, no commit. The service still needs a db to construct, so
the db_session fixture is passed but never queried.

expected_lede is the source of truth: the renderer is deterministic, so we assert
the full string equals it exactly, then render twice to prove determinism.
"""
import json
from pathlib import Path

import pytest

from app.models.ai_explanation import AIExplanation
from app.models.patient_severity import PatientSeverity
from app.services.triage_service import TriageService

UNIT_CASES = Path(__file__).parent / "unit_cases"
CASES = json.loads((UNIT_CASES / "lede_test_cases.json").read_text(encoding="utf-8"))["cases"]


def _severity(inputs):
    return PatientSeverity(
        severity_score=inputs["severity_score"],
        system_ESI=inputs["system_ESI"],
    )


def _explanation(inputs):
    # 5/5 cases never read gaps; default to empty buckets so the attr always exists.
    gaps = inputs.get("gaps", {"assumed": [], "not_provided": []})
    return AIExplanation(
        factor_breakdown=inputs["factor_breakdown"],
        data_completeness=inputs["data_completeness"],
        gaps=gaps,
    )


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["_name"])
def test_render_lede(case, db_session):
    inputs = case["inputs"]
    severity = _severity(inputs)
    explanation = _explanation(inputs)

    service = TriageService(db_session)  # db is unused by _render_lede
    lede = service._render_lede(severity, explanation)

    assert lede == case["expect"]["expected_lede"]
    # Deterministic: same inputs -> identical text.
    assert service._render_lede(severity, explanation) == lede
