"""Standalone scoring worker.

Runs as its own process (`python -m app.scorer`), separate from the uvicorn web
workers. The web app only stores intakes as `pending`; this loop claims them and
scores them out-of-band, one at a time, each in a single transaction:

    SELECT ... WHERE scoring_status = 'pending'
    ORDER BY created_at, intake_id
    LIMIT 1 FOR UPDATE SKIP LOCKED

SKIP LOCKED lets several scorer processes each claim a distinct row (run more
processes to use more cores). Claim + score + status all ride one transaction, so
a crash mid-score rolls back (Postgres aborts the dropped connection's txn) and
the row stays `pending` for the next pass — no stuck rows, no recovery job.
"""
import logging
import signal
import time

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from fastapi.exceptions import HTTPException

from .dependencies import SessionLocal
from .models.intake_record import IntakeRecord
from .services.scoring_engine import CannotScoreError
from .services.triage_service import ScoringStatus, TriageService

logger = logging.getLogger(__name__)

POLL_INTERVAL = 0.5  # seconds to wait when nothing is pending

_running = True


def _stop(_signum, _frame):
    global _running
    _running = False


def _mark_terminal(db, intake_id, scoring_status):
    """Best-effort terminal-status write after a rolled-back attempt. Guarded: a
    dead connection must not crash the loop."""
    try:
        TriageService(db).set_scoring_status(intake_id, scoring_status)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Could not mark intake %s as %s", intake_id, scoring_status)


def score_claimed(db, intake_id):
    """Score one intake (already selected/claimed in `db`'s transaction) and commit,
    mapping every failure to a terminal scoring_status. Shared by the poll loop and
    by tests that drive scoring for a specific intake."""
    service = TriageService(db)
    try:
        # scoreIntake only flushes; this transaction (holding the FOR UPDATE lock)
        # stays open through the SCORED mark and commit below.
        service.scoreIntake(intake_id)
        service.set_scoring_status(intake_id, ScoringStatus.SCORED)
        db.commit()
    except CannotScoreError:
        db.rollback()
        _mark_terminal(db, intake_id, ScoringStatus.UNSCOREABLE)
        logger.info("Intake %s unscoreable", intake_id)
    except IntegrityError:
        # Backstop: another scorer already queued this intake (only reachable if a
        # claim is bypassed). The winner owns it; discard this attempt.
        db.rollback()
        logger.info("Intake %s already queued; skipping", intake_id)
    except (SQLAlchemyError, HTTPException):
        db.rollback()
        _mark_terminal(db, intake_id, ScoringStatus.FAILED)
        logger.exception("Scoring intake %s failed", intake_id)
    except Exception:
        # Unexpected: mark FAILED so a poison-pill intake can't block the queue.
        db.rollback()
        _mark_terminal(db, intake_id, ScoringStatus.FAILED)
        logger.exception("Unexpected error scoring intake %s", intake_id)


def claim_and_score_one():
    """Claim the next pending intake and score it in one transaction. Returns True
    if a row was processed, False if none were pending."""
    db = SessionLocal()
    try:
        intake = db.execute(
            select(IntakeRecord)
            .where(IntakeRecord.scoring_status == ScoringStatus.PENDING)
            .order_by(IntakeRecord.created_at, IntakeRecord.intake_id)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).scalar_one_or_none()

        if intake is None:
            db.commit()  # end the read transaction
            return False

        score_claimed(db, intake.intake_id)
        return True
    finally:
        db.close()


def run(poll_interval=POLL_INTERVAL):
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    logger.info("Scorer started (poll %.2fs)", poll_interval)
    while _running:
        try:
            worked = claim_and_score_one()
        except Exception:
            # Claim-query blip (no intake in hand) — log and back off, then retry.
            logger.exception("Scorer claim failed")
            worked = False
        if not worked:
            time.sleep(poll_interval)
    logger.info("Scorer stopped")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    run()
