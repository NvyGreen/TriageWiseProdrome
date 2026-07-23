import logging
from fastapi import APIRouter, Depends, status
from fastapi.exceptions import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from ..dependencies import get_queue, get_db
from ..schemas.intake_update import IntakeUpdate
from ..services.priority_queue import PriorityQueue
from ..services.triage_service import TriageService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/test")
def test_intakes():
    return {"message": "Intakes API is running"}

@router.patch("/{intake_id}", status_code=status.HTTP_200_OK)
def update_patient(intake_id: int, updates: IntakeUpdate, queue: PriorityQueue = Depends(get_queue), db: Session = Depends(get_db)):
    triageService = TriageService(db)
    result = triageService.updatePatient(intake_id, updates, queue)
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