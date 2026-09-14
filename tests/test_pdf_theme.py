from app.services import pdf_theme as theme


def test_styles_are_paragraph_styles():
    for style_fn in (theme.title_style, theme.subtitle_style, theme.body_style):
        style = style_fn()
        assert style.fontName
        assert style.fontSize > 0


def test_font_names_fall_back_gracefully(monkeypatch, tmp_path):
    # Point the "Windows fonts" lookup at an empty dir: no font files exist,
    # so every role must fall back to a built-in Helvetica variant instead of
    # crashing the whole PDF pipeline.
    theme._font_names.cache_clear()
    monkeypatch.setattr(theme, "_WIN_FONTS", tmp_path)
    names = theme._font_names()
    assert names == {
        "Body": "Helvetica",
        "Body-Bold": "Helvetica-Bold",
        "Body-Italic": "Helvetica-Oblique",
    }
    theme._font_names.cache_clear()


def test_decorate_page_draws_without_error():
    from reportlab.pdfgen import canvas

    class FakeDoc:
        page = 3

    c = canvas.Canvas("NUL" if __import__("os").name == "nt" else "/dev/null")
    theme.decorate_page(c, FakeDoc())  # must not raise
