"""Unit tests for app/services/simulation.py, driven by simulation_test_cases.json.

The simulation is pure and in-memory (no DB, no real queue), so these tests need
no fixtures — they call run_simulation directly and compare against expected output
captured from the real functions.

Key detail: JSON object keys are strings, but the generator uses INT keys for both
the ESI band and the flag tier (bands.get(esi) / flags.get(FlagTier)). So a case's
custom_bands is converted to int keys before building the SimRequest — otherwise the
counts/flags would silently not apply.
"""
import json
from pathlib import Path

import pytest

from app.services.simulation import SimRequest, run_simulation

CASES = json.loads(
    (Path(__file__).parent / "unit_cases" / "simulation_test_cases.json").read_text(
        encoding="utf-8"
    )
)["cases"]

SUCCESS_CASES = [c for c in CASES if "expect" in c]
ERROR_CASES = [c for c in CASES if "expect_error" in c]

_ERRORS = {"ValueError": ValueError}


def _to_int_keys(custom_bands: dict) -> dict:
    """JSON forces string keys; the generator keys bands and flag tiers by int.
    Convert both levels so custom counts/flags actually apply."""
    return {
        int(band): {
            "n": spec.get("n", 0),
            "flags": {int(tier): count for tier, count in spec.get("flags", {}).items()},
        }
        for band, spec in custom_bands.items()
    }


def _request(call: dict) -> SimRequest:
    if "preset" in call:
        return SimRequest(preset=call["preset"])
    if "custom_bands" in call:
        return SimRequest(custom_bands=_to_int_keys(call["custom_bands"]))
    return SimRequest()  # neither field — the missing-both error case


@pytest.mark.parametrize("case", SUCCESS_CASES, ids=[c["_name"] for c in SUCCESS_CASES])
def test_simulation_success(case):
    assert run_simulation(_request(case["call"])) == case["expect"]


@pytest.mark.parametrize("case", ERROR_CASES, ids=[c["_name"] for c in ERROR_CASES])
def test_simulation_error(case):
    with pytest.raises(_ERRORS[case["expect_error"]]):
        run_simulation(_request(case["call"]))
