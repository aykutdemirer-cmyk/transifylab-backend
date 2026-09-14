"""Files router: info / download / delete / expiry."""
from __future__ import annotations

import time

from app.schemas import JobKind
from app.services.storage import store


def _make_job():
    job = store.create(JobKind.text_to_pdf)
    dst = job.dir / "doc.pdf"
    dst.write_bytes(b"%PDF-1.4 test")
    store.attach_file(job, "pdf", dst, "doc.pdf")
    return job


def test_job_info_and_download(client):
    job = _make_job()
    info = client.get(f"/api/v1/files/{job.job_id}")
    assert info.status_code == 200
    assert info.json()["files"][0]["format"] == "pdf"

    dl = client.get(f"/api/v1/files/{job.job_id}/download")
    assert dl.status_code == 200
    assert dl.content == b"%PDF-1.4 test"


def test_download_unknown_format_404(client):
    job = _make_job()
    r = client.get(f"/api/v1/files/{job.job_id}/download", params={"format": "docx"})
    assert r.status_code == 404


def test_delete_job(client):
    job = _make_job()
    r = client.delete(f"/api/v1/files/{job.job_id}")
    assert r.status_code == 204
    assert client.get(f"/api/v1/files/{job.job_id}").status_code == 404


def test_expired_job_not_downloadable(client):
    job = _make_job()
    job.expires_at = time.time() - 1
    r = client.get(f"/api/v1/files/{job.job_id}/download")
    assert r.status_code == 404
