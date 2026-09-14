from app.services.transcription.base import Segment, Transcript, render_srt, render_txt
from app.services.transcription.diarization import SpeakerTurn, assign_speakers


def _segments():
    return [
        Segment(1, 0.0, 2.0, "Merhaba."),
        Segment(2, 2.0, 4.0, "Nasılsın?"),
        Segment(3, 4.0, 6.0, "İyiyim, teşekkürler."),
    ]


def test_assign_speakers_by_max_overlap():
    segs = _segments()
    turns = [
        SpeakerTurn(0.0, 2.1, "Konuşmacı 1"),
        SpeakerTurn(2.1, 4.0, "Konuşmacı 2"),
        SpeakerTurn(4.0, 6.5, "Konuşmacı 1"),
    ]
    count = assign_speakers(segs, turns)
    assert count == 2
    assert [s.speaker for s in segs] == ["Konuşmacı 1", "Konuşmacı 2", "Konuşmacı 1"]


def test_assign_speakers_no_turns_is_noop():
    segs = _segments()
    assert assign_speakers(segs, []) == 0
    assert all(s.speaker is None for s in segs)


def test_render_groups_by_speaker_turn():
    segs = _segments()
    assign_speakers(
        segs,
        [SpeakerTurn(0.0, 4.0, "Konuşmacı 1"), SpeakerTurn(4.0, 6.0, "Konuşmacı 2")],
    )
    t = Transcript("tr", 6.0, "Merhaba. Nasılsın? İyiyim, teşekkürler.", segs, "fake", 2)
    txt = render_txt(t)
    assert txt.startswith("[Konuşmacı 1] Merhaba. Nasılsın?")
    assert "\n\n[Konuşmacı 2] İyiyim, teşekkürler." in txt
    assert "[Konuşmacı 1]" in render_srt(t)
