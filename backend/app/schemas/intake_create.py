from datetime import date
from enum import StrEnum
from pydantic import BaseModel, Field


class ChiefComplaint(StrEnum):
    STROKE_SYMPTOMS = "stroke_symptoms"
    CHEST_PAIN = "chest_pain"
    SHORTNESS_OF_BREATH = "shortness_of_breath"
    SEVERE_HEADACHE = "severe_headache"
    SYNCOPE = "syncope"
    ABDOMINAL_PAIN = "abdominal_pain"
    MINOR_INJURY = "minor_injury"
    MINOR_COMPLAINT = "minor_complaint"
    OTHER_GENERAL = "other_general"


class PreExistingConditions(StrEnum):
    DIABETES = "diabetes"
    HYPERTENSION = "hypertension"
    CHF = "chf"
    COPD = "copd"
    PRIOR_MI = "prior_mi"
    PRIOR_STROKE = "prior_stroke"
    CANCER = "cancer"
    ANTICOAGULANT = "anticoagulant"
    IMMUNOCOMPROMISED = "immunocompromised"
    SICKLE_CELL = "sickle_cell"


class Sex(StrEnum):
    M = "M"
    F = "F"
    OTHER = "other"
    UNKNOWN = "unknown"


class PregnancyStatus(StrEnum):
    NONE = "none"
    PREGNANT = "pregnant"
    POSTPARTUM = "postpartum"


class IntakeCreate(BaseModel):
    name: str
    date_of_birth: date
    sex: Sex
    chief_complaint: ChiefComplaint
    symptoms: list[str] = []
    heart_rate: int | None = None
    blood_pressure_systolic: int | None = None
    blood_pressure_diastolic: int | None = None
    temperature: float | None = None
    oxygen_saturation: int | None = Field(default=None, ge=0, le=100)
    respiration_rate: int | None = None
    pain_level: int | None = Field(default=None, ge=0, le=10)
    blood_sugar: float | None = None
    pregnancy_status: PregnancyStatus = PregnancyStatus.NONE
    pre_existing_conditions: list[PreExistingConditions] = []
    arrival_by_ambulance: bool | None = None
    recent_ed_visit_72h: bool | None = None
    injury_related: bool | None = None
    source: str = "form"