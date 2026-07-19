from datetime import datetime, timezone
import heapq
from app.services.queue_key import sortKey


class PriorityQueue:
    def __init__(self):
        self.heap: list[sortKey] = []
    

    def insert(self, esi_band: int, flag_tier: int, arrival_time: str, intake_id: int, fmt: str | None = None) -> None:
        if not isinstance(esi_band, int) or isinstance(esi_band, bool) or esi_band < 1 or esi_band > 5:
            raise ValueError("ESI band must be an integer in the range 1-5, inclusive")
        
        if not isinstance(flag_tier, int) or isinstance(flag_tier, bool) or flag_tier < 1 or flag_tier > 3:
            raise ValueError("Flag tier must be an integer in the range 1-3, inclusive")
        
        timestamp = datetime.fromisoformat(arrival_time) if fmt is None else datetime.strptime(arrival_time, fmt)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        
        row = sortKey(esi_band, flag_tier, timestamp.timestamp(), intake_id)
        heapq.heappush(self.heap, row)
    

    def updatePatientPosition(self, intake_id, esi_band, flag_tier):
        raise NotImplementedError("Updating patient position not implemented yet")


    def popHighest(self) -> int:
        if len(self.heap) == 0:
            raise IndexError("Queue is empty")
        record = heapq.heappop(self.heap)
        return record.intakeID


    def orderedIntakeIds(self) -> list[int]:
        heap_copy = self.heap[:]
        result = []
        while len(heap_copy) > 0:
            intake_id = heapq.heappop(heap_copy).intakeID
            result.append(intake_id)

        return result