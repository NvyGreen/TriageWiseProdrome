# API Latency Smoke Test

Server-side handler latency (uvicorn, `triage_wise_prodrome_test` DB). Steady-state drops the first 10 calls per endpoint.

`POST /patients` is the async pending-ack path — scoring runs out-of-band, not in the request. The intakes are then scored as untimed setup so the detail / PATCH / override endpoints are measured against real scored rows.

| Endpoint | n (steady) | avg steady ms | p95 steady ms | avg all-in ms |
| --- | --- | --- | --- | --- |
| `POST /patients` | 50 | 13.5 | 18.2 | 17.3 |
| `GET /queue` | 50 | 15.2 | 29.0 | 14.7 |
| `GET /intakes/{id}` | 50 | 20.0 | 29.5 | 21.3 |
| `PATCH /intakes/{id}` | 50 | 28.3 | 49.6 | 27.6 |
| `POST /overrides` | 50 | 20.6 | 27.0 | 20.1 |

**Overall steady-state average: 19.5 ms** — DoD (< 150 ms): **PASS**
