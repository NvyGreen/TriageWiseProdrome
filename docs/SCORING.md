# Scoring — Missing Data Handling

Fallback rules for partial patient inputs.

Scoring runs even when vitals are missing. Each missing vital follows a
fallback rule so a partial intake produces a score instead of an error.

## Fallback types

| Type | Meaning | Applies to |
|---|---|---|
| **Skip** | Rule not evaluated; no points added; confidence set LOW | `heart_rate`, `respiration_rate`, `blood_pressure_systolic` |
| **Default** | Assume a safe value, then score normally; confidence set LOW | `oxygen_saturation` → assume normal (flag re-measure); `pain_level` → assume 0 |

Every fallback also:
- Records the absent field in `missing_fields`.
- Lowers data completeness (surfaced in the UI and the explanation layer).

## Exception

`chief_complaint` has **no fallback** — it is required. A missing
`chief_complaint` is rejected at input validation with HTTP 400 before
scoring runs.

## Source of truth

The per-rule fallback action lives in the `fallback_if_missing` column of the
`scoring_rule` reference table. **That reference table is authoritative** —
this document describes the pattern; the reference table holds the exact values.

> Note: `temperature` and `blood_sugar` are not `scoring_rule` factors, so they
> have no scoring fallback here. (They may be read by the red-flag layer via
> `vital_range`, which is separate from scoring.)