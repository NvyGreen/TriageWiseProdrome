class Result:
    def __init__(self, intake_id: int | None = None, severity_score: int | None = None, queue_placement: int | None = None):
        self.intake_id = intake_id
        self.severity_score = severity_score
        self.queue_placement = queue_placement