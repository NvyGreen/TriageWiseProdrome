import logging

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from fastapi.exceptions import HTTPException

from ..models.scoring_rule import ScoringRule
from ..models.esi_band import ESIBand
from ..models.red_flag_rule import RedFlagRule
from ..utils.enums import ESILevels
from ..utils.constants import ESI_THRESHOLDS, LABEL_MAP
from .red_flag_layer import BORDERLINE


logger = logging.getLogger(__name__)

# Helpers encapsulate their own logic, so they add no field-comparison leaves to a
# trigger tree — surface the intake fields each helper actually inspects so a
# helper-driven rule reads as substantive, not empty. Sourced from RedFlagLayer
# where possible (count_borderline_vitals / all_vitals_normal both use BORDERLINE),
# so the two stay in sync.
HELPER_FIELDS = {
    "count_borderline_vitals": sorted(BORDERLINE),
    "all_vitals_normal": sorted(set(BORDERLINE) | {"oxygen_saturation"}),
    "age_in_years": ["date_of_birth"],
    "age_in_days": ["date_of_birth"],
}


class RulesInfoService:
    def __init__(self, db: Session):
        self.db = db


    def scoring_rules(self) -> dict[str, list]:
        try:
            stmt = select(ScoringRule)
            rules = self.db.scalars(stmt).all()
        except SQLAlchemyError as e:
            logger.exception("Fetching scoring rules failed")
            raise HTTPException(status_code=500) from e
    
        response = {
            "complaint": [],
            "vital": [],
            "age": [],
            "total_rules": len(rules),
            "active_rules": 0
        }
        for raw_rule in rules:
            if raw_rule.rule_type == "complaint":
                rule = {
                    "weight": raw_rule.weight,
                    "complaint_group": raw_rule.complaint_group,
                    "resource_level": raw_rule.resource_level,
                    "esi_anchor": raw_rule.esi_anchor
                }
            elif raw_rule.rule_type == "vital" or raw_rule.rule_type == "age":
                rule = {
                    "weight": raw_rule.weight,
                    "factor": raw_rule.factor,
                    "min_bound": raw_rule.min_bound,
                    "max_bound": raw_rule.max_bound,
                    "units": raw_rule.units
                }
            else:
                logger.error(f"Unrecognized rule type: {raw_rule.rule_type}")
                raise HTTPException(status_code=500)
    
            response[raw_rule.rule_type].append(rule)
            if raw_rule.is_active:
                response["active_rules"] += 1
    
        return response


    def esi_bands(self) -> list[dict]:
        try:
            stmt = select(ESIBand)
            bands = self.db.scalars(stmt).all()
        except SQLAlchemyError as e:
            logger.exception("Fetching ESI bands failed")
            raise HTTPException(status_code=500) from e
    
        response = []
        for raw_band in bands:
            band = {
                "esi_level": raw_band.esi_level,
                "min_points": raw_band.min_points,
                "max_points": raw_band.max_points,
                "label": LABEL_MAP[raw_band.esi_level]
            }
            response.append(band)
    
        return response


    def red_flag_rules(self) -> dict[str, list]:
        try:
            stmt = select(RedFlagRule)
            flags = self.db.scalars(stmt).all()
        except SQLAlchemyError as e:
            logger.exception("Fetching red flag rules failed")
            raise HTTPException(status_code=500) from e

        response = {
            "Tier 1": [],
            "Tier 2": []
        }
        for raw_flag in flags:
            if raw_flag.flag_tier < 1 or raw_flag.flag_tier > 2:
                logger.error(f"Tier {raw_flag.flag_tier} not a valid tier")
                raise HTTPException(status_code=500)
            
            tree_summary = self._summarize_tree(raw_flag.trigger_pattern_tree)
            flag = {
                "message": raw_flag.message,
                "rationale": raw_flag.rationale,
                "flag_tier": raw_flag.flag_tier,
                "depth": tree_summary["depth"],
                "fields": tree_summary["fields"],
                "helpers": tree_summary["helpers"]
            }

            response[f"Tier {raw_flag.flag_tier}"].append(flag)

        return response


    def complaint_esi(self) -> list[dict]:
        try:
            stmt = select(ScoringRule).where(ScoringRule.rule_type == "complaint")
            complaint_rules = self.db.scalars(stmt).all()
        except SQLAlchemyError as e:
            logger.exception("Failed to fetch complaint rules")
            raise HTTPException(status_code=500) from e

        response = []
        for rule in complaint_rules:
            if rule.weight >= ESI_THRESHOLDS["ESI-1"]:
                esi_level = ESILevels.ESI_1
            elif rule.weight >= ESI_THRESHOLDS["ESI-2"]:
                esi_level = ESILevels.ESI_2
            elif rule.weight >= ESI_THRESHOLDS["ESI-3"]:
                esi_level = ESILevels.ESI_3
            elif rule.weight >= ESI_THRESHOLDS["ESI-4"]:
                esi_level = ESILevels.ESI_4
            else:
                esi_level = ESILevels.ESI_5

            if esi_level == ESILevels.ESI_3:
                if rule.resource_level == "one":
                    esi_level = ESILevels.ESI_4
                elif rule.resource_level == "none":
                    esi_level = ESILevels.ESI_5

            result = {
                "complaint": rule.complaint_group,
                "points": rule.weight,
                "esi": esi_level
            }
            response.append(result)

        return response


    def _summarize_tree(self, tree: dict) -> dict:
        """Summarize a red-flag trigger_pattern_tree for display:

            - depth:   levels of nested AND/OR operators (a bare field/helper is 0)
            - fields:  intake fields the rule inspects (field-comparison leaves)
            - helpers: computed helpers the rule calls (age_in_days, all_vitals_normal, ...)

        Mirrors the node shapes the RedFlagLayer parser walks: an operator node
        {"op", "conditions"}, a helper leaf {"helper", ...}, or a field leaf
        {"field", ...}. Defensive against malformed/None nodes so a bad tree can't
        crash the read-only endpoint.
        """
        fields: set[str] = set()
        helpers: set[str] = set()

        def visit(node) -> int:
            if not isinstance(node, dict):
                return 0
            if node.get("op"):
                # one AND/OR level, plus the deepest branch beneath it
                depths = [visit(child) for child in node.get("conditions", [])]
                return 1 + max(depths, default=0)
            if node.get("helper"):
                name = node["helper"]
                helpers.add(name)
                # a helper's logic is opaque to the tree; surface what it inspects
                fields.update(HELPER_FIELDS.get(name, ()))
                return 0
            if node.get("field"):
                fields.add(node["field"])
                return 0
            return 0

        return {
            "depth": visit(tree),
            "fields": sorted(fields),
            "helpers": sorted(helpers),
        }