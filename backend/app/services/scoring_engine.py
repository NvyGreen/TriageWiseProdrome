import logging
from enum import StrEnum
from collections import namedtuple

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from fastapi.exceptions import HTTPException

from ..models.intake_record import IntakeRecord
from ..models.scoring_rule import ScoringRule
from ..models.patient_severity import PatientSeverity

from ..utils.rule import Rule
from ..utils.driver import Driver
from ..utils.severity_result import SeverityResult


ESI_1_THRESHOLD = 8
ESI_2_THRESHOLD = 6
ESI_3_THRESHOLD = 3
ESI_4_THRESHOLD = 1

VITAL_MAP = {
            "SpO2": "oxygen_saturation",
            "Heart rate": "heart_rate",
            "Respiratory rate": "respiration_rate",
            "Systolic BP": "blood_pressure_systolic",
            "Pain score": "pain_level"
        }

class ESILevels(StrEnum):
    ESI_1 = "ESI-1"
    ESI_2 = "ESI-2"
    ESI_3 = "ESI-3"
    ESI_4 = "ESI-4"
    ESI_5 = "ESI-5"

incompleteDriver = namedtuple("incompleteDriver", ["rule_id", "factor", "threshold", "patient_value", "weight"])

TOTAL_VITALS = 5

logger = logging.getLogger(__name__)


class CannotScoreError(Exception):
    def __init__(self, msg: str):
        self.msg = msg


