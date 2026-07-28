import logging
import operator

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from fastapi.exceptions import HTTPException

from ..models.red_flag_rule import RedFlagRule
from ..models.intake_record import IntakeRecord
from ..models.patient import Patient

from ..utils.trigger import Trigger
from ..utils.severity_result import SeverityResult
from ..utils.driver import Driver
from ..utils.dates import age_in_years, age_in_days


logger = logging.getLogger(__name__)

BORDERLINE = {
    "heart_rate": (90, 99),
    "respiration_rate": (21, 24),
    "blood_pressure_systolic": (90, 99),
    "temperature": (99.5, 100.3)
}

VITAL_SET = {"SpO2", "Heart rate", "Respiratory rate", "Systolic BP"}


def _between(value: int | float, thresholds: list[int | float]) -> bool:
    if not isinstance(thresholds, list):
        logger.error("Bad thresholds")
        raise TypeError(f"Expected list of length 2, got {type(thresholds)}")

    if len(thresholds) != 2:
        logger.error("Bad thresholds")
        raise TypeError(f"Expected list of length 2, got list of length {len(thresholds)}")
    
    return value >= thresholds[0] and value <= thresholds[1]

def _in(value, arr: list) -> bool:
    if not isinstance(arr, list):
        logger.error("Bad arr")
        raise TypeError(f"Expected list, got {type(arr)}")
    
    return value in arr

def _contains_any(main_list: list, comp_list: list) -> bool:
    if not isinstance(main_list, list) or not isinstance(comp_list, list):
        logger.error("Bad arr")
        raise TypeError(f"Expected arguments of type (list, list), got arguments of type ({type(main_list)}, {type(comp_list)})")

    for item in comp_list:
        if item in main_list:
            return True

    return False

OPERATORS = {
    ">": operator.gt,
    "<": operator.lt,
    "==": operator.eq,
    "!=": operator.ne,
    ">=": operator.ge,
    "<=": operator.le,
    "between": _between,
    "in": _in,
    "contains": operator.contains,
    "contains_any": _contains_any
}


