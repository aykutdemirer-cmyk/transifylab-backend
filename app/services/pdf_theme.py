"""Shared visual theme for generated PDFs (text-to-pdf, docx-to-pdf).

A left accent bar, a coloured title block with a rule, justified body text,
and a page-number footer — instead of reportlab's bare default look. Tries to
register Segoe UI (present on Windows) for nicer typography; falls back to
the built-in Helvetica so rendering still works on any OS/container.
"""
from __future__ import annotations

import functools
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm

BRAND = colors.HexColor("#3b5bdb")
BRAND_DARK = colors.HexColor("#27398c")
TEXT = colors.HexColor("#1f2937")
MUTED = colors.HexColor("#6b7280")
RULE = colors.HexColor("#c7d2fe")

PAGE_SIZE = A4
MARGIN_LEFT = 24 * mm
MARGIN_RIGHT = 20 * mm
MARGIN_TOP = 22 * mm
MARGIN_BOTTOM = 20 * mm
ACCENT_BAR_WIDTH = 3.2 * mm

_WIN_FONTS = Path(r"C:\Windows\Fonts")
_CANDIDATES = {
    "Body": ("segoeui.ttf", "Helvetica"),
    "Body-Bold": ("segoeuib.ttf", "Helvetica-Bold"),
    "Body-Italic": ("segoeuii.ttf", "Helvetica-Oblique"),
}


@functools.lru_cache(maxsize=1)
def _font_names() -> dict[str, str]:
    """Register Segoe UI if present; otherwise map to Helvetica. Cached."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    names: dict[str, str] = {}
    for role, (filename, fallback) in _CANDIDATES.items():
        path = _WIN_FONTS / filename
        if path.exists():
            font_name = f"DocFont-{role}"
            try:
                pdfmetrics.registerFont(TTFont(font_name, str(path)))
                names[role] = font_name
                continue
            except Exception:  # noqa: BLE001 - corrupt/locked font file etc.
                pass
        names[role] = fallback
    return names


def title_style() -> ParagraphStyle:
    return ParagraphStyle(
        "DocTitle",
        fontName=_font_names()["Body-Bold"],
        fontSize=22,
        leading=27,
        textColor=BRAND_DARK,
    )


def subtitle_style() -> ParagraphStyle:
    return ParagraphStyle(
        "DocSubtitle",
        fontName=_font_names()["Body"],
        fontSize=9,
        leading=13,
        textColor=MUTED,
    )


def body_style() -> ParagraphStyle:
    return ParagraphStyle(
        "DocBody",
        fontName=_font_names()["Body"],
        fontSize=11,
        leading=16.5,
        textColor=TEXT,
        alignment=4,  # TA_JUSTIFY
        spaceAfter=6,
    )


def decorate_page(canvas, doc) -> None:
    """onPage callback: left accent bar + footer page number."""
    canvas.saveState()
    page_h = PAGE_SIZE[1]
    page_w = PAGE_SIZE[0]

    canvas.setFillColor(BRAND)
    canvas.rect(0, 0, ACCENT_BAR_WIDTH, page_h, stroke=0, fill=1)

    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.6)
    footer_y = MARGIN_BOTTOM - 8 * mm
    canvas.line(MARGIN_LEFT, footer_y, page_w - MARGIN_RIGHT, footer_y)

    canvas.setFont(_font_names()["Body"], 8)
    canvas.setFillColor(MUTED)
    canvas.drawRightString(page_w - MARGIN_RIGHT, footer_y - 10, f"Sayfa {doc.page}")
    canvas.restoreState()
