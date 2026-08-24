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
from fastapi.exceptions import HTTPException

from app.models.intake_record import IntakeRecord
from app.models.patient import Patient
from app.services.red_flag_layer import RedFlagLayer, _between, _in, _contains_any
from app.services.scoring_engine import ScoringEngine
from app.utils.trigger import Trigger

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
    _, severity = ScoringEngine(db_session).score(intake, RedFlagLayer(db_session), db_session)
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


# --- Branch / error-path coverage (not driven by the JSON cases) ---

def _custom_layer(db_session, tree):
    """A RedFlagLayer with one hand-crafted trigger, to drive the pattern-tree
    parser directly. These trees don't read `score`, so check() is called with None."""
    layer = RedFlagLayer(db_session)
    layer.triggers = [Trigger(999, "test-pattern", tree, "obvious", 1, "msg", "why")]
    return layer


def _fired_ids(layer, intake, db_session):
    return [t.flag_id for t in layer.check(intake, None, db_session)]


def test_between_rejects_non_list():
    with pytest.raises(TypeError):
        _between(5, "not-a-list")


def test_between_rejects_wrong_length():
    with pytest.raises(TypeError):
        _between(5, [1, 2, 3])


def test_in_rejects_non_list():
    with pytest.raises(TypeError):
        _in("x", "not-a-list")


def test_contains_any_rejects_non_list():
    with pytest.raises(TypeError):
        _contains_any("not-a-list", [])


def test_field_only_pattern_tree(db_session):
    layer = _custom_layer(db_session, {"field": "heart_rate", "cmp": ">", "value": 100})
    assert _fired_ids(layer, IntakeRecord(heart_rate=120), db_session) == [999]


def test_and_within_and(db_session):
    tree = {"op": "AND", "conditions": [
        {"op": "AND", "conditions": [{"field": "heart_rate", "cmp": ">", "value": 100}]},
    ]}
    assert _fired_ids(_custom_layer(db_session, tree), IntakeRecord(heart_rate=120), db_session) == [999]


def test_or_within_or(db_session):
    tree = {"op": "OR", "conditions": [
        {"op": "OR", "conditions": [{"field": "heart_rate", "cmp": ">", "value": 100}]},
    ]}
    assert _fired_ids(_custom_layer(db_session, tree), IntakeRecord(heart_rate=120), db_session) == [999]


def test_and_within_or(db_session):
    tree = {"op": "OR", "conditions": [
        {"op": "AND", "conditions": [{"field": "heart_rate", "cmp": ">", "value": 100}]},
    ]}
    assert _fired_ids(_custom_layer(db_session, tree), IntakeRecord(heart_rate=120), db_session) == [999]


def test_helper_within_or(db_session):
    # heart_rate 95 is borderline (90-99) -> count_borderline_vitals == 1.
    tree = {"op": "OR", "conditions": [
        {"helper": "count_borderline_vitals", "cmp": ">=", "value": 1},
    ]}
    assert _fired_ids(_custom_layer(db_session, tree), IntakeRecord(heart_rate=95), db_session) == [999]


# Malformed trees fall through the elif chains to the "Unrecognized format" raises.

def test_unrecognized_top_op_raises(db_session):
    layer = _custom_layer(db_session, {"op": "XOR", "conditions": [{"field": "heart_rate", "cmp": ">", "value": 100}]})
    with pytest.raises(HTTPException):
        layer.check(IntakeRecord(), None, db_session)


def test_unrecognized_top_node_raises(db_session):
    with pytest.raises(HTTPException):
        _custom_layer(db_session, {"unknown": "node"}).check(IntakeRecord(), None, db_session)


def test_unrecognized_op_within_and_raises(db_session):
    tree = {"op": "AND", "conditions": [{"op": "XOR", "conditions": [{"field": "heart_rate", "cmp": ">", "value": 100}]}]}
    with pytest.raises(HTTPException):
        _custom_layer(db_session, tree).check(IntakeRecord(), None, db_session)


def test_unrecognized_node_within_and_raises(db_session):
    tree = {"op": "AND", "conditions": [{"unknown": "node"}]}
    with pytest.raises(HTTPException):
        _custom_layer(db_session, tree).check(IntakeRecord(), None, db_session)


def test_unrecognized_op_within_or_raises(db_session):
    tree = {"op": "OR", "conditions": [{"op": "XOR", "conditions": [{"field": "heart_rate", "cmp": ">", "value": 100}]}]}
    with pytest.raises(HTTPException):
        _custom_layer(db_session, tree).check(IntakeRecord(), None, db_session)


def test_unrecognized_node_within_or_raises(db_session):
    tree = {"op": "OR", "conditions": [{"unknown": "node"}]}
    with pytest.raises(HTTPException):
        _custom_layer(db_session, tree).check(IntakeRecord(), None, db_session)


def test_unrecognized_helper_raises(db_session):
    with pytest.raises(HTTPException):
        _custom_layer(db_session, {"helper": "bogus", "cmp": ">", "value": 1}).check(IntakeRecord(), None, db_session)
