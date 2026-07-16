from datetime import date
import logging
from fastapi import APIRouter, Depends, status
from fastapi.exceptions import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from ..schemas.intake_create import IntakeCreate
from ..database import get_db
from ..models.patient import Patient
from ..models.intake_record import IntakeRecord


VITAL_FIELDS = ("heart_rate", "blood_pressure_systolic", "blood_pressure_diastolic", "temperature", "oxygen_saturation", "respiration_rate", "pain_level", "blood_sugar")
logger = logging.getLogger(__name__)

class DuplicateRequestException(Exception):
    pass

class UnscoreableException(Exception):
    pass

router = APIRouter()

@router.get("/test")
def test_patients():
    return {"message": "Patients API is running"}

@router.post("/", status_code=status.HTTP_201_CREATED)
def record_intake(record: IntakeCreate, db: Session = Depends(get_db)):
    # if duplicate_record(record):
    #     raise DuplicateRequestException()

    # if unscoreable(record):
    #     raise UnscoreableException()
    
    try:
        new_patient = Patient(
            name=record.name,
            date_of_birth=record.date_of_birth,
            sex=record.sex
        )
        db.add(new_patient)
        db.flush()
        patient_id = new_patient.patient_id
    except SQLAlchemyError as e:
        db.rollback()
        logger.exception("Patient creation failed")
        raise HTTPException(status_code=500) from e
    
    missing_fields = [field for field in VITAL_FIELDS if getattr(record, field) is None]
    try:
        new_intake = IntakeRecord(**record.model_dump(exclude={"name", "date_of_birth", "sex"}), patient_id=patient_id, missing_fields=missing_fields)
        db.add(new_intake)
        db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        logger.exception("Intake creation failed")
        raise HTTPException(status_code=500) from e
        
    return {"message": "Intake recorded successfully", "patient_id": patient_id}