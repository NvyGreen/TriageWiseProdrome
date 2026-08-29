"""Shared helpers for the queue load/stress drivers.

Importing this module repoints DB_NAME to the *_test* database BEFORE any app.*
import (so the oracle's DB session and the server both target the test DB), then
exposes:
  - a live-uvicorn launcher (any worker count — the queue is the shared DB
    `triage_queue` table, so workers no longer split it)
  - a standalone scorer launcher (`app.scorer`): submit is async and returns
    `pending`, so a scorer process must run to fill the queue out-of-band
  - an IntakeCreate payload builder that spreads records across ESI bands
  - the DB-side ordering ORACLE: wait for the scoring backlog to drain, then read
    the final queue straight from the DB and check it against the DB-derived
    expected order for lost / duplicate / misordered entries

Reused by queue_concurrency_smoke.py (barrier burst) and locustfile.py (sustained
Locust load).
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

# Repoint to the _test DB BEFORE importing app.* (mirrors conftest) so the
# oracle's SessionLocal hits the same DB the server writes to.
sys.path.insert(0, str(BACKEND))
from app.config import get_settings  # noqa: E402

_base = get_settings().DB_NAME
TEST_DB = _base if _base.endswith("_test") else f"{_base}_test"
os.environ["DB_NAME"] = TEST_DB
get_settings.cache_clear()

from sqlalchemy import func, select  # noqa: E402
from app.dependencies import SessionLocal  # noqa: E402
from app.models.intake_record import IntakeRecord  # noqa: E402
from app.models.patient import Patient  # noqa: E402
from app.models.patient_severity import PatientSeverity  # noqa: E402
from app.models.triage_queue import TriageQueue  # noqa: E402

# Rotated across records so the queue spans multiple ESI bands (weights differ
# per complaint) — makes ordering non-trivial to verify.
COMPLAINTS = [
    "cardiac", "respiratory", "abdominal", "neuro", "stroke", "syncope",
    "sepsis", "trauma", "weakness", "general", "minor_injury", "minor_general",
]


# ---- HTTP -----------------------------------------------------------------

def http_req(method, url, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, None


def unwrap(resp_body):
    """Strip the MedicalDisclaimerResponse envelope."""
    if isinstance(resp_body, dict) and "payload" in resp_body:
        return resp_body["payload"]
    return resp_body


def make_intake(i):
    """A valid, distinct IntakeCreate body. Vitals vary to widen band/flag spread;
    diastolic stays below systolic to pass validation."""
    return {
        "name": f"QConc {i}",
        "date_of_birth": "1980-05-17",
        "sex": "M",
        "chief_complaint": COMPLAINTS[i % len(COMPLAINTS)],
        "heart_rate": 70 + (i * 7) % 80,          # 70..149
        "blood_pressure_systolic": 100 + (i % 40),  # 100..139
        "blood_pressure_diastolic": 60 + (i % 20),  # 60..79  (< systolic)
        "temperature": 98.6,
        "oxygen_saturation": 90 + (i % 11),        # 90..100
        "respiration_rate": 14 + (i % 12),         # 14..25
        "pain_level": i % 11,                      # 0..10
        "pregnancy_status": "none",
    }


def post_intake(base_url, i):
    """POST one intake; return its intake_id on 201, else None."""
    status, body = http_req(
        "POST", f"{base_url}/patients/", make_intake(i),
        {"Idempotency-Key": uuid.uuid4().hex},
    )
    if status != 201:
        return None
    return unwrap(body)["intake_id"]


def fetch_queue_ids(base_url):
    """intake_ids in queue order from GET /queue/."""
    status, body = http_req("GET", f"{base_url}/queue/")
    if status != 200:
        raise RuntimeError(f"GET /queue returned {status}")
    entries = unwrap(body)["entries"]
    return [e["intake_id"] for e in entries]


# ---- server ---------------------------------------------------------------

def start_server(port, log_path, workers=1):
    """Launch uvicorn on the _test DB. The queue is persisted in triage_queue, so
    multiple workers share it correctly (each worker has its own DB pool)."""
    child_env = {**os.environ, "DB_NAME": TEST_DB, "PYTHONPATH": str(BACKEND)}
    log_file = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning",
         "--workers", str(workers)],
        cwd=str(BACKEND), env=child_env, stdout=log_file, stderr=subprocess.STDOUT,
    )
    return proc, log_file


def start_scorer(log_path):
    """Launch the standalone scoring worker (app/scorer.py) on the _test DB. The web
    server no longer scores; without this process nothing drains the pending queue."""
    child_env = {**os.environ, "DB_NAME": TEST_DB, "PYTHONPATH": str(BACKEND)}
    log_file = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.scorer"],
        cwd=str(BACKEND), env=child_env, stdout=log_file, stderr=subprocess.STDOUT,
    )
    return proc, log_file


def wait_until_up(base_url, timeout=45):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            status, _ = http_req("GET", f"{base_url}/")
            if status == 200:
                return
        except urllib.error.URLError:
            pass
        time.sleep(0.3)
    raise RuntimeError(f"server did not come up at {base_url}")


def stop_server(proc, log_file):
    # On Windows, proc.terminate()/kill() only signal the master; uvicorn --workers
    # children are orphaned and keep holding the port (they then answer the next
    # run's requests with stale code). taskkill /T kills the whole process tree.
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
        )
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
    else:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    log_file.close()


# ---- DB reset -------------------------------------------------------------
# Reference/lookup tables loaded by load_reference_data.py — NEVER truncated.
_REFERENCE_TABLES = frozenset({
    "scoring_rule", "red_flag_rule", "esi_band", "vital_range", "condition_reference",
})
# Transactional tables a stress run writes. TRUNCATE ... CASCADE also clears any
# table FK-referencing these; reference tables have no FK into them, so they are
# never touched.
_TRANSACTIONAL_TABLES = [
    "patient", "intake_record", "patient_severity", "ai_explanation",
    "triage_queue", "event_log", "override", "case_update", "idempotency_key",
]
assert not (set(_TRANSACTIONAL_TABLES) & _REFERENCE_TABLES), \
    "refusing to truncate a reference table"


def reset_transactional_tables():
    """Truncate the transactional tables so a stress run starts from an empty DB
    (only this run fills the queue). Reference/lookup tables are preserved, so the
    server can still score. Targets the _test DB (DB_NAME repointed on import)."""
    from sqlalchemy import text  # noqa: PLC0415
    db = SessionLocal()
    try:
        db.execute(text(
            "TRUNCATE TABLE " + ", ".join(_TRANSACTIONAL_TABLES)
            + " RESTART IDENTITY CASCADE"
        ))
        db.commit()
    finally:
        db.close()


# ---- ordering oracle ------------------------------------------------------

def expected_order(intake_ids):
    """The order the queue SHOULD be in, derived independently from the DB:
    sort by the same key insert() uses — (esi_band, flag_tier, arrival_epoch,
    intake_id). esi_band/flag_tier come from patient_severity, arrival from
    intake_record.created_at (the exact value insert() timestamped)."""
    db = SessionLocal()
    try:
        rows = db.execute(
            select(
                PatientSeverity.intake_id,
                PatientSeverity.system_ESI,
                PatientSeverity.flag_tier,
                IntakeRecord.created_at,
            )
            .join(IntakeRecord, IntakeRecord.intake_id == PatientSeverity.intake_id)
            .where(PatientSeverity.intake_id.in_(intake_ids))
        ).all()
    finally:
        db.close()

    keyed = [
        (int(esi[-1]), tier, created.timestamp(), iid)
        for iid, esi, tier, created in rows
    ]
    keyed.sort()
    return [k[3] for k in keyed]


def db_run_intake_ids(name_prefix="QConc "):
    """intake_ids this run created, from the DB (server truth) via patient-name
    prefix. Reliable even when a load tool kills client greenlets mid-flight —
    unlike a client-side 'submitted' list, which undercounts in-flight requests
    the server still committed."""
    db = SessionLocal()
    try:
        rows = db.execute(
            select(IntakeRecord.intake_id)
            .join(Patient, Patient.patient_id == IntakeRecord.patient_id)
            .where(Patient.name.like(f"{name_prefix}%"))
        ).all()
    finally:
        db.close()
    return [r[0] for r in rows]


def check_queue(submitted_ids, actual_ids):
    """Compare the actual queue to the DB-derived order. `submitted_ids` is the
    membership truth (what SHOULD be queued); ordering is checked over the queue's
    ACTUAL members so a membership mismatch can't masquerade as a misordering."""
    submitted = set(submitted_ids)
    actual_set = set(actual_ids)

    lost = sorted(submitted - actual_set)          # created but not in queue
    unexpected = sorted(actual_set - submitted)    # in queue but not created

    seen, duplicates = set(), []
    for x in actual_ids:
        if x in seen:
            duplicates.append(x)
        seen.add(x)

    # Order the queue's own members by the sort key and check the queue matches.
    expected = expected_order(actual_ids)
    misordered = actual_ids != expected
    misorder_index = None
    if misordered:
        misorder_index = next(
            (i for i, (a, e) in enumerate(zip(actual_ids, expected)) if a != e),
            min(len(actual_ids), len(expected)),
        )

    ok = not lost and not unexpected and not duplicates and not misordered
    return {
        "ok": ok,
        "submitted": len(submitted_ids),
        "in_queue": len(actual_ids),
        "lost": lost,
        "unexpected": unexpected,
        "duplicates": duplicates,
        "misordered": misordered,
        "first_misorder_index": misorder_index,
        "expected": expected,
        "actual": actual_ids,
    }


