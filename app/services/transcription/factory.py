"""Selects the active :class:`TranscriptionService` from settings.

Cached per backend name so the (expensive) local model is loaded once.
"""
from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.services.transcription.base import TranscriptionService

_BACKENDS = {"faster_whisper", "openai"}


@lru_cache
def _build(backend: str) -> TranscriptionService:
    if backend == "faster_whisper":
        from app.services.transcription.faster_whisper_service import FasterWhisperService

        return FasterWhisperService()
    if backend == "openai":
        from app.services.transcription.openai_whisper_service import OpenAIWhisperService

        return OpenAIWhisperService()
    raise ValueError(
        f"Unknown TRANSCRIPTION_BACKEND '{backend}'. Valid: {sorted(_BACKENDS)}"
    )


def get_transcription_service() -> TranscriptionService:
    return _build(get_settings().transcription_backend)
