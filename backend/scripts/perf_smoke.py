"""API latency smoke test.

Launches the app under a live uvicorn server pointed at the *_test* database,
exercises the five endpoints, and reports per-endpoint and overall average
latency from the server-side timing middleware (the `PERF ...` log lines).

  python scripts/perf_smoke.py [--port 8099] [--measured 50] [--warmup 10]
                               [--out-dir <dir>]

Metric source: the middleware's server-side handler time (request in -> response
out), parsed from the captured server log. Steady-state = measured samples after
dropping the first `--warmup` per endpoint (a warm process / primed pool, which
is what prod sees); all-in includes the warmup calls.

Notes:
  - Writes ~(warmup + measured) patients/intakes/overrides to the _test DB. That
    DB is disposable; run `pytest` once to (re)seed reference data first.
  - Requires the _test DB to already hold reference data (scoring rules etc.).
"""
import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

# Repoint to the _test DB BEFORE importing app.* (mirrors conftest) so the
# severity-id lookup below hits the same DB the server writes to.
sys.path.insert(0, str(BACKEND))
from app.config import get_settings  # noqa: E402

_base = get_settings().DB_NAME
TEST_DB = _base if _base.endswith("_test") else f"{_base}_test"
os.environ["DB_NAME"] = TEST_DB
get_settings.cache_clear()

from sqlalchemy import select  # noqa: E402
from app.dependencies import SessionLocal  # noqa: E402
from app.models.patient_severity import PatientSeverity  # noqa: E402
from app import scorer  # noqa: E402

ENDPOINTS = [
    "POST /patients",
    "GET /queue",
    "GET /intakes/{id}",
    "PATCH /intakes/{id}",
    "POST /overrides",
]
_INTAKE_ID_RE = re.compile(r"^/intakes/\d+$")


def _req(method, url, body=None, headers=None):
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


def _payload(resp_body):
    """Unwrap the MedicalDisclaimerResponse envelope."""
    if isinstance(resp_body, dict) and "payload" in resp_body:
        return resp_body["payload"]
    return resp_body


def _make_intake(i):
    return {
        "name": f"Perf Test {i}",
        "date_of_birth": "1980-05-17",
        "sex": "M",
        "chief_complaint": "cardiac",
        "heart_rate": 96,
        "blood_pressure_systolic": 128,
        "blood_pressure_diastolic": 78,
        "temperature": 98.6,
        "oxygen_saturation": 97,
        "respiration_rate": 18,
        "pain_level": 4,
        "pregnancy_status": "none",
    }


def _wait_until_up(base_url, timeout=45):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            status, _ = _req("GET", f"{base_url}/")
            if status == 200:
                return
        except urllib.error.URLError:
            pass
        time.sleep(0.3)
    raise RuntimeError(f"server did not come up at {base_url}")


def _exercise(base_url, warmup, measured):
    pool = warmup + measured

    # 1. POST /patients -> collect intake_ids.
    intake_ids = []
    for i in range(pool):
        status, body = _req(
            "POST", f"{base_url}/patients/", _make_intake(i),
            {"Idempotency-Key": uuid.uuid4().hex},
        )
        if status != 201:
            raise RuntimeError(f"POST /patients returned {status}")
        intake_ids.append(_payload(body)["intake_id"])

    # 1b. Score the posted intakes (UNTIMED setup). Async POST returns `pending`
    #     and doesn't score, but the endpoints below (detail, PATCH, overrides)
    #     need real severity + queue rows — so score them out-of-band here, the
    #     same path the scorer process runs.
    db = SessionLocal()
    try:
        for iid in intake_ids:
            scorer.score_claimed(db, iid)
    finally:
        db.close()

    # 2. Map intake_id -> severity_id from the DB (POST response omits it).
    db = SessionLocal()
    try:
        rows = db.execute(
            select(PatientSeverity.intake_id, PatientSeverity.severity_id)
            .where(PatientSeverity.intake_id.in_(intake_ids))
        ).all()
    finally:
        db.close()
    sev_by_intake = {iid: sid for iid, sid in rows}
    severity_ids = [sev_by_intake[iid] for iid in intake_ids]

    # 3. GET /queue.
    for _ in range(pool):
        _req("GET", f"{base_url}/queue/")

    # 4. GET /intakes/{id}?mode=xai (distinct id per call).
    for i in range(pool):
        _req("GET", f"{base_url}/intakes/{intake_ids[i]}?mode=xai")

    # 5. PATCH /intakes/{id} (distinct id per call, single vital).
    for i in range(pool):
        _req("PATCH", f"{base_url}/intakes/{intake_ids[i]}", {"heart_rate": 70 + (i % 40)})

    # 6. POST /overrides (distinct severity per call — one override per severity).
    for i in range(pool):
        status, _ = _req(
            "POST", f"{base_url}/overrides/",
            {"severity_id": severity_ids[i], "clinician_esi": "ESI-2", "reason_code": "Other"},
            {"Idempotency-Key": uuid.uuid4().hex},
        )
        if status != 201:
            raise RuntimeError(f"POST /overrides returned {status} (severity {severity_ids[i]})")


