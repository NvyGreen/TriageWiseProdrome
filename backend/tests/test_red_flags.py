"""RedFlagLayer tests, driven by red_flag_test_cases.json (reqs 1.31, 1.33).

Each case seeds an intake, runs the REAL ScoringEngine to get a genuine
SeverityResult (so `all_vitals_normal` is derived from real drivers, not
hand-faked), then runs RedFlagLayer and checks the fired flags + tier.

The layer's method is `score(intake, severity, db) -> list[Trigger]`, so:
  - fired flag ids  = sorted(t.flag_id for t in triggers)
  - flag_tier       = min tier among fired flags, else 3 (no flag)
The min-tier / persistence to patient_severity is NOT done here; we derive it.

Invariant: red flags never change the score — assert severity_score is the same
before and after the layer runs.

Intakes must be persisted: the age helpers (flags 1, 8) look the patient up by
intake.patient_id. `date_of_birth` lives on Patient; everything else on IntakeRecord.
"""
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.models.intake_record import IntakeRecord
from app.models.patient import Patient
from app.services.red_flag_layer import RedFlagLayer
from app.services.scoring_engine import ScoringEngine

UNIT_CASES = Path(__file__).parent / "unit_cases"
CASES = json.loads((UNIT_CASES / "red_flag_test_cases.json").read_text(encoding="utf-8"))["cases"]


def _seed(db_session, case_intake):
    """Persist a Patient (dob) + IntakeRecord (everything else) from a case's intake.

    A case may carry `_dob_days_ago` instead of a literal `date_of_birth`; the dob
    is then computed as today minus that many days, so an age-window case (the
    febrile neonate) stays inside its window as the calendar moves.
    """
    fields = dict(case_intake)
    days_ago = fields.pop("_dob_days_ago", None)
    if days_ago is not None:
        dob = date.today() - timedelta(days=days_ago)
    else:
        dob = date.fromisoformat(fields.pop("date_of_birth"))

    patient = Patient(name="Flag Patient", date_of_birth=dob, sex="M")
    db_session.add(patient)
    db_session.flush()

    intake = IntakeRecord(patient_id=patient.patient_id, **fields)
    db_session.add(intake)
    db_session.commit()
    return intake


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["_name"])
def test_red_flags(case, db_session):
    intake = _seed(db_session, case["intake"])

    # Real scoring -> real drivers, so all_vitals_normal is genuinely derived.
    severity = ScoringEngine(db_session).score(intake, RedFlagLayer(db_session), db_session)
    db_session.commit()

    score_before = severity.severity_score
    triggers = RedFlagLayer(db_session).check(intake, severity, db_session)

    fired = sorted(t.flag_id for t in triggers)
    flag_tier = min((t.flag_tier for t in triggers), default=3)

    expect = case["expect"]
    assert fired == sorted(expect["fired"])
    assert flag_tier == expect["flag_tier"]
    # score_unchanged: the layer must never mutate the severity.
    assert severity.severity_score == score_before
