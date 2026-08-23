"""Concurrent-insert ordering stress test (build order: queue stability).

Proves the triage queue stays correctly ordered under concurrent inserts. Fires
bursts of N simultaneous POST /patients (aligned with a Barrier so they hit the
shared in-memory queue at the same instant — the worst-case interleave), repeated
over R rounds, then checks the whole queue against a DB-derived expected order.

  python scripts/queue_concurrency_smoke.py [--port 8098] [--concurrent 50]
                                            [--rounds 20] [--out-dir <dir>]

DoD: no lost inserts, no duplicates, no misordering.

Honest limits (also in the report):
  - Single uvicorn worker (the queue is per-process; >1 worker would split it).
  - Concurrency tests are probabilistic — high parallelism x repetition raises
    confidence, it can't prove absence of races. With the queue's RLock in place
    a clean pass is expected.
  - FastAPI caps concurrent sync handlers (~40); beyond that requests queue
    server-side. Still ample interleave.
  - Writes ~N*R rows to the disposable _test DB; not cleaned up.
"""
import argparse
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import load_common as lc  # noqa: E402


def _run_round(base_url, indices):
    """Fire len(indices) POSTs simultaneously (Barrier-aligned). Return the
    intake_ids that came back 201."""
    n = len(indices)
    barrier = threading.Barrier(n)

    def _task(i):
        barrier.wait(timeout=30)  # all threads release together
        return lc.post_intake(base_url, i)

    with ThreadPoolExecutor(max_workers=n) as pool:
        results = list(pool.map(_task, indices))
    return [r for r in results if r is not None]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8098)
    ap.add_argument("--concurrent", type=int, default=50)
    ap.add_argument("--rounds", type=int, default=20)
    ap.add_argument(
        "--out-dir",
        default=str(lc.BACKEND.parent / "docs" / "validation"),
    )
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / "queue_concurrency.md"
    server_log = Path(tempfile.gettempdir()) / "queue_concurrency_server.log"
    base_url = f"http://127.0.0.1:{args.port}"

    proc, log_file = lc.start_server(args.port, server_log)
    submitted, attempted = [], 0
    try:
        lc.wait_until_up(base_url)
        print(f"server up on {base_url}; {args.rounds} rounds x {args.concurrent} "
              f"simultaneous inserts...")
        counter = 0
        for r in range(args.rounds):
            indices = list(range(counter, counter + args.concurrent))
            counter += args.concurrent
            attempted += args.concurrent
            submitted.extend(_run_round(base_url, indices))

        actual_ids = lc.fetch_queue_ids(base_url)
    finally:
        lc.stop_server(proc, log_file)

    result = lc.check_queue(submitted, actual_ids)
    verdict = "PASS" if result["ok"] else "FAIL"
    failed_posts = attempted - result["submitted"]

    lines = [
        "# Queue Concurrency Stress — Concurrent Inserts",
        "",
        f"Barrier-aligned simultaneous `POST /patients` against a single-worker "
        f"uvicorn on the `{lc.TEST_DB}` DB. Queue order checked against a "
        f"DB-derived expected order (sort key: esi_band, flag_tier, arrival, intake_id).",
        "",
        "## Run",
        "",
        f"- Rounds x concurrency: **{args.rounds} x {args.concurrent}**",
        f"- POSTs attempted: {attempted}",
        f"- Succeeded (201): {result['submitted']}"
        + (f"  ⚠ {failed_posts} failed" if failed_posts else ""),
        f"- In queue after run: {result['in_queue']}",
        "",
        "## Result",
        "",
        f"- Lost inserts: {len(result['lost'])}",
        f"- Duplicates: {len(result['duplicates'])}",
        f"- Misordered: {'yes' if result['misordered'] else 'no'}"
        + (f" (first at index {result['first_misorder_index']})"
           if result["misordered"] else ""),
        "",
        f"**DoD (no lost / no duplicates / no misordering): {verdict}**",
        "",
        "## Notes",
        "",
        "- Single uvicorn worker (the in-memory queue is per-process).",
        "- Concurrency tests are probabilistic; this raises confidence, it can't "
        "prove absence of races. The queue's `RLock` is what makes ordering robust.",
        "- FastAPI caps concurrent sync handlers (~40); extra requests queue "
        "server-side but still interleave.",
        f"- Added ~{result['submitted']} rows to the disposable `{lc.TEST_DB}` DB.",
        "",
    ]
    text = "\n".join(lines)
    summary_path.write_text(text, encoding="utf-8")
    print("\n" + text)
    print(f"Summary written to {summary_path}")
    if not result["ok"]:
        # Surface a compact diff for debugging.
        print(f"\nFAIL details: lost={result['lost'][:10]} "
              f"dups={result['duplicates'][:10]} "
              f"first_misorder_index={result['first_misorder_index']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
