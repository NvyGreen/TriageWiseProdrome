"""Validation tests for the IntakeCreate schema, driven by a case table.

Cases live in tests/unit_cases/validation_test_cases.json:
  - "valid" cases must pass validation
  - "invalid" cases must be rejected, with "expects" naming the field(s) that fail

The table is loaded at module level rather than via a fixture because
pytest.mark.parametrize needs its data at COLLECTION time, before fixtures exist.

Assertions match on the FIELD that errored, not on the "issue" text: those strings
are the contract's intended wording, not Pydantic's literal messages (e.g. the file
says "must be between 0 and 100" where Pydantic says "Input should be less than or
equal to 100"). Matching fields keeps these tests from breaking on Pydantic wording.
"""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.intake_create import IntakeCreate

UNIT_CASES = Path(__file__).parent / "unit_cases"
CASES = json.loads((UNIT_CASES / "validation_test_cases.json").read_text(encoding="utf-8"))
VALID_CASES = CASES["valid"]
INVALID_CASES = CASES["invalid"]


@pytest.mark.parametrize("case", VALID_CASES, ids=lambda c: c["_name"])
def test_valid_cases(case):
    """Every "valid" payload must validate cleanly."""
    IntakeCreate.model_validate(case["payload"])


@pytest.mark.parametrize("case", INVALID_CASES, ids=lambda c: c["_name"])
def test_invalid_cases(case):
    """Every "invalid" payload must be rejected on the fields named in "expects"."""
    with pytest.raises(ValidationError) as e:
        IntakeCreate.model_validate(case["payload"])

    # loc is a tuple like ("pain_level",) or ("pre_existing_conditions", 1);
    # loc[0] is the field. Guard on empty loc — a model-level error has no field.
    errored_fields = {err["loc"][0] for err in e.value.errors() if err["loc"]}

    # Subset, not equality: stays green if the schema later adds another
    # required field that these payloads happen to omit.
    for expected in case["expects"]:
        assert expected["field"] in errored_fields
