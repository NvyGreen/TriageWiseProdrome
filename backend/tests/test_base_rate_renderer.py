"""Base-rate rendering tests, driven by base_rate_test_cases.json (req R3).

_render_base_rate(chief_complaint) -> str | None reads the REAL condition_reference
table (loaded from condition_reference.csv by conftest), so these are integration
tests: they need db_session but seed no per-case rows for the CSV-backed cases.

The `context_condition_row_missing_skips_subset` case can't be reproduced with the
shipped CSV (every context_condition has a matching row), so it gets its own test
that seeds a custom row with an orphan context_condition and tears it down in a
finally — leaving the shared reference table exactly as the CSV seeded it.
"""
import json
from pathlib import Path

import pytest
from sqlalchemy import delete

from app.models.condition_reference import ConditionReference
from app.services.triage_service import TriageService

UNIT_CASES = Path(__file__).parent / "unit_cases"
CASES = json.loads((UNIT_CASES / "base_rate_test_cases.json").read_text(encoding="utf-8"))["cases"]

ORPHAN_CASE = "context_condition_row_missing_skips_subset"
# CSV-backed cases run against the reference data as-is; the orphan case needs a
# seeded row, so it's handled in its own test below.
CSV_CASES = [c for c in CASES if c["_name"] != ORPHAN_CASE]

# An id well outside the CSV's 1-11 range (condition_reference_id is not autoincrement).
ORPHAN_ID = 9001


@pytest.mark.parametrize("case", CSV_CASES, ids=lambda c: c["_name"])
def test_render_base_rate(case, db_session):
    result = TriageService(db_session)._render_base_rate(case["call"]["chief_complaint"])
    assert result == case["expect"]["base_rate_line"]


def test_context_condition_row_missing_skips_subset(db_session):
    """A complaint row names a context_condition with no matching row -> the
    dangerous-subset clause is skipped. Seed a custom orphan row, then remove it."""
    case = next(c for c in CASES if c["_name"] == ORPHAN_CASE)

    db_session.add(
        ConditionReference(
            condition_reference_id=ORPHAN_ID,
            condition="Orphan complaint",
            match_type="complaint",
            complaint_key=case["call"]["chief_complaint"],
            context_condition="Nonexistent Dx",  # no row has this condition -> subset skipped
            icd10_prefixes="R00",
            visits=100,
            admitted=10,
            admit_rate=0.10,  # -> 10.0%
            reliable="yes",
            source_label="NHAMCS 2022",
        )
    )
    db_session.commit()
    try:
        result = TriageService(db_session)._render_base_rate(case["call"]["chief_complaint"])
        assert result == case["expect"]["base_rate_line"]
    finally:
        db_session.execute(
            delete(ConditionReference).where(ConditionReference.condition_reference_id == ORPHAN_ID)
        )
        db_session.commit()
