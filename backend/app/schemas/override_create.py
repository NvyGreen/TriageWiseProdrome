from pydantic import BaseModel, Field
from ..utils.enums import ReasonCode, ESILevels


class OverrideCreate(BaseModel):
    severity_id: int
    clinician_esi: ESILevels
    reason_code: ReasonCode
    note: str | None = None