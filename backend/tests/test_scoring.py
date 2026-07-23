"""ScoringEngine tests, driven by scoring_test_cases.json.

Covers rule firing, weight summation, and point-to-band mapping (reqs 1.4, 1.12).
Resource refinement and missing-data fallback are separate JSON files.

Key facts about the engine that shape these tests:
  - ScoringEngine(db) snapshots the ACTIVE rules in __init__, so any is_active
    change must happen BEFORE the engine is built.
  - score(intake, db) takes a persisted IntakeRecord and writes a PatientSeverity
    row, so each case seeds a real intake and commits (real DB, like
    test_triage_service.py).
  - The JSON's `esi_band` is the RAW point-to-band. `general` has
    resource_level="one", which refines a raw ESI-3 down to ESI-4 — so we assert
    against result.initial_esi (pre-refinement), not result.esi_level.
  - `fired_rules` is recovered from result.named_drivers (one driver per fired
    rule). Order isn't guaranteed to match the JSON, so compare as sets.
  - Vital drivers format patient_value as "<value> <units>" (e.g. "124 bpm"),
    "%" vitals have no space ("89%"), and a complaint stays raw ("abdominal").
"""
import json
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import update

from app.models.intake_record import IntakeRecord
from app.models.patient import Patient
from app.models.scoring_rule import ScoringRule
from app.services.scoring_engine import ScoringEngine

UNIT_CASES = Path(__file__).parent / "unit_cases"
CASES = json.loads((UNIT_CASES / "scoring_test_cases.json").read_text(encoding="utf-8"))["cases"]

# Cases needing special handling are pulled out; the rest are the plain
# score + band + fired-rules checks.
BY_NAME = {c["_name"]: c for c in CASES}
SPECIAL = {
    "inactive_rule_is_skipped",       # mutates scoring_rule.is_active
    "determinism_same_input_same_score",
    "drivers_trace_to_fired_rules_only",
}
STANDARD = [c for c in CASES if c["_name"] not in SPECIAL]


def _seed_intake(db_session, intake_fields):
    """Persist a Patient + IntakeRecord from a case's `intake` dict."""
    patient = Patient(name="Scoring Patient", date_of_birth=date(1980, 5, 17), sex="M")
    db_session.add(patient)
    db_session.flush()

    intake = IntakeRecord(patient_id=patient.patient_id, **intake_fields)
    db_session.add(intake)
    db_session.commit()
    return intake


def _fired_ids(result):
    return {d.rule_id for d in result.named_drivers}


def _expected_esi(case):
    # JSON esi_band is the raw band -> compare to initial_esi.
    return f"ESI-{case['expect']['esi_band']}"


@pytest.mark.parametrize("case", STANDARD, ids=lambda c: c["_name"])
def test_score_and_band(case, db_session):
    intake = _seed_intake(db_session, case["intake"])
    result = ScoringEngine(db_session).score(intake, db_session)
    db_session.commit()

    expect = case["expect"]
    assert result.severity_score == expect["severity_score"]
    assert result.initial_esi == _expected_esi(case)
    assert _fired_ids(result) == set(expect["fired_rules"])


def test_inactive_rule_is_skipped(db_session):
    """A deactivated rule contributes nothing. Flip is_active in the DB, build the
    engine AFTER (it snapshots rules), then restore in finally so the shared test
    DB isn't left polluted."""
    case = BY_NAME["inactive_rule_is_skipped"]
    (rule_id,) = case["setup"]["deactivate_rules"]

    db_session.execute(
        update(ScoringRule).where(ScoringRule.rule_id == rule_id).values(is_active=False)
    )
    db_session.commit()
    try:
        engine = ScoringEngine(db_session)  # snapshot excludes the disabled rule
        intake = _seed_intake(db_session, case["intake"])
        result = engine.score(intake, db_session)
        db_session.commit()

        expect = case["expect"]
        assert result.severity_score == expect["severity_score"]
        assert result.initial_esi == _expected_esi(case)
        assert _fired_ids(result) == set(expect["fired_rules"])
    finally:
        db_session.execute(
            update(ScoringRule).where(ScoringRule.rule_id == rule_id).values(is_active=True)
        )
        db_session.commit()


def test_determinism_same_input_same_score(db_session):
    """Same intake scored twice -> identical output (req 1.4 DoD)."""
    case = BY_NAME["determinism_same_input_same_score"]
    intake = _seed_intake(db_session, case["intake"])
    engine = ScoringEngine(db_session)

    first = engine.score(intake, db_session)
    db_session.commit()
    second = engine.score(intake, db_session)
    db_session.commit()

    assert first.severity_score == second.severity_score
    assert first.initial_esi == second.initial_esi
    assert _fired_ids(first) == _fired_ids(second)

    expect = case["expect"]
    assert first.severity_score == expect["severity_score"]
    assert first.initial_esi == _expected_esi(case)
    assert _fired_ids(first) == set(expect["fired_rules"])


def test_drivers_trace_to_fired_rules_only(db_session):
    """One driver per fired rule, each carrying the patient's actual value."""
    case = BY_NAME["drivers_trace_to_fired_rules_only"]
    intake = _seed_intake(db_session, case["intake"])
    result = ScoringEngine(db_session).score(intake, db_session)
    db_session.commit()

    expect = case["expect"]
    by_id = {d.rule_id: d for d in result.named_drivers}

    # driver_count_equals_fired_rules: no invented or dropped drivers.
    assert set(by_id) == set(expect["fired_rules"])
    assert len(result.named_drivers) == len(expect["fired_rules"])

    for exp in expect["named_drivers"]:
        driver = by_id[exp["rule_id"]]
        assert driver.weight == exp["weight"]
        # patient_value is formatted ("124 bpm" / "89%" / "abdominal"); assert the
        # raw value is present rather than hardcoding each unit string.
        assert str(exp["patient_value"]) in str(driver.patient_value)
