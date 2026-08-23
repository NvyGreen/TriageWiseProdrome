"""Sustained-load queue stress (build order 62 — D4 stress testing).

Validates the triage queue stays correct under sustained concurrent load (no
duplicates / no misordering / no lost inserts) and reports throughput. Uses the
shared harness in load_common: same single-worker server, payload builder, and
DB-derived ordering oracle as the barrier burst test — only the concurrency
engine differs (Locust users vs. Barrier).

Run (headless):
    cd backend
    ../.venv/Scripts/locust.exe -f scripts/locustfile.py --headless -u 50 -r 10 -t 60s

  -u users  -r spawn-rate/sec  -t duration. Host is set on the user class, so
  --host isn't needed.

Lifecycle:
  - test_start: launch a single-worker uvicorn on the _test DB (fresh => empty
    queue, so only this run fills it).
  - users: loop POST /patients with distinct payloads + unique Idempotency-Keys;
    each 201 records its intake_id.
  - test_stop: run the oracle (GET /queue vs. expected order), write
    docs/validation/queue_stress.md, set the process exit code, stop the server.

Honest limits (same family as the burst test): single worker required; ~40
concurrent handlers server-side; probabilistic; adds rows to the disposable
_test DB. Sustained load probes stability over time, not the same-instant
collision the barrier test manufactures.
"""
import itertools
import sys
import tempfile
import time
import uuid
from pathlib import Path

from locust import HttpUser, events, task

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load_common as lc  # noqa: E402

PORT = 8097
BASE_URL = f"http://127.0.0.1:{PORT}"
SERVER_LOG = Path(tempfile.gettempdir()) / "queue_stress_server.log"
SUMMARY_PATH = lc.BACKEND.parent / "docs" / "validation" / "queue_stress.md"

# gevent runs one OS thread cooperatively, so a plain counter/list are safe here.
_counter = itertools.count()
SUBMITTED = []
_server = {}


class QueueUser(HttpUser):
    host = BASE_URL

    @task
    def submit(self):
        i = next(_counter)
        with self.client.post(
            "/patients/",
            json=lc.make_intake(i),
            headers={"Idempotency-Key": uuid.uuid4().hex},
            name="POST /patients",
            catch_response=True,
        ) as resp:
            if resp.status_code == 201:
                SUBMITTED.append(lc.unwrap(resp.json())["intake_id"])
                resp.success()
            else:
                resp.failure(f"status {resp.status_code}")


@events.test_start.add_listener
def _on_start(environment, **_kw):
    proc, log_file = lc.start_server(PORT, SERVER_LOG)
    _server["proc"], _server["log"] = proc, log_file
    lc.wait_until_up(BASE_URL)


def _drain_and_fetch(timeout=30.0):
    """When the run stops, in-flight requests may still be committing. Because
    queue.insert happens BEFORE the router's DB commit, GET /queue can transiently
    500 on a queued id that isn't committed-visible yet. Wait until submissions
    stop arriving and the queue matches, retrying past those transients."""
    deadline = time.time() + timeout
    prev, last_ids = -1, []
    while time.time() < deadline:
        time.sleep(0.5)
        try:
            ids = lc.fetch_queue_ids(BASE_URL)
        except Exception:
            continue  # transient: a queued id isn't committed-visible yet
        if len(ids) == prev:
            return ids  # queue size settled -> in-flight requests drained
        prev, last_ids = len(ids), ids
    return last_ids or lc.fetch_queue_ids(BASE_URL)


@events.test_stop.add_listener
def _on_stop(environment, **_kw):
    try:
        actual_ids = _drain_and_fetch()
        # Membership truth from the DB, not the client list: Locust kills in-flight
        # greenlets at shutdown after the server already committed, so the
        # client-side SUBMITTED count is short. The DB has every committed intake.
        universe = lc.db_run_intake_ids()
        result = lc.check_queue(universe, actual_ids)
        verdict = "PASS" if result["ok"] else "FAIL"

        total = environment.stats.total
        opts = environment.parsed_options
        run_time = getattr(opts, "run_time", None)
        rps = (total.num_requests / run_time) if run_time else None
        p95 = total.get_response_time_percentile(0.95)

        lines = [
            "# Queue Stress — Sustained Load (build order 62)",
            "",
            f"Sustained concurrent `POST /patients` (Locust) against a single-worker "
            f"uvicorn on the `{lc.TEST_DB}` DB. Queue order checked against a "
            f"DB-derived expected order (sort key: esi_band, flag_tier, arrival, intake_id).",
            "",
            "## Load",
            "",
            f"- Users / spawn rate / duration: **{opts.num_users} / {opts.spawn_rate}/s / {run_time}s**",
            f"- Requests: {total.num_requests}  (failures: {total.num_failures})",
            f"- Throughput: {rps:.1f} req/s" if rps else "- Throughput: n/a",
            f"- Latency: avg {total.avg_response_time:.1f} ms, p95 {p95:.1f} ms",
            "",
            "## Correctness",
            "",
            f"- Succeeded (201): {result['submitted']}",
            f"- In queue after run: {result['in_queue']}",
            f"- Lost inserts: {len(result['lost'])}",
            f"- Duplicates: {len(result['duplicates'])}",
            f"- Misordered: {'yes' if result['misordered'] else 'no'}"
            + (f" (first at index {result['first_misorder_index']})"
               if result["misordered"] else ""),
            "",
            f"**DoD (no duplicates / no misordering / no lost inserts): {verdict}**",
            "",
            "## Notes",
            "",
            "- Single uvicorn worker (the in-memory queue is per-process).",
            "- Sustained overlap over time; does not manufacture the same-instant "
            "collision the barrier test does. Complementary probes.",
            "- ~40 concurrent handlers server-side; extra requests queue briefly.",
            "- Probabilistic — raises confidence, can't prove absence of races.",
            f"- Added ~{result['submitted']} rows to the disposable `{lc.TEST_DB}` DB.",
            "",
        ]
        SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
        SUMMARY_PATH.write_text("\n".join(lines), encoding="utf-8")
        print("\n" + "\n".join(lines))
        print(f"Summary written to {SUMMARY_PATH}")

        if not result["ok"]:
            print(f"\nFAIL details: lost={result['lost'][:10]} "
                  f"dups={result['duplicates'][:10]} "
                  f"first_misorder_index={result['first_misorder_index']}")
            environment.process_exit_code = 1
        else:
            environment.process_exit_code = 0
    finally:
        lc.stop_server(_server["proc"], _server["log"])
