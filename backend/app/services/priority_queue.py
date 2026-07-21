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
    

    def remove(self, intake_id):
        remove_index = -1
        for i in range(len(self.heap)):
            if self.heap[i].intakeID == intake_id:
                remove_index = i
                break
        
        if remove_index == -1:
            raise ValueError(f"{intake_id} not in queue")

        last_index = len(self.heap) - 1
        if remove_index == 0:
            record = heapq.heappop(self.heap)
            return record.intakeID
        elif remove_index == last_index:
            record = self.heap.pop()
            return record.intakeID

        moved_element = self.heap[last_index]
        self.heap[remove_index] = moved_element
        self.heap.pop()

        parent_index = (remove_index - 1) // 2
        if remove_index > 0 and self.heap[remove_index] < self.heap[parent_index]:
            self._sift_up(remove_index)
        else:
            self._sift_down(remove_index)


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
    

    def _sift_up(self, i):
        while i > 0:
            parent = (i - 1) // 2
            if self.heap[i] < self.heap[parent]:
                self.heap[i], self.heap[parent] = self.heap[parent], self.heap[i]
                i = parent
            else:
                break
    

    def _sift_down(self, i):
        length = len(self.heap)
        while 2 * i + 1 < length:
            left = 2 * i + 1
            right = 2 * i + 2
            smallest = left

            if right < length and self.heap[right] < self.heap[left]:
                smallest = right
            
            if self.heap[i] > self.heap[smallest]:
                self.heap[i], self.heap[smallest] = self.heap[smallest], self.heap[i]
                i = smallest
            else:
                break