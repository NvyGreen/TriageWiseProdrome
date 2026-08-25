import logging
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, status, Query
from fastapi.exceptions import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from ..dependencies import get_db
from ..models.event_log import EventLog
from ..models.intake_record import IntakeRecord
from ..schemas.intake_update import IntakeUpdate
from ..schemas.patient_detail_out import PatientDetailOut
from ..services.triage_service import (
    TriageService, EventType, ScoringStatus, IntakeNotFoundError,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/test")
def test_intakes():
    return {"message": "Intakes API is running"}

@router.patch("/{intake_id}", status_code=status.HTTP_200_OK)
def update_patient(intake_id: int, updates: IntakeUpdate, db: Session = Depends(get_db)):
    triageService = TriageService(db)
    result = triageService.updatePatient(intake_id, updates)
    response_body = {
        "message": "Patient updated successfully",
        "intake_id": result.intake_id,
        "severity_score": result.severity_score,
        "queue_placement": result.queue_placement
    }

    try:
        db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        logger.exception("Patient update failed")
        raise HTTPException(status_code=500) from e
    
    return response_body

@router.get("/{intake_id}", status_code=status.HTTP_200_OK)
def patient_details(intake_id: int, mode: Annotated[Literal['xai', 'blackbox'], Query()], db: Session = Depends(get_db)):
    triageService = TriageService(db)

    # The intake exists before scoring produces a result. Until it's SCORED there's
    # no severity/explanation to render, so return {intake_id, status} and let the
    # client poll (pending) or surface the terminal state (unscoreable/failed).
    intake = db.get(IntakeRecord, intake_id)
    if intake is None:
        raise IntakeNotFoundError(intake_id)
    if intake.scoring_status != ScoringStatus.SCORED:
        return {"intake_id": intake_id, "status": intake.scoring_status}

    details = triageService.getPatientDetail(intake_id)
    try:
        if mode == 'xai':
            explanation_viewed = EventLog(
                event_type=EventType.EXPLANATION_VIEWED,
                patient_id=details.patient.patient_id,
                intake_id=intake_id
            )
            db.add(explanation_viewed)
            db.flush()
        db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        logger.exception("Getting patient details failed")
        raise HTTPException(status_code=500) from e
    
    return PatientDetailOut.from_detail(details, mode).model_dump(exclude_none=True)