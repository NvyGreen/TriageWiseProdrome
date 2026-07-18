from collections import namedtuple
from datetime import datetime
import heapq

sortKey = namedtuple("sortKey", ["ESIBand", "flagTier", "arrivalTime", "intakeID"])

class PriorityQueue:
    def __init__(self):
        self.heap: list[sortKey] = []
    

    def insert(self, esi_band: int, flag_tier: int, arrival_time: str, intake_id: int, format: str) -> None:
        if format is None:
            timestamp = datetime.fromisoformat(arrival_time)
        else:
            timestamp = datetime.strptime(arrival_time, format)
        
        row = sortKey(esi_band, flag_tier, timestamp, intake_id)
        heapq.heappush(self.heap, row)
    

    def updatePatientPosition(self, esi_band, flag_tier):
        pass


    def peek(self):
        pass


    def orderedIntakeIds(self) -> list[int]:
        heap_copy = self.heap[:]
        result = []
        while len(heap_copy) > 0:
            intake_id = heapq.heappop(heap_copy).intakeID
            result.append(intake_id)

        return result