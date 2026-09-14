"""Test bootstrap.

Environment is configured *before* ``app`` is imported so settings pick it up:
an isolated temp dir, short TTLs, and a small upload cap.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="fctk-test-"))

os.environ.update(
    {
        "TEMP_DIR": str(_TMP),
        "FILE_TTL_SECONDS": "2",
        "CLEANUP_INTERVAL_SECONDS": "1",
        "MAX_UPLOAD_SIZE_MB": "1",
        "CORS_ORIGINS": "http://localhost:5173",
        "TRANSCRIPTION_BACKEND": "faster_whisper",
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services.storage import store  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    store.clear_all()


@pytest.fixture(scope="session", autouse=True)
def _cleanup_tmp_dir():
    yield
    shutil.rmtree(_TMP, ignore_errors=True)
