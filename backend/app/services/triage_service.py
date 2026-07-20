import logging
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from fastapi.exceptions import HTTPException
from ..models.patient import Patient
from ..models.intake_record import IntakeRecord
from ..schemas.intake_create import IntakeCreate
from ..utils.result import Result


VITAL_FIELDS = ("heart_rate", "blood_pressure_systolic", "blood_pressure_diastolic", "temperature", "oxygen_saturation", "respiration_rate", "pain_level", "blood_sugar")
logger = logging.getLogger(__name__)

class TriageService:
    @staticmethod
    def submitIntake(intake: IntakeCreate, db: Session) -> Result:
        try:
            new_patient = Patient(
                name=intake.name,
                date_of_birth=intake.date_of_birth,
                sex=intake.sex
            )
            db.add(new_patient)
            db.flush()
            patient_id = new_patient.patient_id
        except SQLAlchemyError as e:
            db.rollback()
            logger.exception("Patient creation failed")
            raise HTTPException(status_code=500) from e

        missing_fields = [field for field in VITAL_FIELDS if getattr(intake, field) is None]
        try:
            new_intake = IntakeRecord(**intake.model_dump(exclude={"name", "date_of_birth", "sex"}), patient_id=patient_id, missing_fields=missing_fields)
            db.add(new_intake)
            db.flush()
            # TODO: score severity and place record in queue
            return Result(new_intake.intake_id)
        except SQLAlchemyError as e:
            db.rollback()
            logger.exception("Intake creation failed")
            raise HTTPException(status_code=500) from e