from dataclasses import dataclass

@dataclass
class Driver:
    rule_id: int
    factor: str
    threshold: str
    weight: int
    patient_value: str
    contribution_pct: int