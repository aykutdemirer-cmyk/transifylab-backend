from app.services.transcription.base import Segment
from app.services.transcription.postprocess import (
    clean_text,
    drop_hallucinated_segments,
    is_hallucinated,
)


def test_capitalises_sentences_and_adds_final_stop():
    assert clean_text("merhaba dünya. ikinci cümle") == "Merhaba dünya. İkinci cümle."


def test_turkish_dotless_i_at_sentence_start():
    assert clean_text("ışık geldi").startswith("Işık")


def test_strips_space_before_punctuation_and_collapses_spaces():
    assert clean_text("evet , tamam  mı ?") == "Evet, tamam mı?"


def test_empty_passthrough():
    assert clean_text("") == ""
    assert clean_text("   ") == "   "


def test_detects_known_hallucinations():
    for junk in [
        "Altyazı M.K.",
        "Altyazı: M.K.",
        "Altyazılar Amara.org topluluğu tarafından",
        "Abone olmayı unutmayın",
        "İzlediğiniz için teşekkür ederim",
        "Thanks for watching!",
        "Subtitles by the community",
    ]:
        assert is_hallucinated(junk), junk


def test_keeps_real_speech():
    for good in [
        "Merhaba, nasılsınız?",
        "Altyazı sistemini açar mısınız?",  # 'altyazı' inside a real sentence
        "Bugün hava çok güzel.",
    ]:
        assert not is_hallucinated(good), good


def test_drop_hallucinated_segments_reindexes():
    segs = [
        Segment(1, 0.0, 2.0, "Alo, merhaba."),
        Segment(2, 2.0, 4.0, "Altyazı M.K."),
        Segment(3, 4.0, 6.0, "Görüşmek üzere."),
    ]
    dropped = drop_hallucinated_segments(segs)
    assert dropped == 1
    assert [s.text for s in segs] == ["Alo, merhaba.", "Görüşmek üzere."]
    assert [s.index for s in segs] == [1, 2]
