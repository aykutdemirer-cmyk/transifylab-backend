"""Transcription route tests with a fake backend (no audio / models needed)."""
from __future__ import annotations

import pytest

from app.routers import transcribe as route
from app.services.transcription.base import (
    Segment,
    Transcript,
    TranscriptionError,
    TranscriptionService,
    TranscriptionUnavailableError,
)


class FakeService(TranscriptionService):
    name = "fake"

    def __init__(self, *, raise_exc: Exception | None = None):
        self._raise = raise_exc

    def transcribe(self, audio_path, *, language=None):
        if self._raise:
            raise self._raise
        return Transcript(
            language=language or "tr",
            duration=3.5,
            text="Merhaba dünya. İkinci cümle.",
            segments=[
                Segment(1, 0.0, 1.6, "Merhaba dünya."),
                Segment(2, 1.6, 3.5, " İkinci cümle."),
            ],
            backend=self.name,
        )


@pytest.fixture
def fake_backend(monkeypatch):
    svc = FakeService()
    monkeypatch.setattr(route, "get_transcription_service", lambda: svc)
    return svc


def _audio():
    return {"file": ("clip.mp3", b"ID3fake-audio-bytes", "audio/mpeg")}


def test_transcribe_returns_text_and_segments(client, fake_backend):
    r = client.post("/api/v1/transcribe", files=_audio(), data={"language": "tr"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["language"] == "tr"
    assert body["backend"] == "fake"
    assert len(body["segments"]) == 2
    assert set(body["downloads"]) == {"txt", "srt", "json"}


def test_transcribe_srt_download_is_well_formed(client, fake_backend):
    r = client.post("/api/v1/transcribe", files=_audio(), data={"formats": "srt"})
    assert r.status_code == 200, r.text
    srt = client.get(r.json()["downloads"]["srt"]).text
    assert "1\n00:00:00,000 --> 00:00:01,600\nMerhaba dünya." in srt


def test_transcribe_rejects_bad_language(client, fake_backend):
    r = client.post("/api/v1/transcribe", files=_audio(), data={"language": "de"})
    assert r.status_code == 400


def test_transcribe_rejects_bad_format(client, fake_backend):
    r = client.post("/api/v1/transcribe", files=_audio(), data={"formats": "doc"})
    assert r.status_code == 400


def test_transcribe_rejects_non_audio(client, fake_backend):
    r = client.post(
        "/api/v1/transcribe",
        files={"file": ("x.pdf", b"%PDF", "application/pdf")},
    )
    assert r.status_code == 400


def test_transcribe_gsm_is_transcoded_first(client, fake_backend, monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_transcode(src, dst):
        calls.append((src.name, dst.name))
        dst.write_bytes(b"RIFF....WAVEfmt ")
        return dst

    monkeypatch.setattr(route, "transcode_to_wav", fake_transcode)
    r = client.post(
        "/api/v1/transcribe",
        files={"file": ("call.gsm", b"\x00\x01gsm-bytes", "audio/gsm")},
        data={"formats": "txt"},
    )
    assert r.status_code == 200, r.text
    assert calls and calls[0][1] == "audio_16k.wav"


def test_transcribe_gsm_decode_failure_maps_to_422(client, fake_backend, monkeypatch):
    from app.services.transcription.audio import AudioDecodeError

    def boom(src, dst):
        raise AudioDecodeError("codec yok")

    monkeypatch.setattr(route, "transcode_to_wav", boom)
    r = client.post(
        "/api/v1/transcribe",
        files={"file": ("call.gsm", b"\x00\x01", "audio/gsm")},
    )
    assert r.status_code == 422


def test_backend_unavailable_maps_to_503(client, monkeypatch):
    svc = FakeService(raise_exc=TranscriptionUnavailableError("faster-whisper missing"))
    monkeypatch.setattr(route, "get_transcription_service", lambda: svc)
    r = client.post("/api/v1/transcribe", files=_audio())
    assert r.status_code == 503


def test_backend_runtime_error_maps_to_422(client, monkeypatch):
    svc = FakeService(raise_exc=TranscriptionError("decode failed"))
    monkeypatch.setattr(route, "get_transcription_service", lambda: svc)
    r = client.post("/api/v1/transcribe", files=_audio())
    assert r.status_code == 422
