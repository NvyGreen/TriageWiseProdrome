from dataclasses import dataclass

from ..utils.explanation import Explanation

from ..schemas.patient_info import PatientInfo
from ..schemas.intake_info import IntakeInfo
from ..schemas.severity_info import SeverityInfo
from ..schemas.trigger_info import TriggerInfo
from ..schemas.override_info import OverrideInfo


@dataclass
class PatientDetail:
    patient: PatientInfo
    intake: IntakeInfo
    missing_fields: list[str]
    severity: SeverityInfo
    explanation: Explanation
    red_flags: list[TriggerInfo]
    lede: str
    dual_score_line: str | None = None
    xai_line: str | None = None
    base_rate_line: str | None = None
    override: OverrideInfo | None = None