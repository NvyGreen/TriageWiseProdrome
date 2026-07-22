from dataclasses import dataclass
from .driver import Driver

@dataclass
class SeverityResult:
    severity_score: int
    esi_level: str
    initial_esi: str
    resource_level: str
    refined: bool
    named_drivers: list[Driver]
    missing_fields: list[str]
    data_completeness: str
    fallbacks_applied: dict[str, str]
    confidence: str
    flag_tier: int = 3