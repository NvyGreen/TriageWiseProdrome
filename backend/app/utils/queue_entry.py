from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

@dataclass
class QueueEntry:
    position: int
    patient_id: int
    name: str
    age: int
    esi_level: str | None
    priority_label: str | None
    # Numeric(5,1) on patient_severity -> Decimal, not int
    severity_score: Decimal | None
    status: str
    entered_at: datetime