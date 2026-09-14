"""Download / inspect / delete generated job files."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import FileResponse

from app.services.storage import store

router = APIRouter(prefix="/api/v1/files", tags=["files"])

_MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain; charset=utf-8",
    "srt": "application/x-subrip",
    "json": "application/json",
}


def _job_or_404(job_id: str):
    job = store.get(job_id)
    if job is None or job.is_expired():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found or expired.")
    return job


@router.get("/{job_id}")
def job_info(job_id: str) -> dict:
    job = _job_or_404(job_id)
    return {
        "job_id": job.job_id,
        "kind": job.kind,
        "created_at": datetime.fromtimestamp(job.created_at, tz=timezone.utc),
        "expires_at": datetime.fromtimestamp(job.expires_at, tz=timezone.utc),
        "files": [
            {"format": f.fmt, "filename": f.filename, "size_bytes": f.size_bytes}
            for f in job.files.values()
        ],
    }


@router.get("/{job_id}/download")
def download(job_id: str, format: str | None = None) -> FileResponse:
    job = _job_or_404(job_id)
    if not job.files:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job has no output files.")

    fmt = format or next(iter(job.files))
    jf = job.files.get(fmt)
    if jf is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Format '{fmt}' not available. Have: {', '.join(job.files)}",
        )
    if not jf.path.exists():
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="File already cleaned up.")

    return FileResponse(
        path=jf.path,
        media_type=_MEDIA_TYPES.get(fmt, "application/octet-stream"),
        filename=jf.filename,
    )


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(job_id: str) -> Response:
    if not store.delete(job_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
