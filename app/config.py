"""Application settings, loaded from environment / .env once at import time."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "File Conversion & Transcription API"
    environment: str = "development"
    log_level: str = "INFO"

    # NoDecode: keep pydantic-settings from JSON-parsing the raw env string;
    # the validator below splits a plain comma-separated list instead.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default=["http://localhost:5173", "http://127.0.0.1:5173"]
    )

    # Uploads / temp files
    temp_dir: str = ".tmp"
    max_upload_size_mb: int = 100
    file_ttl_seconds: int = 3600
    cleanup_interval_seconds: int = 300

    # Transcription
    transcription_backend: str = "faster_whisper"
    fw_model_size: str = "large-v3"
    fw_device: str = "cpu"
    fw_compute_type: str = "int8"
    # Whisper's initial_prompt primes the decoder with "prior context". An
    # instruction-style sentence here makes large-v3 hallucinate subtitle
    # credits ("Altyazı M.K.") on real phone audio, so it is EMPTY by default.
    # Only set it to a short sample of the expected wording/domain if you know
    # what you are doing.
    fw_initial_prompt: str = ""
    openai_api_key: str = ""
    openai_transcribe_model: str = "whisper-1"

    # ffmpeg/PyAV filter chain applied while transcoding to WAV. Cleans up quiet
    # narrowband telephony (.gsm/.amr) recordings so VAD/Whisper hear the speech.
    # Empty string disables it.
    audio_filter_chain: str = "highpass=f=85,loudnorm=I=-16:TP=-1.5:LRA=11"

    # Speaker diarization (sherpa-onnx, offline, no torch/HF token).
    diarization_enabled: bool = True
    diarization_segmentation_model: str = "models/diarization/segmentation.onnx"
    diarization_embedding_model: str = "models/diarization/embedding.onnx"
    diarization_max_speakers: int = 0  # 0 => auto-detect count

    # Rule-based punctuation / paragraph cleanup of the final transcript.
    transcript_cleanup: bool = True

    # Optional LibreOffice binary for high-fidelity docx -> pdf
    soffice_bin: str | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def temp_path(self) -> Path:
        p = Path(self.temp_dir)
        if not p.is_absolute():
            p = BACKEND_ROOT / p
        return p

    def _resolve(self, value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else BACKEND_ROOT / p

    @property
    def diarization_segmentation_path(self) -> Path:
        return self._resolve(self.diarization_segmentation_model)

    @property
    def diarization_embedding_path(self) -> Path:
        return self._resolve(self.diarization_embedding_model)

    @property
    def diarization_available(self) -> bool:
        return (
            self.diarization_enabled
            and self.diarization_segmentation_path.exists()
            and self.diarization_embedding_path.exists()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
