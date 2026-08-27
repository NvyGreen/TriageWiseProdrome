import logging
from enum import StrEnum
from collections import namedtuple

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from ..models.intake_record import IntakeRecord
from ..models.scoring_rule import ScoringRule
from ..models.patient_severity import PatientSeverity

from ..services.red_flag_layer import RedFlagLayer

from ..utils.rule import Rule
from ..utils.driver import Driver
from ..utils.severity_result import SeverityResult
from ..utils.constants import ESI_THRESHOLDS, VITAL_MAP, TOTAL_VITALS
from ..utils.enums import ESILevels


class FallbackCodes(StrEnum):
    ASSUME_NORMAL = "assume_normal"
    SKIP_RULE = "skip_rule"
    ASSUME_ZERO = "assume_zero"

incompleteDriver = namedtuple("incompleteDriver", ["rule_id", "factor", "threshold", "unit", "patient_value", "weight", "esi_anchor"])

logger = logging.getLogger(__name__)


class CannotScoreException(Exception):
    def __init__(self, msg: str):
        self.msg = msg

class ScoringRetrievalException(Exception):
    def __init__(self, msg: str):
        self.msg = msg


class ScoringEngine:
    def __init__(self, db: Session):
        try:
            stmt = select(ScoringRule).where(ScoringRule.is_active.is_(True))
            raw_rules = db.scalars(stmt).all()
        except SQLAlchemyError as e:
            logger.exception("Could not get scoring rules")
            raise ScoringRetrievalException("Could not get scoring rules")

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
                raw_rule.fallback_if_missing,
                raw_rule.scoring_action,
                raw_rule.confidence_effect
            )
            self.rules.append(rule)
    

    def score(self, intake: IntakeRecord, red_flag_layer: RedFlagLayer, db: Session) -> tuple[int, SeverityResult]:
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
                    raise CannotScoreException(f"{rule.factor} min bound and max bound are both missing")

                if rule.min_bound is not None and check_vital >= rule.min_bound:
                    if rule.max_bound is None or check_vital <= rule.max_bound:
                        points += rule.weight
                        if rule.units == '%':
                            incomplete_drivers.append(incompleteDriver(rule.rule_id, rule.factor, rule.threshold_display, rule.units, f"{check_vital}{rule.units}", rule.weight, rule.esi_anchor))
                        else:
                            incomplete_drivers.append(incompleteDriver(rule.rule_id, rule.factor, rule.threshold_display, rule.units, f"{check_vital} {rule.units}", rule.weight, rule.esi_anchor))
                elif rule.min_bound is None and rule.max_bound is not None and check_vital <= rule.max_bound:
                    points += rule.weight
                    if rule.units == '%':
                        incomplete_drivers.append(incompleteDriver(rule.rule_id, rule.factor, rule.threshold_display, rule.units, f"{check_vital}{rule.units}", rule.weight, rule.esi_anchor))
                    else:
                        incomplete_drivers.append(incompleteDriver(rule.rule_id, rule.factor, rule.threshold_display, rule.units, f"{check_vital} {rule.units}", rule.weight, rule.esi_anchor))

            elif rule.rule_type == "complaint":
                if intake.chief_complaint is None:
                    raise CannotScoreException("Chief complaint cannot be missing")
                if intake.chief_complaint == rule.complaint_group:
                    points += rule.weight
                    # An intake can only ever have one chief complaint, so this will only trigger once
                    resource_level = rule.resource_level
                    incomplete_drivers.append(incompleteDriver(rule.rule_id, rule.factor, rule.threshold_display, rule.units, intake.chief_complaint, rule.weight, rule.esi_anchor))
                
        if len(incomplete_drivers) == 0:
            raise CannotScoreException("The intake is valid but cannot be scored")
        
        initial_esi = ""
        if points >= ESI_THRESHOLDS["ESI-1"]:
            initial_esi = ESILevels.ESI_1
        elif points >= ESI_THRESHOLDS["ESI-2"]:
            initial_esi = ESILevels.ESI_2
        elif points >= ESI_THRESHOLDS["ESI-3"]:
            initial_esi = ESILevels.ESI_3
        elif points >= ESI_THRESHOLDS["ESI-4"]:
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
                incomplete_driver.unit,
                incomplete_driver.weight,
                incomplete_driver.patient_value,
                pct,
                incomplete_driver.esi_anchor
            )
            drivers.append(driver)

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

        result = SeverityResult(
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

        fired_flags = red_flag_layer.check(intake, result, db)
        red_flags = []
        red_flag_ids = []
        flag_tier = 3
        for flag in fired_flags:
            red_flags.append({
                "flag_id": flag.flag_id,
                "message": flag.message,
                "flag_tier": flag.flag_tier
            })
            red_flag_ids.append(flag.flag_id)
            flag_tier = min(flag_tier, flag.flag_tier)

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
                    confidence=confidence,
                    red_flags=red_flags,
                    red_flag_fired=len(red_flags) != 0,
                    flag_tier=flag_tier
                )
                db.add(new_severity)
            else:
                severity.severity_score = min(points, 100)
                severity.system_ESI = esi_level
                severity.score_reason = reason
                severity.fallbacks_applied = fallbacks
                severity.confidence = confidence
                severity.red_flags = red_flags
                severity.red_flag_fired = len(red_flags) != 0
                severity.flag_tier = flag_tier

            db.flush()
            severity_id = severity.severity_id if severity is not None else new_severity.severity_id
        except SQLAlchemyError as e:
            db.rollback()
            logger.exception("Patient severity creation failed")
            raise CannotScoreException("Patient severity creation failed")

        result.flag_tier = flag_tier
        result.red_flag_ids = red_flag_ids
        return severity_id, result


    def applyFallback(self, field):
        for rule in self.rules:
            if rule.factor == field:
                if rule.scoring_action not in FallbackCodes:
                    logger.error(f"{rule.scoring_action} not a recognized fallback")
                    raise ScoringRetrievalException(f"{rule.scoring_action} not a recognized fallback")
                return rule.confidence_effect == "low", rule.scoring_action

        raise CannotScoreException("Could not find matching rule")
    

    def refineByResource(self, band: str, resource_level: str):
        if resource_level is None:
            raise CannotScoreException("resource_level cannot be missing")

        if band != ESILevels.ESI_3:
            return False, band
        
        if resource_level == "none":
            return True, ESILevels.ESI_5
        elif resource_level == "one":
            return True, ESILevels.ESI_4
        return False, ESILevels.ESI_3