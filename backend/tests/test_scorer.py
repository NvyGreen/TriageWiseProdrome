"""Tests for the scorer's failure-handling paths.

The happy path (SCORED) and the CannotScoreException -> UNSCOREABLE path are
covered by test_endpoints / test_patient_endpoint. These drive score_claimed's
remaining `except` branches by monkeypatching TriageService.score_intake to raise,
then asserting the terminal scoring_status the scorer records.
"""
from datetime import date

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app import scorer
from app.models.intake_record import IntakeRecord
from app.models.patient import Patient
from app.services.triage_service import ScoringStatus, TriageService


def _seed_pending_intake(db):
    """A committed patient + pending intake (chief_complaint is the only required
    non-default field besides patient_id)."""
    patient = Patient(name="ZZTEST Scorer", date_of_birth=date(1980, 1, 1), sex="M")
    db.add(patient)
    db.flush()
    intake = IntakeRecord(patient_id=patient.patient_id, chief_complaint="cardiac")
    db.add(intake)
    db.commit()
    return intake.intake_id


def _status(db, intake_id):
    db.expire_all()  # see the scorer's committed write, not a cached copy
    return db.get(IntakeRecord, intake_id).scoring_status


def test_sqlalchemy_error_marks_failed(db_session, monkeypatch):
    intake_id = _seed_pending_intake(db_session)

    def boom(self, _intake_id):
        raise SQLAlchemyError("db blew up mid-score")

    monkeypatch.setattr(TriageService, "score_intake", boom)
    scorer.score_claimed(db_session, intake_id)

    assert _status(db_session, intake_id) == ScoringStatus.FAILED


def test_unexpected_error_marks_failed(db_session, monkeypatch):
    intake_id = _seed_pending_intake(db_session)

    def boom(self, _intake_id):
        raise ValueError("something unforeseen")

    monkeypatch.setattr(TriageService, "score_intake", boom)
    scorer.score_claimed(db_session, intake_id)

    assert _status(db_session, intake_id) == ScoringStatus.FAILED


def test_integrity_error_skips_and_leaves_pending(db_session, monkeypatch):
    intake_id = _seed_pending_intake(db_session)

    def boom(self, _intake_id):
        raise IntegrityError("insert", {}, Exception("duplicate key"))

    monkeypatch.setattr(TriageService, "score_intake", boom)
    scorer.score_claimed(db_session, intake_id)

    # The winning scorer owns the row; this attempt is discarded, not marked.
    assert _status(db_session, intake_id) == ScoringStatus.PENDING


def test_mark_terminal_swallows_write_failure(db_session, monkeypatch):
    intake_id = _seed_pending_intake(db_session)

    def boom_score(self, _intake_id):
        raise SQLAlchemyError("score failed")

    def boom_status(self, _intake_id, _scoring_status):
        raise SQLAlchemyError("terminal write failed")

    monkeypatch.setattr(TriageService, "score_intake", boom_score)
    monkeypatch.setattr(TriageService, "set_scoring_status", boom_status)

    # _mark_terminal must swallow the write failure — score_claimed does not raise.
    scorer.score_claimed(db_session, intake_id)

    # The terminal write could not land, so the row stays pending; no crash is the point.
    assert _status(db_session, intake_id) == ScoringStatus.PENDING


# --- claim_and_score_one ---------------------------------------------------

def test_claim_and_score_one_scores_a_pending_row(db_session, monkeypatch):
    _seed_pending_intake(db_session)  # guarantees at least one pending row
    claimed = []
    monkeypatch.setattr(scorer, "score_claimed", lambda db, intake_id: claimed.append(intake_id))

    result = scorer.claim_and_score_one()

    assert result is True
    assert claimed  # a pending intake was claimed and handed to score_claimed


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeSession:
    """Minimal stand-in for a SQLAlchemy session, to drive the no-pending branch
    deterministically without depending on the shared _test DB being empty."""
    def __init__(self, value):
        self._value = value
        self.committed = False
        self.closed = False

    def execute(self, _stmt):
        return _FakeResult(self._value)

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


def test_claim_and_score_one_returns_false_when_none_pending(monkeypatch):
    fake = _FakeSession(None)
    monkeypatch.setattr(scorer, "SessionLocal", lambda: fake)

    result = scorer.claim_and_score_one()

    assert result is False
    assert fake.committed  # the empty read transaction is ended
    assert fake.closed


# --- run loop --------------------------------------------------------------

def test_run_loops_until_stopped(monkeypatch):
    monkeypatch.setattr(scorer.signal, "signal", lambda *args, **kwargs: None)
    monkeypatch.setattr(scorer, "_running", True)
    calls = []

    def fake_claim():
        calls.append(1)
        if len(calls) >= 2:
            scorer._running = False  # break the loop after two passes
        return True

    monkeypatch.setattr(scorer, "claim_and_score_one", fake_claim)

    scorer.run(poll_interval=0)

    assert len(calls) == 2


def test_run_swallows_claim_error(monkeypatch):
    monkeypatch.setattr(scorer.signal, "signal", lambda *args, **kwargs: None)
    monkeypatch.setattr(scorer, "_running", True)
    calls = []

    def fake_claim():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("claim query blip")  # caught by run's except
        scorer._running = False
        return False  # also exercises the `if not worked` back-off path

    monkeypatch.setattr(scorer, "claim_and_score_one", fake_claim)

    scorer.run(poll_interval=0)

    assert len(calls) == 2
