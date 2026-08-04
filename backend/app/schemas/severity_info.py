from datetime import datetime
from pydantic import BaseModel


class SeverityInfo(BaseModel):
    severity_id: int
    severity_score: float
    system_ESI: str
    clinician_ESI: str | None
    score_reason: str
    fallbacks_applied: dict
    confidence: str
    flag_tier: int
    created_at: datetime