from dataclasses import dataclass
from decimal import Decimal

@dataclass
class Rule:
    rule_id: int
    rule_type: str
    factor: str
    min_bound: Decimal | None
    max_bound: Decimal | None
    units: str
    threshold_display: str
    weight: int
    complaint_group: str | None = None
    resource_level: str | None = None
    esi_anchor: str | None = None
    fallback_if_missing: str | None = None