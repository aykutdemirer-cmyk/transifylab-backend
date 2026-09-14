"""Job store + cleanup behaviour."""
from __future__ import annotations

import time

import pytest

from app.schemas import JobKind
from app.services.cleanup import cleanup_loop
from app.services.storage import store


def test_create_attach_get_delete(tmp_path):
    job = store.create(JobKind.text_to_pdf)
    assert job.dir.is_dir()
    f = tmp_path / "out.pdf"
    f.write_bytes(b"%PDF-1.4")
    # copy into job dir the way routes do
    dst = job.dir / "out.pdf"
    dst.write_bytes(f.read_bytes())
    store.attach_file(job, "pdf", dst, "out.pdf")

    got = store.get(job.job_id)
    assert got is not None and "pdf" in got.files

    assert store.delete(job.job_id) is True
    assert store.get(job.job_id) is None
    assert not job.dir.exists()


def test_sweep_expired_removes_only_old_jobs():
    fresh = store.create(JobKind.transcription)
    stale = store.create(JobKind.transcription)
    stale.expires_at = time.time() - 1  # force-expire

    removed = store.sweep_expired()
    assert removed >= 1
    assert store.get(stale.job_id) is None
    assert store.get(fresh.job_id) is not None
    store.delete(fresh.job_id)


@pytest.mark.asyncio
async def test_cleanup_loop_runs_a_sweep_and_stops():
    import asyncio

    stale = store.create(JobKind.transcription)
    stale.expires_at = time.time() - 1

    stop = asyncio.Event()
    task = asyncio.create_task(cleanup_loop(stop))
    await asyncio.sleep(1.4)  # CLEANUP_INTERVAL_SECONDS=1 in tests
    stop.set()
    await asyncio.wait_for(task, timeout=2)

    assert store.get(stale.job_id) is None
