"""Document conversion.

Heavy/optional dependencies (``pdf2docx``, ``python-docx``) are imported inside
the functions that need them so the API still boots when they are absent; a
missing dependency surfaces as a 503 via :class:`FeatureUnavailableError`.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger("app.document")


class FeatureUnavailableError(RuntimeError):
    """A conversion dependency is not installed / configured."""


class ConversionError(RuntimeError):
    """The conversion ran but failed."""


def pdf_to_word(src_pdf: Path, dst_docx: Path) -> None:
    try:
        from pdf2docx import Converter  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on env
        raise FeatureUnavailableError(
            "pdf2docx is not installed. Run: pip install pdf2docx"
        ) from exc

    try:
        cv = Converter(str(src_pdf))
        try:
            # Whole document; pdf2docx preserves layout and reconstructs tables.
            cv.convert(str(dst_docx), start=0, end=None)
        finally:
            cv.close()
    except Exception as exc:  # noqa: BLE001 - pdf2docx raises broad errors
        raise ConversionError(f"PDF to Word conversion failed: {exc}") from exc

    if not dst_docx.exists() or dst_docx.stat().st_size == 0:
        raise ConversionError("PDF to Word conversion produced no output.")


def text_to_pdf(text: str, dst_pdf: Path, title: str | None = None) -> None:
    _render_pdf(_wrap_plaintext(text), dst_pdf, title=title)


def docx_to_pdf(src_docx: Path, dst_pdf: Path, title: str | None = None) -> None:
    settings = get_settings()
    if settings.soffice_bin:
        _docx_to_pdf_libreoffice(src_docx, dst_pdf, settings.soffice_bin)
        return

    try:
        import docx  # type: ignore  (python-docx)
    except ImportError as exc:  # pragma: no cover - depends on env
        raise FeatureUnavailableError(
            "python-docx is not installed. Run: pip install python-docx"
        ) from exc

    try:
        document = docx.Document(str(src_docx))
    except Exception as exc:  # noqa: BLE001
        raise ConversionError(f"Could not read .docx: {exc}") from exc

    paragraphs = [p.text for p in document.paragraphs]
    # `title` is the caller's real (uploaded) file name; `src_docx` is only the
    # temp path we saved the upload to (e.g. "input.docx") and must never be
    # shown to the user as a heading.
    _render_pdf(paragraphs, dst_pdf, title=title)


# --------------------------------------------------------------------------
# internals
# --------------------------------------------------------------------------
def _wrap_plaintext(text: str) -> list[str]:
    # Preserve blank lines; reportlab Paragraph handles the rest.
    return text.replace("\r\n", "\n").split("\n")


def _render_pdf(lines: list[str], dst_pdf: Path, *, title: str | None) -> None:
    try:
        from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer
    except ImportError as exc:  # pragma: no cover - depends on env
        raise FeatureUnavailableError(
            "reportlab is not installed. Run: pip install reportlab"
        ) from exc

    from datetime import datetime
    from xml.sax.saxutils import escape

    from reportlab.lib.units import mm

    from app.services import pdf_theme as theme

    story: list = []
    if title:
        story.append(Paragraph(escape(title), theme.title_style()))
        story.append(
            Paragraph(
                f"Oluşturulma tarihi: {datetime.now():%d.%m.%Y %H:%M}",
                theme.subtitle_style(),
            )
        )
        story.append(Spacer(1, 3 * mm))
        story.append(HRFlowable(width="100%", thickness=1.2, color=theme.RULE, spaceAfter=6 * mm))
    else:
        story.append(Spacer(1, 4 * mm))

    body = theme.body_style()
    for line in lines:
        if line.strip():
            story.append(Paragraph(escape(line), body))
        else:
            story.append(Spacer(1, 4 * mm))

    if not story:
        story.append(Paragraph("(boş belge)", body))

    try:
        SimpleDocTemplate(
            str(dst_pdf),
            pagesize=theme.PAGE_SIZE,
            leftMargin=theme.MARGIN_LEFT,
            rightMargin=theme.MARGIN_RIGHT,
            topMargin=theme.MARGIN_TOP,
            bottomMargin=theme.MARGIN_BOTTOM,
            title=title or dst_pdf.stem,
        ).build(story, onFirstPage=theme.decorate_page, onLaterPages=theme.decorate_page)
    except Exception as exc:  # noqa: BLE001
        raise ConversionError(f"PDF rendering failed: {exc}") from exc

    if not dst_pdf.exists() or dst_pdf.stat().st_size == 0:
        raise ConversionError("PDF rendering produced no output.")


def _docx_to_pdf_libreoffice(src_docx: Path, dst_pdf: Path, soffice_bin: str) -> None:
    outdir = dst_pdf.parent
    try:
        proc = subprocess.run(
            [
                soffice_bin,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(outdir),
                str(src_docx),
            ],
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ConversionError(f"LibreOffice conversion failed: {exc}") from exc

    produced = outdir / (src_docx.stem + ".pdf")
    if proc.returncode != 0 or not produced.exists():
        raise ConversionError(
            "LibreOffice conversion failed: "
            + (proc.stderr.decode(errors="replace") or "unknown error")
        )
    if produced != dst_pdf:
        produced.replace(dst_pdf)
