from dataclasses import dataclass

from ..utils.explanation import Explanation

from ..schemas.patient_info import PatientInfo
from ..schemas.intake_info import IntakeInfo
from ..schemas.severity_info import SeverityInfo
from ..schemas.trigger_info import TriggerInfo


@dataclass
class PatientDetail:
    patient: PatientInfo
    intake: IntakeInfo
    missing_fields: list[str]
    severity: SeverityInfo
    explanation: Explanation
    red_flags: list[TriggerInfo]
    lede: str
    # TODO: Add Override once implemented
    override: None = None