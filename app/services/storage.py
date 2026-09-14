"""Temp-file job store.

Every conversion/transcription produces one or more output files that live under
``<TEMP_DIR>/<job_id>/``. The store keeps lightweight metadata in memory and is
the single place that knows where a job's bytes are and when they expire.

In-memory metadata is fine for a single-process utility service; the files
themselves are the source of truth and the startup sweep reconciles the two.
"""
from __future__ import annotations

import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock

from app.config import get_settings
from app.schemas import JobKind


@dataclass
class JobFile:
    fmt: str          # "docx", "pdf", "txt", "srt", "json"
    path: Path
    filename: str     # suggested download name

    @property
    def size_bytes(self) -> int:
        return self.path.stat().st_size if self.path.exists() else 0


@dataclass
class Job:
    job_id: str
    kind: JobKind
    created_at: float
    expires_at: float
    files: dict[str, JobFile] = field(default_factory=dict)

    @property
    def dir(self) -> Path:
        return get_settings().temp_path / self.job_id

    def is_expired(self, now: float | None = None) -> bool:
        return (now or time.time()) >= self.expires_at


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = RLock()

    # -- lifecycle -------------------------------------------------------
    def create(self, kind: JobKind) -> Job:
        settings = get_settings()
        now = time.time()
        job = Job(
            job_id=uuid.uuid4().hex,
            kind=kind,
            created_at=now,
            expires_at=now + settings.file_ttl_seconds,
        )
        job.dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def attach_file(self, job: Job, fmt: str, path: Path, filename: str) -> JobFile:
        jf = JobFile(fmt=fmt, path=path, filename=filename)
        with self._lock:
            job.files[fmt] = jf
        return jf

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def delete(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.pop(job_id, None)
        if job is None:
            return False
        shutil.rmtree(job.dir, ignore_errors=True)
        return True

    # -- maintenance ---------------------------------------------------
    def sweep_expired(self, now: float | None = None) -> int:
        now = now or time.time()
        with self._lock:
            expired = [jid for jid, job in self._jobs.items() if job.is_expired(now)]
        for jid in expired:
            self.delete(jid)
        return len(expired)

    def reconcile_disk(self) -> None:
        """On startup: drop any leftover job directories from a previous run."""
        root = get_settings().temp_path
        root.mkdir(parents=True, exist_ok=True)
        for child in root.iterdir():
            if child.is_dir() and child.name not in self._jobs:
                shutil.rmtree(child, ignore_errors=True)

    def clear_all(self) -> None:
        with self._lock:
            job_ids = list(self._jobs)
        for jid in job_ids:
            self.delete(jid)


store = JobStore()
