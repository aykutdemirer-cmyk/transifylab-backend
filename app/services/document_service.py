"""Document conversion.

Heavy/optional dependencies (``fitz`` / PyMuPDF, ``python-docx``) are imported inside
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
    """Convert PDF to Word preserving multi-column layout and embedded images (PyMuPDF + python-docx)."""
    try:
        import pymupdf as fitz
        import docx
        from docx.shared import Inches, Pt, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.enum.table import WD_TABLE_ALIGNMENT
    except ImportError as exc:
        raise FeatureUnavailableError(
            "Required dependencies (PyMuPDF / python-docx) are not installed. Run: pip install PyMuPDF python-docx"
        ) from exc

    try:
        doc = fitz.open(str(src_pdf))
        word_doc = docx.Document()

        # Sayfa kenar boşluklarını daraltarak tam sayfa kullanım alanı sağlıyoruz
        for section in word_doc.sections:
            section.top_margin = Inches(0.75)
            section.bottom_margin = Inches(0.75)
            section.left_margin = Inches(0.75)
            section.right_margin = Inches(0.75)

        for page_index, page in enumerate(doc):
            if page_index > 0:
                word_doc.add_page_break()

            # 1. Görselleri Çıkart ve Kaydet
            image_list = page.get_images(full=True)
            for img_index, img in enumerate(image_list):
                xref = img[0]
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                image_ext = base_image["ext"]
                
                image_path = src_pdf.parent / f"extracted_img_{page_index}_{img_index}.{image_ext}"
                image_path.write_bytes(image_bytes)

                try:
                    # Fotoğrafı Word belgesine ekle
                    word_doc.add_picture(str(image_path), width=Inches(1.2))
                except Exception:
                    pass
                finally:
                    if image_path.exists():
                        image_path.unlink(missing_ok=True)

            # 2. Metin Bloklarını Koordinatlarına Göre Al (x0, y0, x1, y1, text, block_no, block_type)
            blocks = page.get_text("blocks")
            # Sadece metin içeren blokları filtrele (tip 0: metin, 1: görsel)
            text_blocks = [b for b in blocks if b[6] == 0]

            if not text_blocks:
                continue

            # Sayfa genişliğine göre sol ve sağ sütun sınırını ayarla (LinkedIn için sol taraf daha dardır)
            page_width = page.rect.width
            split_x = page_width * 0.32  # İlk %32'lik kısım sol sütun (iletişim, yetenekler)

            left_column_texts = []
            right_column_texts = []

            for b in text_blocks:
                x0, y0, x1, y1, text, block_no, block_type = b
                cleaned_text = text.strip()
                if not cleaned_text:
                    continue
                
                if x0 < split_x:
                    left_column_texts.append((y0, cleaned_text))
                else:
                    right_column_texts.append((y0, cleaned_text))

            # Dikey sıraya göre sırala
            left_column_texts.sort(key=lambda x: x[0])
            right_column_texts.sort(key=lambda x: x[0])

            # 3. İki Sütunlu Yapı İçin Tablo Oluştur ve Kenar Çizgilerini Kaldır
            table = word_doc.add_table(rows=1, cols=2)
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            table.autofit = False

            # Sütun genişliklerini LinkedIn oranına göre ayarla (Sol: 2.0 inç, Sağ: 4.5 inç)
            table.columns[0].width = Inches(2.0)
            table.columns[1].width = Inches(4.5)

            cell_left = table.cell(0, 0)
            cell_right = table.cell(0, 1)

            # Tablo kenarlıklarını tamamen gizle (görünmez tablo)
            for cell in (cell_left, cell_right):
                tcPr = cell._tc.get_or_add_tcPr()
                tcBorders = docx.oxml.OxmlElement('w:tcBorders')
                for border_name in ['top', 'left', 'bottom', 'right', 'insideH', 'insideV']:
                    border = docx.oxml.OxmlElement(f'w:{border_name}')
                    border.set(docx.oxml.ns.qn('w:val'), 'none')
                    tcBorders.append(border)
                tcPr.append(tcBorders)

            # Sol sütun içeriklerini ekle
            for _, text in left_column_texts:
                p = cell_left.add_paragraph()
                p.paragraph_format.space_after = Pt(3)
                p.paragraph_format.line_spacing = 1.15
                run = p.add_run(text)
                run.font.name = "Arial"
                run.font.size = Pt(9)

            # Sağ sütun içeriklerini ekle
            for _, text in right_column_texts:
                p = cell_right.add_paragraph()
                p.paragraph_format.space_after = Pt(4)
                p.paragraph_format.line_spacing = 1.15
                run = p.add_run(text)
                run.font.name = "Arial"
                run.font.size = Pt(9.5)

        word_doc.save(str(dst_docx))
        doc.close()

    except Exception as exc:
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
    except ImportError as exc:
        raise FeatureUnavailableError(
            "python-docx is not installed. Run: pip install python-docx"
        ) from exc

    try:
        document = docx.Document(str(src_docx))
    except Exception as exc:
        raise ConversionError(f"Could not read .docx: {exc}") from exc

    paragraphs = [p.text for p in document.paragraphs]
    _render_pdf(paragraphs, dst_pdf, title=title)


# --------------------------------------------------------------------------
# internals
# --------------------------------------------------------------------------
def _wrap_plaintext(text: str) -> list[str]:
    return text.replace("\r\n", "\n").split("\n")


def _render_pdf(lines: list[str], dst_pdf: Path, *, title: str | None) -> None:
    try:
        from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer
    except ImportError as exc:
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
    except Exception as exc:
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
