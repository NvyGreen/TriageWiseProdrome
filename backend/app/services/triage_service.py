import logging
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from fastapi.exceptions import HTTPException
from ..models.patient import Patient
from ..models.intake_record import IntakeRecord
from ..models.patient_severity import PatientSeverity
from ..models.esi_band import ESIBand
from ..schemas.intake_create import IntakeCreate
from ..services.priority_queue import PriorityQueue
from ..utils.result import Result
from ..utils.queue_entry import QueueEntry
from ..utils.dates import age_from_dob


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

    @staticmethod
    def getQueue(queue: PriorityQueue, db: Session) -> list[QueueEntry]:
        intake_ids = queue.orderedIntakeIds()
        if not intake_ids:
            return []

        # A clinician ESI overrides the system one; join the band off whichever wins.
        effective_esi = func.coalesce(PatientSeverity.clinician_ESI, PatientSeverity.system_ESI)

        # One query for the whole queue instead of four per patient. The severity
        # and band joins are OUTER because scoring may not have run yet.
        stmt = (
            select(IntakeRecord, Patient, PatientSeverity, ESIBand.priority,
                   effective_esi.label("esi_level"))
            .join(Patient, Patient.patient_id == IntakeRecord.patient_id)
            .outerjoin(PatientSeverity, PatientSeverity.intake_id == IntakeRecord.intake_id)
            .outerjoin(ESIBand, ESIBand.esi_level == effective_esi)
            .where(IntakeRecord.intake_id.in_(intake_ids))
        )
        rows_by_intake_id = {row.IntakeRecord.intake_id: row for row in db.execute(stmt).all()}

        entries = []
        # IN doesn't preserve order, so queue order comes from walking intake_ids.
        for i, intake_id in enumerate(intake_ids):
            row = rows_by_intake_id.get(intake_id)
            if row is None:
                logger.error("intake_id wasn't in database when it should be")
                raise HTTPException(status_code=500)

            record, patient, severity = row.IntakeRecord, row.Patient, row.PatientSeverity

            # TODO: Once scoring is implemented, these should never be None
            esi_level = row.esi_level
            priority_label = row.priority
            severity_score = severity.severity_score if severity is not None else None
            if severity is not None and priority_label is None:
                logger.error("esi_level wasn't in database when it should be")
                raise HTTPException(status_code=500)

            entry = QueueEntry(i + 1, patient.patient_id, patient.name, age_from_dob(patient.date_of_birth), esi_level, priority_label, severity_score, "WAITING", record.created_at)
            entries.append(entry)

        return entries