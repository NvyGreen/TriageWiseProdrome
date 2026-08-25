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
SCORER_LOG = Path(tempfile.gettempdir()) / "queue_stress_scorer.log"


@events.init_command_line_parser.add_listener
def _add_args(parser):
    parser.add_argument(
        "--label", type=str, default="",
        help="suffix for the summary file: docs/validation/queue_stress_<label>.md",
    )
    parser.add_argument(
        "--workers", type=int, default=1,
        help="uvicorn worker processes for the server under test",
    )

# gevent runs one OS thread cooperatively, so a plain counter/list are safe here.
_counter = itertools.count()
SUBMITTED = []
_server = {}


class QueueUser(HttpUser):
    host = BASE_URL

    @task(3)
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

    @task(1)
    def read_queue(self):
        # Exercise the read path under the same load, so we measure whether
        # GET /queue survives concurrent submits + background scoring.
        with self.client.get("/queue/", name="GET /queue", catch_response=True) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"status {resp.status_code}")


@events.test_start.add_listener
def _on_start(environment, **_kw):
    workers = getattr(environment.parsed_options, "workers", 1) or 1
    proc, log_file = lc.start_server(PORT, SERVER_LOG, workers=workers)
    _server["proc"], _server["log"] = proc, log_file
    lc.wait_until_up(BASE_URL)
    # The web server no longer scores; start the standalone scorer so the pending
    # backlog actually drains during/after the run.
    scorer_proc, scorer_log = lc.start_scorer(SCORER_LOG)
    _server["scorer_proc"], _server["scorer_log"] = scorer_proc, scorer_log


def _stat(environment, name, method):
    """Per-endpoint (avg ms, p95 ms, count, failures) or None if it never ran."""
    entry = environment.stats.get(name, method)
    if entry is None or entry.num_requests == 0:
        return None
    return {
        "count": entry.num_requests,
        "failures": entry.num_failures,
        "avg": entry.avg_response_time,
        "p95": entry.get_response_time_percentile(0.95),
    }


@events.test_stop.add_listener
def _on_stop(environment, **_kw):
    try:
        # Submit is async: wait for the scoring backlog to drain, then read final
        # state straight from the DB (not by polling GET /queue, which would add
        # read load while the server is still churning through scoring).
        counts = lc.wait_until_scored()
        actual_ids = lc.db_queue_ids()
        scored_ids = lc.db_scored_intake_ids()
        result = lc.check_queue(scored_ids, actual_ids)
        verdict = "PASS" if result["ok"] else "FAIL"

        opts = environment.parsed_options
        label = getattr(opts, "label", "") or ""
        workers = getattr(opts, "workers", 1) or 1
        run_time = getattr(opts, "run_time", None)
        post = _stat(environment, "POST /patients", "POST")
        getq = _stat(environment, "GET /queue", "GET")

        scored = counts.get("scored", 0)
        unscoreable = counts.get("unscoreable", 0)
        failed = counts.get("failed", 0)
        pending_left = counts.get("pending", 0)

        def _line(label_, s):
            if s is None:
                return f"- {label_}: (none)"
            rps = s["count"] / run_time if run_time else 0
            return (f"- {label_}: {s['count']} reqs, {s['failures']} fail, "
                    f"{rps:.1f} req/s, avg {s['avg']:.1f} ms, p95 {s['p95']:.1f} ms")

        lines = [
            f"# Queue Stress — Sustained Load (build order 62){f' [{label}]' if label else ''}",
            "",
            f"Sustained concurrent `POST /patients` + `GET /queue` (Locust) against a "
            f"{workers}-worker uvicorn on the `{lc.TEST_DB}` DB. Submit is async "
            f"(returns `pending`; scoring runs out-of-band), so correctness is checked "
            f"after the scoring backlog drains, read straight from the DB.",
            "",
            "## Load (client-measured)",
            "",
            f"- Workers: **{workers}**",
            f"- Users / spawn rate / duration: **{opts.num_users} / {opts.spawn_rate}/s / {run_time}s**",
            _line("POST /patients", post),
            _line("GET /queue", getq),
            "",
            "## Scoring (async, after drain)",
            "",
            f"- Scored: {scored}",
            f"- Unscoreable: {unscoreable}",
            f"- Failed: {failed}",
            f"- Still pending (backlog didn't drain): {pending_left}",
            "",
            "## Correctness (scored intakes vs. triage_queue)",
            "",
            f"- Should be queued (scored): {result['submitted']}",
            f"- In queue: {result['in_queue']}",
            f"- Lost (scored but not queued): {len(result['lost'])}",
            f"- Unexpected (queued but not scored): {len(result['unexpected'])}",
            f"- Duplicates: {len(result['duplicates'])}",
            f"- Misordered: {'yes' if result['misordered'] else 'no'}"
            + (f" (first at index {result['first_misorder_index']})"
               if result["misordered"] else ""),
            "",
            f"**DoD (no duplicates / no misordering / no lost inserts): {verdict}**",
            "",
            "## Notes",
            "",
            "- Submit returns fast (`pending`); scoring is an in-process background "
            "task, so throughput is still bounded by the worker's CPU + DB.",
            "- GET /queue runs under the same load (read-path stress).",
            "- If 'still pending' > 0, scoring couldn't keep up with submit — a real "
            "capacity signal, not a correctness failure.",
            f"- Added rows to the disposable `{lc.TEST_DB}` DB.",
            "",
        ]
        suffix = f"_{label}" if label else ""
        summary_path = lc.BACKEND.parent / "docs" / "validation" / f"queue_stress{suffix}.md"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text("\n".join(lines), encoding="utf-8")
        print("\n" + "\n".join(lines))
        print(f"Summary written to {summary_path}")

        if not result["ok"]:
            print(f"\nFAIL details: lost={result['lost'][:10]} "
                  f"dups={result['duplicates'][:10]} "
                  f"first_misorder_index={result['first_misorder_index']}")
            environment.process_exit_code = 1
        else:
            environment.process_exit_code = 0
    finally:
        # Stop the scorer only after the drain wait above, so it can finish scoring.
        if "scorer_proc" in _server:
            lc.stop_server(_server["scorer_proc"], _server["scorer_log"])
        lc.stop_server(_server["proc"], _server["log"])
