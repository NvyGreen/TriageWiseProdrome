"""E2E fixtures: start/stop the backend + scorer + frontend against a dedicated
E2E database.

This suite is deliberately OUTSIDE backend/tests, so it does NOT pick up that
package's conftest. It provisions and runs against its OWN `<db>_e2e` database
(created/migrated/seeded below), separate from both the real DB and the unit-test
`_test` DB, so the suites never collide. Tests still mark their rows (name starts
with 'ZZTEST') and db_cleanup removes them between tests.

Run manually from the project root:  pytest e2e/
Not part of the backend `pytest` run (that has testpaths = tests) and not wired
into CI.
"""
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"

BACKEND_URL = "http://127.0.0.1:8000"       # matches frontend/.env VITE_API_BASE_URL
FRONTEND_URL = "http://localhost:5173"      # origin allowed by backend CORS

# Backend must be importable (this dir isn't on the path by default).
sys.path.insert(0, str(BACKEND_DIR))

# Repoint the whole app at a dedicated E2E database BEFORE app.dependencies builds
# an engine: the launched subprocesses (uvicorn, scorer, alembic, seed) inherit
# this env, and the in-process ZZTEST cleanup's SessionLocal picks it up too.
from app.config import get_settings  # noqa: E402

_base_settings = get_settings()
E2E_DB = (
    _base_settings.DB_NAME
    if _base_settings.DB_NAME.endswith("_e2e")
    else f"{_base_settings.DB_NAME}_e2e"
)
_DB_SERVER = dict(
    user=_base_settings.DB_USER,
    password=_base_settings.DB_PASSWORD,
    host=_base_settings.DB_HOST,
    port=_base_settings.DB_PORT,
)
os.environ["DB_NAME"] = E2E_DB
get_settings.cache_clear()

# Subprocesses run from backend/ and must be able to `import app` (the seed script
# doesn't fix sys.path itself); they inherit the DB_NAME override above.
_CHILD_ENV = {
    **os.environ,
    "PYTHONPATH": os.pathsep.join(
        [str(BACKEND_DIR), os.environ.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep),
}

_LOG_DIR = Path(tempfile.gettempdir())


def _wait_until_up(url: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status < 500:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _kill_tree(proc: subprocess.Popen) -> None:
    # Kill the whole process tree (npm -> node, python -> uvicorn), not just the
    # launcher, so the child servers don't outlive the fixture and hold their port.
    if os.name == "nt":
        # Windows: taskkill /T walks the PID tree.
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True
        )
    else:
        # POSIX: the children share the session/process group created by
        # start_new_session=True, so one signal to the group takes them all down.
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass  # already exited


@pytest.fixture(scope="session", autouse=True)
def _e2e_database():
    """Create (if missing), migrate, and seed the dedicated `<db>_e2e` database.

    Mirrors backend/tests/conftest, but against a separate name so it never
    collides with the unit-test DB. The seed script truncates + reloads, so
    re-running each session is safe. Runs before the backend fixture starts."""
    import psycopg2
    from psycopg2 import sql

    # 1. Create the E2E database if missing (via the always-present 'postgres' DB).
    conn = psycopg2.connect(dbname="postgres", **_DB_SERVER)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (E2E_DB,))
            if cur.fetchone() is None:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(E2E_DB)))
    finally:
        conn.close()

    # 2. Build the schema (alembic/env.py targets E2E_DB via the inherited env).
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(BACKEND_DIR), env=_CHILD_ENV, check=True,
    )
    # 3. Load the reference tables (truncates + reloads, so safe to re-run).
    subprocess.run(
        [sys.executable, "scripts/load_reference_data.py"],
        cwd=str(BACKEND_DIR), env=_CHILD_ENV, check=True,
    )
    yield


@pytest.fixture(scope="session", autouse=True)
def frontend():
    """Vite dev server for the whole session (stateless SPA, no per-test reset)."""
    fe_log = open(_LOG_DIR / "e2e_frontend.log", "w")
    proc = subprocess.Popen(
        "npm run dev", cwd=str(FRONTEND_DIR), shell=True,
        stdout=fe_log, stderr=subprocess.STDOUT,
        start_new_session=True,  # own process group so _kill_tree can killpg it (POSIX)
    )
    try:
        if not _wait_until_up(FRONTEND_URL, timeout=60):
            raise RuntimeError(f"frontend did not start; see {_LOG_DIR / 'e2e_frontend.log'}")
        yield
    finally:
        _kill_tree(proc)
        fe_log.close()


