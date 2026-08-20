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


# Coverage-clause branches the JSON cases don't hit: one gap group empty while the
# other is populated (all JSON non-5/5 cases have BOTH groups non-empty).
_LEDE_DRIVERS = [
    {"rule_id": 9, "factor": "Chief complaint", "threshold": "chest pain (cardiac concern)",
     "unit": "", "weight": 6, "patient_value": "cardiac", "contribution_pct": 60, "esi_anchor": "a"},
    {"rule_id": 3, "factor": "Heart rate", "threshold": "> 120 bpm",
     "unit": "bpm", "weight": 3, "patient_value": 124, "contribution_pct": 40, "esi_anchor": "b"},
]


def test_lede_coverage_only_missing_no_assumed(db_session):
    severity = PatientSeverity(severity_score=5, system_ESI="ESI-3")
    explanation = AIExplanation(
        factor_breakdown=_LEDE_DRIVERS,
        data_completeness="4 of 5",
        gaps={"assumed": [], "not_provided": ["respiration_rate"]},
    )
    lede = TriageService(db_session)._render_lede(severity, explanation)
    assert "Respiratory rate missing" in lede
    assert "assumed" not in lede


def test_lede_coverage_only_assumed_no_missing(db_session):
    severity = PatientSeverity(severity_score=6, system_ESI="ESI-2")
    explanation = AIExplanation(
        factor_breakdown=_LEDE_DRIVERS,
        data_completeness="4 of 5",
        gaps={"assumed": ["oxygen_saturation"], "not_provided": []},
    )
    lede = TriageService(db_session)._render_lede(severity, explanation)
    assert "SpO2 assumed" in lede
    assert "missing" not in lede
