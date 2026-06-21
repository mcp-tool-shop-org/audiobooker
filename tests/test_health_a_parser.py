"""
Regression tests for the Stage A parser/language health fixes (PARSER-A-00x).

Each test targets one verified defect and is written to FAIL against the
pre-fix behavior and PASS against the fix. No network, no real ffmpeg/voice,
no real ebooklib/pymupdf (PDF/EPUB internals are faked via sys.modules /
small in-process fakes).
"""

import sys
import types

import pytest

from audiobooker.parser import epub as epub_mod
from audiobooker.parser import pdf as pdf_mod
from audiobooker.parser import text_cleaners as tc
from audiobooker.language.profile import get_profile


# ---------------------------------------------------------------------------
# PARSER-A-001 — EPUB file-size guard
# ---------------------------------------------------------------------------
class TestEpubSizeGuard:
    def test_oversize_epub_rejected_like_pdf(self, tmp_path, monkeypatch):
        """An over-limit EPUB raises a clear ValueError before read_epub runs."""
        book = tmp_path / "huge.epub"
        book.write_bytes(b"PK\x03\x04 not really a zip")

        original_stat = type(book).stat

        def fake_stat(self, *args, **kwargs):
            real = original_stat(self, *args, **kwargs)
            if self == book:
                return types.SimpleNamespace(
                    st_size=epub_mod._MAX_EPUB_FILE_BYTES + 1,
                    st_mode=real.st_mode,
                )
            return real

        monkeypatch.setattr(type(book), "stat", fake_stat)

        with pytest.raises(ValueError, match="too large"):
            epub_mod.parse_epub(book)

    def test_max_epub_bytes_constant_exists(self):
        """The guard constant exists and mirrors the PDF guard magnitude."""
        assert epub_mod._MAX_EPUB_FILE_BYTES == 200 * 1024 * 1024


# ---------------------------------------------------------------------------
# PARSER-A-002 — PDF document handle always closed; bad page skipped
# ---------------------------------------------------------------------------
class _FakePage:
    def __init__(self, text, raise_on_get=False):
        self._text = text
        self._raise = raise_on_get

    def get_text(self, _mode):
        if self._raise:
            raise RuntimeError("simulated extraction failure")
        return self._text


class _FakeDoc:
    def __init__(self, pages, metadata=None):
        self._pages = pages
        self.metadata = metadata or {}
        self.closed = False

    def __len__(self):
        return len(self._pages)

    def __getitem__(self, i):
        return self._pages[i]

    def close(self):
        self.closed = True


def _install_fake_fitz(monkeypatch, doc):
    """Inject a fake `fitz` module whose open() returns `doc`."""
    fake = types.ModuleType("fitz")
    fake.open = lambda *_a, **_k: doc
    monkeypatch.setitem(sys.modules, "fitz", fake)


class TestPdfHandleClosed:
    def test_doc_closed_and_parsing_continues_after_bad_page(self, tmp_path, monkeypatch):
        """A page that raises during extraction is skipped; the doc still closes."""
        good = "Word " * 60  # >= min_chapter_words, plenty of words per page
        doc = _FakeDoc(
            pages=[
                _FakePage(good),
                _FakePage("", raise_on_get=True),  # mid-loop failure
                _FakePage(good),
            ]
        )
        _install_fake_fitz(monkeypatch, doc)

        pdf = tmp_path / "book.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        metadata, chapters = pdf_mod.parse_pdf(pdf, min_chapter_words=10)

        # Bad page skipped, good content still parsed into at least one chapter.
        assert chapters, "parsing should continue past the bad page"
        # The document handle must always be closed (Windows file-lock leak).
        assert doc.closed is True

    def test_doc_closed_even_when_all_pages_raise(self, tmp_path, monkeypatch):
        """Even when every page fails, the doc is closed (scanned-PDF error path)."""
        doc = _FakeDoc(pages=[_FakePage("", raise_on_get=True)])
        _install_fake_fitz(monkeypatch, doc)

        pdf = tmp_path / "broken.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")

        with pytest.raises(ValueError):
            pdf_mod.parse_pdf(pdf, min_chapter_words=10)
        assert doc.closed is True


