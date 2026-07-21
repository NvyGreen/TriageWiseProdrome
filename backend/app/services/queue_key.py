from dataclasses import dataclass


@dataclass(order=True)
class SortKey:
    esi_band: int
    flag_tier: int
    arrival_epoch: float
    intake_id: int