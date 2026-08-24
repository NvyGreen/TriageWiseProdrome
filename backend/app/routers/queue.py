from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from ..dependencies import get_queue, get_db
from ..services.priority_queue import PriorityQueue
from ..services.triage_service import TriageService

router = APIRouter()

@router.get("/test")
def test_queue():
    return {"message": "Queue API is running"}


@router.get("/", status_code=status.HTTP_200_OK)
def queue_triage(db: Session = Depends(get_db)):
    triageService = TriageService(db)
    entries = triageService.getQueue()
    return {"entries": entries}