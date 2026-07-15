from datetime import date
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from ..schemas.intake_create import IntakeCreate
from ..database import get_db
from ..models.patient import Patient
from ..models.intake_record import IntakeRecord


class DuplicateRequestException(Exception):
    pass

class UnscoreableException(Exception):
    pass

router = APIRouter()

@router.get("/test")
def test_patients():
    return {"message": "Patients API is running"}

@router.post("/", status_code=status.HTTP_201_CREATED)
def record_intake(record: IntakeCreate, db: Session = Depends(get_db)):
    # if duplicate_record(record):
    #     raise DuplicateRequestException()

    # if unscoreable(record):
    #     raise UnscoreableException()

    patient = db.query(Patient.patient_id).where(Patient.name == record.name).all()
    patient_id = None
    if len(patient) == 0:
        today = date.today()
        age = today.year - record.date_of_birth.year - ((today.month, today.day) < (record.date_of_birth.month, record.date_of_birth.day))
        new_patient = Patient(
            name=record.name,
            age=age,
            date_of_birth=record.date_of_birth,
            sex=record.sex
        )
        db.add(new_patient)
        db.flush()
        patient_id = new_patient.patient_id
    else:
        patient_id = patient[0][0]
        old_patient = db.get(Patient, patient_id)

        if old_patient.date_of_birth != record.date_of_birth:
            today = date.today()
            age = today.year - record.date_of_birth.year - ((today.month, today.day) < (record.date_of_birth.month, record.date_of_birth.day))
            old_patient.date_of_birth = record.date_of_birth
            old_patient.age = age
        
        old_patient.sex = record.sex
    
    missing_fields = []
    if record.heart_rate is None:
        missing_fields.append("heart_rate")
    if record.blood_pressure_systolic is None:
        missing_fields.append("blood_pressure_systolic")
    if record.blood_pressure_diastolic is None:
        missing_fields.append("blood_pressure_diastolic")
    if record.temperature is None:
        missing_fields.append("temperature")
    if record.oxygen_saturation is None:
        missing_fields.append("oxygen_saturation")
    if record.respiration_rate is None:
        missing_fields.append("respiration_rate")
    if record.pain_level is None:
        missing_fields.append("pain_level")
    if record.blood_sugar is None:
        missing_fields.append("blood_sugar")
    
    new_intake = IntakeRecord(
        patient_id=patient_id,
        symptoms=record.symptoms,
        chief_complaint=record.chief_complaint,
        heart_rate=record.heart_rate,
        blood_pressure_systolic=record.blood_pressure_systolic,
        blood_pressure_diastolic=record.blood_pressure_diastolic,
        temperature=record.temperature,
        oxygen_saturation=record.oxygen_saturation,
        pain_level=record.pain_level,
        blood_sugar=record.blood_sugar,
        missing_fields=missing_fields,
        source=record.source,
        pregnancy_status=record.pregnancy_status,
        pre_existing_conditions=record.pre_existing_conditions,
        arrival_by_ambulance=record.arrival_by_ambulance,
        recent_ed_visit_72h=record.recent_ed_visit_72h,
        injury_related=record.injury_related,
        respiration_rate=record.respiration_rate
    )
    db.add(new_intake)
    db.commit()
        
    return {"message": "Intake recorded successfully", "patient_id": patient_id}