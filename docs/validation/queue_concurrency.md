# Queue Concurrency Stress — Concurrent Submits

Barrier-aligned simultaneous `POST /patients` against a single-worker uvicorn + a separate scorer process on the `triage_wise_prodrome_test` DB. Submit is async (returns `pending`); the scorer scores intakes out-of-band into `triage_queue`. After the backlog drains, the queue is read from the DB and checked against a DB-derived expected order (sort key: esi_band, flag_tier, arrival, intake_id).

## Run

- Rounds x concurrency: **20 x 50**
- POSTs attempted: 1000
- Scored (should be queued): 1000
- Unscoreable / Failed: 0 / 0
- Still pending (backlog didn't drain): 0
- In queue after run: 1000

## Result

- Lost inserts: 0
- Duplicates: 0
- Misordered: no

**DoD (no lost / no duplicates / no misordering): PASS**

## Notes

- The barrier aligns concurrent SUBMITS; scoring is out-of-band, so this probes the concurrent DB-insert + async-scoring path, not an in-process lock.
- Correctness comes from the DB: the sort-key ordering and the unique `triage_queue.intake_id` constraint (prevents duplicate queue rows).
- Concurrency tests are probabilistic; this raises confidence, it can't prove absence of races.
- FastAPI caps concurrent sync handlers (~40); extra requests queue server-side but still interleave.
- Added ~1000 rows to the disposable `triage_wise_prodrome_test` DB.
