import logging
from fastapi import APIRouter
from ..services.simulation import PRESETS, run_simulation, SimRequest


router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/test")
def test_demo():
    return {"message": "Demo API is running"}


@router.post("/simulation")
def simulate(req: SimRequest):
    return run_simulation(req)


@router.get("/presets")
def get_presets():
    return PRESETS