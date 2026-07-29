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
from ..services.scoring_engine import ScoringEngine, CannotScoreError
from ..services.red_flag_layer import RedFlagLayer

from ..utils.result import Result
from ..utils.queue_entry import QueueEntry
from ..utils.severity_result import SeverityResult
from ..utils.dates import age_in_years


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


class UnscoreableException(Exception):
    pass


class TriageService:
    def __init__(self, db: Session):
        self.db = db
        self.scoringEngine = ScoringEngine(db)
        self.redFlagLayer = RedFlagLayer(db)

    def submitIntake(self, intake: IntakeCreate, queue: PriorityQueue) -> Result:
        try:
            new_patient = Patient(
                name=intake.name,
                date_of_birth=intake.date_of_birth,
                sex=intake.sex
            )
            self.db.add(new_patient)
            self.db.flush()
            patient_id = new_patient.patient_id
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.exception("Patient creation failed")
            raise HTTPException(status_code=500) from e

        missing_fields = [field for field in VITAL_FIELDS if getattr(intake, field) is None]
        try:
            new_intake = IntakeRecord(**intake.model_dump(exclude={"name", "date_of_birth", "sex"}), patient_id=patient_id, missing_fields=missing_fields)
            self.db.add(new_intake)
            self.db.flush()

            intake_created = EventLog(
                event_type=EventType.INTAKE_CREATED,
                patient_id=patient_id,
                intake_id=new_intake.intake_id,
                details={"chief_complaint": new_intake.chief_complaint}
            )
            self.db.add(intake_created)

            # Scores intake and places record in queue
            severityResult: SeverityResult = self.scoringEngine.score(new_intake, self.redFlagLayer, self.db)
            score_calculated = EventLog(
                event_type=EventType.SCORE_CALCULATED,
                patient_id=patient_id,
                intake_id=new_intake.intake_id,
                details={
                    "esi": severityResult.esi_level,
                    "score": severityResult.severity_score
                }
            )
            self.db.add(score_calculated)

            if severityResult.flag_tier < 3:
                red_flag_fired = EventLog(
                    event_type=EventType.RED_FLAG_FIRED,
                    patient_id=patient_id,
                    intake_id=new_intake.intake_id,
                    details = {"flags": severityResult.red_flag_ids}
                )
                self.db.add(red_flag_fired)

            esi_num = int(severityResult.esi_level[-1])
            queue_position = queue.insert(esi_num, severityResult.flag_tier, new_intake.created_at, new_intake.intake_id)
            queued = EventLog(
                event_type=EventType.QUEUED,
                patient_id=patient_id,
                intake_id=new_intake.intake_id,
                details={
                    "esi": severityResult.esi_level,
                    "flag_tier": severityResult.flag_tier
                }
            )
            self.db.add(queued)

            self.db.flush()
            return Result(new_intake.intake_id, severityResult.severity_score, queue_position)
        except SQLAlchemyError as e:
            try:
                queue.remove(new_intake.intake_id)
            except ValueError:
                pass

            self.db.rollback()
            logger.exception("Intake creation failed")
            raise HTTPException(status_code=500) from e
        except CannotScoreError:
            try:
                queue.remove(new_intake.intake_id)
            except ValueError:
                pass

            self.db.rollback()
            logger.exception("The intake is valid but cannot be scored")
            raise UnscoreableException()


    def getQueue(self, queue: PriorityQueue) -> list[QueueEntry]:
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
        rows_by_intake_id = {row.IntakeRecord.intake_id: row for row in self.db.execute(stmt).all()}

        entries = []
        # IN doesn't preserve order, so queue order comes from walking intake_ids.
        for i, intake_id in enumerate(intake_ids):
            row = rows_by_intake_id.get(intake_id)
            if row is None:
                logger.error("intake_id wasn't in database when it should be")
                raise HTTPException(status_code=500)

            record, patient, severity = row.IntakeRecord, row.Patient, row.PatientSeverity

            # TODO: Once queue is persisted to database, these should never be none
            esi_level = row.esi_level
            priority_label = row.priority
            severity_score = severity.severity_score if severity is not None else None
            if severity is not None and priority_label is None:
                logger.error("esi_level wasn't in database when it should be")
                raise HTTPException(status_code=500)

            entry = QueueEntry(
                i + 1,
                patient.patient_id,
                patient.name,
                age_in_years(patient.date_of_birth),
                esi_level,
                priority_label,
                severity_score,
                "WAITING",
                record.created_at
            )
            entries.append(entry)

        return entries
    

    def updatePatient(self, intake_id: int, updates: IntakeUpdate, queue: PriorityQueue) -> Result:
        try:
            intake = self.db.get(IntakeRecord, intake_id)
        except SQLAlchemyError as e:
            logger.exception("Intake retrieval failed")
            raise HTTPException(status_code=500) from e
        
        if intake is None:
            logger.error("No intake with this id")
            raise IntakeNotFoundError(intake_id=intake_id)
        patient_id = intake.patient_id

        try:
            stmt = select(PatientSeverity).where(PatientSeverity.intake_id == intake_id)
            severity = self.db.scalar(stmt)
            if severity is None:
                logger.error("severity wasn't in database when it should be")
                raise HTTPException(status_code=500)
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.exception("Getting patient severity failed")
            raise HTTPException(status_code=500) from e

        # Status change, no re-queue
        if updates.status is not None:
            # TODO: Persist status change in triage_queue table
            if updates.status == Status.DISPOSITIONED:
                try:
                    queue.remove(intake_id)
                    new_event = EventLog(
                        event_type=EventType.STATUS_CHANGED,
                        patient_id=patient_id,
                        intake_id=intake_id
                        # TODO: Add details about the status change once persisted
                    )
                    self.db.add(new_event)
                    self.db.flush()
                except SQLAlchemyError as e:
                    self.db.rollback()
                    logger.exception("Event logging failed")
                    raise HTTPException(status_code=500) from e
                except ValueError:
                    # TODO: Once triage_queue is implemented, may make this error out instead of a no-op
                    # logger.exception("No intake with this id")
                    # raise HTTPException(status_code=404)
                    pass
                return Result(intake_id, severity.severity_score)
            
            try:
                new_event = EventLog(
                    event_type=EventType.STATUS_CHANGED,
                    patient_id=patient_id,
                    intake_id=intake_id
                    # TODO: Add details about the status change once persisted
                )
                self.db.add(new_event)
                self.db.flush()
                queue_position = queue.getIntakePosition(intake_id)
                return Result(intake_id, severity.severity_score, queue_position)
            except SQLAlchemyError as e:
                self.db.rollback()
                logger.exception("Event logging failed")
                raise HTTPException(status_code=500) from e
        

        # Updating patient info, may re-queue
        try:
            dia = updates.blood_pressure_diastolic if 'blood_pressure_diastolic' in updates.model_fields_set else intake.blood_pressure_diastolic
            syst = updates.blood_pressure_systolic if 'blood_pressure_systolic' in updates.model_fields_set else intake.blood_pressure_systolic
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
            details = {}
            for field in VITAL_FIELDS:
                # Only fields the client actually sent — model_fields_set lets an
                # explicit null clear a vital, which `is not None` would swallow.
                if field not in updates.model_fields_set:
                    continue
                old_value = getattr(intake, field)
                if isinstance(old_value, Decimal):
                    old_value = float(old_value)

                new_value = getattr(updates, field)
                if new_value != old_value:
                    setattr(intake, field, new_value)
                    updated_vitals[field] = new_value
                    details[field] = {
                        "old_value": old_value,
                        "new_value": new_value
                    }

            if updated_vitals:
                # Re-score and re-queue based on these values
                old_esi = severity.clinician_ESI if severity.clinician_ESI is not None else severity.system_ESI
                old_flag_tier = severity.flag_tier

                severityResult: SeverityResult = self.scoringEngine.score(intake, self.redFlagLayer, self.db)
                severity_score = severityResult.severity_score
                score_calculated = EventLog(
                    event_type=EventType.SCORE_CALCULATED,
                    patient_id=patient_id,
                    intake_id=intake_id,
                    details={
                        "esi": severityResult.esi_level,
                        "score": severityResult.severity_score
                    }
                )
                self.db.add(score_calculated)

                if severityResult.flag_tier < 3:
                    red_flag_fired = EventLog(
                        event_type=EventType.RED_FLAG_FIRED,
                        patient_id=patient_id,
                        intake_id=intake_id,
                        details = {"flags": severityResult.red_flag_ids}
                    )
                    self.db.add(red_flag_fired)

                esi_num = int(severityResult.esi_level[-1])
                old_position, new_position = queue.updatePatientPosition(intake_id, esi_num, severityResult.flag_tier)
                if old_position != new_position:
                    reprioritized = EventLog(
                        event_type=EventType.REPRIORITIZED,
                        patient_id=patient_id,
                        intake_id=intake_id,
                        details={
                            "old_esi": old_esi,
                            "old_flag_tier": old_flag_tier,
                            "new_esi": severityResult.esi_level,
                            "new_flag_tier": severityResult.flag_tier
                        }
                    )
                    self.db.add(reprioritized)

                case_update = CaseUpdate(patient_id=patient_id, intake_id=intake_id, updated_vitals=updated_vitals)
                new_event = EventLog(
                    event_type=EventType.CASE_UPDATED,
                    patient_id=patient_id,
                    intake_id=intake_id,
                    details=details
                )
                self.db.add(case_update)
                self.db.add(new_event)
            else:
                stmt = select(PatientSeverity).where(PatientSeverity.intake_id == intake_id)
                severity = self.db.scalar(stmt)
                severity_score = severity.severity_score if severity is not None else None
                new_position = queue.getIntakePosition(intake_id)
            
            self.db.flush()
            return Result(intake_id, severity_score, new_position)
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.exception("Vitals update failed")
            raise HTTPException(status_code=500) from e
        except CannotScoreError:
            self.db.rollback()
            logger.exception("The intake is valid but cannot be scored")
            raise UnscoreableException()