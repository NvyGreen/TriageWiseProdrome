# Queue Stress — Sustained Load

Sustained concurrent `POST /patients` + `GET /queue` (Locust) against a 4-worker uvicorn on the `triage_wise_prodrome_test` DB. Submit is async (returns `pending`; scoring runs out-of-band), so correctness is checked after the scoring backlog drains, read straight from the DB.

## Load (client-measured)

- Workers: **4**
- Users / spawn rate / duration: **50 / 10.0/s / 60s**
- POST /patients: 4759 reqs, 0 fail, 79.3 req/s, avg 290.6 ms, p95 570.0 ms
- GET /queue: 1494 reqs, 0 fail, 24.9 req/s, avg 290.5 ms, p95 560.0 ms

## Scoring (async, after drain)

- Scored: 4759
- Unscoreable: 0
- Failed: 0
- Still pending (backlog didn't drain): 0

## Correctness (scored intakes vs. triage_queue)

- Should be queued (scored): 4759
- In queue: 4759
- Lost (scored but not queued): 0
- Unexpected (queued but not scored): 0
- Duplicates: 0
- Misordered: no

**DoD (no duplicates / no misordering / no lost inserts): PASS**

## Notes

- Submit returns fast (`pending`); scoring runs in a **separate process** (`app/scorer.py`), not in the web worker. Submit throughput is decoupled from scoring; total scoring throughput is bounded by the scorer's CPU + DB.
- GET /queue runs under the same load (read-path stress).
- **Latency is under concurrent load** (50 users, ~79 req/s on POST, 4 workers, one machine). These are not comparable to `latency.md`, which times a single request against an idle server; the difference is queueing + DB contention under load — a capacity characterization, not a regression.
- **p95 values sit on Locust bucket boundaries.** Locust buckets response times, so p95 rounds to a bucket edge; identical round p95s across endpoints are a bucketing artifact, not a coincidence.
- **Load vs. correctness counts are measured differently.** Load counts are client-side (Locust); Scoring/Correctness counts are read from the DB (server truth). A small gap between the POST count and the scored count is expected — requests in flight when the run stops commit server-side without being counted by the client. The correctness check uses the DB counts.
- If 'still pending' > 0, scoring couldn't keep up with submit — a real capacity signal, not a correctness failure.
- **Probabilistic, single run.** Like the burst test (`queue_concurrency.md`), sustained load gives evidence of correctness under this profile, not proof that no race can ever occur — a green run is not a proof of absence.
- Transactional tables were reset before the run; reference tables preserved. Rows were added to the disposable `triage_wise_prodrome_test` DB.
