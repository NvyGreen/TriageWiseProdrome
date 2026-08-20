"""Queue ordering tests, driven by a case table.

Runs the same cases against BOTH queue implementations — PriorityQueue (heap)
and NaiveListQueue (linear reference). They must produce identical orderings;
parametrizing over both is a cross-check that the optimized heap agrees with the
naive oracle on every case.

Cases live in tests/unit_cases/queue_test_cases.json. Two shapes:
  - standard: "setup" rows + an "action" + "expected_order"
  - sequence: "full_sequence_p1_to_p5" asserts order after each arrival

The table is loaded at module level because pytest.mark.parametrize needs its
data at COLLECTION time, before fixtures exist. Both queues are pure stdlib, so
these tests need no DB / fixtures.

Arrival times in the JSON are "HH:MM", so we pass format="%H:%M". (Each queue's
format/fmt=None path uses datetime.fromisoformat, for the ISO timestamps the API
will send — but fromisoformat rejects "HH:MM", so tests must pass the format.)
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.services.naive_list_queue import NaiveListQueue
from app.services.priority_queue import PriorityQueue

UNIT_CASES = Path(__file__).parent / "unit_cases"
CASES = json.loads((UNIT_CASES / "queue_test_cases.json").read_text(encoding="utf-8"))

TIME_FORMAT = "%H:%M"

QUEUE_CLASSES = [PriorityQueue, NaiveListQueue]

# Standard cases carry a top-level "expected_order"; the sequence case does not.
STANDARD_CASES = [c for c in CASES["cases"] if "expected_order" in c]
SEQUENCE_CASE = next(c for c in CASES["cases"] if "sequence" in c)


def _insert(queue, row: dict) -> None:
    # The two queues' insert signatures have DIVERGED: PriorityQueue now takes a
    # datetime (4 args); NaiveListQueue still takes a string + format (5 args).
    # See the note at the top of the module — update NaiveListQueue to converge.
    if isinstance(queue, PriorityQueue):
        queue.insert(
            row["esi_band"],
            row["flag_tier"],
            datetime.strptime(row["arrival_time"], TIME_FORMAT).replace(tzinfo=timezone.utc),
            row["intake_id"],
        )
    else:
        queue.insert(
            row["esi_band"],
            row["flag_tier"],
            row["arrival_time"],
            row["intake_id"],
            TIME_FORMAT,
        )


@pytest.mark.parametrize("queue_cls", QUEUE_CLASSES, ids=lambda c: c.__name__)
@pytest.mark.parametrize("case", STANDARD_CASES, ids=lambda c: c["_name"])
def test_queue_ordering(case, queue_cls):
    """Build a queue from setup + action, assert the ordered intake_ids."""
    queue = queue_cls()
    for row in case["setup"]:
        _insert(queue, row)

    # action is either "insert_all" (setup only) or {"insert": {...}} (one more).
    action = case["action"]
    if isinstance(action, dict) and "insert" in action:
        _insert(queue, action["insert"])

    assert queue.orderedIntakeIds() == case["expected_order"]


@pytest.mark.parametrize("queue_cls", QUEUE_CLASSES, ids=lambda c: c.__name__)
def test_queue_full_sequence(queue_cls):
    """Patients arrive over time; the order is correct after each arrival."""
    queue = queue_cls()
    for step in SEQUENCE_CASE["sequence"]:
        _insert(queue, step["arrives"])
        assert queue.orderedIntakeIds() == step["expected_order"]


# --- PriorityQueue-specific error / branch coverage ---

def _dt(minute=0):
    return datetime(2020, 1, 1, 10, minute, tzinfo=timezone.utc)


def test_insert_rejects_invalid_esi_band():
    queue = PriorityQueue()
    with pytest.raises(ValueError):
        queue.insert(0, 3, _dt(), 1)
    with pytest.raises(ValueError):
        queue.insert(6, 3, _dt(), 1)


def test_insert_rejects_invalid_flag_tier():
    queue = PriorityQueue()
    with pytest.raises(ValueError):
        queue.insert(3, 0, _dt(), 1)
    with pytest.raises(ValueError):
        queue.insert(3, 4, _dt(), 1)


def test_remove_last_element():
    queue = PriorityQueue()
    queue.insert(1, 3, _dt(0), 100)   # more acute -> heap root
    queue.insert(2, 3, _dt(1), 200)   # less acute -> last index
    assert queue.remove(200) == 200
    assert queue.orderedIntakeIds() == [100]


def test_pop_highest_returns_most_acute():
    queue = PriorityQueue()
    queue.insert(2, 3, _dt(1), 200)
    queue.insert(1, 3, _dt(0), 100)
    assert queue.popHighest() == 100
    assert queue.orderedIntakeIds() == [200]


def test_pop_highest_on_empty_raises():
    with pytest.raises(IndexError):
        PriorityQueue().popHighest()


def test_remove_unknown_intake_raises():
    queue = PriorityQueue()
    queue.insert(1, 3, _dt(), 100)
    with pytest.raises(ValueError):
        queue.remove(999)


def test_position_unknown_intake_raises():
    queue = PriorityQueue()
    queue.insert(1, 3, _dt(), 100)
    with pytest.raises(ValueError):
        queue.getIntakePosition(999)
