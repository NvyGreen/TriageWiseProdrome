"""Shared pytest fixtures and test-database setup.

Tests run against a REAL Postgres (so JSONB, foreign keys, and autoincrement
behave exactly like production), but against a SEPARATE ``*_test`` database so
your real data is never touched.

Connection details come from the same place the app uses:
  - locally: ``backend/.env`` (read by ``app.config.Settings``)
  - in CI:   environment variables set by the workflow

The session-scoped fixture below:
  1. creates the ``<DB_NAME>_test`` database if it doesn't exist,
  2. repoints the app at it (before any engine is built),
  3. runs ``alembic upgrade head`` to build the schema,
  4. loads the reference tables from the committed CSVs.

NOTE: ``app.database`` builds its engine at import time from the settings, so
nothing from ``app.database`` / ``app.main`` may be imported until AFTER the
fixture has repointed ``DB_NAME``. That's why those imports are done lazily
inside the fixtures rather than at module top.
"""
import os
import subprocess
import sys
import json, copy
from pathlib import Path

import pytest

# app.config is safe to import eagerly — it never touches the database.
from app.config import get_settings

BACKEND_ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = Path(__file__).parent / "contracts"


def _test_db_name(base_name: str) -> str:
    """Derive the test database name, avoiding a doubled suffix."""
    return base_name if base_name.endswith("_test") else f"{base_name}_test"


@pytest.fixture(scope="session", autouse=True)
def _database():
    """Create + migrate + seed the test database once per test session."""
    base = get_settings()
    server = dict(
        user=base.DB_USER,
        password=base.DB_PASSWORD,
        host=base.DB_HOST,
        port=base.DB_PORT,
    )
    test_db = _test_db_name(base.DB_NAME)

    # 1. Create the test database if missing (connect to the always-present
    #    'postgres' maintenance database to issue CREATE DATABASE).
    import psycopg2
    from psycopg2 import sql

    conn = psycopg2.connect(dbname="postgres", **server)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (test_db,))
            if cur.fetchone() is None:
                cur.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(test_db))
                )
    finally:
        conn.close()

    # 2. Repoint the whole app at the test DB before any engine is created.
    #    An env var overrides the .env value, and clearing the lru_cache makes
    #    the next get_settings() pick it up.
    os.environ["DB_NAME"] = test_db
    get_settings.cache_clear()

    # Subprocesses run from backend/ and must be able to `import app`; put
    # backend/ on PYTHONPATH so the load script (which doesn't fix sys.path
    # itself) can resolve the app package.
    child_env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [str(BACKEND_ROOT), os.environ.get("PYTHONPATH", "")]
        ).rstrip(os.pathsep),
    }

    # 3. Build the schema via migrations (subprocess inherits the env override,
    #    so alembic/env.py targets the test DB).
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        env=child_env,
        check=True,
    )

    # 4. Load the reference tables (esi_band, condition_reference, ...) from the
    #    committed CSVs. The script truncates + reloads, so it's safe to re-run.
    subprocess.run(
        [sys.executable, "scripts/load_reference_data.py"],
        cwd=BACKEND_ROOT,
        env=child_env,
        check=True,
    )

    yield


@pytest.fixture
def client():
    """A FastAPI TestClient bound to the test database."""
    # Imported lazily so app.database's engine is built only after _database
    # has repointed DB_NAME (see module docstring).
    from app.main import app

    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client

@pytest.fixture
def intake_body():
    data = json.loads((CONTRACTS / "intake_post_body_1_1.json").read_text())
    return copy.deepcopy(data)