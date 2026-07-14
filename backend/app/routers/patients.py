from fastapi import APIRouter
from ..schemas.intake_create import IntakeCreate


class DuplicateRequestException(Exception):
    pass

class UnscoreableException(Exception):
    pass

router = APIRouter()

@router.get("/test")
def test_patients():
    return {"message": "Patients API is running"}

@router.post("/")
def record_intake(record: IntakeCreate):
    # if duplicate_record(record):
    #     raise DuplicateRequestException()

    # if unscoreable(record):
    #     raise UnscoreableException()

    return {"message": "Intake recorded successfully", "record": record}