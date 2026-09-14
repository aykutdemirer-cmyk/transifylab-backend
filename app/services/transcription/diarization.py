"""Offline speaker diarization via sherpa-onnx (no torch, no HF token).

Given a 16 kHz mono WAV it returns speaker turns, then labels each transcript
segment with the speaker it overlaps most. Models are two small ONNX files
under ``models/diarization/`` (see README); if they are missing the feature
reports itself unavailable rather than failing the whole request.
"""
from __future__ import annotations

import array
import logging
import wave
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings
from app.services.transcription.base import Segment

logger = logging.getLogger("app.transcription.diarization")


class DiarizationUnavailableError(RuntimeError):
    """sherpa-onnx or its models are not installed."""


class DiarizationError(RuntimeError):
    """Diarization ran but failed."""


@dataclass
class SpeakerTurn:
    start: float
    end: float
    speaker: str


def _read_wav_mono_16k(path: Path) -> tuple[list[float], int]:
    with wave.open(str(path), "rb") as wf:
        if wf.getsampwidth() != 2:
            raise DiarizationError("Diarization expects 16-bit PCM WAV.")
        n = wf.getnframes()
        raw = wf.readframes(n)
        rate = wf.getframerate()
        channels = wf.getnchannels()
    samples = array.array("h")
    samples.frombytes(raw)
    if channels > 1:  # average to mono
        samples = array.array(
            "h",
            [
                sum(samples[i : i + channels]) // channels
                for i in range(0, len(samples), channels)
            ],
        )
    return [s / 32768.0 for s in samples], rate


class DiarizationService:
    def __init__(self) -> None:
        self._sd = None

    def _get(self):
        if self._sd is not None:
            return self._sd
        s = get_settings()
        if not s.diarization_available:
            raise DiarizationUnavailableError(
                "Konuşmacı ayrımı yapılandırılmadı: "
                "models/diarization/ altında segmentation.onnx + embedding.onnx gerekli."
            )
        try:
            import sherpa_onnx  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on env
            raise DiarizationUnavailableError(
                "sherpa-onnx kurulu değil. Kurulum: pip install sherpa-onnx"
            ) from exc

        cfg = sherpa_onnx.OfflineSpeakerDiarizationConfig(
            segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                    model=str(s.diarization_segmentation_path)
                )
            ),
            embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(s.diarization_embedding_path)
            ),
            clustering=sherpa_onnx.FastClusteringConfig(
                num_clusters=s.diarization_max_speakers
                if s.diarization_max_speakers > 0
                else -1,
                threshold=0.5,
            ),
            min_duration_on=0.3,
            min_duration_off=0.5,
        )
        if not cfg.validate():
            raise DiarizationError("Geçersiz diarization yapılandırması.")
        self._sd = sherpa_onnx.OfflineSpeakerDiarization(cfg)
        return self._sd

    def diarize(self, wav_16k_mono: Path) -> list[SpeakerTurn]:
        sd = self._get()
        samples, rate = _read_wav_mono_16k(wav_16k_mono)
        if rate != sd.sample_rate:
            raise DiarizationError(
                f"WAV {rate} Hz; diarization {sd.sample_rate} Hz bekliyor."
            )
        try:
            result = sd.process(samples).sort_by_start_time()
        except Exception as exc:  # noqa: BLE001
            raise DiarizationError(f"Diarization çalışmadı: {exc}") from exc
        return [
            SpeakerTurn(float(seg.start), float(seg.end), f"Konuşmacı {seg.speaker + 1}")
            for seg in result
        ]


def assign_speakers(
    segments: list[Segment], turns: list[SpeakerTurn]
) -> int:
    """Label each segment with the speaker turn it overlaps most.

    Returns the count of speakers that are actually present in the transcript
    (not the number of diarization clusters — short/noisy calls over-cluster).
    If only one speaker ends up used, the labels are cleared and 0 is returned,
    so the UI doesn't show a pointless "[Konuşmacı 1]" on every line.
    """
    if not turns:
        return 0
    for seg in segments:
        best, best_overlap = None, 0.0
        for turn in turns:
            overlap = min(seg.end, turn.end) - max(seg.start, turn.start)
            if overlap > best_overlap:
                best, best_overlap = turn.speaker, overlap
        seg.speaker = best or turns[0].speaker

    used = sorted({s.speaker for s in segments if s.speaker})
    if len(used) <= 1:
        for s in segments:
            s.speaker = None
        return 0
    # Renumber so labels are contiguous (Konuşmacı 1..N) in first-appearance order.
    order: dict[str, str] = {}
    for s in segments:
        if s.speaker and s.speaker not in order:
            order[s.speaker] = f"Konuşmacı {len(order) + 1}"
    for s in segments:
        if s.speaker:
            s.speaker = order[s.speaker]
    return len(order)


_service: DiarizationService | None = None


def get_diarization_service() -> DiarizationService:
    global _service
    if _service is None:
        _service = DiarizationService()
    return _service
