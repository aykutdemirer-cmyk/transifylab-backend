"""Transcription via the OpenAI Whisper API."""
from __future__ import annotations

import logging
from pathlib import Path

from app.config import get_settings
from app.services.transcription.base import (
    Segment,
    Transcript,
    TranscriptionError,
    TranscriptionService,
    TranscriptionUnavailableError,
)

logger = logging.getLogger("app.transcription.openai")

_SUPPORTED = {"tr", "en"}


class OpenAIWhisperService(TranscriptionService):
    name = "openai"

    def __init__(self) -> None:
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        s = get_settings()
        if not s.openai_api_key:
            raise TranscriptionUnavailableError(
                "OPENAI_API_KEY is not set; cannot use the OpenAI transcription backend."
            )
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on env
            raise TranscriptionUnavailableError(
                "openai is not installed. Run: pip install openai"
            ) from exc
        self._client = OpenAI(api_key=s.openai_api_key)
        return self._client

    def transcribe(
        self, audio_path: Path, *, language: str | None = None
    ) -> Transcript:
        if language and language.lower() not in _SUPPORTED:
            raise TranscriptionError(
                f"Unsupported language '{language}'. Supported: {sorted(_SUPPORTED)}"
            )
        client = self._get_client()
        model = get_settings().openai_transcribe_model
        try:
            with audio_path.open("rb") as fh:
                resp = client.audio.transcriptions.create(
                    model=model,
                    file=fh,
                    language=language.lower() if language else None,
                    response_format="verbose_json",
                    timestamp_granularities=["segment"],
                )
        except Exception as exc:  # noqa: BLE001
            raise TranscriptionError(f"OpenAI transcription failed: {exc}") from exc

        return _parse_verbose_json(resp, backend=self.name, fallback_lang=language)


def _parse_verbose_json(resp: object, *, backend: str, fallback_lang: str | None) -> Transcript:
    # The SDK returns a pydantic-ish object; normalise via dict access.
    data = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)  # type: ignore
    raw_segments = data.get("segments") or []
    segments: list[Segment] = []
    for i, seg in enumerate(raw_segments, start=1):
        segments.append(
            Segment(
                index=i,
                start=float(seg.get("start", 0.0)),
                end=float(seg.get("end", 0.0)),
                text=str(seg.get("text", "")),
            )
        )
    text = str(data.get("text", "")).strip()
    duration = float(data.get("duration") or (segments[-1].end if segments else 0.0))
    return Transcript(
        language=str(data.get("language") or fallback_lang or "unknown"),
        duration=duration,
        text=text,
        segments=segments,
        backend=backend,
    )
