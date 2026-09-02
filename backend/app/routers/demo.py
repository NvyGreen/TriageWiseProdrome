import logging
from fastapi import APIRouter
from ..services.simulation import PRESETS, run_simulation, SimRequest
from ..services.epic_fhir_pull import fetch_patient_fhir
from ..services.epic_fhir_adapter import build_intake


router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/test")
def test_demo():
    return {"message": "Demo API is running"}


@router.post("/simulation")
def simulate(req: SimRequest):
    return run_simulation(req)


@router.post("/fhir/{fhir_id}")
def fetch_fhir(fhir_id: str):
    bundles = fetch_patient_fhir(fhir_id)
    return build_intake(**bundles)


@router.get("/presets")
def get_presets():
    return PRESETS