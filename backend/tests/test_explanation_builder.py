"""ExplanationBuilder.build tests, driven by explanation_test_cases.json (req 1.8).

build() needs three things in the DB before it runs:
  - a persisted IntakeRecord (it reads intake.<field> and intake.intake_id),
  - a PatientSeverity row for that intake (it looks the row up; missing -> 500),
  - the red_flag_rule reference rows (seeded by conftest) so red_flag_ids resolve
    to the values/field-names that fed each fired flag.

The JSON's `severity_result` is a PARTIAL SeverityResult carrying only the fields
build() actually reads; the rest are filled with placeholders here. Two shape
conversions:
  - fallbacks_applied is a list [{field, action}] in JSON but a dict on
    SeverityResult -> convert.
  - data_completeness is NOT computed by the builder (it's echoed straight
    through), so it's fed from the case's expected value.

Gap lists are asserted as SETS: the builder walks ALLOWED_FIELDS (a set), so the
order within a bucket isn't stable. named_drivers order IS stable (the builder
copies the list verbatim), so those are asserted in order.
"""
import json
from datetime import date
from pathlib import Path

import pytest

from app.models.intake_record import IntakeRecord
from app.models.patient import Patient
from app.models.patient_severity import PatientSeverity
from app.services.explanation_builder import ExplanationBuilder
from app.utils.driver import Driver
from app.utils.severity_result import SeverityResult

UNIT_CASES = Path(__file__).parent / "unit_cases"
CASES = json.loads((UNIT_CASES / "explanation_test_cases.json").read_text(encoding="utf-8"))["cases"]

GAP_KEYS = {"not_provided", "assumed", "recorded_not_scored", "red_flag_input", "beyond_the_data"}


def _fallbacks_to_dict(entries):
    """JSON gives a list [{field, action}]; SeverityResult wants {field: action}."""
    return {e["field"]: e["action"] for e in entries}


def _drivers(raw):
    return [
        Driver(
            rule_id=d["rule_id"],
            factor=d["factor"],
            threshold=d["threshold"],
            weight=d["weight"],
            patient_value=d["patient_value"],
            contribution_pct=d["contribution_pct"],
        )
        for d in raw
    ]


def _severity_result(sr, data_completeness):
    """Build a SeverityResult from a case's partial severity_result block.

    initial_esi/resource_level/refined/confidence are unread by build() — filled
    with harmless placeholders so the dataclass constructs.
    """
    return SeverityResult(
        severity_score=sr["severity_score"],
        esi_level=sr["esi_level"],
        initial_esi=sr["esi_level"],
        resource_level="",
        refined=False,
        named_drivers=_drivers(sr["named_drivers"]),
        missing_fields=sr["missing_fields"],
        data_completeness=data_completeness,
        fallbacks_applied=_fallbacks_to_dict(sr["fallbacks_applied"]),
        confidence="HIGH",
        red_flag_ids=sr.get("red_flag_ids", []),
    )


def _seed(db_session, intake_fields):
    """Persist Patient + IntakeRecord + a PatientSeverity row (build() reads it)."""
    patient = Patient(name="Explanation Patient", date_of_birth=date(1980, 5, 17), sex="M")
    db_session.add(patient)
    db_session.flush()

    intake = IntakeRecord(patient_id=patient.patient_id, **intake_fields)
    db_session.add(intake)
    db_session.flush()

    db_session.add(
        PatientSeverity(intake_id=intake.intake_id, severity_score=1, system_ESI="ESI-4")
    )
    db_session.commit()
    return intake


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["_name"])
def test_build(case, db_session):
    expect = case["expect"]
    # build() needs a data_completeness string; use the expected one where the case
    # pins it, otherwise a harmless default (that case doesn't assert it).
    data_completeness = expect.get("data_completeness", "5 of 5")

    severity_result = _severity_result(case["severity_result"], data_completeness)
    intake = _seed(db_session, case["intake"])

    explanation = ExplanationBuilder(db_session).build(severity_result, intake)

    # fallback_instruction is a constant on the dataclass — identical every case.
    if "fallback_instruction" in expect:
        assert explanation.fallback_instruction == expect["fallback_instruction"]

    if "data_completeness" in expect:
        assert explanation.data_completeness == expect["data_completeness"]

    # named_drivers are copied verbatim from severity_result — same ids, same order,
    # nothing invented or dropped.
    if "named_drivers_rule_ids" in expect:
        assert [d.rule_id for d in explanation.named_drivers] == expect["named_drivers_rule_ids"]
    if "driver_count" in expect:
        assert len(explanation.named_drivers) == expect["driver_count"]

    gaps = explanation.gap_acknowledgement
    # Structural invariant: all five buckets always present, even when empty.
    assert set(gaps.keys()) == GAP_KEYS
    if "gap_keys_present" in expect:
        assert set(gaps.keys()) == set(expect["gap_keys_present"])

    # Full gap_acknowledgement pinned by the case — compare each bucket as a set.
    if "gap_acknowledgement" in expect:
        for key, values in expect["gap_acknowledgement"].items():
            assert set(gaps[key]) == set(values), key

    # A case that pins only one bucket (e.g. gap_dict_always_has_all_five_keys).
    if "recorded_not_scored" in expect:
        assert set(gaps["recorded_not_scored"]) == set(expect["recorded_not_scored"])

    # An OR-branch value the patient lacks must be dropped from red_flag_input.
    for forbidden in expect.get("must_not_contain_in_red_flag_input", []):
        assert forbidden not in gaps["red_flag_input"]
