"""
load_reference_data.py

Loads the project's reference/lookup tables from reference_data/*.csv into the
database. Run AFTER `alembic upgrade head` (migrations create the tables; this
script fills them).

WHAT IT LOADS
-------------
Five reference tables (all standalone lookups, no inter-table FKs):
    scoring_rule        - scoring weights / thresholds / complaint tiers
    red_flag_rule       - red-flag trigger patterns, tiers, messages
    esi_band            - point-range -> ESI level cutoffs
    vital_range         - normal/borderline/abnormal bands per vital
    condition_reference - NHAMCS admit rates (derived; see
                          derive_condition_reference.py)

guideline_snippet is intentionally NOT loaded here — it is Phase-2 / RAG-only.

IDEMPOTENT
----------
Reference tables are config-like. This script TRUNCATEs each table (or deletes
all rows) before loading, so re-running always yields a clean, current state
with no duplicates. Safe to run repeatedly.

USAGE
-----
    python scripts/load_reference_data.py
    python scripts/load_reference_data.py --only scoring_rule vital_range
    python scripts/load_reference_data.py --dir reference_data --dry-run
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

# --- DB wiring -------------------------------------------------------------
# Expects a SQLAlchemy engine/session and the ORM models from the app package.
# Adjust these imports to match your project layout.
try:
    from app.dependencies import engine, SessionLocal            # type: ignore
    from app.models import (                                 # type: ignore
        ScoringRule,
        RedFlagRule,
        ESIBand,
        VitalRange,
        ConditionReference,
    )
except Exception as exc:  # pragma: no cover - import guard for standalone use
    engine = None
    SessionLocal = None
    print(
        "WARNING: could not import app DB models "
        f"({exc}). Wire app.dependencies / app.models to your project, "
        "or run with --dry-run to validate the CSVs only.",
        file=sys.stderr,
    )


# Maps each CSV filename (without extension) to its ORM model.
# Order is arbitrary — these tables have no FKs between them.
TABLE_MAP = {
    "scoring_rule": "ScoringRule",
    "red_flag_rule": "RedFlagRule",
    "esi_band": "ESIBand",
    "vital_range": "VitalRange",
    "condition_reference": "ConditionReference",
}


def _model_for(name: str):
    return {
        "ScoringRule": globals().get("ScoringRule"),
        "RedFlagRule": globals().get("RedFlagRule"),
        "ESIBand": globals().get("ESIBand"),
        "VitalRange": globals().get("VitalRange"),
        "ConditionReference": globals().get("ConditionReference"),
    }[TABLE_MAP[name]]


def _read_csv(path: Path) -> list[dict]:
    """Read a CSV into a list of dict rows, normalizing blanks to None."""
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = []
        for raw in reader:
            row = {k: (v if v not in ("", None) else None) for k, v in raw.items()}
            rows.append(row)
        return rows


def load_table(session, name: str, rows: list[dict]) -> int:
    """Truncate + bulk-insert one reference table. Returns row count."""
    model = _model_for(name)
    if model is None:
        raise RuntimeError(f"No ORM model wired for '{name}'.")
    # idempotent: clear existing reference rows first
    session.query(model).delete()
    objects = [model(**row) for row in rows]
    session.bulk_save_objects(objects)
    return len(objects)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dir",
        type=Path,
        default=Path("reference_data"),
        help="Directory holding the reference CSVs (default: reference_data/)",
    )
    ap.add_argument(
        "--only",
        nargs="*",
        choices=list(TABLE_MAP.keys()),
        help="Load only these tables (default: all five).",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report the CSVs without writing to the DB.",
    )
    args = ap.parse_args()

    targets = args.only or list(TABLE_MAP.keys())

    # Validate CSVs exist and parse
    parsed: dict[str, list[dict]] = {}
    for name in targets:
        path = args.dir / f"{name}.csv"
        if not path.exists():
            sys.exit(f"ERROR: missing reference CSV: {path}")
        parsed[name] = _read_csv(path)
        print(f"parsed {name}: {len(parsed[name])} rows", file=sys.stderr)

    if args.dry_run:
        print("dry-run: no database writes performed.", file=sys.stderr)
        return

    if SessionLocal is None:
        sys.exit(
            "ERROR: DB not wired. Fix app.dependencies/app.models imports, "
            "or use --dry-run."
        )

    session = SessionLocal()
    try:
        total = 0
        for name in targets:
            n = load_table(session, name, parsed[name])
            print(f"loaded {name}: {n} rows", file=sys.stderr)
            total += n
        session.commit()
        print(f"done: {total} rows across {len(targets)} tables.", file=sys.stderr)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()