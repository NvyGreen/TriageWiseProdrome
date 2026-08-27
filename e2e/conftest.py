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


def _wait_until_down(url: str, timeout: float) -> bool:
    """Wait until nothing answers at url — so a restarted backend can rebind 8000."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1):
                pass
        except Exception:
            return True
        time.sleep(0.3)
    return False


def _kill_tree(proc: subprocess.Popen) -> None:
    # Windows-robust: kill the whole process tree (npm -> node, python -> uvicorn).
    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True
    )


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
    )
    try:
        if not _wait_until_up(FRONTEND_URL, timeout=60):
            raise RuntimeError(f"frontend did not start; see {_LOG_DIR / 'e2e_frontend.log'}")
        yield
    finally:
        _kill_tree(proc)
        fe_log.close()


@pytest.fixture(scope="module", autouse=True)
def backend(_e2e_database, frontend):
    """A FRESH backend + scorer per test module, both against the E2E DB.

    The web app only accepts intakes (returns `pending`); the separate scorer
    process claims and scores them out-of-band, so it must run for the queue to
    fill. Both are torn down per module; leftover ZZTEST rows are purged by
    db_cleanup."""
    be_log = open(_LOG_DIR / "e2e_backend.log", "w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8000"],
        cwd=str(BACKEND_DIR), env=_CHILD_ENV, stdout=be_log, stderr=subprocess.STDOUT,
    )
    scorer_log = open(_LOG_DIR / "e2e_scorer.log", "w")
    scorer_proc = subprocess.Popen(
        [sys.executable, "-m", "app.scorer"],
        cwd=str(BACKEND_DIR), env=_CHILD_ENV, stdout=scorer_log, stderr=subprocess.STDOUT,
    )
    try:
        if not _wait_until_up(f"{BACKEND_URL}/intakes/test", timeout=45):
            raise RuntimeError(f"backend did not start; see {_LOG_DIR / 'e2e_backend.log'}")
        yield
    finally:
        _kill_tree(scorer_proc)
        scorer_log.close()
        _kill_tree(proc)
        _wait_until_down(f"{BACKEND_URL}/intakes/test", timeout=10)  # free 8000 for the next module
        be_log.close()


def _purge_test_rows(idempotency_keys: list[str]) -> None:
    """Delete ZZTEST-marked patients (+ dependents) and the given idempotency keys."""
    from sqlalchemy import bindparam, text
    from app.dependencies import SessionLocal

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
    finally:
        session.close()


@pytest.fixture
def db_cleanup():
    """Yield a list to collect idempotency keys; purge test rows on teardown."""
    keys: list[str] = []
    try:
        yield keys
    finally:
        _purge_test_rows(keys)
