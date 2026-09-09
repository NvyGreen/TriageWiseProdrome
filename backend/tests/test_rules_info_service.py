"""Service-only tests for RulesInfoService (the Scoring & Rules page's backend).

Read-only over the reference tables that conftest seeds (scoring_rule, esi_band,
red_flag_rule), so most tests assert against the shipped reference data. Defensive
branches (unknown rule type, bad tier) and the ESI-3 resource refinement are
driven by crafting a row and tearing it down. The endpoint isn't tested here — the
service is exercised directly.
"""
import pytest
from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError
from fastapi.exceptions import HTTPException

from app.models.scoring_rule import ScoringRule
from app.models.red_flag_rule import RedFlagRule
from app.services.rules_info_service import RulesInfoService, HELPER_FIELDS


def _summarize(tree):
    # _summarize_tree never touches self.db, so a db-less instance is fine.
    return RulesInfoService(None)._summarize_tree(tree)


# --- _summarize_tree (pure, no DB) -----------------------------------------

def test_summarize_bare_field():
    out = _summarize({"field": "heart_rate", "cmp": ">", "value": 100})
    assert out == {"depth": 0, "fields": ["heart_rate"], "helpers": []}


def test_summarize_bare_helper():
    out = _summarize({"helper": "age_in_days", "cmp": "<", "value": 28})
    # a helper surfaces the intake fields it inspects (age -> date_of_birth)
    assert out == {"depth": 0, "fields": ["date_of_birth"], "helpers": ["age_in_days"]}


def test_summarize_single_op_level():
    tree = {"op": "AND", "conditions": [
        {"field": "temperature", "cmp": ">", "value": 100.4},
        {"field": "heart_rate", "cmp": ">", "value": 120},
    ]}
    out = _summarize(tree)
    assert out["depth"] == 1
    assert out["fields"] == ["heart_rate", "temperature"]  # sorted
    assert out["helpers"] == []


def test_summarize_nested_ops_depth():
    tree = {"op": "OR", "conditions": [
        {"op": "AND", "conditions": [{"field": "heart_rate", "cmp": ">", "value": 120}]},
    ]}
    assert _summarize(tree)["depth"] == 2


def test_summarize_dedups_and_collects_helpers():
    tree = {"op": "AND", "conditions": [
        {"field": "heart_rate", "cmp": ">", "value": 120},
        {"field": "heart_rate", "cmp": "<", "value": 40},   # duplicate field
        {"helper": "all_vitals_normal"},
    ]}
    out = _summarize(tree)
    assert out["depth"] == 1
    assert out["helpers"] == ["all_vitals_normal"]
    # field leaf de-duplicated, plus the vitals the helper inspects (sorted)
    assert out["fields"] == sorted({"heart_rate"} | set(HELPER_FIELDS["all_vitals_normal"]))


@pytest.mark.parametrize("bad", [None, {}, {"unknown": "node"}, "not-a-dict"])
def test_summarize_malformed_is_empty(bad):
    assert _summarize(bad) == {"depth": 0, "fields": [], "helpers": []}


# --- scoring_rules ----------------------------------------------------------

def test_scoring_rules_shape_and_values(db_session):
    result = RulesInfoService(db_session).scoring_rules()

    assert set(result) == {"complaint", "vital", "age", "total_rules", "active_rules"}

    by_complaint = {r["complaint_group"]: r for r in result["complaint"]}
    assert set(by_complaint["cardiac"]) == {"weight", "complaint_group", "resource_level", "esi_anchor"}
    assert by_complaint["cardiac"]["weight"] == 6
    assert by_complaint["stroke"]["weight"] == 6
    assert by_complaint["abdominal"]["weight"] == 2
    assert by_complaint["general"]["weight"] == 1

    assert result["vital"]
    assert set(result["vital"][0]) == {"weight", "factor", "min_bound", "max_bound", "units"}

    assert len(result["age"]) == 2
    assert all(r["factor"] == "Age" for r in result["age"])

    # total_rules counts every row; every shipped rule is active
    assert result["total_rules"] == len(result["complaint"]) + len(result["vital"]) + len(result["age"])
    assert result["active_rules"] == result["total_rules"]


def test_scoring_rules_unknown_type_raises(db_session):
    db_session.add(ScoringRule(
        rule_id=9110, rule_type="bogus", factor="x", threshold_display="t",
        weight=1, esi_anchor="a", fallback_if_missing="n/a",
    ))
    db_session.commit()
    try:
        with pytest.raises(HTTPException) as exc:
            RulesInfoService(db_session).scoring_rules()
        assert exc.value.status_code == 500
    finally:
        db_session.execute(delete(ScoringRule).where(ScoringRule.rule_id == 9110))
        db_session.commit()


# --- esi_bands --------------------------------------------------------------

