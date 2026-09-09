import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..dependencies import get_db
from ..services.rules_info_service import RulesInfoService


router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/test")
def test_rules():
    return {"message": "Rules API is running"}


@router.get("/scoring-rules")
def get_scoring_rules(db: Session = Depends(get_db)):
    rules_info_service = RulesInfoService(db)
    return rules_info_service.scoring_rules()


@router.get("/esi-bands")
def get_esi_bands(db: Session = Depends(get_db)):
    rules_info_service = RulesInfoService(db)
    return rules_info_service.esi_bands()


@router.get("/red-flags")
def get_red_flags(db: Session = Depends(get_db)):
    rules_info_service = RulesInfoService(db)
    return rules_info_service.red_flag_rules()


@router.get("/complaint-esi")
def get_complaint_esi(db: Session = Depends(get_db)):
    rules_info_service = RulesInfoService(db)
    return rules_info_service.complaint_esi()