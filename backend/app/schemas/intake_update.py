from enum import StrEnum
from pydantic import BaseModel, ValidationInfo, Field, field_validator, model_validator


class Status(StrEnum):
    WAITING = "WAITING"
    IN_ROOM = "IN_ROOM"
    DISPOSITIONED = "DISPOSITIONED"

VITAL_FIELDS = ("heart_rate", "blood_pressure_systolic", "blood_pressure_diastolic", "temperature", "oxygen_saturation", "respiration_rate", "pain_level", "blood_sugar")


class IntakeUpdate(BaseModel):
    heart_rate: int | None = Field(default=None, gt=0, le=350)
    blood_pressure_systolic: int | None = Field(default=None, gt=0, le=300)
    blood_pressure_diastolic: int | None = Field(default=None, gt=0, le=250)
    temperature: float | None = Field(default=None, ge=68.0, le=115.0)
    oxygen_saturation: int | None = Field(default=None, ge=0, le=100)
    respiration_rate: int | None = Field(default=None, gt=0, le=99)
    pain_level: int | None = Field(default=None, ge=0, le=10)
    blood_sugar: float | None = Field(default=None, gt=0.0, le=1600.0)
    status: Status | None = None


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

    @model_validator(mode="after")
    def at_least_one_field(self):
        if self.status is None and all(getattr(self, f) is None for f in VITAL_FIELDS):
            raise ValueError("Provide a status or at least one vital")
        return self
    
    @model_validator(mode="after")
    def status_or_vitals_not_both(self):
        if self.status is not None and any(getattr(self, f) is not None for f in VITAL_FIELDS):
            raise ValueError("Send either status or vitals, not both")
        return self