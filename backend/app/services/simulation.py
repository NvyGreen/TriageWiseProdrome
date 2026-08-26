"""
What-if Simulation (req D3 / build order 58).

Purpose: inject a burst of synthetic arrivals and show how the queue
reprioritises them. This is a DEMO of the queue's ordering logic under a
surge — it is NOT scoring validation and it NEVER touches the live queue
or the database.

Design decisions (per the build discussion):
  - In-memory only. Sim arrivals are generated, sorted, and returned in
    one request. Nothing is persisted, so there is nothing to reset and
    no risk of polluting the real queue.
  - Reuses the REAL sort key — (esi_band, flag_tier, arrival_epoch,
    intake_id) — so the demo reflects the actual prioritisation logic,
    not a re-implementation that could drift.
  - Preset and Custom feed the SAME generator; only the band/flag counts
    differ. A preset is just a named set of counts.

Wire this to a route like  POST /demo/simulate  that takes a SimRequest
and returns the ordered list. The frontend renders the returned order.
"""

import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from ..services.queue_key import SortKey


# Fixed demo clock: arrivals are stamped at this base plus a random offset, so the
# demo shows real (time-only) timestamps. Fixed base + seed => deterministic output,
# which is all a demo needs and keeps the captured test fixture stable.
BASE_EPOCH = datetime(2026, 6, 26, 18, 56, 57, tzinfo=timezone.utc).timestamp()
ARRIVAL_WINDOW_SECONDS = 3600
RNG_SEED = 42


# --- ESI band as an int so it sorts naturally (1 = most acute = first) ---
# If your queue keys off a different representation, map to it here — the
# ordering contract is what matters, not the type.

class FlagTier(IntEnum):
    TIME_CRITICAL = 1   # red  — sorts ahead
    OCCULT = 2          # amber
    NONE = 3            # no flag — sorts last within a band


@dataclass
class SimArrival:
    """One synthetic arrival. Mirrors only the fields the queue sorts on."""
    sim_id: str                 # e.g. "SIM-004" — clearly synthetic
    esi_band: int               # 1..5
    flag_tier: int = FlagTier.NONE
    arrival_epoch: float = 0.0  # tie-break within (band, tier): real arrival time
    flag_label: str | None = None   # display only: "Time-critical" / "Occult risk"


# ----------------------------------------------------------------------
# Presets — named sets of counts. Each entry: how many per ESI band, and
# how many of those carry a red flag (tier). Edit freely; this is config.
# ----------------------------------------------------------------------
# format per band: {"n": total_arrivals, "flags": {tier: how_many}}

PRESETS: dict[str, dict[int, dict]] = {
    "mass_casualty": {
        1: {"n": 3, "flags": {FlagTier.TIME_CRITICAL: 1}},
        2: {"n": 4, "flags": {FlagTier.OCCULT: 1}},
        3: {"n": 2, "flags": {}},
        4: {"n": 1, "flags": {}},
        5: {"n": 0, "flags": {}},
    },
    "cardiac_cluster": {
        1: {"n": 1, "flags": {FlagTier.TIME_CRITICAL: 1}},
        2: {"n": 5, "flags": {FlagTier.OCCULT: 2}},   # several ESI-2, 2 flagged -> shows tie-break
        3: {"n": 2, "flags": {}},
        4: {"n": 0, "flags": {}},
        5: {"n": 0, "flags": {}},
    },
    "quiet_night": {
        1: {"n": 0, "flags": {}},
        2: {"n": 1, "flags": {}},
        3: {"n": 2, "flags": {}},
        4: {"n": 3, "flags": {}},
        5: {"n": 2, "flags": {}},
    },
}


@dataclass
class SimRequest:
    """
    Either name a preset OR pass custom band counts.
    custom_bands: {esi_band: {"n": int, "flags": {tier: count}}}
    """
    preset: str | None = None
    custom_bands: dict[int, dict] | None = None