class RedFlagLayer:
    def __init__(self, db: Session):
        try:
            stmt = select(RedFlagRule).where(RedFlagRule.is_active.is_(True))
            raw_triggers = db.scalars(stmt).all()
        except SQLAlchemyError as e:
            logger.exception("Could not get red flag rules")
            raise HTTPException(status_code=500) from e

        self.triggers: list[Trigger] = []
        for raw_trigger in raw_triggers:
            trigger = Trigger(
                raw_trigger.flag_id,
                raw_trigger.trigger_pattern,
                raw_trigger.trigger_pattern_tree,
                raw_trigger.flag_type,
                raw_trigger.flag_tier,
                raw_trigger.message,
                raw_trigger.rationale
            )
            self.triggers.append(trigger)


    def check(self, intake: IntakeRecord, score: SeverityResult, db: Session) -> list[Trigger]:
        fired_flags: list[Trigger] = []
        for trigger in self.triggers:
            pattern_tree = trigger.trigger_pattern_tree
            triggered = False
            if pattern_tree.get("op"):
                if not pattern_tree.get("conditions"):
                    logger.error("Expected conditions")
                    raise HTTPException(status_code=500)
                
                if pattern_tree["op"] == "AND":
                    triggered = self._parse_and(pattern_tree["conditions"], intake, score, db)
                elif pattern_tree["op"] == "OR":                    
                    triggered = self._parse_or(pattern_tree["conditions"], intake, score, db)
                else:
                    logger.error(f"Unrecognized format: {pattern_tree}")
                    raise HTTPException(status_code=500)
            elif pattern_tree.get("helper"):
                triggered = self._parse_helper(pattern_tree, intake, score, db)
            elif pattern_tree.get("field"):
                triggered = self._parse_field(pattern_tree, intake)
            else:
                logger.error(f"Unrecognized format: {pattern_tree}")
                raise HTTPException(status_code=500)

            if triggered:
                fired_flags.append(trigger)

        return fired_flags


    def _parse_and(self, conditions: list[dict], intake: IntakeRecord, score: SeverityResult, db: Session) -> bool:
        status = True
        if len(conditions) == 0:
            logger.error("Coniditions empty")
            raise HTTPException(status_code=500)
        
        for condition in conditions:
            if condition.get("op"):
                if not condition.get("conditions"):
                    logger.error("Expected conditions")
                    raise HTTPException(status_code=500)
                
                if condition["op"] == "OR":
                    status = status and self._parse_or(condition["conditions"], intake, score, db)
                elif condition["op"] == "AND":
                    status = status and self._parse_and(condition["conditions"], intake, score, db)
                else:
                    logger.error(f"Unrecognized format: {condition}")
                    raise HTTPException(status_code=500)
            elif condition.get("helper"):
                status = status and self._parse_helper(condition, intake, score, db)
            elif condition.get("field"):
                status = status and self._parse_field(condition, intake)
            else:
                logger.error(f"Unrecognized format: {condition}")
                raise HTTPException(status_code=500)

            if status is False:
                return status

        return status


    def _parse_or(self, conditions: list[dict], intake: IntakeRecord, score: SeverityResult, db: Session) -> bool:
        status = False
        if len(conditions) == 0:
            raise HTTPException(status_code=500)
        
        for condition in conditions:
            if condition.get("op"):
                if not condition.get("conditions"):
                    logger.error("Expected conditions")
                    raise HTTPException(status_code=500)
                
                if condition["op"] == "AND":
                    status = status or self._parse_and(condition["conditions"], intake, score, db)
                elif condition["op"] == "OR":
                    status = status or self._parse_or(condition["conditions"], intake, score, db)
                else:
                    logger.error(f"Unrecognized format: {condition}")
                    raise HTTPException(status_code=500)
            elif condition.get("helper"):
                status = status or self._parse_helper(condition, intake, score, db)
            elif condition.get("field"):
                status = status or self._parse_field(condition, intake)
            else:
                logger.error(f"Unrecognized format: {condition}")
                raise HTTPException(status_code=500)

            if status is True:
                return status

        return status


    def _require_cmp_value(self, helper_info: dict) -> None:
        """Validate that a comparison helper has a usable cmp + value."""
        if not helper_info.get("cmp") or helper_info.get("value") is None:
            logger.error(f"cmp and/or value not in helper when helper is {helper_info["helper"]}")
            raise HTTPException(status_code=500)

        if not OPERATORS.get(helper_info["cmp"]):
            logger.error(f"Operator {helper_info["cmp"]} not recognized")
            raise HTTPException(status_code=500)

    def _parse_helper(self, helper_info: dict, intake: IntakeRecord, score: SeverityResult, db: Session) -> bool:
        if helper_info["helper"] == "age_in_years":
            self._require_cmp_value(helper_info)

            stmt = select(Patient).where(Patient.patient_id == intake.patient_id)
            patient = db.scalar(stmt)
            if patient is None:
                logger.error("patient_id wasn't in database when it should be")
                raise HTTPException(status_code=500)

            years_age = age_in_years(patient.date_of_birth)
            op_func = OPERATORS[helper_info["cmp"]]
            return op_func(years_age, helper_info["value"])

        elif helper_info["helper"] == "all_vitals_normal":
            return self._all_vitals_normal(intake, score.named_drivers)

        elif helper_info["helper"] == "count_borderline_vitals":
            self._require_cmp_value(helper_info)

            op_func = OPERATORS[helper_info["cmp"]]
            return op_func(self._count_borderline_vitals(intake), helper_info["value"])

        elif helper_info["helper"] == "age_in_days":
            self._require_cmp_value(helper_info)

            stmt = select(Patient).where(Patient.patient_id == intake.patient_id)
            patient = db.scalar(stmt)
            if patient is None:
                logger.error("patient_id wasn't in database when it should be")
                raise HTTPException(status_code=500)

            days_age = age_in_days(patient.date_of_birth)
            op_func = OPERATORS[helper_info["cmp"]]
            return op_func(days_age, helper_info["value"])

        else:
            logger.error(f"Unrecognized format: {helper_info}")
            raise HTTPException(status_code=500)


    def _parse_field(self, field_info: dict, intake: IntakeRecord) -> bool:
        if not field_info.get("cmp") or field_info.get("value") is None:
            logger.error("cmp and/or value not in field")
            raise HTTPException(status_code=500)

        if not OPERATORS.get(field_info["cmp"]):
            logger.error(f"Operator {field_info["cmp"]} not recognized")
            raise HTTPException(status_code=500)

        try:
            field = getattr(intake, field_info["field"])
        except AttributeError:
            logger.exception(f"Unknown vital {field_info["field"]}")
            raise HTTPException(status_code=500)
        
        if field is None:
            return False
        op_func = OPERATORS[field_info["cmp"]]
        return op_func(field, field_info["value"])


    def _all_vitals_normal(self, intake: IntakeRecord, drivers: list[Driver]) -> bool:
        if self._count_borderline_vitals(intake) > 0:
            return False

        for driver in drivers:
            if driver.factor in VITAL_SET:
                return False

        return True


    def _count_borderline_vitals(self, intake: IntakeRecord) -> int:
        borderline_count = 0
        for vital, border in BORDERLINE.items():
            min_val, max_val = border
            check_vital = getattr(intake, vital)
            if check_vital is not None and check_vital >= min_val and check_vital <= max_val:
                borderline_count += 1
        return borderline_count