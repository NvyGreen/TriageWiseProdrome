from uuid import uuid4

import pytest

from app.dependencies import get_queue
from app.main import patients_app, queue_app
from app.services.priority_queue import PriorityQueue


def test_endpoints_have_disclaimer(client):
    disclaimer_message = "simplified/educational, not clinically validated; explains & prioritizes, does not diagnose."

    root_response = client.get("/")
    root_body = root_response.json()
    assert "meta" in root_body
    root_meta = root_body["meta"]
    assert "disclaimer" in root_meta
    assert root_meta["disclaimer"] == disclaimer_message

    esi_response = client.get("/esi-bands")
    esi_body = esi_response.json()
    assert "meta" in esi_body
    esi_meta = esi_body["meta"]
    assert "disclaimer" in esi_meta
    assert esi_meta["disclaimer"] == disclaimer_message

    cr_response = client.get("/condition-reference")
    cr_body = cr_response.json()
    assert "meta" in cr_body
    cr_meta = cr_body["meta"]
    assert "disclaimer" in cr_meta
    assert cr_meta["disclaimer"] == disclaimer_message


@pytest.fixture
def shared_queue():
    """One fresh queue shared by BOTH POST /patients (insert) and GET /queue (read).

    get_queue resolves per-app, so the override must go on both sub-apps with the
    same instance — otherwise the POST inserts into one queue and the GET reads
    another (empty) one.
    """
    queue = PriorityQueue()
    for sub_app in (patients_app, queue_app):
        sub_app.dependency_overrides[get_queue] = lambda: queue
    yield queue
    for sub_app in (patients_app, queue_app):
        sub_app.dependency_overrides.pop(get_queue, None)


def test_post_patient_appears_in_queue(client, shared_queue, api_examples):
    """End-to-end: POST a valid intake -> scored + queued -> GET /queue shows it.

    Uses the contract's valid_201 body as input; asserts the REAL computed values
    (cardiac + all-normal-for-scoring vitals -> 6 pts -> ESI-2), not the contract's
    illustrative GET numbers.
    """
    body = api_examples["POST /patients"]["valid_201"]["request"]["body"]

    resp = client.post("/patients/", json=body, headers={"Idempotency-Key": uuid4().hex})
    assert resp.status_code == 201

    # Scoring is out-of-band (separate scorer process); drive it so the intake gets
    # scored + queued before we read the queue.
    from app.dependencies import SessionLocal
    from app import scorer
    session = SessionLocal()
    try:
        scorer.score_claimed(session, resp.json()["payload"]["intake_id"])
    finally:
        session.close()

    entries = client.get("/queue/").json()["payload"]["entries"]
    match = [e for e in entries if e["name"] == body["name"]]
    assert len(match) == 1

    entry = match[0]
    assert entry["esi_level"] == "ESI-2"
    assert entry["priority_label"] == "High"
    # Numeric(5,1) serializes as a float.
    assert float(entry["severity_score"]) == 6.0
