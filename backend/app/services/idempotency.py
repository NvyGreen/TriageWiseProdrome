"""Idempotency boundary logic for POST /patients (req 1.1b).

Split into two boundary functions the handler calls directly — a dependency
can't do the store half, because it runs *before* the handler produces the
response. `check_idempotency` runs at the top of the handler; `store_idempotency`
runs alongside the final commit so the key row is written in the same
transaction as the patient/intake.

TTL is enforced at read time against `created_at` (the table has no expires_at
column, by design). A key older than IDEMPOTENCY_TTL is treated as absent, and
`store_idempotency` upserts so reusing it overwrites the stale row.
"""
import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.idempotency_key import IdempotencyKey
from app.schemas.intake_create import IntakeCreate

# How long a stored key stays authoritative. Retries within this window replay;
# after it, the key is fresh again.
IDEMPOTENCY_TTL = timedelta(hours=24)


class DuplicateRequestException(Exception):
    """Same Idempotency-Key reused with a different payload -> 409."""


class IdempotencyKeyRequiredException(Exception):
    """No Idempotency-Key header on a request that requires one -> 400."""


def hash_payload(record: IntakeCreate) -> str:
    """SHA-256 of the canonicalized *validated* model (64 hex chars).

    Hashing the validated model (not raw bytes) makes the hash independent of
    key order / whitespace, so a genuine retry of the same intake matches.
    """
    canonical = json.dumps(
        record.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def check_idempotency(
    key: str | None, request_hash: str, db: Session
) -> IdempotencyKey | None:
    """Boundary pre-check. Runs before any domain logic.

    Returns the stored row when the caller should replay it; returns None when
    the caller should process normally (no key on record, or the key expired).
    Raises IdempotencyKeyRequiredException (missing header) or
    DuplicateRequestException (same key, different payload).
    """
    if not key:
        raise IdempotencyKeyRequiredException()

    row = db.get(IdempotencyKey, key)
    if row is None:
        return None

    # Outside the TTL window -> treat as absent; store_idempotency will upsert.
    if row.created_at < datetime.now(timezone.utc) - IDEMPOTENCY_TTL:
        return None

    if row.request_hash == request_hash:
        return row  # safe retry -> caller replays the original response

    raise DuplicateRequestException()  # same key, different body


def store_idempotency(
    key: str,
    request_hash: str,
    response_body: dict,
    status_code: int,
    db: Session,
) -> None:
    """Persist (or refresh) the key -> response mapping in the caller's transaction.

    Upsert so a key reused after its TTL expires overwrites the stale row
    instead of colliding on the primary key; created_at resets, restarting the
    window. Does not commit — the caller commits alongside the domain writes.
    """
    stmt = (
        pg_insert(IdempotencyKey)
        .values(
            idempotency_key=key,
            request_hash=request_hash,
            response_body=response_body,
            status_code=status_code,
        )
        .on_conflict_do_update(
            index_elements=[IdempotencyKey.idempotency_key],
            set_={
                "request_hash": request_hash,
                "response_body": response_body,
                "status_code": status_code,
                "created_at": func.now(),
            },
        )
    )
    db.execute(stmt)
