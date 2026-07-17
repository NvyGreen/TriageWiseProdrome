# Scoring Rubric

The rule table the scoring engine evaluates. Each rule maps a **factor → threshold → weight**, contributing additively to a severity score that maps to an ESI band.

**Anchored to a published reference:** Emergency Severity Index (ESI) Version 4 Implementation Handbook, AHRQ 2012. Per-rule rationale additionally draws on NHAMCS admit-rate data and published clinical risk tools.

**Source of truth:** the `scoring_rule` reference table (loaded into the DB). The engine reads it at runtime — rules are **not** hardcoded. This document presents that table for review; the reference table holds the authoritative values.

## Vital-sign rules

| Factor | Threshold (fires when) | Weight | Rationale / anchor |
|---|---|---|---|
| SpO₂ | < 92% | 4 | Hypoxia — ESI-2 danger vital |
| SpO₂ | 92–94% (borderline) | 2 | Borderline low |
| Heart rate | > 120 bpm | 3 | Marked tachycardia |
| Heart rate | 100–120 bpm | 1 | Mild tachycardia |
| Respiratory rate | > 24 / min | 3 | Tachypnea |
| Systolic BP | < 90 mmHg | 4 | Hypotension / shock — ESI-1/2 |
| Pain score | ≥ 7 / 10 | 1 | Severe pain modifier |

## Chief-complaint rules

| Complaint | Group | Resource level | Weight | Rationale / anchor |
|---|---|---|---|---|
| Stroke symptoms (FAST) | stroke | many | 6 | Time-critical; NHAMCS stroke ~53% admit → push ESI-2 |
| Chest pain (cardiac concern) | cardiac | many | 6 | Cardiac dx ~70% admit vs 14% all chest pain → ESI-2 |
| Shortness of breath | respiratory | many | 4 | NHAMCS SOB ~26% admit |
| Severe headache / neuro | neuro | many | 4 | High-risk neuro presentation |
| Syncope (fainting) | syncope | one | 3 | ECG, labs, monitor — NHAMCS ~21% admit |
| Abdominal pain | abdominal | many | 2 | NHAMCS abdominal ~9% admit — lower baseline |
| Other / general | general | one | 1 | Default low weight |
| Minor injury (sprain, small laceration) | minor_injury | one | 1 | Single X-ray or repair |
| Minor complaint (rash, med refill, cold) | minor_general | none | 1 | Exam only, fast-track |

## Design note — why the red-flag layer exists

Additive scoring can **under-triage** in edge cases. Example: a 58-year-old with chest pain scores ESI-2 via the +6 complaint tier, but additive points alone may not capture a patient who is individually high-risk despite modest vitals. The deterministic **red-flag escalation layer** exists as the safety net — it catches time-critical and occult-risk patterns that a purely additive score could miss, and it affects queue ordering without altering the ESI band the score produces.

## Scope

This rubric defines the rules. Whether the engine implements them exactly is verified separately (scoring engine + its tests). Missing-vital fallback behavior is documented in `scoring.md`.