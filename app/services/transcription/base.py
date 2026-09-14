"""``TranscriptionService`` interface + shared result model and formatters.

A backend only has to implement :meth:`TranscriptionService.transcribe` and
return a :class:`Transcript`. Formatting to txt/srt/json is backend-agnostic and
lives here so every backend renders identical output.
"""
from __future__ import annotations

import abc
import json
from dataclasses import dataclass
from pathlib import Path


class TranscriptionError(RuntimeError):
    """Transcription failed at runtime."""


class TranscriptionUnavailableError(RuntimeError):
    """The selected backend is not installed / not configured."""


@dataclass
class Segment:
    index: int
    start: float
    end: float
    text: str
    speaker: str | None = None  # e.g. "Konuşmacı 1"; set by diarization


@dataclass
class Transcript:
    language: str
    duration: float
    text: str
    segments: list[Segment]
    backend: str
    speaker_count: int = 0  # 0 => diarization not run


class TranscriptionService(abc.ABC):
    """Swap-in speech-to-text backend."""

    name: str = "base"

    @abc.abstractmethod
    def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None = None,
    ) -> Transcript:
        """Transcribe ``audio_path``. ``language`` None => auto-detect."""
        raise NotImplementedError


# --------------------------------------------------------------------------
# formatters
# --------------------------------------------------------------------------
def _speaker_prefix(seg: Segment) -> str:
    return f"[{seg.speaker}] " if seg.speaker else ""


def render_txt(t: Transcript) -> str:
    if not t.speaker_count:
        return t.text.strip() + "\n"
    # One block per speaker turn; blank line between turns.
    lines: list[str] = []
    current: str | None = object()  # sentinel != any speaker
    buf: list[str] = []
    for seg in t.segments:
        if seg.speaker != current:
            if buf:
                lines.append(" ".join(buf).strip())
            current = seg.speaker
            buf = [f"{_speaker_prefix(seg)}{seg.text.strip()}"]
        else:
            buf.append(seg.text.strip())
    if buf:
        lines.append(" ".join(buf).strip())
    return "\n\n".join(lines) + "\n"


def _srt_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def render_srt(t: Transcript) -> str:
    blocks: list[str] = []
    for seg in t.segments:
        blocks.append(
            f"{seg.index}\n"
            f"{_srt_timestamp(seg.start)} --> {_srt_timestamp(seg.end)}\n"
            f"{_speaker_prefix(seg)}{seg.text.strip()}\n"
        )
    return "\n".join(blocks) + ("\n" if blocks else "")


def render_json(t: Transcript) -> str:
    payload = {
        "language": t.language,
        "duration": round(t.duration, 3),
        "backend": t.backend,
        "speaker_count": t.speaker_count,
        "text": t.text.strip(),
        "segments": [
            {
                "index": s.index,
                "start": round(s.start, 3),
                "end": round(s.end, 3),
                "speaker": s.speaker,
                "text": s.text.strip(),
            }
            for s in t.segments
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


RENDERERS = {"txt": render_txt, "srt": render_srt, "json": render_json}
