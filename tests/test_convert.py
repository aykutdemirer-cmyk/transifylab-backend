"""Conversion route tests.

The heavy engines (pdf2docx / reportlab) are stubbed so routing, validation,
job bookkeeping and error mapping are covered without those dependencies. One
test opts in to the real reportlab path when it is installed.
"""
from __future__ import annotations

import pytest

from app.services import document_service as docs


@pytest.fixture
def text_to_pdf_calls():
    return []


@pytest.fixture
def stub_engines(monkeypatch, text_to_pdf_calls):
    def fake_pdf_to_word(src, dst):
        dst.write_bytes(b"PK\x03\x04 fake docx")

    def fake_text_to_pdf(text, dst, title=None):
        text_to_pdf_calls.append(title)
        dst.write_bytes(b"%PDF-1.4 fake " + text.encode("utf-8", "replace")[:32])

    def fake_docx_to_pdf(src, dst, title=None):
        dst.write_bytes(b"%PDF-1.4 fake from docx")

    monkeypatch.setattr(docs, "pdf_to_word", fake_pdf_to_word)
    monkeypatch.setattr(docs, "text_to_pdf", fake_text_to_pdf)
    monkeypatch.setattr(docs, "docx_to_pdf", fake_docx_to_pdf)


def test_pdf_to_word_happy_path(client, stub_engines):
    r = client.post(
        "/api/v1/convert/pdf-to-word",
        files={"file": ("report.pdf", b"%PDF-1.4 minimal", "application/pdf")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "pdf_to_word"
    assert body["filename"] == "report.docx"
    assert body["download_url"].endswith("format=docx")

    dl = client.get(body["download_url"])
    assert dl.status_code == 200
    assert dl.content.startswith(b"PK")
    assert "report.docx" in dl.headers["content-disposition"]


def test_pdf_to_word_rejects_wrong_extension(client, stub_engines):
    r = client.post(
        "/api/v1/convert/pdf-to-word",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 400
    assert "Unsupported PDF file" in r.json()["detail"]


def test_docx_to_pdf_uses_real_filename_as_title(client, monkeypatch):
    """Regression: the PDF title must come from the uploaded file name, not the
    temp path ("input.docx") it was saved to on disk."""
    seen: dict = {}

    def fake_docx_to_pdf(src, dst, title=None):
        seen["src_name"] = src.name
        seen["title"] = title
        dst.write_bytes(b"%PDF-1.4 fake")

    monkeypatch.setattr(docs, "docx_to_pdf", fake_docx_to_pdf)

    r = client.post(
        "/api/v1/convert/docx-to-pdf",
        files={
            "file": (
                "Toplanti Notlari.docx",
                b"PK\x03\x04 fake docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert r.status_code == 200, r.text
    assert seen["src_name"] == "input.docx"  # the temp path — not shown to the user
    assert seen["title"] == "Toplanti Notlari"


def test_text_to_pdf_from_form_text(client, stub_engines):
    r = client.post(
        "/api/v1/convert/text-to-pdf",
        data={"text": "Merhaba dünya\nİkinci satır", "filename": "note"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["filename"] == "note.pdf"


def test_text_to_pdf_requires_input(client, stub_engines):
    r = client.post("/api/v1/convert/text-to-pdf", data={})
    assert r.status_code == 400


def test_text_to_pdf_no_title_by_default(client, stub_engines, text_to_pdf_calls):
    """A fallback output filename must never leak into the PDF as a heading."""
    r = client.post("/api/v1/convert/text-to-pdf", data={"text": "merhaba"})
    assert r.status_code == 200, r.text
    assert r.json()["filename"] == "belge.pdf"
    assert text_to_pdf_calls == [None]


def test_text_to_pdf_explicit_title_is_used(client, stub_engines, text_to_pdf_calls):
    r = client.post(
        "/api/v1/convert/text-to-pdf",
        data={"text": "merhaba", "title": "Toplantı Notları"},
    )
    assert r.status_code == 200, r.text
    assert text_to_pdf_calls == ["Toplantı Notları"]


def test_text_to_pdf_uploaded_filename_becomes_title(
    client, stub_engines, text_to_pdf_calls
):
    r = client.post(
        "/api/v1/convert/text-to-pdf",
        files={"file": ("rapor.txt", b"merhaba", "text/plain")},
    )
    assert r.status_code == 200, r.text
    assert text_to_pdf_calls == ["rapor"]


def test_feature_unavailable_maps_to_503(client, monkeypatch):
    def boom(src, dst):
        raise docs.FeatureUnavailableError("pdf2docx is not installed")

    monkeypatch.setattr(docs, "pdf_to_word", boom)
    r = client.post(
        "/api/v1/convert/pdf-to-word",
        files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert r.status_code == 503


def test_conversion_error_maps_to_422(client, monkeypatch):
    def boom(src, dst):
        raise docs.ConversionError("bad pdf")

    monkeypatch.setattr(docs, "pdf_to_word", boom)
    r = client.post(
        "/api/v1/convert/pdf-to-word",
        files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert r.status_code == 422


def test_upload_size_limit_413(client, stub_engines):
    big = b"x" * (1024 * 1024 + 10)  # > 1 MB test cap
    r = client.post(
        "/api/v1/convert/pdf-to-word",
        files={"file": ("big.pdf", big, "application/pdf")},
    )
    assert r.status_code == 413


def test_real_reportlab_text_to_pdf(client):
    pytest.importorskip("reportlab")
    r = client.post(
        "/api/v1/convert/text-to-pdf",
        data={"text": "Real PDF rendering test", "filename": "real"},
    )
    assert r.status_code == 200, r.text
    dl = client.get(r.json()["download_url"])
    assert dl.status_code == 200
    assert dl.content.startswith(b"%PDF")
