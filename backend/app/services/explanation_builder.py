import logging
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from fastapi.exceptions import HTTPException

from ..models.intake_record import IntakeRecord
from ..models.ai_explanation import AIExplanation
from ..models.patient_severity import PatientSeverity
from ..models.red_flag_rule import RedFlagRule

from ..utils.severity_result import SeverityResult
from ..utils.explanation import Explanation
from ..utils.vitals import VITAL_MAP


BEYOND_THE_DATA = "Appearance, work of breathing, distress, social context, staffing - outside this engine."
ALL_VITALS = {"heart_rate", "blood_pressure_systolic", "blood_pressure_diastolic", "temperature", "oxygen_saturation", "respiration_rate", "pain_level", "blood_sugar"}
LABEL_MAP = {
    "ESI-1": "Critical",
    "ESI-2": "Emergent",
    "ESI-3": "Urgent",
    "ESI-4": "Less urgent",
    "ESI-5": "Non-urgent"
}

RULE_FIELDS = set(VITAL_MAP.values())
RULE_FIELDS.add("chief_complaint")

ALLOWED_FIELDS = {c.name for c in IntakeRecord.__table__.columns}
ALLOWED_FIELDS.difference_update(["intake_id", "patient_id", "missing_fields", "source", "external_patient_id", "actual_outcome", "outcome_source", "created_at", "arrival_by_ambulance", "recent_ed_visit_72h", "injury_related"])

FIELDS_MAP = {
    "pre_existing_conditions": "Pre-existing conditions",
    "symptoms": "Symptoms"
}

VALUE_FIELDS = {"pre_existing_conditions", "symptoms", "pregnancy_status"}
EXCLUDED_FIELDS = {"chief_complaint"}

logger = logging.getLogger(__name__)


