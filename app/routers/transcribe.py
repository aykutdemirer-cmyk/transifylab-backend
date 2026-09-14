"""Speech-to-text endpoint."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, status
from fastapi import UploadFile

from app.config import get_settings
from app.schemas import JobKind, TranscriptionResult, TranscriptionSegment
from app.services.storage import store
from app.services.transcription import get_transcription_service
from app.services.transcription.audio import (
    ACCEPTED_EXT,
    AudioDecodeError,
    needs_transcode,
    transcode_to_wav,
)
from app.services.transcription.base import (
    RENDERERS,
    TranscriptionError,
    TranscriptionUnavailableError,
)
from app.services.transcription.diarization import (
    DiarizationError,
    DiarizationUnavailableError,
    assign_speakers,
    get_diarization_service,
)
from app.services.transcription.postprocess import (
    clean_segments_text,
    clean_text,
    drop_hallucinated_segments,
)
from app.uploads import save_upload, validate_extension

logger = logging.getLogger("app.routers.transcribe")

router = APIRouter(prefix="/api/v1", tags=["transcribe"])

AUDIO_EXT = ACCEPTED_EXT
SUPPORTED_LANGS = {"tr", "en"}


@router.post("/transcribe", response_model=TranscriptionResult)
async def transcribe(
    file: Annotated[UploadFile, File()],
    language: Annotated[str | None, Form()] = None,
    formats: Annotated[str, Form()] = "txt,srt,json",
    diarize: Annotated[bool, Form()] = False,
) -> TranscriptionResult:
    settings = get_settings()
    ext = validate_extension(file, AUDIO_EXT, label="audio")

    if language:
        language = language.strip().lower()
        if language in {"", "auto"}:
            language = None
        elif language not in SUPPORTED_LANGS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported language '{language}'. Supported: tr, en (or omit for auto-detect).",
            )

    wanted = [f.strip().lower() for f in formats.split(",") if f.strip()]
    bad = [f for f in wanted if f not in RENDERERS]
    if bad:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown output format(s): {', '.join(bad)}. Valid: txt, srt, json.",
        )
    if not wanted:
        wanted = ["txt"]

    job = store.create(JobKind.transcription)
    audio_path = job.dir / f"audio.{ext}"
    await save_upload(file, audio_path)

    import anyio

    warnings: list[str] = []

    # Always decode to a loudness-normalised 16 kHz mono WAV: it is what Whisper
    # wants anyway, what diarization needs, and the filter chain lifts quiet
    # phone recordings so the VAD doesn't throw the speech away. If it fails for
    # a format Whisper can read natively, fall back to the raw upload.
    wav_path: Path | None = job.dir / "audio_16k.wav"
    try:
        await anyio.to_thread.run_sync(transcode_to_wav, audio_path, wav_path)
    except AudioDecodeError as exc:
        if needs_transcode(ext):
            store.delete(job.job_id)
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        logger.warning("transcode failed for %s, using raw upload: %s", ext, exc)
        wav_path = None
    stt_path = wav_path or audio_path

    service = get_transcription_service()
    try:
        transcript = await anyio.to_thread.run_sync(
            lambda: service.transcribe(stt_path, language=language)
        )
    except TranscriptionUnavailableError as exc:
        store.delete(job.job_id)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except TranscriptionError as exc:
        store.delete(job.job_id)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        store.delete(job.job_id)
        logger.exception("unexpected transcription failure")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Transcription failed.") from exc

    if settings.transcript_cleanup:
        clean_segments_text(transcript.segments)
        dropped = drop_hallucinated_segments(transcript.segments)
        transcript.text = " ".join(s.text for s in transcript.segments).strip()
        transcript.text = clean_text(transcript.text)
        if dropped and not transcript.segments:
            warnings.append(
                "Konuşma tespit edilemedi (ses çok düşük ya da çok kısa olabilir); "
                "yalnızca model uydurması metin çıktı ve atıldı."
            )
        elif dropped:
            warnings.append(f"{dropped} uydurma/altyazı-artığı segment atıldı.")

    if diarize and transcript.segments and wav_path is not None:
        try:
            turns = await anyio.to_thread.run_sync(
                get_diarization_service().diarize, wav_path
            )
            transcript.speaker_count = assign_speakers(transcript.segments, turns)
            if not transcript.speaker_count:
                warnings.append("Konuşmacı ayrımı: farklı konuşmacı tespit edilmedi.")
        except DiarizationUnavailableError as exc:
            warnings.append(str(exc))
        except DiarizationError as exc:
            warnings.append(f"Konuşmacı ayrımı başarısız: {exc}")

    audio_path.unlink(missing_ok=True)
    if wav_path is not None:
        wav_path.unlink(missing_ok=True)

    stem = Path(file.filename or "audio").stem
    downloads: dict[str, str] = {}
    for fmt in wanted:
        rendered = RENDERERS[fmt](transcript)
        out = job.dir / f"{stem}.{fmt}"
        # newline="" so line endings are not rewritten to CRLF on Windows and
        # the file matches the rendered string byte-for-byte.
        with out.open("w", encoding="utf-8", newline="") as fh:
            fh.write(rendered)
        store.attach_file(job, fmt, out, f"{stem}.{fmt}")
        downloads[fmt] = f"/api/v1/files/{job.job_id}/download?format={fmt}"

    return TranscriptionResult(
        job_id=job.job_id,
        language=transcript.language,
        duration=round(transcript.duration, 3),
        text=transcript.text,
        segments=[
            TranscriptionSegment(
                index=s.index, start=s.start, end=s.end, text=s.text.strip(),
                speaker=s.speaker,
            )
            for s in transcript.segments
        ],
        backend=transcript.backend,
        model=settings.fw_model_size if transcript.backend == "faster_whisper" else None,
        speaker_count=transcript.speaker_count,
        warnings=warnings,
        downloads=downloads,
        expires_at=datetime.fromtimestamp(job.expires_at, tz=timezone.utc),
    )