class ScoringEngine:
    def __init__(self, db: Session):
        try:
            stmt = select(ScoringRule).where(ScoringRule.is_active.is_(True))
            raw_rules = db.scalars(stmt).all()
        except SQLAlchemyError as e:
            logger.exception("Could not get scoring rules")
            raise HTTPException(status_code=500) from e

        self.rules: list[Rule] = []
        for raw_rule in raw_rules:
            rule = Rule(
                raw_rule.rule_id,
                raw_rule.rule_type,
                raw_rule.factor,
                raw_rule.min_bound,
                raw_rule.max_bound,
                raw_rule.units,
                raw_rule.threshold_display,
                raw_rule.weight,
                raw_rule.complaint_group,
                raw_rule.resource_level,
                raw_rule.esi_anchor,
                raw_rule.fallback_if_missing
            )
            self.rules.append(rule)
    

    def score(self, intake: IntakeRecord, db: Session) -> SeverityResult:
        points = 0
        resource_level = None
        missing_fields = set()
        low_confidence = False
        fallbacks = {}
        incomplete_drivers: list[incompleteDriver] = []

        for rule in self.rules:
            if rule.rule_type == "vital":
                field = VITAL_MAP[rule.factor]
                check_vital = getattr(intake, field)
                if check_vital is None:
                    missing_fields.add(field)
                    if field not in fallbacks:
                        fallback_confidence, fallbacks[field] = self.applyFallback(rule.factor)
                        low_confidence = low_confidence or fallback_confidence
                    continue

                if rule.min_bound is None and rule.max_bound is None:
                    raise CannotScoreError(f"{rule.factor} min bound and max bound are both missing")

                if rule.min_bound is not None and check_vital >= rule.min_bound:
                    if rule.max_bound is None or check_vital <= rule.max_bound:
                        points += rule.weight
                        if rule.units == '%':
                            incomplete_drivers.append(incompleteDriver(rule.rule_id, rule.factor, rule.threshold_display, f"{check_vital}{rule.units}", rule.weight))
                        else:
                            incomplete_drivers.append(incompleteDriver(rule.rule_id, rule.factor, rule.threshold_display, f"{check_vital} {rule.units}", rule.weight))
                elif rule.min_bound is None and rule.max_bound is not None and check_vital <= rule.max_bound:
                    points += rule.weight
                    if rule.units == '%':
                        incomplete_drivers.append(incompleteDriver(rule.rule_id, rule.factor, rule.threshold_display, f"{check_vital}{rule.units}", rule.weight))
                    else:
                        incomplete_drivers.append(incompleteDriver(rule.rule_id, rule.factor, rule.threshold_display, f"{check_vital} {rule.units}", rule.weight))

            elif rule.rule_type == "complaint":
                if intake.chief_complaint is None:
                    raise CannotScoreError("Chief complaint cannot be missing")
                if intake.chief_complaint == rule.complaint_group:
                    points += rule.weight
                    # An intake can only ever have one chief complaint, so this will only trigger once
                    resource_level = rule.resource_level
                    incomplete_drivers.append(incompleteDriver(rule.rule_id, rule.factor, rule.threshold_display, intake.chief_complaint, rule.weight))
                
        if len(incomplete_drivers) == 0:
            raise CannotScoreError("The intake is valid but cannot be scored")
        
        initial_esi = ""
        if points >= ESI_1_THRESHOLD:
            initial_esi = ESILevels.ESI_1
        elif points >= ESI_2_THRESHOLD:
            initial_esi = ESILevels.ESI_2
        elif points >= ESI_3_THRESHOLD:
            initial_esi = ESILevels.ESI_3
        elif points >= ESI_4_THRESHOLD:
            initial_esi = ESILevels.ESI_4
        else:
            initial_esi = ESILevels.ESI_5
        
        refined, esi_level = self.refineByResource(initial_esi, resource_level)

        drivers: list[Driver] = []
        for incomplete_driver in incomplete_drivers:
            pct = 0 if points == 0 else round(((incomplete_driver.weight) / points) * 100)
            driver = Driver(
                incomplete_driver.rule_id,
                incomplete_driver.factor,
                incomplete_driver.threshold,
                incomplete_driver.weight,
                incomplete_driver.patient_value,
                pct
            )
            drivers.append(driver)
        
        # TODO: Add red flags fired from RedFlagLayer

        completeness_ratio = f"{TOTAL_VITALS - len(missing_fields)} of {TOTAL_VITALS}"
        confidence = "LOW" if low_confidence else "HIGH"
        score_reason_list = []
        for driver in drivers:
            score_reason = f"{driver.factor} {driver.threshold} +{driver.weight}"
            score_reason_list.append(score_reason)
        
        base_reason = ";".join(score_reason_list) + f" = {points} points"
        if refined:
            reason = base_reason + f" + {resource_level} resource(s) -> {esi_level}"
        else:
            reason = base_reason + f" -> {esi_level}"

        try:
            stmt = select(PatientSeverity).where(PatientSeverity.intake_id == intake.intake_id)
            severity = db.scalar(stmt)

            if severity is None:
                new_severity = PatientSeverity(
                    intake_id=intake.intake_id,
                    severity_score=min(points, 100),
                    system_ESI=esi_level,
                    score_reason=reason,
                    fallbacks_applied=fallbacks,
                    confidence=confidence
                    # TODO: red_flags
                    # TODO: red_flags_fired
                    # TODO: flag_tier
                )
                db.add(new_severity)
            else:
                severity.severity_score = min(points, 100)
                severity.system_ESI=esi_level
                severity.score_reason=reason
                severity.fallbacks_applied=fallbacks
                severity.confidence=confidence
                # TODO: red_flags
                # TODO: red_flags_fired
                # TODO: flag_tier

            db.flush()
        except SQLAlchemyError as e:
            db.rollback()
            logger.exception("Patient severity creation failed")
            raise HTTPException(status_code=500) from e

        return SeverityResult(
            min(points, 100),
            esi_level,
            initial_esi,
            resource_level,
            refined,
            drivers,
            list(missing_fields),
            completeness_ratio,
            fallbacks,
            confidence
        )
    

    def applyFallback(self, field):
        fallback = ""
        for rule in self.rules:
            if rule.factor == field:
                fallback = rule.fallback_if_missing
                break
        
        if fallback == "":
            raise CannotScoreError("Could not find matching rule")

        if "required field" in fallback:
            raise CannotScoreError(f"{field} cannot be missing")

        fallback_code = ""
        low_confidence = False
        if "confidence LOW" in fallback:
            low_confidence = True
        if "assume normal" in fallback:
            fallback_code = "assumed_normal"
        if "assume 0" in fallback:
            fallback_code = "assumed_zero"
        if "skip rule" in fallback:
            fallback_code = "rule_skipped"
        
        if fallback_code == "":
            raise HTTPException(status_code=500)
        
        return low_confidence, fallback_code
    

    def refineByResource(self, band: str, resource_level: str):
        if resource_level is None:
            raise CannotScoreError("resource_level cannot be missing")

        if band != ESILevels.ESI_3:
            return False, band
        
        if resource_level == "none":
            return True, ESILevels.ESI_5
        elif resource_level == "one":
            return True, ESILevels.ESI_4
        return False, ESILevels.ESI_3