def _bands_from_request(req: SimRequest) -> dict[int, dict]:
    if req.preset is not None:
        if req.preset not in PRESETS:
            raise ValueError(f"unknown preset: {req.preset}")
        return PRESETS[req.preset]
    if req.custom_bands is not None:
        # Normalize keys to int at both levels. Callers (e.g. the JSON API body,
        # where the inner `flags` dict is untyped) may hand us string keys; the
        # generator looks bands and flag tiers up by int, so coerce here — the one
        # choke point every custom request passes through.
        return {
            int(band): {
                "n": spec.get("n", 0),
                "flags": {int(tier): count for tier, count in spec.get("flags", {}).items()},
            }
            for band, spec in req.custom_bands.items()
        }
    raise ValueError("SimRequest needs either a preset or custom_bands")


def generate_arrivals(req: SimRequest) -> list[SimArrival]:
    """Turn band/flag counts into synthetic arrivals. No persistence.

    Each arrival is stamped with a real epoch (BASE_EPOCH + a random offset within
    ARRIVAL_WINDOW_SECONDS). A locally-seeded RNG keeps this deterministic — same
    input always yields the same times and ordering.

    sim_ids are then assigned in ARRIVAL-TIME order (earliest -> SIM-001), mirroring
    the real queue where a lower id means an earlier arrival. So the id tracks arrival
    time even though the times are random, and intake_id (int of sim_id), used as the
    SortKey tie-break, tracks arrival order too."""
    bands = _bands_from_request(req)
    rng = random.Random(RNG_SEED)
    arrivals: list[SimArrival] = []

    for esi in (1, 2, 3, 4, 5):
        spec = bands.get(esi)
        if not spec:
            continue
        n = spec.get("n", 0)
        flags = dict(spec.get("flags", {}))  # {tier: how_many}, consumed below

        for _ in range(n):
            # assign a flag tier if any remain for this band
            tier = FlagTier.NONE
            label = None
            for t in (FlagTier.TIME_CRITICAL, FlagTier.OCCULT):
                if flags.get(t, 0) > 0:
                    tier = t
                    flags[t] -= 1
                    label = "Time-critical" if t == FlagTier.TIME_CRITICAL else "Occult risk"
                    break
            arrivals.append(SimArrival(
                sim_id="",  # assigned below, in arrival-time order
                esi_band=esi,
                flag_tier=int(tier),
                arrival_epoch=BASE_EPOCH + rng.randint(0, ARRIVAL_WINDOW_SECONDS),
                flag_label=label,
            ))

    # Number by arrival time (stable sort keeps generation order for equal epochs).
    arrivals.sort(key=lambda a: a.arrival_epoch)
    for i, arrival in enumerate(arrivals, start=1):
        arrival.sim_id = f"SIM-{i:03d}"
    return arrivals


def order_queue(arrivals: list[SimArrival]) -> list[SimArrival]:
    """
    Sort by the production SortKey (esi_band, flag_tier, arrival_epoch, intake_id)
    so the demo can't drift from the real prioritisation logic. Lower is more
    urgent / earlier; intake_id (derived from sim_id) is the stable final tie-break
    when two arrivals draw the same epoch.
    """
    return sorted(
        arrivals,
        key=lambda a: SortKey(
            a.esi_band, a.flag_tier, a.arrival_epoch, int(a.sim_id.removeprefix("SIM-"))
        ),
    )


def run_simulation(req: SimRequest) -> list[dict]:
    """
    Entry point for the route. Returns display-ready rows in queue order.
    Nothing is saved.
    """
    ordered = order_queue(generate_arrivals(req))
    return [
        {
            "position": i + 1,
            "sim_id": a.sim_id,
            "esi_band": a.esi_band,
            "flag_tier": a.flag_tier if a.flag_tier != FlagTier.NONE else None,
            "arrival_epoch": a.arrival_epoch,
            "flag_label": a.flag_label,
        }
        for i, a in enumerate(ordered)
    ]
