"""Seed the 5 DEMO patients into the CURRENT DB (whatever DB_* points at) and score
them so they land in the queue. Run from backend/ with your Neon DB_* env vars set:
    python seed_demo_patients.py
Data mirrors the originals exactly (source='demo').
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import get_settings
from app.dependencies import SessionLocal
from app.schemas.intake_create import IntakeCreate
from app.services.triage_service import TriageService
from app import scorer

s = get_settings()
print(f"Seeding into: {s.DB_NAME} @ {s.DB_HOST}")   # confirm this is Neon before continuing

PATIENTS = [
    {"name": "DEMO Robert Chen", "date_of_birth": "1958-03-14", "sex": "M", "chief_complaint": "stroke",
     "heart_rate": 112, "blood_pressure_systolic": 96, "blood_pressure_diastolic": 62, "temperature": 98.9,
     "oxygen_saturation": 93, "respiration_rate": 26, "pain_level": 7, "blood_sugar": 141.0,
     "symptoms": ["fast_positive"], "pregnancy_status": "none",
     "pre_existing_conditions": ["hypertension", "prior_stroke", "anticoagulant"],
     "arrival_by_ambulance": True, "recent_ed_visit_72h": False, "injury_related": False,
     "source": "demo", "notes": "Demo seed: full data, high acuity, FAST-positive."},

    {"name": "DEMO Maria Alvarez", "date_of_birth": "1972-07-09", "sex": "F", "chief_complaint": "abdominal",
     "heart_rate": 105, "blood_pressure_systolic": 108, "blood_pressure_diastolic": None, "temperature": 100.1,
     "oxygen_saturation": None, "respiration_rate": None, "pain_level": None, "blood_sugar": None,
     "symptoms": ["abdominal_pain"], "pregnancy_status": "none", "pre_existing_conditions": ["diabetes"],
     "arrival_by_ambulance": False, "recent_ed_visit_72h": False, "injury_related": False,
     "source": "demo", "notes": "Demo seed: sparse vitals, fallbacks + low confidence."},

    {"name": "DEMO Aisha Bello", "date_of_birth": "1995-11-02", "sex": "F", "chief_complaint": "minor_general",
     "heart_rate": 88, "blood_pressure_systolic": 118, "blood_pressure_diastolic": 74, "temperature": 98.6,
     "oxygen_saturation": 98, "respiration_rate": 16, "pain_level": 3, "blood_sugar": None,
     "symptoms": ["heavy_bleeding"], "pregnancy_status": "postpartum", "pre_existing_conditions": [],
     "arrival_by_ambulance": False, "recent_ed_visit_72h": False, "injury_related": False,
     "source": "demo", "notes": "Demo seed: red flag drives priority, not score."},

    {"name": "DEMO Tom Becker", "date_of_birth": "1997-05-20", "sex": "M", "chief_complaint": "minor_injury",
     "heart_rate": 76, "blood_pressure_systolic": 122, "blood_pressure_diastolic": 78, "temperature": 98.4,
     "oxygen_saturation": 99, "respiration_rate": 14, "pain_level": 3, "blood_sugar": None,
     "symptoms": [], "pregnancy_status": "none", "pre_existing_conditions": [],
     "arrival_by_ambulance": False, "recent_ed_visit_72h": False, "injury_related": True,
     "source": "demo", "notes": "Demo seed: routine low-acuity case."},

    {"name": "DEMO Priya Raman", "date_of_birth": "1982-01-15", "sex": "F", "chief_complaint": "minor_general",
     "heart_rate": 84, "blood_pressure_systolic": 116, "blood_pressure_diastolic": 76, "temperature": 98.7,
     "oxygen_saturation": 93, "respiration_rate": 15, "pain_level": 2, "blood_sugar": None,
     "symptoms": [], "pregnancy_status": "none", "pre_existing_conditions": [],
     "arrival_by_ambulance": False, "recent_ed_visit_72h": False, "injury_related": False,
     "source": "demo", "notes": "Demo seed: ESI-3 by points, refined down by resource use."},
]

db = SessionLocal()
try:
    for data in PATIENTS:
        result = TriageService(db).submit_intake(IntakeCreate(**data))
        scorer.score_claimed(db, result["intake_id"])   # scores + queues + commits
        print(f"  seeded + scored: {data['name']} (intake {result['intake_id']})")
finally:
    db.close()
print("Done.")