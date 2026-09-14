"""Rule-based tidy-up of a raw transcript. No model, no network.

Whisper large-v3 already punctuates reasonably; this only fixes the mechanical
leftovers: stray spacing around punctuation, missing sentence capitalisation,
a missing final period, and repeated filler tokens.
"""
from __future__ import annotations

import re

_SENTENCE_END = re.compile(r"([.!?…])")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?…])")
_MULTISPACE = re.compile(r"[ \t]{2,}")


def _upper_tr(ch: str) -> str:
    # Turkish-aware: dotless i -> I, dotted i -> İ
    return {"i": "İ", "ı": "I"}.get(ch, ch.upper())


def clean_text(text: str) -> str:
    if not text or not text.strip():
        return text

    s = text.replace("\r\n", "\n").strip()
    s = _SPACE_BEFORE_PUNCT.sub(r"\1", s)
    s = _MULTISPACE.sub(" ", s)

    # Capitalise the first letter of every sentence.
    out: list[str] = []
    capitalize_next = True
    for token in re.split(r"(\s+)", s):
        if not token or token.isspace():
            out.append(token)
            continue
        if capitalize_next and token[0].isalpha():
            token = _upper_tr(token[0]) + token[1:]
            capitalize_next = False
        if _SENTENCE_END.search(token[-1:]):
            capitalize_next = True
        out.append(token)
    s = "".join(out).strip()

    if s and s[-1] not in ".!?…":
        s += "."
    return s


def clean_segments_text(segments: list) -> None:
    """In-place tidy of each Segment.text (keeps timings/speakers)."""
    for seg in segments:
        seg.text = clean_text(seg.text)


# Credit / subtitle boilerplate Whisper hallucinates from YouTube training data
# when the audio is (near) silent. Each pattern must match a segment's WHOLE
# text (anchored) — a real sentence that merely contains the word "altyazı"
# is not touched.
_HALLUCINATION_PATTERNS = [
    r"alt ?yaz[ıi][:\s]*[a-zçğıöşü]{1,4}\.?(?:\s*[a-zçğıöşü]\.?){0,2}",  # "Altyazı M.K."
    r"alt ?yaz[ıi]lar?\b.{0,40}?(amara|topluluk|g[öo]n[üu]ll[üu]|taraf[ıi]ndan|[çc]eviri)\b.{0,40}",
    r"(alt ?yaz[ıi]|[çc]eviri)\s*[:·-].{0,40}",
    r".{0,25}amara\.org.{0,40}",
    r".{0,50}(be[ğg]enmeyi|abone olmay[ıi]|yorum yapmay[ıi]) unutmay[ıi]n.{0,20}",
    r".{0,40}kanal[ıi]m[ıi]za? abone ol.{0,20}",
    r".{0,60}izledi[ğg]iniz i[çc]in (te[şs]ekk[üu]rler|te[şs]ekk[üu]r eder(im|iz)).{0,25}",
    r".{0,50}bir sonraki (videoda|b[öo]l[üu]mde) g[öo]r[üu][şs].{0,25}",
    r"thanks for watching\.?",
    r"subtitles? by .{0,40}",
    r"please subscribe.{0,25}",
    r"m\.?\s*k\.?",
]
_HALLUCINATION_RE = re.compile(
    r"^\W*(?:" + "|".join(_HALLUCINATION_PATTERNS) + r")\W*$",
    re.IGNORECASE | re.UNICODE,
)


def is_hallucinated(text: str) -> bool:
    t = (text or "").strip()
    if not t or len(t) > 90:  # real credit junk is short
        return False
    return bool(_HALLUCINATION_RE.match(t))


def drop_hallucinated_segments(segments: list) -> int:
    """Remove junk-credit segments in place; return how many were dropped."""
    keep = [s for s in segments if not is_hallucinated(s.text)]
    dropped = len(segments) - len(keep)
    if dropped:
        segments[:] = keep
        for i, s in enumerate(segments, start=1):
            s.index = i
    return dropped
