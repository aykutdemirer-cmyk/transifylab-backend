"""Document conversion endpoints."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.schemas import JobKind, JobResult, JobStatus
from app.services import document_service as docs
from app.services.storage import Job, store
from app.uploads import save_upload, validate_extension

logger = logging.getLogger("app.routers.convert")

router = APIRouter(prefix="/api/v1/convert", tags=["convert"])


def _result(job: Job, fmt: str) -> JobResult:
    jf = job.files[fmt]
    return JobResult(
        job_id=job.job_id,
        kind=job.kind,
        status=JobStatus.completed,
        filename=jf.filename,
        size_bytes=jf.size_bytes,
        download_url=f"/api/v1/files/{job.job_id}/download?format={fmt}",
        expires_at=datetime.fromtimestamp(job.expires_at, tz=timezone.utc),
    )


def _handle_conversion_errors(exc: Exception) -> HTTPException:
    if isinstance(exc, docs.FeatureUnavailableError):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    if isinstance(exc, docs.ConversionError):
        return HTTPException(status_code=422, detail=str(exc))
    logger.exception("unexpected conversion failure")
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Conversion failed.")


@router.post("/pdf-to-word", response_model=JobResult)
async def pdf_to_word(file: Annotated[UploadFile, File()]) -> JobResult:
    validate_extension(file, {"pdf"}, label="PDF")
    job = store.create(JobKind.pdf_to_word)
    src = job.dir / "input.pdf"
    await save_upload(file, src)

    stem = Path(file.filename or "document").stem
    dst = job.dir / f"{stem}.docx"
    try:
        import anyio

        await anyio.to_thread.run_sync(docs.pdf_to_word, src, dst)
    except Exception as exc:  # noqa: BLE001
        store.delete(job.job_id)
        raise _handle_conversion_errors(exc) from exc

    store.attach_file(job, "docx", dst, f"{stem}.docx")
    src.unlink(missing_ok=True)
    return _result(job, "docx")


@router.post("/docx-to-pdf", response_model=JobResult)
async def docx_to_pdf(file: Annotated[UploadFile, File()]) -> JobResult:
    validate_extension(file, {"docx"}, label="Word")
    job = store.create(JobKind.docx_to_pdf)
    src = job.dir / "input.docx"
    await save_upload(file, src)

    stem = Path(file.filename or "document").stem
    dst = job.dir / f"{stem}.pdf"
    try:
        import anyio

        await anyio.to_thread.run_sync(docs.docx_to_pdf, src, dst, stem)
    except Exception as exc:  # noqa: BLE001
        store.delete(job.job_id)
        raise _handle_conversion_errors(exc) from exc

    store.attach_file(job, "pdf", dst, f"{stem}.pdf")
    src.unlink(missing_ok=True)
    return _result(job, "pdf")


@router.post("/text-to-pdf", response_model=JobResult)
async def text_to_pdf(
    file: Annotated[UploadFile | None, File()] = None,
    text: Annotated[str | None, Form()] = None,
    filename: Annotated[str | None, Form()] = None,
    title: Annotated[str | None, Form()] = None,
) -> JobResult:
    if file is None and not (text and text.strip()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either a .txt file upload or a non-empty 'text' field.",
        )

    job = store.create(JobKind.text_to_pdf)
    # `title` is what's printed at the top of the PDF; `stem`/`filename` is only
    # the download's file name. Keep them independent — a fallback file name
    # must never silently become a heading the user never typed.
    doc_title = title.strip() if title and title.strip() else None

    if file is not None:
        validate_extension(file, {"txt", "md", "text"}, label="text")
        src = job.dir / "input.txt"
        await save_upload(file, src)
        content = src.read_text(encoding="utf-8", errors="replace")
        src.unlink(missing_ok=True)
        stem = Path(filename).stem if filename else Path(file.filename or "belge").stem
        if doc_title is None:
            doc_title = Path(file.filename or "").stem or None
    else:
        content = text  # type: ignore[assignment]
        stem = Path(filename).stem if filename else "belge"

    dst = job.dir / f"{stem}.pdf"
    try:
        import anyio

        await anyio.to_thread.run_sync(docs.text_to_pdf, content, dst, doc_title)
    except Exception as exc:  # noqa: BLE001
        store.delete(job.job_id)
        raise _handle_conversion_errors(exc) from exc

    store.attach_file(job, "pdf", dst, f"{stem}.pdf")
    return _result(job, "pdf")
