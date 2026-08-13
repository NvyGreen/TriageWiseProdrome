from pydantic import BaseModel

class OverrideInfo(BaseModel):
    override_id: int
    system_esi: str
    clinician_esi: str
    reason_code: str
    note: str | None