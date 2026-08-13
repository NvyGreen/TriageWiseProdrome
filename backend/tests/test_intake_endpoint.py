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
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import update

from app.dependencies import get_queue
from app.main import intakes_app
from app.models.ai_explanation import AIExplanation
from app.models.case_update import CaseUpdate
from app.models.event_log import EventLog
from app.models.intake_record import IntakeRecord
from app.models.override import Override
from app.models.patient import Patient
from app.models.patient_severity import PatientSeverity
from app.models.scoring_rule import ScoringRule
from app.services.priority_queue import PriorityQueue
from app.services.scoring_engine import ScoringEngine
from app.services.red_flag_layer import RedFlagLayer
from app.services.triage_service import EventType

UNIT_CASES = Path(__file__).parent / "unit_cases"
CASES = json.loads((UNIT_CASES / "update_test_cases.json").read_text(encoding="utf-8"))
DETAIL_CASES = json.loads(
    (UNIT_CASES / "patient_detail_test_cases.json").read_text(encoding="utf-8")
)["endpoint_cases"]

def _at(hhmm: str) -> datetime:
    """Arrival time as a datetime — PriorityQueue.insert takes datetimes now."""
    return datetime.strptime(hhmm, "%H:%M").replace(tzinfo=timezone.utc)

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
    db_session.flush()
    # A queued intake has been scored (submitIntake invariant); the status path
    # reads its severity back, so give it one.
    db_session.add(
        PatientSeverity(intake_id=intake.intake_id, severity_score=1, system_ESI="ESI-4")
    )
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
        queue.insert(position, 3, _at("10:00"), real_id)
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


def test_clinical_update_rewrites_flag_tier(client, db_session, queue_override):
    """clinical_update_fires_flag_tier_rewrite (requires red flags, not queueing).

    A clinical patch that trips a red flag rewrites flag_tier + red_flags on the
    re-scored severity row; the flag never sets the band (esi_level comes from the
    score). Needs no queue placement, so it runs now that red flags are wired into
    scoring. `_seed` hardcodes cardiac, so build the intake inline with normal
    vitals for a clean baseline.
    """
    case = next(
        c for c in CASES["cases"] if c["_name"] == "clinical_update_fires_flag_tier_rewrite"
    )

    # Cardiac + normal vitals -> baseline ESI-2, no flag (flag_tier 3).
    patient = Patient(name="Flag Rewrite", date_of_birth=date(1980, 1, 1), sex="M")
    db_session.add(patient)
    db_session.flush()
    intake = IntakeRecord(
        patient_id=patient.patient_id, chief_complaint="cardiac",
        heart_rate=80, blood_pressure_systolic=120, respiration_rate=16,
        oxygen_saturation=98, temperature=98.6, pain_level=2,
    )
    db_session.add(intake)
    db_session.commit()

    baseline = ScoringEngine(db_session).score(intake, RedFlagLayer(db_session), db_session)
    db_session.commit()
    assert baseline.flag_tier == 3  # normal vitals -> no flag yet

    # Clinical update re-queues, so the intake must already be in the queue.
    queue_override.insert(2, 3, _at("10:00"), intake.intake_id)

    # Patch to shock vitals (HR 145 + SBP 88) -> fires flag 9 (Tier 1).
    resp = client.patch(f"/intakes/{intake.intake_id}", json=case["patch"])
    assert resp.status_code == 200

    latest = (
        db_session.query(PatientSeverity)
        .filter(PatientSeverity.intake_id == intake.intake_id)
        .order_by(PatientSeverity.severity_id.desc())
        .first()
    )
    # flag_tier_updated + red_flags_rewritten
    assert latest.flag_tier == 1
    assert latest.flag_tier < baseline.flag_tier
    assert latest.red_flags            # non-empty
    assert latest.red_flag_fired is True
    # esi_band_unchanged_by_flag: the band is the score's (13 pts -> ESI-1); the
    # Tier-1 flag did NOT drag it there.
    assert latest.system_ESI == "ESI-1"


