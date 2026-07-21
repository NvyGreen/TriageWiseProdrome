from enum import StrEnum
from pydantic import BaseModel, Field


class Status(StrEnum):
    WAITING = "WAITING"
    IN_ROOM = "IN_ROOM"
    DISPOSITIONED = "DISPOSITIONED"


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