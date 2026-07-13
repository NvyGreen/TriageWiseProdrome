from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from .config import get_settings, Settings
from .database import get_db
from .models.esi_band import ESIBand
from .models.condition_reference import ConditionReference

app = FastAPI()

@app.get("/")
def root(settings: Settings = Depends(get_settings)):
    return {
        "message": f"{settings.app_name} API is running"
    }

@app.get("/esi-bands")
def get_esi_bands(db: Session = Depends(get_db)):
    # Fetch all 5 bands sorted by their primary key
    bands = db.query(ESIBand).order_by(ESIBand.band_id).all()
    return bands

@app.get("/condition-reference")
def get_condition_reference(db: Session = Depends(get_db)):
    conditions = db.query(ConditionReference).all()
    return conditions