def test_esi_bands(db_session):
    bands = RulesInfoService(db_session).esi_bands()

    assert len(bands) == 5
    assert {b["esi_level"] for b in bands} == {"ESI-1", "ESI-2", "ESI-3", "ESI-4", "ESI-5"}
    for b in bands:
        assert set(b) == {"esi_level", "min_points", "max_points", "label"}
        assert isinstance(b["min_points"], int)

    by_level = {b["esi_level"]: b for b in bands}
    assert by_level["ESI-5"]["min_points"] == 0
    # ESI-1 is the most acute -> highest points floor
    assert by_level["ESI-1"]["min_points"] == max(b["min_points"] for b in bands)


# --- red_flag_rules ---------------------------------------------------------

def test_red_flag_rules_shape(db_session):
    result = RulesInfoService(db_session).red_flag_rules()

    assert set(result) == {"Tier 1", "Tier 2"}
    all_flags = result["Tier 1"] + result["Tier 2"]
    assert len(all_flags) == 11

    for f in all_flags:
        assert set(f) == {"message", "rationale", "flag_tier", "depth", "fields", "helpers"}
        assert isinstance(f["depth"], int) and f["depth"] >= 0
        assert isinstance(f["fields"], list) and isinstance(f["helpers"], list)

    assert all(f["flag_tier"] == 1 for f in result["Tier 1"])
    assert all(f["flag_tier"] == 2 for f in result["Tier 2"])

    # the tree walker actually pulled helpers out of the real rules
    all_helpers = {h for f in all_flags for h in f["helpers"]}
    assert all_helpers


def test_red_flag_rules_bad_tier_raises(db_session):
    db_session.add(RedFlagRule(
        flag_id=9110, trigger_pattern="ztest",
        trigger_pattern_tree={"field": "heart_rate", "cmp": ">", "value": 100},
        flag_type="obvious", flag_tier=3, message="ztest bad tier",
        evidence_source="test", outcome_validated="no",
    ))
    db_session.commit()
    try:
        with pytest.raises(HTTPException) as exc:
            RulesInfoService(db_session).red_flag_rules()
        assert exc.value.status_code == 500
    finally:
        db_session.execute(delete(RedFlagRule).where(RedFlagRule.flag_id == 9110))
        db_session.commit()


# --- complaint_esi ----------------------------------------------------------

def test_complaint_esi_values(db_session):
    result = RulesInfoService(db_session).complaint_esi()
    by_complaint = {r["complaint"]: r for r in result}

    for r in result:
        assert set(r) == {"complaint", "points", "esi"}

    assert by_complaint["cardiac"]["points"] == 6
    assert by_complaint["cardiac"]["esi"] == "ESI-2"
    assert by_complaint["stroke"]["esi"] == "ESI-2"
    assert by_complaint["respiratory"]["esi"] == "ESI-3"   # 4 pts
    assert by_complaint["abdominal"]["esi"] == "ESI-4"     # 2 pts
    assert by_complaint["general"]["esi"] == "ESI-4"       # 1 pt


def test_complaint_esi_resource_refinement(db_session):
    # No shipped complaint lands at ESI-3 with a low resource level, so craft two
    # weight-4 (ESI-3) complaints that refine down: one -> ESI-4, none -> ESI-5.
    db_session.add_all([
        ScoringRule(rule_id=9201, rule_type="complaint", factor="Chief complaint",
                    threshold_display="ztest one", weight=4, complaint_group="ztest_one",
                    resource_level="one", esi_anchor="a", fallback_if_missing="n/a"),
        ScoringRule(rule_id=9202, rule_type="complaint", factor="Chief complaint",
                    threshold_display="ztest none", weight=4, complaint_group="ztest_none",
                    resource_level="none", esi_anchor="a", fallback_if_missing="n/a"),
    ])
    db_session.commit()
    try:
        by_complaint = {r["complaint"]: r for r in RulesInfoService(db_session).complaint_esi()}
        assert by_complaint["ztest_one"]["esi"] == "ESI-4"    # ESI-3 refined down (one)
        assert by_complaint["ztest_none"]["esi"] == "ESI-5"   # ESI-3 refined down (none)
    finally:
        db_session.execute(delete(ScoringRule).where(ScoringRule.rule_id.in_([9201, 9202])))
        db_session.commit()


# --- DB-error paths ---------------------------------------------------------

@pytest.mark.parametrize("method", ["scoring_rules", "esi_bands", "red_flag_rules", "complaint_esi"])
def test_db_error_raises_500(db_session, monkeypatch, method):
    def boom(*args, **kwargs):
        raise SQLAlchemyError("db unavailable")

    monkeypatch.setattr(db_session, "scalars", boom)
    with pytest.raises(HTTPException) as exc:
        getattr(RulesInfoService(db_session), method)()
    assert exc.value.status_code == 500