def test_unscoreable_update_returns_422(client, db_session, queue_override, api_examples):
    """Re-score after the patch has nothing to fire on -> 422 unscoreable.

    The patch clears the 5 scoreable vitals but sends temperature (non-scoreable)
    so it passes the "at least one field" validator; with the complaint rule
    deactivated, the re-score fires nothing. Config-toggle path: flip is_active
    off, restore in finally. This case lives in api_contract_examples.json (the
    contract), not update_test_cases.json.
    """
    case = api_examples["PATCH /intakes/{id}"]["unscoreable_422"]
    (rule_id,) = case["setup"]["deactivate_rules"]
    complaint = case["setup"]["seeded_intake_complaint"]

    # Seed an intake whose complaint matches the rule we disable (_seed hardcodes
    # "cardiac", so build it inline with the case's complaint).
    patient = Patient(name="Unscoreable Update", date_of_birth=date(1980, 5, 17), sex="M")
    db_session.add(patient)
    db_session.flush()
    intake = IntakeRecord(patient_id=patient.patient_id, chief_complaint=complaint)
    db_session.add(intake)
    db_session.flush()
    # An updated intake has already been scored (submitIntake invariant).
    db_session.add(
        PatientSeverity(intake_id=intake.intake_id, severity_score=1, system_ESI="ESI-4")
    )
    db_session.commit()

    db_session.execute(
        update(ScoringRule).where(ScoringRule.rule_id == rule_id).values(is_active=False)
    )
    db_session.commit()
    try:
        resp = client.patch(f"/intakes/{intake.intake_id}", json=case["request"]["body"])
        assert resp.status_code == 422
        err = resp.json()["error"]
        assert err["code"] == "unscoreable"
        assert err["message"] == case["response"]["body"]["error"]["message"]
    finally:
        db_session.execute(
            update(ScoringRule).where(ScoringRule.rule_id == rule_id).values(is_active=True)
        )
        db_session.commit()


def test_clinical_update_partial_only_changes_sent_fields(client, db_session, queue_override):
    """clinical_update_partial_only_changes_sent_fields: patching one vital changes
    only it, re-scores, and writes a case_update carrying just that field.
    """
    patient = Patient(name="Partial Endpoint", date_of_birth=date(1980, 1, 1), sex="M")
    db_session.add(patient)
    db_session.flush()
    intake = IntakeRecord(
        patient_id=patient.patient_id, chief_complaint="cardiac",
        heart_rate=100, pain_level=4, respiration_rate=18,
    )
    db_session.add(intake)
    db_session.flush()
    # An updated intake has already been scored (submitIntake invariant).
    db_session.add(
        PatientSeverity(intake_id=intake.intake_id, severity_score=1, system_ESI="ESI-4")
    )
    db_session.commit()
    intake_id = intake.intake_id

    # Clinical update re-queues, so the intake must already be in the queue.
    queue_override.insert(2, 3, _at("10:00"), intake_id)

    resp = client.patch(f"/intakes/{intake_id}", json={"pain_level": 8})
    assert resp.status_code == 200

    db_session.expire_all()
    updated = db_session.get(IntakeRecord, intake_id)
    assert updated.pain_level == 8              # sent field changed
    assert updated.heart_rate == 100            # untouched
    assert updated.respiration_rate == 18       # untouched

    # rescored + case_update carries only the sent field.
    assert len(_events(db_session, intake_id, EventType.SCORE_CALCULATED)) == 1
    rows = _case_updates(db_session, intake_id)
    assert len(rows) == 1
    assert rows[0].updated_vitals == {"pain_level": 8}


def test_clinical_update_raises_esi(client, db_session, queue_override):
    """clinical_update_raises_esi: a clinical patch that raises severity re-scores,
    moves the patient UP the queue, and fires case_updated + reprioritized.
    """
    # Target: abdominal + normal-for-scoring vitals -> baseline ESI-4.
    patient = Patient(name="Rising Severity", date_of_birth=date(1980, 1, 1), sex="M")
    db_session.add(patient)
    db_session.flush()
    target = IntakeRecord(
        patient_id=patient.patient_id, chief_complaint="abdominal",
        heart_rate=92, blood_pressure_systolic=120, oxygen_saturation=98,
        respiration_rate=16, pain_level=2, temperature=98.6,
    )
    db_session.add(target)
    db_session.commit()
    target_id = target.intake_id

    baseline = ScoringEngine(db_session).score(target, RedFlagLayer(db_session), db_session)
    db_session.commit()

    # A higher-priority filler sits above the target so it has room to move up.
    queue_override.insert(2, 3, _at("09:00"), 88_888)     # filler, ESI-2
    queue_override.insert(4, 3, _at("10:00"), target_id)  # target, ESI-4
    position_before = queue_override.getIntakePosition(target_id)

    # HR 138 (+3) + SpO2 89 (+4) -> ESI-1.
    resp = client.patch(f"/intakes/{target_id}", json={"heart_rate": 138, "oxygen_saturation": 89})
    assert resp.status_code == 200

    latest = (
        db_session.query(PatientSeverity)
        .filter(PatientSeverity.intake_id == target_id)
        .order_by(PatientSeverity.severity_id.desc())
        .first()
    )
    # rescored + esi_band rose (more severe == lower number).
    assert int(latest.system_ESI[-1]) < int(baseline.esi_level[-1])
    # queue_moved_up.
    assert queue_override.getIntakePosition(target_id) < position_before
    # case_update_written + both events.
    assert _case_updates(db_session, target_id)
    assert len(_events(db_session, target_id, EventType.CASE_UPDATED)) == 1
    assert len(_events(db_session, target_id, EventType.REPRIORITIZED)) == 1


