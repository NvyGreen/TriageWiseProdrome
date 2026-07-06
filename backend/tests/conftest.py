"""Shared pytest fixtures and test environment setup.

The application's ``Settings`` (see ``app/config.py``) requires the six
env vars below and has no defaults, so they must be present *before* the
``app`` package is imported. We set dummy values here at collection time.
No real database is contacted by the current test suite.
"""
import os

# Must run before any `from app...` import happens (i.e. before the imports below).
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DB_USER", "test_user")
os.environ.setdefault("DB_PASSWORD", "test_password")
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "test_db")

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


@pytest.fixture
def client():
    """A FastAPI TestClient for exercising the API in tests."""
    # get_settings() is lru_cached; clear it so tests always see the env
    # values set above rather than a stale cached Settings instance.
    get_settings.cache_clear()
    with TestClient(app) as test_client:
        yield test_client
