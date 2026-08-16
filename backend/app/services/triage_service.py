import logging
from enum import StrEnum
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from fastapi.exceptions import HTTPException, RequestValidationError
from pydantic import ValidationError

from ..models.patient import Patient
from ..models.intake_record import IntakeRecord
from ..models.patient_severity import PatientSeverity
from ..models.esi_band import ESIBand
from ..models.event_log import EventLog
from ..models.case_update import CaseUpdate
from ..models.ai_explanation import AIExplanation
from ..models.red_flag_rule import RedFlagRule
from ..models.override import Override
from ..models.condition_reference import ConditionReference

from ..schemas.intake_create import IntakeCreate
from ..schemas.intake_update import IntakeUpdate, Status, VITAL_FIELDS
from ..schemas.patient_info import PatientInfo
from ..schemas.intake_info import IntakeInfo
from ..schemas.severity_info import SeverityInfo
from ..schemas.trigger_info import TriggerInfo
from ..schemas.override_info import OverrideInfo

from ..services.priority_queue import PriorityQueue
from ..services.scoring_engine import ScoringEngine, CannotScoreError
from ..services.red_flag_layer import RedFlagLayer
from ..services.explanation_builder import ExplanationBuilder

from ..utils.result import Result
from ..utils.queue_entry import QueueEntry
from ..utils.severity_result import SeverityResult
from ..utils.driver import Driver
from ..utils.patient_detail import PatientDetail
from ..utils.explanation import Explanation
from ..utils.trigger import Trigger
from ..utils.dates import age_in_years
from ..utils.constants import ESI_THRESHOLDS, VITAL_MAP, TOTAL_VITALS, LABEL_MAP
from ..utils.enums import ReasonCode


logger = logging.getLogger(__name__)

VITAL_RENDER = {v: k for k, v in VITAL_MAP.items()}
VITAL_RENDER["temperature"] = "Temperature"
VITAL_RENDER["blood_pressure_diastolic"] = "Diastolic BP"
VITAL_RENDER["blood_sugar"] = "Blood sugar"


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


class SeverityNotFoundError(Exception):
    def __init__(self, severity_id: int):
        self.severity_id = severity_id


