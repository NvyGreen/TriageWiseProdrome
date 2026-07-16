from datetime import date
from enum import StrEnum
from pydantic import BaseModel, Field, ValidationInfo, field_validator
from ..utils.dates import age_from_dob


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
    name: str = Field(max_length=100)
    date_of_birth: date
    sex: Sex
    chief_complaint: ChiefComplaint
    symptoms: list[str] = []
    heart_rate: int | None = Field(default=None, gt=0, le=350)
    blood_pressure_systolic: int | None = Field(default=None, gt=0, le=300)
    blood_pressure_diastolic: int | None = Field(default=None, gt=0, le=250)
    temperature: float | None = Field(default=None, ge=68.0, le=115.0)
    oxygen_saturation: int | None = Field(default=None, ge=0, le=100)
    respiration_rate: int | None = Field(default=None, gt=0, le=99)
    pain_level: int | None = Field(default=None, ge=0, le=10)
    blood_sugar: float | None = Field(default=None, gt=0.0, le=1600.0)
    pregnancy_status: PregnancyStatus = PregnancyStatus.NONE
    pre_existing_conditions: list[PreExistingConditions] = []
    arrival_by_ambulance: bool | None = None
    recent_ed_visit_72h: bool | None = None
    injury_related: bool | None = None
    source: str = Field(default="form", max_length=10)

    @field_validator("date_of_birth")
    @classmethod
    def check_valid_dob(cls, dob: date) -> date:
        if age_from_dob(dob) < 0:
            raise ValueError("Date of birth is in the future")
        return dob
    
    @field_validator("blood_pressure_diastolic")
    @classmethod
    def check_dia_lower_than_sys(cls, dia: int | None, info: ValidationInfo) -> int | None:
        # A field validator (not a model one) so the error attaches to
        # blood_pressure_diastolic and still fires when other fields are invalid.
        # .get() because systolic is absent from info.data if it failed its own checks.
        sys = info.data.get("blood_pressure_systolic")
        if dia is not None and sys is not None and dia >= sys:
            raise ValueError("Diastolic must be lower than systolic")
        return dia