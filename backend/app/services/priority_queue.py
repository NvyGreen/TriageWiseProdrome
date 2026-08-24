from datetime import datetime
import heapq
import threading
from app.services.queue_key import SortKey


class PriorityQueue:
    def __init__(self):
        self.heap: list[SortKey] = []
        # Re-entrant: public methods call each other (e.g. insert -> getIntakePosition,
        # remove -> _find_index_from_intake_id), so the same thread must be able to
        # re-acquire. Serializes all heap mutations/reads so concurrent inserts,
        # updates, and removes can't interleave and corrupt the heap.
        self._lock = threading.RLock()


    def insert(self, esi_band: int, flag_tier: int, arrival_time: datetime, intake_id: int) -> int:
        if not isinstance(esi_band, int) or isinstance(esi_band, bool) or esi_band < 1 or esi_band > 5:
            raise ValueError("ESI band must be an integer in the range 1-5, inclusive")

        if not isinstance(flag_tier, int) or isinstance(flag_tier, bool) or flag_tier < 1 or flag_tier > 3:
            raise ValueError("Flag tier must be an integer in the range 1-3, inclusive")

        with self._lock:
            row = SortKey(esi_band, flag_tier, arrival_time.timestamp(), intake_id)
            heapq.heappush(self.heap, row)
            return self.getIntakePosition(intake_id)


    def updatePatientPosition(self, intake_id: int, esi_band: int, flag_tier: int) -> tuple[int, int]:
        with self._lock:
            update_index = self._find_index_from_intake_id(intake_id)
            old_position = self.getIntakePosition(intake_id)

            if update_index == 0:
                heapq.heapreplace(self.heap, SortKey(esi_band, flag_tier, self.heap[update_index].arrival_epoch, intake_id))
                new_position = self.getIntakePosition(intake_id)
                return old_position, new_position

            self.heap[update_index].esi_band = esi_band
            self.heap[update_index].flag_tier = flag_tier

            parent_index = (update_index - 1) // 2
            if update_index > 0 and self.heap[update_index] < self.heap[parent_index]:
                self._sift_up(update_index)
            else:
                self._sift_down(update_index)

            new_position = self.getIntakePosition(intake_id)
            return old_position, new_position


    def remove(self, intake_id):
        with self._lock:
            remove_index = self._find_index_from_intake_id(intake_id)

            last_index = len(self.heap) - 1
            if remove_index == 0:
                record = heapq.heappop(self.heap)
                return record.intake_id
            elif remove_index == last_index:
                record = self.heap.pop()
                return record.intake_id

            moved_element = self.heap[last_index]
            self.heap[remove_index] = moved_element
            self.heap.pop()

            parent_index = (remove_index - 1) // 2
            if remove_index > 0 and self.heap[remove_index] < self.heap[parent_index]:
                self._sift_up(remove_index)
            else:
                self._sift_down(remove_index)

            return intake_id


    def popHighest(self) -> int:
        with self._lock:
            if len(self.heap) == 0:
                raise IndexError("Queue is empty")
            record = heapq.heappop(self.heap)
            return record.intake_id


    def orderedIntakeIds(self) -> list[int]:
        with self._lock:
            heap_copy = self.heap[:]
        result = []
        while len(heap_copy) > 0:
            intake_id = heapq.heappop(heap_copy).intake_id
            result.append(intake_id)

        return result


    def getIntakePosition(self, intake_id: int) -> int:
        # Position = 1 + the number of entries that rank strictly ahead. A direct
        # O(n) count over the heap, instead of copying + draining the whole heap
        # into sorted order (O(n log n)) on every insert/update. SortKey is a
        # total order (unique intake_id tiebreak), so this equals the sorted rank.
        with self._lock:
            target = next((row for row in self.heap if row.intake_id == intake_id), None)
            if target is None:
                raise ValueError(f"{intake_id} not in queue")
            return 1 + sum(1 for row in self.heap if row < target)


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


    def _find_index_from_intake_id(self, intake_id: int) -> int:
        with self._lock:
            for i in range(len(self.heap)):
                if self.heap[i].intake_id == intake_id:
                    return i

        raise ValueError(f"{intake_id} not in queue")