class TriageService:
    def __init__(self, db: Session):
        self.db = db
        self.scoringEngine = ScoringEngine(db)
        self.redFlagLayer = RedFlagLayer(db)
        self.explanationBuilder = ExplanationBuilder(db)

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
            self.explanationBuilder.build(severityResult, new_intake)

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
            flag_tier = severity.flag_tier if severity is not None else None
            if severity is not None and priority_label is None:
                logger.error("esi_level wasn't in database when it should be")
                raise HTTPException(status_code=500)

            entry = QueueEntry(
                i + 1,
                patient.patient_id,
                record.intake_id,
                patient.name,
                age_in_years(patient.date_of_birth),
                patient.sex,
                esi_level,
                flag_tier,
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
                self.explanationBuilder.build(severityResult, intake)

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


    def getPatientDetail(self, intake_id: int) -> PatientDetail:
        try:
            intake = self.db.get(IntakeRecord, intake_id)
            if intake is None:
                logger.error(f"Intake {intake_id} not found")
                raise IntakeNotFoundError(intake_id)

            stmt = select(Patient).where(Patient.patient_id == intake.patient_id)
            patient = self.db.scalar(stmt)
            if patient is None:
                logger.error("Patient was none when it shouldn't be")
                raise HTTPException(status_code=500)

            stmt = select(PatientSeverity).where(PatientSeverity.intake_id == intake_id)
            severity = self.db.scalar(stmt)
            if severity is None:
                logger.error("Severity was none when it shouldn't be")
                raise HTTPException(status_code=500)

            stmt = select(AIExplanation).where(AIExplanation.intake_id == intake_id)
            ai_explanation = self.db.scalar(stmt)
            if ai_explanation is None:
                logger.error("Explanation was none when it shouldn't be")
                raise HTTPException(status_code=500)
        except SQLAlchemyError as e:
            logger.exception("Getting objects for PatientDetail failed")
            raise HTTPException(status_code=500) from e

        try:
            patient_info = PatientInfo(
                patient_id=patient.patient_id,
                name=patient.name,
                date_of_birth=patient.date_of_birth,
                sex=patient.sex
            )

            intake_info = IntakeInfo(
                intake_id=intake_id,
                symptoms=intake.symptoms,
                chief_complaint=intake.chief_complaint,
                heart_rate=intake.heart_rate,
                blood_pressure_systolic=intake.blood_pressure_systolic,
                blood_pressure_diastolic=intake.blood_pressure_diastolic,
                temperature=intake.temperature,
                oxygen_saturation=intake.oxygen_saturation,
                respiration_rate=intake.respiration_rate,
                pain_level=intake.pain_level,
                blood_sugar=intake.blood_sugar,
                missing_fields=intake.missing_fields,
                pregnancy_status=intake.pregnancy_status,
                pre_existing_conditions=intake.pre_existing_conditions,
                arrival_by_ambulance=intake.arrival_by_ambulance,
                recent_ed_visit_72h=intake.recent_ed_visit_72h,
                injury_related=intake.injury_related,
                notes=intake.notes,
                created_at=intake.created_at
            )

            severity_info = SeverityInfo(
                severity_id=severity.severity_id,
                severity_score=severity.severity_score,
                system_ESI=severity.system_ESI,
                clinician_ESI=severity.clinician_ESI,
                score_reason=severity.score_reason,
                fallbacks_applied=severity.fallbacks_applied,
                confidence=severity.confidence,
                flag_tier=severity.flag_tier,
                created_at=severity.created_at
            )
        except ValidationError as e:
            logger.exception("Creating Info objects failed")
            raise HTTPException(status_code=500) from e

        explanation = Explanation(
            ai_explanation.data_completeness,
            [Driver(**d) for d in ai_explanation.factor_breakdown],
            ai_explanation.gaps
        )

        try:
            triggers: list[TriggerInfo] = []
            flag_ids = [flag['flag_id'] for flag in severity.red_flags]
            stmt = select(RedFlagRule).where(RedFlagRule.flag_id.in_(flag_ids))
            flag_rules = self.db.scalars(stmt).all()
            if len(flag_rules) != len(flag_ids):
                logger.error("Number of flag rules does not match with number of flag ids")
                raise HTTPException(status_code=500)
            
            for flag_rule in flag_rules:                
                trigger = TriggerInfo(
                    flag_id=flag_rule.flag_id,
                    flag_type=flag_rule.flag_type,
                    flag_tier=flag_rule.flag_tier,
                    message=flag_rule.message,
                    rationale=flag_rule.rationale
                )
                triggers.append(trigger)
        except (SQLAlchemyError, ValidationError) as e:
            logger.exception("Creating Triggers failed")
            raise HTTPException(status_code=500) from e

        lede = self._render_lede(severity, ai_explanation)
        dual_score_line, xai_line = self._render_dual_score(severity, ai_explanation)
        base_rate_line = self._render_base_rate(intake.chief_complaint)
        risk_blurb = self._render_risk_blurb(severity, ai_explanation)

        try:
            stmt = select(Override).where(Override.severity_id == severity.severity_id)
            override = self.db.scalar(stmt)
            override_info = None
            if override is not None:
                override_info = OverrideInfo(
                    override_id=override.override_id,
                    system_esi=override.system_ESI,
                    clinician_esi=override.clinician_ESI,
                    reason_code=override.reason_code,
                    note=override.note
                )
        except (SQLAlchemyError, ValidationError) as e:
            logger.exception("Getting override info failed")
            raise HTTPException(status_code=500) from e

        return PatientDetail(
            patient=patient_info,
            intake=intake_info,
            missing_fields=intake_info.missing_fields,
            severity=severity_info,
            explanation=explanation,
            red_flags=triggers,
            lede=lede,
            risk_blurb=risk_blurb,
            dual_score_line=dual_score_line,
            xai_line=xai_line,
            base_rate_line=base_rate_line,
            override=override_info
        )


    def applyOverride(self, severity_id: int, clinician_esi: str, reason_code: ReasonCode, note: str | None, queue: PriorityQueue) -> Result:
        try:
            severity = self.db.get(PatientSeverity, severity_id)
            if severity is None:
                raise SeverityNotFoundError(severity_id)
            
            old_esi = severity.clinician_ESI if severity.clinician_ESI is not None else severity.system_ESI
            severity.clinician_ESI = clinician_esi
            new_override = Override(
                intake_id=severity.intake_id,
                severity_id=severity_id,
                system_ESI=severity.system_ESI,
                clinician_ESI=clinician_esi,
                reason_code=reason_code,
                note=note
            )

            intake = self.db.get(IntakeRecord, severity.intake_id)
            if intake is None:
                raise HTTPException(status_code=500)
            override_event = EventLog(
                event_type=EventType.OVERRIDE_APPLIED,
                patient_id=intake.patient_id,
                intake_id=severity.intake_id,
                details={
                    "old_esi": old_esi,
                    "new_esi": clinician_esi,
                    "reason_code": reason_code
                }
            )

            self.db.add(new_override)
            self.db.add(override_event)
            self.db.flush()

            try:
                old_position, new_position = queue.updatePatientPosition(severity.intake_id, int(clinician_esi[-1]), severity.flag_tier)
            except ValueError as e:
                self.db.rollback()
                logger.exception("Intake wasn't in queue when it should be")
                raise HTTPException(status_code=500) from e
            
            if old_position != new_position:
                reprioritized_event = EventLog(
                    event_type=EventType.REPRIORITIZED,
                    patient_id=intake.patient_id,
                    intake_id=severity.intake_id,
                    details={
                        "old_esi": old_esi,
                        "old_flag_tier": severity.flag_tier,
                        "new_esi": clinician_esi,
                        "new_flag_tier": severity.flag_tier
                    }
                )
                self.db.add(reprioritized_event)
                self.db.flush()

            return Result(
                intake_id=severity.intake_id,
                severity_score=int(severity.severity_score),
                queue_placement=new_position
            )
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.exception("Overriding failed")
            raise HTTPException(status_code=500) from e


    def _render_lede(self, severity: PatientSeverity, explanation: AIExplanation) -> str:
        lede = f"This patient scored {int(severity.severity_score)} points -> {severity.system_ESI} ({LABEL_MAP[severity.system_ESI]}) from "

        n_drivers = len(explanation.factor_breakdown)
        drivers = [Driver(**d) for d in explanation.factor_breakdown]
        if n_drivers == 1:
            lede += "the chief-complaint rule alone. "
        else:
            drivers.sort(key=lambda d: d.contribution_pct, reverse=True)
            contributors = []
            for driver in drivers:
                contributors.append(driver.threshold if driver.factor == "Chief complaint" else driver.factor)
            
            if n_drivers == 2:
                lede += f"{n_drivers - 1} vital-sign rule and the chief-complaint rule. The largest contributor is {contributors[0]}; {contributors[1]} adds to the total. "
            else:
                lede += f"{n_drivers - 1} vital-sign rules and the chief-complaint rule. The largest contributor is {contributors[0]}; {", ".join(contributors[1:])} add to the total. "

        if explanation.data_completeness == f"{TOTAL_VITALS} of {TOTAL_VITALS}":
            coverage_clause = "All required vitals provided."
        else:
            coverage_clause = f"{explanation.data_completeness} vitals scored - "
            fallbacks = []

            assumed = []
            for field in explanation.gaps["assumed"]:
                assumed.append(VITAL_RENDER[field])
            if len(assumed) > 0:
                fallbacks.append(f"{", ".join(assumed)} assumed")

            missing = []
            for field in explanation.gaps["not_provided"]:
                missing.append(VITAL_RENDER[field])
            if len(missing) > 0:
                fallbacks.append(f"{", ".join(missing)} missing")

            coverage_clause += f"{"; ".join(fallbacks)}."

        return lede + coverage_clause


    def _render_risk_blurb(self, severity: PatientSeverity, explanation: AIExplanation) -> str:
        drivers = [Driver(**d) for d in explanation.factor_breakdown]
        drivers.sort(key=lambda d: d.contribution_pct, reverse=True)

        # same naming rule as the lede: chief complaint renders its threshold,
        # vitals render their factor
        def name(d: Driver) -> str:
            return d.threshold if d.factor == "Chief complaint" else d.factor

        blurb = f"Derived from {severity.system_ESI}. Driven by {name(drivers[0])}"
        if len(drivers) > 1:
            secondary = ", ".join(name(d) for d in drivers[1:])
            blurb += f", plus {secondary}"
        blurb += ". Describes the inputs that scored - not a diagnosis."

        return blurb


    def _render_dual_score(self, severity: PatientSeverity, explanation: AIExplanation) -> tuple[str | None, str | None]:
        if severity.clinician_ESI is None:
            return None, None

        score_line = f"System suggests: {severity.system_ESI}\nClinician score: {severity.clinician_ESI}"
        try:
            stmt = select(Override).where(Override.severity_id == severity.severity_id)
            override = self.db.scalar(stmt)
            if override is not None:
                score_line += f"\nOverride reason: {override.reason_code}"
                if override.note is not None:
                    score_line += f" - '{override.note}'"
        except SQLAlchemyError as e:
            logger.exception("Could not get override info")
            raise HTTPException(status_code=500) from e

        system_num = int(severity.system_ESI[-1])
        clinician_num = int(severity.clinician_ESI[-1])

        if system_num > clinician_num:
            xai_line = f"Your {severity.clinician_ESI} takes precedence."
        else:
            drivers = [Driver(**d) for d in explanation.factor_breakdown]
            drivers.sort(key=lambda d: d.weight, reverse=True)

            i, score = 0, 0
            delta_drivers = []
            while i < len(drivers) and score < ESI_THRESHOLDS[severity.system_ESI]:
                score += drivers[i].weight
                if drivers[i].factor == "Chief complaint":
                    delta_drivers.append(drivers[i].patient_value)
                else:
                    delta_drivers.append(f"{drivers[i].factor} {drivers[i].patient_value}")

                i += 1

            joined = " + ".join(delta_drivers)
            xai_line = f"System weighted {joined} as {severity.system_ESI}. Confirm these were considered."

        return score_line, xai_line


    def _render_base_rate(self, chief_complaint: str) -> str | None:
        try:
            stmt = select(ConditionReference).where(ConditionReference.complaint_key == chief_complaint)
            complaint_condition = self.db.scalar(stmt)
            if complaint_condition is None:
                return None
            base_rate_line = f"Illustrative base rate ({complaint_condition.source_label}): {complaint_condition.condition} -> {round(complaint_condition.admit_rate * 100, 1)}% admitted."

            diagnosis_condition = None
            if complaint_condition.context_condition is not None:
                stmt = select(ConditionReference).where(ConditionReference.condition == complaint_condition.context_condition)
                diagnosis_condition = self.db.scalar(stmt)
            if diagnosis_condition is not None:
                base_rate_line += f" Dangerous subset ({diagnosis_condition.condition}) -> {round(diagnosis_condition.admit_rate * 100, 1)}%, not identifiable at triage."

            base_rate_line += " Population reference, not this patient's probability."
            if complaint_condition.reliable == "low-n (<30)":
                base_rate_line += " Small sample, illustrative only."
            return base_rate_line
        except SQLAlchemyError as e:
            logger.exception("Could not get condition reference")
            raise HTTPException(status_code=500) from e