# ---- async-scoring drain + DB-side queue read ------------------------------
# Submit is async now: POST returns `pending`, scoring happens in a background
# task. So the oracle must (1) wait for scoring to drain, then (2) read final
# state straight from the DB — not by polling GET /queue, which would just pile
# more read load on a server still churning through the scoring backlog. The load
# itself (POST + a GET /queue task) is generated by Locust during the run.

def db_status_counts(name_prefix="QConc "):
    """{scoring_status: count} for this run's intakes."""
    db = SessionLocal()
    try:
        rows = db.execute(
            select(IntakeRecord.scoring_status, func.count())
            .join(Patient, Patient.patient_id == IntakeRecord.patient_id)
            .where(Patient.name.like(f"{name_prefix}%"))
            .group_by(IntakeRecord.scoring_status)
        ).all()
    finally:
        db.close()
    return {status: n for status, n in rows}


def db_scored_intake_ids(name_prefix="QConc "):
    """intake_ids that finished scoring (the ones that SHOULD be in the queue)."""
    db = SessionLocal()
    try:
        rows = db.execute(
            select(IntakeRecord.intake_id)
            .join(Patient, Patient.patient_id == IntakeRecord.patient_id)
            .where(Patient.name.like(f"{name_prefix}%"), IntakeRecord.scoring_status == "scored")
        ).all()
    finally:
        db.close()
    return [r[0] for r in rows]


def db_queue_ids():
    """triage_queue members in sort order (excludes dispositioned), read straight
    from the DB so verification doesn't add HTTP read load during the drain."""
    db = SessionLocal()
    try:
        rows = db.execute(
            select(TriageQueue.intake_id)
            .where(TriageQueue.status != "DISPOSITIONED")
            .order_by(
                TriageQueue.esi_band, TriageQueue.flag_tier,
                TriageQueue.arrival_time, TriageQueue.intake_id,
            )
        ).all()
    finally:
        db.close()
    return [r[0] for r in rows]


def wait_until_scored(name_prefix="QConc ", timeout=300, poll=1.0):
    """Wait for the async scoring backlog to drain: poll the DB until no `pending`
    remain, or the pending count stops dropping (stalled). Returns final counts."""
    deadline = time.time() + timeout
    prev_pending, stable = None, 0
    while time.time() < deadline:
        counts = db_status_counts(name_prefix)
        pending = counts.get("pending", 0)
        if pending == 0:
            return counts
        stable = stable + 1 if pending == prev_pending else 0
        if stable >= 3:  # not draining any more
            return counts
        prev_pending = pending
        time.sleep(poll)
    return db_status_counts(name_prefix)
