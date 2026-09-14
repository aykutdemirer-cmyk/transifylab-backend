"""Pydantic response/request models shared across routers."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class JobKind(str, Enum):
    pdf_to_word = "pdf_to_word"
    docx_to_pdf = "docx_to_pdf"
    text_to_pdf = "text_to_pdf"
    transcription = "transcription"


class JobStatus(str, Enum):
    completed = "completed"
    failed = "failed"


class JobResult(BaseModel):
    """Returned by every conversion/transcription endpoint."""

    job_id: str
    kind: JobKind
    status: JobStatus = JobStatus.completed
    filename: str = Field(description="Suggested download filename for the output.")
    size_bytes: int
    download_url: str
    expires_at: datetime
    detail: str | None = None


class TranscriptionSegment(BaseModel):
    index: int
    start: float
    end: float
    text: str
    speaker: str | None = None


class TranscriptionResult(BaseModel):
    job_id: str
    language: str
    duration: float
    text: str
    segments: list[TranscriptionSegment]
    backend: str
    model: str | None = None
    speaker_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    # Download links for the same result rendered in each format.
    downloads: dict[str, str]
    expires_at: datetime


class HealthResponse(BaseModel):
    status: str = "ok"
    app: str
    version: str
    transcription_backend: str
    features: dict[str, bool]


class ErrorResponse(BaseModel):
    detail: str
