from datetime import date
import logging
from fastapi import APIRouter, Depends, Header, status
from fastapi.exceptions import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from ..schemas.intake_create import IntakeCreate
from ..database import get_db
from ..models.patient import Patient
from ..models.intake_record import IntakeRecord
from ..services.idempotency import (
    DuplicateRequestException,
    IdempotencyKeyRequiredException,
    check_idempotency,
    hash_payload,
    store_idempotency,
)

# DuplicateRequestException / IdempotencyKeyRequiredException are defined in the
# idempotency service and re-exported here so main.py's `patients.X` handler
# registrations keep resolving.
__all__ = ["router", "DuplicateRequestException", "IdempotencyKeyRequiredException", "UnscoreableException"]

VITAL_FIELDS = ("heart_rate", "blood_pressure_systolic", "blood_pressure_diastolic", "temperature", "oxygen_saturation", "respiration_rate", "pain_level", "blood_sugar")
logger = logging.getLogger(__name__)

class UnscoreableException(Exception):
    pass

router = APIRouter()

@router.get("/test")
def test_patients():
    return {"message": "Patients API is running"}

@router.post("/", status_code=status.HTTP_201_CREATED)
def record_intake(
    record: IntakeCreate,
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    # Idempotency boundary check — runs before any domain logic. Raises on a
    # missing header (400) or a same-key/different-body collision (409); returns
    # the stored row when this is a safe retry to replay.
    request_hash = hash_payload(record)
    existing = check_idempotency(idempotency_key, request_hash, db)
    if existing is not None:
        # Replay the original stored response verbatim. It's the unwrapped 201
        # handler dict, so returning it re-wraps identically via the default
        # response class (all stored responses are 201 successes).
        return existing.response_body

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
    response_body = {"message": "Intake recorded successfully", "patient_id": patient_id}
    try:
        new_intake = IntakeRecord(**record.model_dump(exclude={"name", "date_of_birth", "sex"}), patient_id=patient_id, missing_fields=missing_fields)
        db.add(new_intake)
        # Store the key -> response mapping in the SAME transaction as the intake,
        # so a replay can never point at data that failed to commit.
        store_idempotency(idempotency_key, request_hash, response_body, status.HTTP_201_CREATED, db)
        db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        logger.exception("Intake creation failed")
        raise HTTPException(status_code=500) from e

    return response_body