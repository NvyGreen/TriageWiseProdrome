from collections import namedtuple
from datetime import datetime

sortKey = namedtuple("sortKey", ["ESIBand", "flagTier", "arrivalTime", "intakeID"])

class NaiveListQueue:
    def __init__(self):
        self.queue: list[sortKey] = []
    

    def insert(self, intake_id: int, esi_band: int, flag_tier: int, arrival_time: str, format: str | None = None) -> None:
        if format is None:
            timestamp = datetime.fromisoformat(arrival_time)
        else:
            timestamp = datetime.strptime(arrival_time, format)
        
        row = sortKey(esi_band, flag_tier, timestamp, intake_id)
        self.queue.append(row)
    

    def popHighest(self):
        self.queue.sort()
        return self.queue.pop(0)

    
    def orderedIntakeIds(self):
        self.queue.sort()
        result = []
        for row in self.queue:
            result.append(row.intakeID)