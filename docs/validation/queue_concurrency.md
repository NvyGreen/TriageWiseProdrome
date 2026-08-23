# Queue Concurrency Stress — Concurrent Inserts

Barrier-aligned simultaneous `POST /patients` against a single-worker uvicorn on the `triage_wise_prodrome_test` DB. Queue order checked against a DB-derived expected order (sort key: esi_band, flag_tier, arrival, intake_id).

## Run

- Rounds x concurrency: **20 x 50**
- POSTs attempted: 1000
- Succeeded (201): 1000
- In queue after run: 1000

## Result

- Lost inserts: 0
- Duplicates: 0
- Misordered: no

**DoD (no lost / no duplicates / no misordering): PASS**

## Notes

- Single uvicorn worker (the in-memory queue is per-process).
- Concurrency tests are probabilistic; this raises confidence, it can't prove absence of races. The queue's `RLock` is what makes ordering robust.
- FastAPI caps concurrent sync handlers (~40); extra requests queue server-side but still interleave.
- Added ~1000 rows to the disposable `triage_wise_prodrome_test` DB.
