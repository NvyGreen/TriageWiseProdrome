"""Ranking validation over validation_dataset_20.json (reqs 1.12 / 1.15 / 46).

Each case is a bare intake plus an independent clinician_esi ground-truth label.
We submit every case, override the ones where the engine disagrees with the
clinician label, build the queue, then assert the queue ranks by clinician ESI:
for any pair (A, B) with A more acute than B, A must sit ahead of B.

Harness notes (confirmed against the code):
  - The method is submitIntake(intake, queue) (not submitPatient).
  - submitIntake/Result don't return severity_id or the system ESI, so we look up
    PatientSeverity by the returned intake_id to decide disagreement and to call
    applyOverride.
  - applyOverride needs a reason_code; the dataset has none, so we pass
    ReasonCode.OTHER — only the band matters here.
  - case_id / clinician_esi aren't IntakeCreate fields; we strip them, add a name,
    and resolve `_dob_days_ago_N` to N days before today.

This validates the submit -> override -> ranked-queue plumbing, not scoring
accuracy against the labels (by design: every disagreeing case is overridden, so
the effective band is the clinician label for all).
"""
import json
from datetime import date, timedelta
from itertools import permutations
from pathlib import Path

import pytest
from sqlalchemy import select

from app.schemas.intake_create import IntakeCreate
from app.models.patient_severity import PatientSeverity
from app.services.priority_queue import PriorityQueue
from app.services.triage_service import TriageService
from app.utils.enums import ReasonCode

UNIT_CASES = Path(__file__).parent / "unit_cases"
CASES = json.loads((UNIT_CASES / "validation_dataset_20.json").read_text(encoding="utf-8"))["cases"]

NON_INTAKE_KEYS = {"case_id", "clinician_esi"}


def _esi_num(esi: str) -> int:
    """'ESI-2' -> 2. Lower is more acute."""
    return int(esi[-1])


def _build_intake(case: dict) -> IntakeCreate:
    fields = {k: v for k, v in case.items() if k not in NON_INTAKE_KEYS}

    dob = fields["date_of_birth"]
    if isinstance(dob, str) and dob.startswith("_dob_days_ago_"):
        days = int(dob.rsplit("_", 1)[-1])
        dob = date.today() - timedelta(days=days)
    fields["date_of_birth"] = dob

    # IntakeCreate requires a name; the dataset omits it.
    fields["name"] = f"Validation {case['case_id']}"
    return IntakeCreate(**fields)


def test_clinician_override_ranking(db_session):
    service = TriageService(db_session)

    clinician_esi = {}   # case_id -> clinician ESI label
    intake_id_of = {}    # case_id -> real intake_id

    for case in CASES:
        cid = case["case_id"]
        clinician_esi[cid] = case["clinician_esi"]

        result = service.submitIntake(_build_intake(case))

        severity = db_session.scalar(
            select(PatientSeverity).where(PatientSeverity.intake_id == result.intake_id)
        )
        # Override only where the engine disagrees with the clinician label.
        if severity.system_ESI != case["clinician_esi"]:
            service.applyOverride(
                severity.severity_id, case["clinician_esi"], ReasonCode.OTHER, None
            )

        intake_id_of[cid] = result.intake_id

    # Position of each case in the finished queue.
    entries = service.getQueue()
    position_by_intake = {e.intake_id: e.position for e in entries}
    position = {cid: position_by_intake[iid] for cid, iid in intake_id_of.items()}

    assert len(position) == len(CASES) == 20

    # For every pair where A is more acute than B (ignoring equal ESI), A must
    # rank ahead of B.
    case_ids = list(clinician_esi)
    for a, b in permutations(case_ids, 2):
        if _esi_num(clinician_esi[a]) < _esi_num(clinician_esi[b]):
            assert position[a] < position[b], (
                f"{a} ({clinician_esi[a]}, pos {position[a]}) should rank ahead of "
                f"{b} ({clinician_esi[b]}, pos {position[b]})"
            )
