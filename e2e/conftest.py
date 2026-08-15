"""E2E fixtures: start/stop the real backend + frontend, and clean the real DB.

This suite is deliberately OUTSIDE backend/tests, so it does NOT pick up that
package's conftest (which repoints to the _test DB). It runs the app against the
REAL database — so every test that writes must mark its rows (name starts with
'ZZTEST') and the db_cleanup fixture removes them afterward.

Run manually from the project root:  pytest e2e/
Not part of the backend `pytest` run (that has testpaths = tests) and not wired
into CI.
"""
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

# Backend imports for the real-DB teardown (this dir isn't on the path by default).
sys.path.insert(0, str(BACKEND_DIR))

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
    # Windows-robust: kill the whole process tree (npm -> node, python -> uvicorn).
    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True
    )


@pytest.fixture(scope="session", autouse=True)
def servers():
    """Start the backend (uvicorn) and frontend (vite) for the whole session."""
    be_log = open(_LOG_DIR / "e2e_backend.log", "w")
    fe_log = open(_LOG_DIR / "e2e_frontend.log", "w")

    backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8000"],
        cwd=str(BACKEND_DIR), stdout=be_log, stderr=subprocess.STDOUT,
    )
    frontend = subprocess.Popen(
        "npm run dev", cwd=str(FRONTEND_DIR), shell=True,
        stdout=fe_log, stderr=subprocess.STDOUT,
    )

    try:
        if not _wait_until_up(f"{BACKEND_URL}/intakes/test", timeout=45):
            raise RuntimeError(f"backend did not start; see {_LOG_DIR / 'e2e_backend.log'}")
        if not _wait_until_up(FRONTEND_URL, timeout=60):
            raise RuntimeError(f"frontend did not start; see {_LOG_DIR / 'e2e_frontend.log'}")
        yield
    finally:
        _kill_tree(frontend)
        _kill_tree(backend)
        be_log.close()
        fe_log.close()


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
