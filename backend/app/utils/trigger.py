from dataclasses import dataclass

@dataclass
class Trigger:
    flag_id: int
    trigger_pattern: str
    trigger_pattern_tree: dict
    flag_type: str
    flag_tier: int
    message: str
    rationale: str