"""Pure-function tests for the backend-agnostic transcript renderers."""
from __future__ import annotations

import json

from app.services.transcription.base import (
    Segment,
    Transcript,
    render_json,
    render_srt,
    render_txt,
)

T = Transcript(
    language="en",
    duration=7.25,
    text="Hello world. Second line.",
    segments=[
        Segment(1, 0.0, 3.2, "Hello world."),
        Segment(2, 3.2, 7.25, " Second line."),
    ],
    backend="fake",
)


def test_txt():
    assert render_txt(T) == "Hello world. Second line.\n"


def test_srt_timestamps_and_indices():
    out = render_srt(T)
    assert out.startswith("1\n00:00:00,000 --> 00:00:03,200\nHello world.\n")
    assert "2\n00:00:03,200 --> 00:00:07,250\nSecond line.\n" in out


def test_json_roundtrip():
    payload = json.loads(render_json(T))
    assert payload["language"] == "en"
    assert payload["backend"] == "fake"
    assert len(payload["segments"]) == 2
    assert payload["segments"][0]["text"] == "Hello world."
