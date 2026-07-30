from dataclasses import dataclass, field

from ..utils.driver import Driver


@dataclass
class Explanation:
    data_completeness: str
    named_drivers: list[Driver] = field(default_factory=list)
    gap_acknowledgement: dict[str, list[str]] = field(default_factory=dict)
    fallback_instruction: str = "This is a triage aid, not a diagnosis. Clinician judgement required."