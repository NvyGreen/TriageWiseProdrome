"""ScoringEngine.refineByResource tests, driven by esi_refinement_test_cases.json.

The second scoring step: an ESI-3 point-band is refined by the complaint's
resource_level (many -> stays ESI-3, one -> ESI-4, none -> ESI-5); other bands
are untouched. See test_scoring.py for the shared engine facts (real DB seeding,
is_active snapshot, int->"ESI-N" mapping).

initial_esi (raw band) and esi_band (final/refined band) are DISTINCT here, so
we assert them against result.initial_esi and result.esi_level respectively.
"""
import json
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select, update

from app.models.intake_record import IntakeRecord
from app.models.patient import Patient
from app.models.patient_severity import PatientSeverity
from app.models.scoring_rule import ScoringRule
from app.services.scoring_engine import ScoringEngine

UNIT_CASES = Path(__file__).parent / "unit_cases"
CASES = json.loads((UNIT_CASES / "esi_refinement_test_cases.json").read_text(encoding="utf-8"))["cases"]

BY_NAME = {c["_name"]: c for c in CASES}
# The one case that deactivates a rule and expects a raise is handled on its own.
RAISES_CASE = "no_complaint_rule_fires_raises"
STANDARD = [c for c in CASES if c["_name"] != RAISES_CASE]


def _seed_intake(db_session, intake_fields):
    patient = Patient(name="Refinement Patient", date_of_birth=date(1980, 5, 17), sex="M")
    db_session.add(patient)
    db_session.flush()

    intake = IntakeRecord(patient_id=patient.patient_id, **intake_fields)
    db_session.add(intake)
    db_session.commit()
    return intake


@pytest.mark.parametrize("case", STANDARD, ids=lambda c: c["_name"])
def test_refinement(case, db_session):
    intake = _seed_intake(db_session, case["intake"])
    result = ScoringEngine(db_session).score(intake, db_session)
    db_session.commit()

    expect = case["expect"]
    assert result.severity_score == expect["severity_score"]
    assert result.initial_esi == f"ESI-{expect['initial_esi']}"   # raw band
    assert result.esi_level == f"ESI-{expect['esi_band']}"        # final band
    assert result.resource_level == expect["resource_level"]
    assert result.refined == expect["refined"]


def test_no_complaint_rule_fires_raises(db_session):
    """Rule 13 off -> no complaint fires -> resource_level None -> TypeError.

    Refusing to score beats silently defaulting to 'none' (which would drop the
    patient to ESI-5 — an under-triage from a config toggle). The raise happens
    before the PatientSeverity write, so no score row is produced.
    """
    case = BY_NAME[RAISES_CASE]
    (rule_id,) = case["setup"]["deactivate_rules"]

    db_session.execute(
        update(ScoringRule).where(ScoringRule.rule_id == rule_id).values(is_active=False)
    )
    db_session.commit()
    try:
        engine = ScoringEngine(db_session)  # snapshot excludes the disabled rule
        intake = _seed_intake(db_session, case["intake"])

        with pytest.raises(TypeError):
            engine.score(intake, db_session)
        db_session.rollback()

        # no_score_produced: nothing was persisted for this intake.
        severity = db_session.scalar(
            select(PatientSeverity).where(PatientSeverity.intake_id == intake.intake_id)
        )
        assert severity is None
    finally:
        db_session.execute(
            update(ScoringRule).where(ScoringRule.rule_id == rule_id).values(is_active=True)
        )
        db_session.commit()
