import logging
from fastapi import APIRouter, Depends, Header, status
from fastapi.exceptions import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from ..schemas.intake_create import IntakeCreate
from ..dependencies import get_db, get_queue
from ..services.idempotency import (
    DuplicateRequestException,
    IdempotencyKeyRequiredException,
    check_idempotency,
    hash_payload,
    store_idempotency,
)
from ..services.triage_service import TriageService
from ..services.priority_queue import PriorityQueue

# DuplicateRequestException / IdempotencyKeyRequiredException are defined in the
# idempotency service and re-exported here so main.py's `patients.X` handler
# registrations keep resolving.
__all__ = ["router", "DuplicateRequestException", "IdempotencyKeyRequiredException"]
logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/test")
def test_patients():
    return {"message": "Patients API is running"}

@router.post("/", status_code=status.HTTP_201_CREATED)
def record_intake(
    record: IntakeCreate,
    db: Session = Depends(get_db),
    # max_length matches idempotency_key's String(64) column, so an overlong key
    # is a 400 from the validation handler instead of a DataError at commit.
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=64),
):
    triageService = TriageService(db)
    request_hash = hash_payload(record)
    existing = check_idempotency(idempotency_key, request_hash, db)
    if existing is not None:
        # Replay the original stored response verbatim. It's the unwrapped 201
        # handler dict, so returning it re-wraps identically via the default
        # response class (all stored responses are 201 successes).
        return existing.response_body
    
    result = triageService.submitIntake(record)
    response_body = {
        "message": "Intake recorded successfully",
        "intake_id": result.intake_id,
        "severity_score": result.severity_score,
        "queue_placement": result.queue_placement
    }
    try:
        store_idempotency(idempotency_key, request_hash, response_body, status.HTTP_201_CREATED, db)
        db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        # try:
        #     queue.remove(result.intake_id)
        # except ValueError:
        #     pass
        logger.exception("Intake commit failed")
        raise HTTPException(status_code=500) from e
    # except HTTPException as e:
    #     try:
    #         queue.remove(result.intake_id)
    #     except ValueError:
    #         pass
    #     raise HTTPException(status_code=500) from e

    return response_body