@pytest.fixture(scope="session", autouse=True)
def backend(_e2e_database, frontend):
    """The backend + scorer for the whole session, both against the E2E DB.

    The web app only accepts intakes (returns `pending`); the separate scorer
    process claims and scores them out-of-band, so it must run for the queue to
    fill. Started ONCE for the session: per-test isolation comes from db_cleanup
    purging ZZTEST rows (at setup and teardown), not from restarting these — so
    port 8000 is bound once and there's no per-module rebind to wait out."""
    be_log = open(_LOG_DIR / "e2e_backend.log", "w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8000"],
        cwd=str(BACKEND_DIR), env=_CHILD_ENV, stdout=be_log, stderr=subprocess.STDOUT,
        start_new_session=True,  # own process group so _kill_tree can killpg it (POSIX)
    )
    scorer_log = open(_LOG_DIR / "e2e_scorer.log", "w")
    scorer_proc = subprocess.Popen(
        [sys.executable, "-m", "app.scorer"],
        cwd=str(BACKEND_DIR), env=_CHILD_ENV, stdout=scorer_log, stderr=subprocess.STDOUT,
        start_new_session=True,  # own process group so _kill_tree can killpg it (POSIX)
    )
    try:
        if not _wait_until_up(f"{BACKEND_URL}/intakes/test", timeout=45):
            raise RuntimeError(f"backend did not start; see {_LOG_DIR / 'e2e_backend.log'}")
        yield
    finally:
        _kill_tree(scorer_proc)
        scorer_log.close()
        _kill_tree(proc)
        be_log.close()


def _purge_test_rows(idempotency_keys: list[str]) -> None:
    """Delete ZZTEST-marked patients (+ dependents) and the given idempotency keys.

    Retries on deadlock (SQLSTATE 40P01): teardown can race the scorer, which may
    hold a just-claimed intake_record row inside its scoring transaction while the
    cleanup DELETE wants that same row. The deadlock is transient — the scorer
    commits within a moment — so a short backoff-and-retry clears it."""
    from sqlalchemy import bindparam, text
    from sqlalchemy.exc import OperationalError
    from app.dependencies import SessionLocal

    for attempt in range(5):
        session = SessionLocal()
        try:
            ids = [r[0] for r in session.execute(
                text("SELECT patient_id FROM patient WHERE name LIKE 'ZZTEST%'")
            )]
            if ids:
                # event_log FK is ON DELETE SET NULL, so delete these explicitly first.
                session.execute(
                    text("DELETE FROM event_log WHERE patient_id IN :ids").bindparams(
                        bindparam("ids", expanding=True)
                    ),
                    {"ids": ids},
                )
                # Deleting the patient cascades intake_record -> severity -> ai_explanation.
                session.execute(
                    text("DELETE FROM patient WHERE patient_id IN :ids").bindparams(
                        bindparam("ids", expanding=True)
                    ),
                    {"ids": ids},
                )
            for key in idempotency_keys:
                session.execute(
                    text("DELETE FROM idempotency_key WHERE idempotency_key = :k"), {"k": key}
                )
            session.commit()
            return
        except OperationalError as exc:
            session.rollback()
            is_deadlock = getattr(exc.orig, "pgcode", None) == "40P01"
            if not is_deadlock or attempt == 4:
                raise
            time.sleep(0.5)
        finally:
            session.close()


@pytest.fixture
def wait_for_scored():
    """Return a poller that blocks until N ZZTEST intakes reach scoring_status
    'scored'. A DB state check (not a page-reload deadline), so a test waits on
    the scorer actually finishing. Also keeps teardown from racing an in-flight
    scoring transaction, which can deadlock the cleanup DELETE."""
    from sqlalchemy import text
    from app.dependencies import SessionLocal

    def _wait(count: int, timeout_s: float = 30.0) -> None:
        deadline = time.monotonic() + timeout_s
        n = 0
        while time.monotonic() < deadline:
            session = SessionLocal()
            try:
                n = session.execute(text(
                    "SELECT COUNT(*) FROM intake_record ir "
                    "JOIN patient p ON p.patient_id = ir.patient_id "
                    "WHERE p.name LIKE 'ZZTEST%' AND ir.scoring_status = 'scored'"
                )).scalar()
            finally:
                session.close()
            if n >= count:
                return
            time.sleep(0.5)
        raise AssertionError(
            f"only {n}/{count} ZZTEST intakes scored within {timeout_s}s"
        )

    return _wait


@pytest.fixture
def db_cleanup():
    """Yield a list to collect idempotency keys; purge test rows on setup AND
    teardown. The setup purge clears ZZTEST rows left behind by a crashed or
    interrupted prior run, so they can't poison this run's row counts."""
    keys: list[str] = []
    _purge_test_rows([])  # setup: drop stale ZZTEST rows from a prior crash
    try:
        yield keys
    finally:
        _purge_test_rows(keys)
