from dataclasses import dataclass


@dataclass
class Result:
    intake_id: int | None = None
    severity_score: int | None = None
    queue_placement: int | None = None