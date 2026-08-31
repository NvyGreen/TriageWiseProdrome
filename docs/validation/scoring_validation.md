# Scoring Engine Validation

_Generated 2026-08-30 21:18. Source: MC-MED-derived datasets (500 records each). Scored against the `triage_wise_prodrome_test` database; all writes rolled back._

## Metrics

| Dataset | Scored | Agreement (exact ESI) | Under-triage | Over-triage | AUC (severity_score → admit) |
| --- | --- | --- | --- | --- | --- |
| `balanced.json` | 500/500 | 40.2% | 31.6% | 28.2% | 0.853 |
| `representative.json` | 500/500 | 32.4% | 46.2% | 21.4% | 0.664 |

- **Agreement** — predicted ESI band equals `true_esi` exactly.
- **Under-triage** — engine scored *less* acute than the real ESI (higher ESI number). The dangerous direction.
- **Over-triage** — engine scored *more* acute than the real ESI. Shown for context.
- **AUC** — rank-based (Mann-Whitney) of the continuous `severity_score` against the real outcome (admit = `admitted` ∪ `icu`, vs `discharged`). 0.5 = chance, 1.0 = perfect separation.

## Limitations

- **Chief-complaint mapping noise.** Free-text ED complaints were mapped down to the engine's nine complaint groups; that mapping is lossy, so a record's complaint may not match what a real intake form would produce — and the complaint drives most of the score.
- **Psychiatric cases out of scope.** The engine does not triage psychiatric or behavioral presentations; the extractor filters them out (suicidal, self-harm, anxiety, panic, agitation) before scoring, so they are absent from these datasets by design. Toxicology (overdose, intoxication) is treated as medical and retained.
- **Neonate / age precision.** The source only provides age in years, so `date_of_birth` is reconstructed as `YYYY-01-01`. Day-level age is lost, so the febrile-neonate red flag (8–60 days) and any day-precision age logic cannot fire.
- **Unscoreable records excluded.** Records whose (mapped) complaint has no scoring rule are dropped from the metrics: 0 from `balanced.json`, 0 from `representative.json`.
- **Single-center source.** MC-MED is one academic ED; agreement and outcome relationships may not generalize to other settings.
- **AUC predictor.** Uses the continuous `severity_score` (raw points), not the discretized 1–5 band, so it reflects the underlying ranking rather than the banded output clinicians see.
