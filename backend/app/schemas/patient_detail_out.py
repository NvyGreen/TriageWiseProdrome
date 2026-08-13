"""
Response schema for GET /intakes/{intake_id}.

Design:
  - PatientDetail (the domain view-model) stays fully populated regardless of mode.
  - This OUTPUT layer decides what leaves the server. In black-box mode the
    reasoning fields are never attached, so `model_dump(exclude_none=True)`
    omits them entirely — the explanation data does not go over the wire.
  - Nested dataclasses (Driver, Trigger) are mapped EXPLICITLY, so only the
    fields meant for the clinician view are exposed (no rule_id, no trigger
    trees).

Mode gating lives in one place: PatientDetailOut.from_detail.

Dual-score (R2): the two ESI numbers ("System suggests X / Clinician score Y")
carry no driver info, so `dual_score_line` is shown in BOTH modes. The
`xai_line` NAMES the delta drivers ("System weighted chest pain + SpO2 ..."),
which is reasoning — so it is XAI-only.
"""

from enum import Enum

from pydantic import BaseModel

from ..utils.dates import age_in_years
from ..utils.constants import LABEL_MAP


class Mode(str, Enum):
    XAI = "xai"
    BLACKBOX = "blackbox"


# --------------------------------------------------------------------------
# Nested output pieces (xai-only content)
# --------------------------------------------------------------------------
class DriverOut(BaseModel):
    factor: str
    threshold: str
    weight: int
    patient_value: str | int
    contribution_pct: int

    @classmethod
    def from_driver(cls, d) -> "DriverOut":
        # rule_id intentionally omitted — rule IDs are not shown in the view.
        return cls(
            factor=d.factor,
            threshold=d.threshold,
            weight=d.weight,
            patient_value=d.patient_value,
            contribution_pct=d.contribution_pct,
        )


class ExplanationOut(BaseModel):
    data_completeness: str
    named_drivers: list[DriverOut]
    gap_acknowledgement: dict[str, list[str]]
    fallback_instruction: str

    @classmethod
    def from_explanation(cls, e) -> "ExplanationOut":
        return cls(
            data_completeness=e.data_completeness,
            named_drivers=[DriverOut.from_driver(d) for d in e.named_drivers],
            gap_acknowledgement=e.gap_acknowledgement,
            fallback_instruction=e.fallback_instruction,
        )


class RedFlagOut(BaseModel):
    message: str
    flag_tier: int
    flag_type: str
    rationale: str

    @classmethod
    def from_trigger(cls, t) -> "RedFlagOut":
        # trigger_pattern / trigger_pattern_tree omitted — evaluation machinery,
        # not display data.
        return cls(
            message=t.message,
            flag_tier=t.flag_tier,
            flag_type=t.flag_type,
            rationale=t.rationale,
        )


class OverrideOut(BaseModel):
    system_esi: str
    clinician_esi: str
    reason_code: str

    @classmethod
    def from_override(cls, o) -> "OverrideOut":
        return cls(
            system_esi=o.system_esi,
            clinician_esi=o.clinician_esi,
            reason_code=o.reason_code,
        )


# --------------------------------------------------------------------------
# The response
# --------------------------------------------------------------------------
class PatientDetailOut(BaseModel):
    # --- always shown (black-box AND xai) ---
    patient_name: str
    age: int
    sex: str
    severity_score: float
    system_esi: str
    band_name: str
    # dual-score numbers carry no driver info -> safe in both modes.
    # None when no clinician_ESI was supplied (omitted by exclude_none).
    dual_score_line: str | None = None

    # --- xai-only (omitted in black-box via exclude_none) ---
    lede: str | None = None
    confidence: str | None = None
    explanation: ExplanationOut | None = None
    red_flags: list[RedFlagOut] | None = None
    override: OverrideOut | None = None
    # xai_line NAMES delta drivers -> reasoning -> XAI only.
    dual_score_detail: str | None = None

    @classmethod
    def from_detail(cls, detail, mode: str | Mode) -> "PatientDetailOut":
        base = dict(
            patient_name=detail.patient.name,
            age=age_in_years(detail.patient.date_of_birth),
            sex=detail.patient.sex,
            severity_score=detail.severity.severity_score,
            system_esi=detail.severity.system_ESI,
            band_name=LABEL_MAP[detail.severity.system_ESI],
            # numbers-only dual score: both modes (None -> omitted)
            dual_score_line=detail.dual_score_line,
        )

        # Black-box: score + level (+ dual-score numbers) only. Reasoning fields
        # stay None and are dropped by exclude_none — never leave the server.
        if mode == Mode.BLACKBOX:
            return cls(**base)

        # XAI: attach the full reasoning, including the driver-naming dual line.
        return cls(
            **base,
            lede=detail.lede,
            confidence=detail.severity.confidence,
            explanation=ExplanationOut.from_explanation(detail.explanation),
            red_flags=[RedFlagOut.from_trigger(t) for t in detail.red_flags],
            override=(
                OverrideOut.from_override(detail.override)
                if detail.override is not None
                else None
            ),
            dual_score_detail=detail.xai_line,
        )