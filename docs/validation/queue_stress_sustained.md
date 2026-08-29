# Queue Stress — Sustained Load (build order 62) [poller_4w]

Sustained concurrent `POST /patients` + `GET /queue` (Locust) against a 4-worker uvicorn on the `triage_wise_prodrome_test` DB. Submit is async (returns `pending`; scoring runs out-of-band), so correctness is checked after the scoring backlog drains, read straight from the DB.

## Load (client-measured)

- Workers: **4**
- Users / spawn rate / duration: **50 / 10.0/s / 60s**
- POST /patients: 3780 reqs, 0 fail, 63.0 req/s, avg 489.6 ms, p95 1100.0 ms
- GET /queue: 1230 reqs, 0 fail, 20.5 req/s, avg 512.2 ms, p95 1100.0 ms

These are **saturated-load** numbers, not the single-client latency in
[`latency.md`](latency.md) (`POST /patients` ~13.5 ms avg). The ~36x gap is queueing
delay, not slower work: 50 concurrent users against 4 workers on one machine drives
requests to wait on workers and DB connections. This run characterises behaviour at
capacity — it is a correctness test under sustained load, and no latency DoD is
claimed against it.

## Scoring (async, after drain)

- Scored: 3784
- Unscoreable: 0
- Failed: 0
- Still pending (backlog didn't drain): 0

## Correctness (scored intakes vs. triage_queue)

- Should be queued (scored): 3784
- In queue: 3784
- Lost (scored but not queued): 0
- Unexpected (queued but not scored): 0
- Duplicates: 0
- Misordered: no

**DoD (no duplicates / no misordering / no lost inserts): PASS**

## Notes

- Submit returns fast (`pending`); scoring happens out-of-band in a separate scorer process (`app/scorer.py`), so submit throughput is bounded by the web workers + DB, and scoring throughput by the scorer + DB independently.
- GET /queue runs under the same load (read-path stress).
- If 'still pending' > 0, scoring couldn't keep up with submit — a real capacity signal, not a correctness failure.
- Added rows to the disposable `triage_wise_prodrome_test` DB.
