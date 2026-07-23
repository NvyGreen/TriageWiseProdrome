"""ScoringEngine missing-data fallback tests, driven by fallback_test_cases.json.

Covers applyFallback and the four data-quality signals on SeverityResult:
missing_fields, fallbacks_applied, data_completeness, confidence (reqs 1.2).
See test_scoring.py for the shared engine facts (real DB seeding, int->"ESI-N").

Shape notes:
  - result.missing_fields is a set of FIELD names -> compare unordered.
  - result.fallbacks_applied is a dict {field: action}; the JSON lists
    [{field, action}] -> convert to a dict before comparing.
  - esi_band is the FINAL (refined) band -> assert against result.esi_level.
"""
import json
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select, update

from app.models.intake_record import IntakeRecord
from app.models.patient import Patient
from app.models.patient_severity import PatientSeverity
from app.services.scoring_engine import ScoringEngine, CannotScoreError

UNIT_CASES = Path(__file__).parent / "unit_cases"
CASES = json.loads((UNIT_CASES / "fallback_test_cases.json").read_text(encoding="utf-8"))["cases"]

BY_NAME = {c["_name"]: c for c in CASES}
SPECIAL = {"fallback_used_flag_set_on_persist", "missing_chief_complaint_is_unscoreable"}
STANDARD = [c for c in CASES if c["_name"] not in SPECIAL]


def _seed_intake(db_session, intake_fields):
    patient = Patient(name="Fallback Patient", date_of_birth=date(1980, 5, 17), sex="M")
    db_session.add(patient)
    db_session.flush()

    intake = IntakeRecord(patient_id=patient.patient_id, **intake_fields)
    db_session.add(intake)
    db_session.commit()
    return intake


def _fallbacks_to_dict(entries):
    """The JSON lists [{field, action}]; the engine returns {field: action}."""
    return {e["field"]: e["action"] for e in entries}


@pytest.mark.parametrize("case", STANDARD, ids=lambda c: c["_name"])
def test_fallback_signals(case, db_session):
    intake = _seed_intake(db_session, case["intake"])
    result = ScoringEngine(db_session).score(intake, db_session)
    db_session.commit()

    expect = case["expect"]
    assert result.severity_score == expect["severity_score"]
    assert result.esi_level == f"ESI-{expect['esi_band']}"
    assert result.confidence == expect["confidence"]

    # Not every case pins every signal; assert only the ones present.
    if "missing_fields" in expect:
        assert set(result.missing_fields) == set(expect["missing_fields"])
    if "fallbacks_applied" in expect:
        assert result.fallbacks_applied == _fallbacks_to_dict(expect["fallbacks_applied"])
    if "data_completeness" in expect:
        assert result.data_completeness == expect["data_completeness"]


def test_fallback_persisted_on_severity_row(db_session):
    """A fired fallback must be written to patient_severity (non-empty) with LOW confidence."""
    case = BY_NAME["fallback_used_flag_set_on_persist"]
    intake = _seed_intake(db_session, case["intake"])
    result = ScoringEngine(db_session).score(intake, db_session)
    db_session.commit()

    expect = case["expect"]
    assert result.severity_score == expect["severity_score"]
    assert result.esi_level == f"ESI-{expect['esi_band']}"

    severity = db_session.scalar(
        select(PatientSeverity).where(PatientSeverity.intake_id == intake.intake_id)
    )
    assert severity is not None
    assert severity.fallbacks_applied  # non-empty
    assert severity.confidence == expect["persisted_confidence"]


def test_missing_chief_complaint_raises(db_session):
    """chief_complaint has no fallback — it's required. The engine raises rather
    than score. It's NOT NULL, so the intake can't be persisted; pass a transient
    row. The raise happens before any PatientSeverity write, so nothing persists.
    """
    case = BY_NAME["missing_chief_complaint_is_unscoreable"]
    # Transient (never added/committed) — a null chief_complaint can't be stored.
    intake = IntakeRecord(**case["intake"])
    engine = ScoringEngine(db_session)

    with pytest.raises(CannotScoreError):
        engine.score(intake, db_session)
