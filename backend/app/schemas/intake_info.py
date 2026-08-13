from datetime import datetime
from pydantic import BaseModel, Field
from ..utils.enums import ChiefComplaint, PreExistingConditions, PregnancyStatus


class IntakeInfo(BaseModel):
    intake_id: int
    symptoms: list[str]
    chief_complaint: ChiefComplaint
    heart_rate: int | None
    blood_pressure_systolic: int | None
    blood_pressure_diastolic: int | None
    temperature: float | None
    oxygen_saturation: int | None
    respiration_rate: int | None
    pain_level: int | None
    blood_sugar: float | None
    missing_fields: list[str]
    pregnancy_status: PregnancyStatus
    pre_existing_conditions: list[PreExistingConditions]
    arrival_by_ambulance: bool | None = None
    recent_ed_visit_72h: bool | None = None
    injury_related: bool | None = None
    notes: str | None = None
    created_at: datetime