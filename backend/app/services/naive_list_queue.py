from datetime import datetime, timezone
from app.services.queue_key import sortKey


class NaiveListQueue:
    def __init__(self):
        self.queue: list[sortKey] = []
    

    def insert(self, esi_band: int, flag_tier: int, arrival_time: str, intake_id: int, fmt: str | None = None) -> None:
        timestamp = datetime.fromisoformat(arrival_time) if fmt is None else datetime.strptime(arrival_time, fmt)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        
        row = sortKey(esi_band, flag_tier, timestamp.timestamp(), intake_id)
        self.queue.append(row)
    

    def updatePatientPosition(self, intake_id, esi_band, flag_tier):
        raise NotImplementedError("Updating patient position not implemented yet")
    

    def remove(self, intake_id):
        remove_index = -1
        for i in range(len(self.heap)):
            if self.heap[i].intakeID == intake_id:
                remove_index = i
                break
        
        if remove_index == -1:
            raise ValueError(f"{intake_id} not in queue")
        
        self.queue.pop(remove_index)
    

    def popHighest(self) -> int:
        if len(self.queue) == 0:
            raise IndexError("Queue is empty")
        i = min(range(len(self.queue)), key=self.queue.__getitem__)
        return self.queue.pop(i).intakeID

    
    def orderedIntakeIds(self) -> list[int]:
        return [r.intakeID for r in sorted(self.queue)]