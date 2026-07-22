"""Endpoint tests for PATCH /intakes/{id}, driven by update_test_cases.json.

Only the `needs_scoring: false` cases run; the rest need req 1.4. The case table
is loaded at module level because pytest.mark.parametrize needs its data at
COLLECTION time, before fixtures exist.

The JSON's intake_ids (5001, 5010, ...) are fabricated, but intake_id is an
autoincrement PK — so each test seeds real rows and maps {json_id: real_id},
translating `target` and `queue_after_order` through it. Same approach as
test_queue.py takes with queue_test_cases.json.

Isolation: the endpoint resolves its queue via Depends(get_queue) (the module
singleton), so `queue_override` swaps in a fresh queue per test. The override
goes on `intakes_app`, NOT `app` — dependency_overrides is per-app-instance and
this route is registered on the mounted sub-app.

Deferred until status is persisted: `status_now`. Note that `still_in_queue` and
`queue_order_unchanged` are weak guards — the non-disposition status path never
touches the queue — so they catch regressions, not correctness.
"""
import json
from datetime import date
from pathlib import Path

import pytest

from app.dependencies import get_queue
from app.main import intakes_app
from app.models.case_update import CaseUpdate
from app.models.event_log import EventLog
from app.models.intake_record import IntakeRecord
from app.models.patient import Patient
from app.services.priority_queue import PriorityQueue
from app.services.triage_service import EventType

UNIT_CASES = Path(__file__).parent / "unit_cases"
CASES = json.loads((UNIT_CASES / "update_test_cases.json").read_text(encoding="utf-8"))

TIME_FORMAT = "%H:%M"

# Only the cases that don't need the scoring engine (req 1.4).
RUNNABLE = {c["_name"]: c for c in CASES["cases"] if not c["needs_scoring"]}


def _case(name):
    return RUNNABLE[name]


@pytest.fixture
def queue_override():
    """Swap the endpoint's queue for a fresh one, scoped to this test."""
    queue = PriorityQueue()
    intakes_app.dependency_overrides[get_queue] = lambda: queue
    yield queue
    intakes_app.dependency_overrides.pop(get_queue, None)


def _seed(db_session, name, **vitals):
    """Insert a Patient + IntakeRecord. Returns the real intake_id."""
    patient = Patient(name=name, date_of_birth=date(1980, 5, 17), sex="M")
    db_session.add(patient)
    db_session.flush()

    intake = IntakeRecord(
        patient_id=patient.patient_id, chief_complaint="cardiac", **vitals
    )
    db_session.add(intake)
    db_session.commit()
    return intake.intake_id


def _seed_and_enqueue(db_session, queue, json_ids):
    """Seed one intake per fabricated id and insert it in that order.

    Returns {json_id: real_id}. Ascending esi_band keeps queue order equal to
    the order given, so `queue_after_order` translates directly.
    """
    id_map = {}
    for position, json_id in enumerate(json_ids, start=1):
        real_id = _seed(db_session, f"Case Patient {json_id}")
        queue.insert(position, 3, "10:00", real_id, TIME_FORMAT)
        id_map[json_id] = real_id
    return id_map


def _events(db_session, intake_id, event_type):
    return (
        db_session.query(EventLog)
        .filter(EventLog.intake_id == intake_id, EventLog.event_type == event_type)
        .all()
    )


def _case_updates(db_session, intake_id):
    return db_session.query(CaseUpdate).filter(CaseUpdate.intake_id == intake_id).all()


@pytest.mark.parametrize(
    "case_name",
    ["status_waiting_to_in_room_no_rescore", "status_in_room_back_to_waiting"],
)
def test_status_change(client, db_session, queue_override, case_name):
    """Status patch fires status_changed, doesn't re-score, leaves the queue alone."""
    case = _case(case_name)
    json_id = case["seed"]["intake_id"]
    id_map = _seed_and_enqueue(db_session, queue_override, [json_id])
    intake_id = id_map[json_id]

    order_before = queue_override.orderedIntakeIds()

    resp = client.patch(f"/intakes/{intake_id}", json=case["patch"])
    assert resp.status_code == 200

    assert len(_events(db_session, intake_id, EventType.STATUS_CHANGED)) == 1
    # expect.rescored == false -> no CaseUpdate row was written.
    assert _case_updates(db_session, intake_id) == []
    # expect.still_in_queue / queue_order_unchanged.
    assert intake_id in queue_override.orderedIntakeIds()
    assert queue_override.orderedIntakeIds() == order_before


def test_disposition_removes_from_queue(client, db_session, queue_override):
    case = _case("disposition_removes_from_queue")
    json_ids = [row["intake_id"] for row in case["seed"]["queue_before"]]
    id_map = _seed_and_enqueue(db_session, queue_override, json_ids)
    target = id_map[case["seed"]["target"]]

    resp = client.patch(f"/intakes/{target}", json=case["patch"])
    assert resp.status_code == 200

    expected = [id_map[j] for j in case["expect"]["queue_after_order"]]
    assert queue_override.orderedIntakeIds() == expected
    assert len(_events(db_session, target, EventType.STATUS_CHANGED)) == 1


def test_unknown_intake_id_returns_404(client, queue_override):
    case = _case("error_unknown_intake_id_404")

    resp = client.patch(case["patch_to"], json=case["patch"])

    assert resp.status_code == case["expect"]["status_code"]
    assert resp.json()["error"]["code"] == case["expect"]["error_code"]


def test_bad_field_returns_400(client, db_session, queue_override):
    """Validation rejects before the id is looked up, so no seeding is needed."""
    case = _case("error_bad_field_400")

    resp = client.patch("/intakes/1", json=case["patch"])

    assert resp.status_code == case["expect"]["status_code"]
    err = resp.json()["error"]
    assert err["code"] == case["expect"]["error_code"]
    assert "heart_rate" in {d["field"] for d in err["details"]}
