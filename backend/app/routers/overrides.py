import logging
from fastapi import APIRouter, Depends, Header, status
from fastapi.exceptions import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from ..dependencies import get_queue, get_db
from ..services.triage_service import TriageService
from ..services.priority_queue import PriorityQueue
from ..services.idempotency import (
    DuplicateRequestException,
    IdempotencyKeyRequiredException,
    check_idempotency,
    hash_payload,
    store_idempotency,
)
from ..schemas.override_create import OverrideCreate


__all__ = ["router", "DuplicateRequestException", "IdempotencyKeyRequiredException"]
router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/test")
def test_overrides():
    return {"message": "Overrides API is running"}


@router.post("/", status_code=status.HTTP_201_CREATED)
def override_system(
    override: OverrideCreate,
    db: Session = Depends(get_db),
    queue: PriorityQueue = Depends(get_queue),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=64)
):
    triageService = TriageService(db)
    request_hash = hash_payload(override)
    existing = check_idempotency(idempotency_key, request_hash, db)
    if existing is not None:
        # Replay the original stored response verbatim. It's the unwrapped 201
        # handler dict, so returning it re-wraps identically via the default
        # response class (all stored responses are 201 successes).
        return existing.response_body
    
    result = triageService.applyOverride(override.severity_id, override.clinician_esi, override.reason_code, override.note, queue)
    response_body = {
        "message": "Override applied successfully",
        "intake_id": result.intake_id,
        "severity_score": result.severity_score,
        "queue_placement": result.queue_placement
    }

    try:
        store_idempotency(idempotency_key, request_hash, response_body, status.HTTP_201_CREATED, db)
        db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        logger.exception("Applying override failed")
        raise HTTPException(status_code=500) from e

    return response_body