class ExplanationBuilder:
    def __init__(self, db: Session):
        self.db = db


    def build(self, severityResult: SeverityResult, intake: IntakeRecord) -> Explanation:
        gaps: dict[str, list[str]] = {
            "not_provided": [],
            "assumed": [],
            "recorded_not_scored": [],
            "red_flag_input": [],
            "beyond_the_data": [BEYOND_THE_DATA],
        }
        fields_flagged = self._get_red_flag_fields(severityResult.red_flag_ids)
        red_flag_vitals = []

        # Build gaps
        for field in ALLOWED_FIELDS:
            if field in severityResult.missing_fields:
                if severityResult.fallbacks_applied[field].startswith("assume"):
                    gaps["assumed"].append(field)
                else:
                    gaps["not_provided"].append(field)
            else:
                intake_field = getattr(intake, field)
                if not self._check_empty(intake_field):
                    if field not in RULE_FIELDS:
                        self._flagged_or_no(field, fields_flagged, intake_field, gaps, red_flag_vitals)

        if len(red_flag_vitals) > 0:
            gaps["red_flag_input"].append(f"Vitals: {", ".join(sorted(red_flag_vitals))}")

        # Generate explanation text
        if len(severityResult.missing_fields) == 0:
            coverage_clause = "All required vitals provided."
        else:
            coverage_clause = f"{severityResult.data_completeness} vitals scored - "
            not_covered = []
            if len(gaps["assumed"]) > 0:
                assumed_normal = []
                assumed_zero = []
                for field in gaps["assumed"]:
                    if severityResult.fallbacks_applied[field] == "assume_normal":
                        assumed_normal.append(field)
                    elif severityResult.fallbacks_applied[field] == "assume_zero":
                        assumed_zero.append(field)

                if len(assumed_normal) > 0:
                    not_covered.append(",".join(assumed_normal))
                if len(assumed_zero) > 0:
                    not_covered.append(",".join(assumed_zero))

            if len(gaps["not_provided"]) > 0:
                not_covered.append(",".join(gaps["not_provided"]))
            coverage_clause += f"{";".join(not_covered)}."

        sorted_drivers = sorted(severityResult.named_drivers, key=lambda d: d.contribution_pct, reverse=True)
        chief_complaint_only = len(severityResult.named_drivers) - 1 == 0

        explanation_text = f"This patient scored {severityResult.severity_score} points -> {severityResult.esi_level} ({LABEL_MAP[severityResult.esi_level]}) "
        if chief_complaint_only:
            explanation_text += "from the chief complaint rule alone. "
        else:
            explanation_text += f"from {len(severityResult.named_drivers) - 1} vital-sign rule(s) and the chief-complaint rule. The largest contributor is rule {sorted_drivers[0].rule_id}; rule(s) {", ".join(str(d.rule_id) for d in sorted_drivers[1:])} add(s) to the total. "
        explanation_text += coverage_clause

        try:
            stmt = select(PatientSeverity).where(PatientSeverity.intake_id == intake.intake_id)
            severity = self.db.scalar(stmt)
            if severity is None:
                logger.error("severity wasn't in database when it should be")
                raise HTTPException(status_code=500)

            explanation = AIExplanation(
                severity_id=severity.severity_id,
                intake_id=intake.intake_id,
                explanation_text=explanation_text,
                factor_breakdown=[asdict(d) for d in severityResult.named_drivers],
                data_completeness=severityResult.data_completeness,
                gaps=gaps
                # TODO: Add step
                # TODO: Add lead element
            )
            self.db.add(explanation)
            self.db.flush()
        except SQLAlchemyError as e:
            self.db.rollback()
            logger.exception("Explanation creation failed")
            raise HTTPException(status_code=500) from e

        return Explanation(
            severityResult.data_completeness,
            severityResult.named_drivers,
            gaps
        )


    def _check_empty(self, field) -> bool:
        if isinstance(field, list):
            return len(field) == 0
        return field is None or field == "none"


    def _flagged_or_no(self, field: str, fields_flagged: set[str], intake_field, gaps: dict[str, list[str]], red_flag_vitals: list[str]):
        if field in ALL_VITALS:
            if field in fields_flagged:
                red_flag_vitals.append(field)
            else:
                gaps["recorded_not_scored"].append(field)
            return

        if field == "pregnancy_status":
            if intake_field in fields_flagged:
                gaps["red_flag_input"].append(f"Pregnancy status: {intake_field}")
            return

        valid_values = []
        for value in intake_field:
            if value in fields_flagged:
                valid_values.append(value)

        if len(valid_values) > 0:
            gaps["red_flag_input"].append(f"{FIELDS_MAP[field]}: {", ".join(sorted(valid_values))}")


    def _get_red_flag_fields(self, red_flag_ids: list[int]) -> set[str]:
        """Flat union of the values/field-names all fired flags reference.
    
        NOT filtered by the intake — the caller intersects with the intake when
        building gaps. Value-bearing fields (conditions/symptoms/pregnancy_status)
        come through as their value; vitals come through as the field name.
        """
        fields: set[str] = set()
        if not red_flag_ids:
            return fields
    
        stmt = select(RedFlagRule).where(RedFlagRule.flag_id.in_(red_flag_ids))
        flags = self.db.scalars(stmt).all()
        for flag in flags:
            fields |= self._get_fields_from_tree(flag.trigger_pattern_tree)
        return fields
    
    
    def _get_fields_from_tree(self, node: dict) -> set[str]:
        """Recursively collect values/field-names from a trigger tree.
    
        - group node  -> recurse into each condition
        - helper node -> nothing (no concrete field)
        - field leaf  -> the value(s) for a value-bearing field
                        (conditions/symptoms/pregnancy_status); the field name for a
                        vital; chief_complaint skipped.
        """
        found: set[str] = set()
    
        if "op" in node:
            for cond in node["conditions"]:
                found |= self._get_fields_from_tree(cond)
            return found
    
        if "helper" in node:
            return found
    
        field = node["field"]
        if field in EXCLUDED_FIELDS:
            return found
    
        # Value-bearing fields contribute their value(s), regardless of operator:
        #  - pre_existing_conditions / symptoms use contains / contains_any / in
        #  - pregnancy_status uses == ("postpartum") or in (["pregnant","postpartum"])
        # For an `in`/list value, add each; for a scalar (==), add the one value.
        if field in VALUE_FIELDS:
            value = node["value"]
            values = value if isinstance(value, list) else [value]
            found.update(values)
        else:
            # vital (or any other) field — field name only
            found.add(field)
    
        return found