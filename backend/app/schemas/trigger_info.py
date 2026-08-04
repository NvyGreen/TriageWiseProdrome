from pydantic import BaseModel


class TriggerInfo(BaseModel):
    flag_id: int
    flag_type: str
    flag_tier: int
    message: str
    rationale: str