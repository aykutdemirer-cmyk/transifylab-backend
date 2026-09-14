"""Local, offline transcription via faster-whisper (CTranslate2)."""
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

logger = logging.getLogger("app.transcription.faster_whisper")

_SUPPORTED = {"tr", "en"}


class FasterWhisperService(TranscriptionService):
    name = "faster_whisper"

    def __init__(self) -> None:
        self._model = None  # lazily loaded on first use

    def _get_model(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on env
            raise TranscriptionUnavailableError(
                "faster-whisper is not installed. Run: pip install faster-whisper"
            ) from exc

        s = get_settings()
        logger.info(
            "loading faster-whisper model=%s device=%s compute=%s",
            s.fw_model_size, s.fw_device, s.fw_compute_type,
        )
        # Render ücretsiz planın 512 MB RAM sınırını korumak için cpu_threads ve num_workers sınırlandı
        self._model = WhisperModel(
            s.fw_model_size,
            device=s.fw_device,
            compute_type=s.fw_compute_type,
            cpu_threads=2,
            num_workers=1,
        )
        return self._model

    def transcribe(
        self, audio_path: Path, *, language: str | None = None
    ) -> Transcript:
        if language and language.lower() not in _SUPPORTED:
            raise TranscriptionError(
                f"Unsupported language '{language}'. Supported: {sorted(_SUPPORTED)}"
            )
        model = self._get_model()
        s = get_settings()
        try:
            segments_iter, info = model.transcribe(
                str(audio_path),
                language=language.lower() if language else None,
                beam_size=5,
                vad_filter=True,  # Silero VAD, default params (tested best)
                # Don't feed generated text back as context: stops the model
                # looping or drifting into another language / subtitle credits.
                condition_on_previous_text=False,
                # Empty by default — an instruction-style prompt here provokes
                # "Altyazı M.K." hallucinations on real phone audio.
                initial_prompt=s.fw_initial_prompt or None,
            )
            segments: list[Segment] = []
            parts: list[str] = []
            for i, seg in enumerate(segments_iter, start=1):
                segments.append(Segment(i, float(seg.start), float(seg.end), seg.text))
                parts.append(seg.text)
        except Exception as exc:  # noqa: BLE001
            raise TranscriptionError(f"faster-whisper failed: {exc}") from exc

        return Transcript(
            language=getattr(info, "language", language or "unknown"),
            duration=float(getattr(info, "duration", segments[-1].end if segments else 0.0)),
            text="".join(parts).strip(),
            segments=segments,
            backend=self.name,
        )
