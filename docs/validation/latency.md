# API Latency Smoke Test

Server-side handler latency (uvicorn, `triage_wise_prodrome_test` DB). Steady-state drops the first 10 calls per endpoint.

| Endpoint | n (steady) | avg steady ms | p95 steady ms | avg all-in ms |
| --- | --- | --- | --- | --- |
| `POST /patients` | 50 | 36.2 | 72.5 | 42.0 |
| `GET /queue` | 50 | 16.3 | 23.4 | 16.7 |
| `GET /intakes/{id}` | 50 | 17.0 | 21.9 | 17.1 |
| `PATCH /intakes/{id}` | 50 | 22.7 | 38.4 | 23.3 |
| `POST /overrides` | 50 | 15.8 | 26.1 | 15.7 |

**Overall steady-state average: 21.6 ms** — DoD (< 150 ms): **PASS**