# ---------------------------------------------------------------------------
# GET /intakes/{id}?mode=... — patient detail response (layer B of
# patient_detail_test_cases.json). Asserts the EMITTED JSON: response casing
# (system_esi), DriverOut dicts, fields ABSENT (not null) when stripped, and the
# explanation_viewed event (route fires it in xai only). The domain-object layer
# lives in test_patient_detail.py. Success bodies are wrapped under "payload" by
# MedicalDisclaimerResponse; errors render the envelope as-is.
# ---------------------------------------------------------------------------
def _seed_detail(db_session, seed):
    """Seed patient + intake + severity + ai_explanation; return the real intake_id.

    Committed so the endpoint's own get_db session sees the rows. PKs autoincrement
    (the JSON's ids are ignored) so re-runs can't collide.
    """
    p = seed["patient"]
    patient = Patient(
        name=p["name"], date_of_birth=date.fromisoformat(p["date_of_birth"]), sex=p["sex"]
    )
    db_session.add(patient)
    db_session.flush()

    ir = seed["intake_record"]
    intake = IntakeRecord(
        patient_id=patient.patient_id,
        chief_complaint=ir["chief_complaint"],
        missing_fields=ir["missing_fields"],
        pregnancy_status="none",  # IntakeInfo.pregnancy_status is a required enum
    )
    db_session.add(intake)
    db_session.flush()

    ps = seed["patient_severity"]
    db_session.add(
        PatientSeverity(
            intake_id=intake.intake_id,
            severity_score=ps["severity_score"],
            system_ESI=ps["system_ESI"],
            clinician_ESI=ps["clinician_ESI"],
            score_reason="seed",
            confidence=ps["confidence"],
            red_flags=ps["red_flags"],
            red_flag_fired=ps["red_flag_fired"],
            flag_tier=ps["flag_tier"],
        )
    )
    db_session.flush()
    severity = (
        db_session.query(PatientSeverity)
        .filter(PatientSeverity.intake_id == intake.intake_id)
        .one()
    )

    ax = seed["ai_explanation"]
    db_session.add(
        AIExplanation(
            severity_id=severity.severity_id,
            intake_id=intake.intake_id,
            explanation_text="seed",
            factor_breakdown=ax["factor_breakdown"],
            data_completeness=ax["data_completeness"],
            gaps=ax["gaps"],
        )
    )

    if "override" in seed:
        ov = seed["override"]
        db_session.add(
            Override(
                intake_id=intake.intake_id,
                severity_id=severity.severity_id,
                system_ESI=ov["system_esi"],
                clinician_ESI=ov["clinician_esi"],
                reason_code=ov["reason_code"],
                note=ov.get("note"),
            )
        )

    db_session.commit()
    return intake.intake_id


@pytest.mark.parametrize("case", DETAIL_CASES, ids=lambda c: c["_name"])
def test_patient_detail_endpoint(case, client, db_session):
    call = case["call"]
    expect = case["expect"]

    # Unseeded cases (the 404) call a fixed missing id; seeded cases use the real
    # autoincremented id, not the JSON's fabricated one.
    intake_id = _seed_detail(db_session, case["seed"]) if case["seed"] else call["intake_id"]

    url = f"/intakes/{intake_id}"
    if "mode" in call:
        url += f"?mode={call['mode']}"
    resp = client.get(url)

    assert resp.status_code == expect["status_code"]

    if "error_code" in expect:
        assert resp.json()["error"]["code"] == expect["error_code"]

    if expect["status_code"] == 200:
        body = resp.json()["payload"]

        for field in expect.get("fields_present", []):
            assert field in body, field
        for field in expect.get("fields_absent", []):
            assert field not in body, field

        if "system_esi" in expect:
            assert body["system_esi"] == expect["system_esi"]
        if "band_name" in expect:
            assert body["band_name"] == expect["band_name"]
        # severity_score may serialize as float (9.0) — assert numeric equality.
        if "severity_score_equals" in expect:
            assert body["severity_score"] == expect["severity_score_equals"]
        if "explanation_driver_count" in expect:
            assert len(body["explanation"]["named_drivers"]) == expect["explanation_driver_count"]
        if expect.get("drivers_are_dicts"):
            assert all(isinstance(d, dict) for d in body["explanation"]["named_drivers"])
        if "override_reason_code" in expect:
            assert body["override"]["reason_code"] == expect["override_reason_code"]
        # base_rate_line is illustrative-labeled when the complaint matches a
        # condition_reference row (xai-only).
        if expect.get("base_rate_line_is_illustrative_labeled"):
            assert "Illustrative base rate" in body["base_rate_line"]
            assert "Population reference" in body["base_rate_line"]

    # explanation_viewed fires in the route, xai branch only.
    viewed = _events(db_session, intake_id, EventType.EXPLANATION_VIEWED)
    if expect.get("event_logged") == "explanation_viewed":
        assert len(viewed) == 1
    if expect.get("no_event_logged"):
        assert len(viewed) == 0
