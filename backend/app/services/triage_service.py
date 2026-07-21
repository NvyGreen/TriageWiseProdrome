import logging
from enum import StrEnum
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from fastapi.exceptions import HTTPException, RequestValidationError

from ..models.patient import Patient
from ..models.intake_record import IntakeRecord
from ..models.patient_severity import PatientSeverity
from ..models.esi_band import ESIBand
from ..models.event_log import EventLog
from ..models.case_update import CaseUpdate

from ..schemas.intake_create import IntakeCreate
from ..schemas.intake_update import IntakeUpdate, Status, VITAL_FIELDS

from ..services.priority_queue import PriorityQueue

from ..utils.result import Result
from ..utils.queue_entry import QueueEntry
from ..utils.dates import age_from_dob


logger = logging.getLogger(__name__)


class EventType(StrEnum):
    INTAKE_CREATED = "intake_created"
    SCORE_CALCULATED = "score_calculated"
    RED_FLAG_FIRED = "red_flag_fired"
    QUEUED = "queued"
    REPRIORITIZED = "reprioritized"
    OVERRIDE_APPLIED = "override_applied"
    CASE_UPDATED = "case_updated"
    STATUS_CHANGED = "status_changed"
    EXPLANATION_VIEWED = "explanation_viewed"


class IntakeNotFoundError(Exception):
    def __init__(self, intake_id: int):
        self.intake_id = intake_id


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

            new_event = EventLog(event_type=EventType.INTAKE_CREATED, patient_id=patient_id, intake_id=new_intake.intake_id)
            db.add(new_event)
            db.flush()
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
    

    @staticmethod
    def updatePatient(intake_id: int, updates: IntakeUpdate, queue: PriorityQueue, db: Session) -> Result:
        try:
            intake = db.get(IntakeRecord, intake_id)
        except SQLAlchemyError as e:
            logger.exception("Intake retrieval failed")
            raise HTTPException(status_code=500) from e
        
        if intake is None:
            logger.error("No intake with this id")
            raise IntakeNotFoundError(intake_id=intake_id)
        patient_id = intake.patient_id
        
        if updates.status is not None:            
            # TODO: Persist status change in triage_queue table            
            if updates.status == Status.DISPOSITIONED:
                try:
                    queue.remove(intake_id)
                except ValueError:
                    # TODO: Once triage_queue is implemented, may make this error out instead of a no-op
                    # logger.exception("No intake with this id")
                    # raise HTTPException(status_code=404)
                    pass
            
            try:
                new_event = EventLog(event_type=EventType.STATUS_CHANGED, patient_id=patient_id, intake_id=intake_id)
                db.add(new_event)
                db.flush()
                return Result(intake_id)
            except SQLAlchemyError as e:
                db.rollback()
                logger.exception("Event logging failed")
                raise HTTPException(status_code=500) from e
        

        try:
            dia = updates.blood_pressure_diastolic if updates.blood_pressure_diastolic is not None else intake.blood_pressure_diastolic
            syst = updates.blood_pressure_systolic if updates.blood_pressure_systolic is not None else intake.blood_pressure_systolic
            if dia is not None and syst is not None and dia >= syst:
                logger.error("Diastolic must be lower than systolic")
                raise RequestValidationError(
                    errors=[
                        {
                            "loc": ("body", "blood_pressure_diastolic"),
                            "msg": "Value error, Diastolic must be lower than systolic",
                            "type": "value_error",
                        }
                    ]
                )
            
            updated_vitals = {}
            for field in VITAL_FIELDS:
                new_value = getattr(updates, field)
                if new_value is not None and _norm(new_value) != _norm(getattr(intake, field)):
                    setattr(intake, field, new_value)
                    updated_vitals[field] = new_value
            
            # TODO: Once scoring is implemented, re-score based on these values

            if updated_vitals:
                case_update = CaseUpdate(patient_id=patient_id, intake_id=intake_id, updated_vitals=updated_vitals)
                new_event = EventLog(event_type=EventType.CASE_UPDATED, patient_id=patient_id, intake_id=intake_id)
                db.add(case_update)
                db.add(new_event)
            
            db.flush()
            return Result(intake_id)
        except SQLAlchemyError as e:
            db.rollback()
            logger.exception("Vitals update failed")
            raise HTTPException(status_code=500) from e
    


def _norm(value):
    """DB Numeric -> Decimal, so float 98.6 compares equal to Decimal('98.6')."""
    return Decimal(str(value)) if isinstance(value, (float, Decimal)) else value