def _bucket(method, path):
    if method == "POST" and path.startswith("/patients"):
        return "POST /patients"
    if method == "GET" and path.startswith("/queue"):
        return "GET /queue"
    if method == "GET" and _INTAKE_ID_RE.match(path):
        return "GET /intakes/{id}"
    if method == "PATCH" and _INTAKE_ID_RE.match(path):
        return "PATCH /intakes/{id}"
    if method == "POST" and path.startswith("/overrides"):
        return "POST /overrides"
    return None  # health checks etc.


def _parse_log(log_path):
    buckets = {e: [] for e in ENDPOINTS}
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) != 5 or parts[0] != "PERF":
            continue
        _, method, path, _status, ms = parts
        b = _bucket(method, path)
        if b is not None:
            buckets[b].append(float(ms))
    return buckets


def _summarize(buckets, warmup):
    lines, all_steady = [], []
    lines.append("| Endpoint | n (steady) | avg steady ms | p95 steady ms | avg all-in ms |")
    lines.append("| --- | --- | --- | --- | --- |")
    for e in ENDPOINTS:
        samples = buckets[e]
        steady = samples[warmup:]
        if not steady:
            lines.append(f"| `{e}` | 0 | n/a | n/a | n/a |")
            continue
        all_steady.extend(steady)
        p95 = sorted(steady)[max(0, int(len(steady) * 0.95) - 1)]
        lines.append(
            f"| `{e}` | {len(steady)} | {statistics.mean(steady):.1f} | "
            f"{p95:.1f} | {statistics.mean(samples):.1f} |"
        )
    overall = statistics.mean(all_steady) if all_steady else float("nan")
    return lines, overall


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--measured", type=int, default=50)
    ap.add_argument("--warmup", type=int, default=10)
    ap.add_argument("--out-dir", default=str(BACKEND.parent / "docs" / "validation"))
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "latency_timing.log"
    summary_path = out_dir / "latency.md"
    base_url = f"http://127.0.0.1:{args.port}"

    child_env = {
        **os.environ,
        "DB_NAME": TEST_DB,
        "PYTHONPATH": str(BACKEND),
        "PERF_LOG_ENABLED": "true",  # turn on the timing middleware for this server
    }
    log_file = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
         "--port", str(args.port), "--log-level", "warning"],
        cwd=str(BACKEND), env=child_env, stdout=log_file, stderr=subprocess.STDOUT,
    )
    try:
        _wait_until_up(base_url)
        print(f"server up on {base_url}; exercising "
              f"(warmup={args.warmup}, measured={args.measured})...")
        _exercise(base_url, args.warmup, args.measured)
        time.sleep(0.5)  # let the last log line flush
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_file.close()

    buckets = _parse_log(log_path)
    table, overall = _summarize(buckets, args.warmup)
    dod = "PASS" if overall < 150 else "FAIL"

    report = [
        "# API Latency Smoke Test",
        "",
        f"Server-side handler latency (uvicorn, `{TEST_DB}` DB). "
        f"Steady-state drops the first {args.warmup} calls per endpoint.",
        "",
        "`POST /patients` is the async pending-ack path — scoring runs out-of-band, "
        "not in the request. The intakes are then scored as untimed setup so the "
        "detail / PATCH / override endpoints are measured against real scored rows.",
        "",
        *table,
        "",
        f"**Overall steady-state average: {overall:.1f} ms** "
        f"— DoD (< 150 ms): **{dod}**",
        "",
        f"_Raw timing log: {log_path.name} ({sum(len(v) for v in buckets.values())} "
        f"matched requests)._",
        "",
    ]
    text = "\n".join(report)
    summary_path.write_text(text, encoding="utf-8")
    print("\n" + text)
    print(f"Summary written to {summary_path}")


if __name__ == "__main__":
    main()