# ---------------------------------------------------------------------------
# PARSER-A-003 — bare numeric lines are NOT stripped by default
# ---------------------------------------------------------------------------
class TestStripPageNumbers:
    def test_countdown_digits_preserved(self):
        text = "The countdown began.\n3\n2\n1\nLiftoff!"
        out = tc.strip_page_numbers(text)
        assert "3" in out
        assert "2" in out
        assert "1" in out
        assert "Liftoff!" in out

    def test_bare_year_line_preserved(self):
        text = "It happened in\n2021\nand changed everything."
        out = tc.strip_page_numbers(text)
        assert "2021" in out

    def test_prefixed_page_number_still_stripped(self):
        text = "Some content.\nPage 12\nMore content."
        out = tc.strip_page_numbers(text)
        assert "Page 12" not in out
        assert "Some content." in out
        assert "More content." in out

    def test_centered_page_number_still_stripped(self):
        text = "Body text here.\n- 42 -\nNext body."
        out = tc.strip_page_numbers(text)
        assert "- 42 -" not in out
        assert "Body text here." in out

    def test_default_pipeline_keeps_countdown(self):
        """End-to-end: the default cleaner pipeline must not eat countdowns."""
        text = "The countdown began.\n3\n2\n1\nLiftoff!"
        out = tc.clean_text(text)
        assert "3" in out and "2" in out and "1" in out


# ---------------------------------------------------------------------------
# PARSER-A-004 — dead font-heading detector removed
# ---------------------------------------------------------------------------
class TestDeadCodeRemoved:
    def test_detect_font_headings_gone(self):
        assert not hasattr(pdf_mod, "_detect_font_headings")

    def test_module_docstring_does_not_advertise_font_size(self):
        assert "font-size" not in (pdf_mod.__doc__ or "").lower()
        assert "font size" not in (pdf_mod.__doc__ or "").lower()


# ---------------------------------------------------------------------------
# PARSER-A-005 — cover extension allowlist
# ---------------------------------------------------------------------------
class TestCoverExtAllowlist:
    def test_junk_suffix_falls_back_to_jpg(self):
        assert epub_mod._safe_cover_ext("cover.exe") == ".jpg"
        assert epub_mod._safe_cover_ext("cover.../etc/passwd") == ".jpg"
        assert epub_mod._safe_cover_ext("cover") == ".jpg"

    def test_allowed_suffix_preserved(self):
        assert epub_mod._safe_cover_ext("art.PNG") == ".png"
        assert epub_mod._safe_cover_ext("photo.jpeg") == ".jpeg"
        assert epub_mod._safe_cover_ext("anim.webp") == ".webp"


# ---------------------------------------------------------------------------
# PARSER-A-006 — ambiguous St./Co. dropped from default expansions
# ---------------------------------------------------------------------------
class TestAbbreviationExpansion:
    def test_street_abbrev_left_unchanged(self):
        # Reset lazy cache so we exercise the current map.
        tc._COMPILED_ABBREVS = None
        out = tc.expand_common_abbreviations("Main St.")
        assert out == "Main St."
        assert "Saint" not in out

    def test_county_abbrev_left_unchanged(self):
        tc._COMPILED_ABBREVS = None
        out = tc.expand_common_abbreviations("Co. Cork")
        assert out == "Co. Cork"
        assert "Company" not in out

    def test_unambiguous_abbrevs_still_expand(self):
        tc._COMPILED_ABBREVS = None
        out = tc.expand_common_abbreviations("Mr. Smith and Dr. Jones")
        assert "Mister Smith" in out
        assert "Doctor Jones" in out


# ---------------------------------------------------------------------------
# PARSER-A-007 — German speaker_blacklist spelling
# ---------------------------------------------------------------------------
class TestGermanBlacklistSpelling:
    def test_nervoes_correct_spelling(self):
        profile = get_profile("de")
        assert "nervös" in profile.speaker_blacklist
        assert "nervos" not in profile.speaker_blacklist


# ---------------------------------------------------------------------------
# PARSER-A-008 — EPUB item BOM-aware decoding
# ---------------------------------------------------------------------------
class TestEpubItemDecode:
    def test_utf16_le_bom_decodes_cleanly(self):
        original = "<p>Café déjà vu — naïve façade</p>"
        raw = b"\xff\xfe" + original.encode("utf-16-le")  # LE BOM + payload
        out = epub_mod._decode_item_content(raw, "ch1.xhtml")
        assert out == original
        assert "�" not in out  # no replacement chars / mojibake
        # The pre-fix code did a blind utf-8 decode, which mojibakes this.
        assert original != raw.decode("utf-8", errors="replace")

    def test_utf16_be_bom_decodes_cleanly(self):
        original = "<p>naïve façade</p>"
        raw = b"\xfe\xff" + original.encode("utf-16-be")  # BE BOM + payload
        out = epub_mod._decode_item_content(raw, "ch1.xhtml")
        assert out == original

    def test_plain_utf8_still_decodes(self):
        original = "<p>plain ascii and café</p>"
        out = epub_mod._decode_item_content(original.encode("utf-8"), "ch1.xhtml")
        assert out == original

    def test_utf8_bom_stripped(self):
        original = "<p>hello</p>"
        raw = b"\xef\xbb\xbf" + original.encode("utf-8")
        out = epub_mod._decode_item_content(raw, "ch1.xhtml")
        assert out == original
        assert "﻿" not in out
