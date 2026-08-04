from datetime import date
from pydantic import BaseModel
from ..utils.intake_enums import Sex


class PatientInfo(BaseModel):
    patient_id: int
    name: str
    date_of_birth: date
    sex: Sex