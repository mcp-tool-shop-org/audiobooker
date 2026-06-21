"""
Regression tests for the Stage C humanization fixes (parser/language domain).

These cover the UX/observability fixes whose goal is a tool that tells the user
how to fix a problem:

1. --lang for EPUB/PDF: parse_epub/parse_pdf accept a LanguageProfile; PDF chapter
   detection uses the profile's localized headings (Kapitel/Capitulo/Chapitre/
   第N章) while English behavior stays byte-for-byte identical.
2. Single-chapter fallback warning when no recurring heading is detected.
3. Parse-observability summary at the end of each parser, and a log of which
   chapter pattern won detection.
4. Scanned-PDF softened wording + word count + force_text override.
5. TXT BOM-sniff (UTF-16 LE/BE + UTF-8 BOM) and explicit empty-file check.
6. Language extensibility: a failing requested language module logs at WARNING.

No network, no real ffmpeg/voice, no real ebooklib/pymupdf (fitz is faked via
sys.modules; EPUB internals via small in-process fakes).
"""

import logging
import sys
import types

import pytest

from audiobooker.parser import pdf as pdf_mod
from audiobooker.parser import text as text_mod
from audiobooker.parser import epub as epub_mod
from audiobooker.language.profile import get_profile
from audiobooker.language import profile as profile_mod


# ---------------------------------------------------------------------------
# Fake fitz plumbing (mirrors test_health_a_parser.py)
# ---------------------------------------------------------------------------
class _FakePage:
    def __init__(self, text):
        self._text = text

    def get_text(self, _mode):
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
    fake = types.ModuleType("fitz")
    fake.open = lambda *_a, **_k: doc
    monkeypatch.setitem(sys.modules, "fitz", fake)


def _make_pdf(tmp_path, name="book.pdf"):
    pdf = tmp_path / name
    pdf.write_bytes(b"%PDF-1.4 fake")
    return pdf


# ---------------------------------------------------------------------------
# Fix 1 — localized chapter detection for PDF via LanguageProfile
# ---------------------------------------------------------------------------
class TestPdfLocalizedChapters:
    def test_english_default_unchanged_identity(self):
        """profile=None / 'en' reuses the exact English pattern list (no behavior drift)."""
        assert pdf_mod._compile_chapter_patterns(None) is pdf_mod._CHAPTER_PATTERNS
        assert (
            pdf_mod._compile_chapter_patterns(get_profile("en"))
            is pdf_mod._CHAPTER_PATTERNS
        )

    def test_english_does_not_match_german_heading(self):
        pats = pdf_mod._compile_chapter_patterns(None)
        assert pdf_mod._is_chapter_heading("Kapitel 1", pats) is None
        assert pdf_mod._is_chapter_heading("Chapter 1", pats) == "Chapter 1"

    def test_german_profile_matches_kapitel(self):
        pats = pdf_mod._compile_chapter_patterns(get_profile("de"))
        assert pdf_mod._is_chapter_heading("Kapitel 1", pats) is not None
        # English fallback still works for mixed-language books.
        assert pdf_mod._is_chapter_heading("Chapter 1", pats) == "Chapter 1"

    @pytest.mark.parametrize(
        "code, heading",
        [
            ("es", "Capítulo 2"),
            ("fr", "Chapitre 3"),
        ],
    )
    def test_profile_matches_localized_heading(self, code, heading):
        pats = pdf_mod._compile_chapter_patterns(get_profile(code))
        assert pdf_mod._is_chapter_heading(heading, pats) is not None

    def test_parse_pdf_splits_on_german_headings(self, tmp_path, monkeypatch):
        """A German PDF splits into multiple chapters only when its profile is passed."""
        body = ("wort " * 60).strip()
        page = f"Kapitel 1\n{body}\nKapitel 2\n{body}"
        _install_fake_fitz(monkeypatch, _FakeDoc(pages=[_FakePage(page)]))
        pdf = _make_pdf(tmp_path)

        _, chapters = pdf_mod.parse_pdf(
            pdf, min_chapter_words=10, profile=get_profile("de")
        )
        assert len(chapters) >= 2, "German headings should split the document"


# ---------------------------------------------------------------------------
# Fix 2 — single-chapter fallback warning (PDF + text)
# ---------------------------------------------------------------------------
class TestSingleChapterFallbackWarning:
    def test_pdf_no_headings_warns(self, tmp_path, monkeypatch, caplog):
        body = ("word " * 80).strip()
        _install_fake_fitz(monkeypatch, _FakeDoc(pages=[_FakePage(body)]))
        pdf = _make_pdf(tmp_path)

        with caplog.at_level(logging.WARNING, logger="audiobooker.parser"):
            _, chapters = pdf_mod.parse_pdf(pdf, min_chapter_words=10)

        assert len(chapters) == 1
        assert any(
            "no chapter headings detected" in r.message.lower()
            for r in caplog.records
        )

    def test_text_no_headings_warns_with_hint(self, caplog):
        text = "Just a plain paragraph with no headings at all whatsoever."
        with caplog.at_level(logging.WARNING, logger="audiobooker.parser"):
            chapters = text_mod.split_into_chapters(text)

        assert chapters == [("Chapter 1", text)]
        msgs = " ".join(r.message.lower() for r in caplog.records)
        assert "no chapter headings detected" in msgs
        # The hint must tell the user HOW to fix it.
        assert "--chapter-delimiter" in msgs or "--lang" in msgs

    def test_text_explicit_delimiter_no_match_warns_differently(self, caplog):
        text = "Some content here that has plenty of words to be a body."
        with caplog.at_level(logging.WARNING, logger="audiobooker.parser"):
            chapters = text_mod.split_into_chapters(
                text, delimiter_pattern=r"^=====$"
            )
        # A delimiter that compiles but matches nothing yields one untitled
        # chapter; the user must be told their pattern did nothing.
        assert len(chapters) == 1
        assert any(
            "matched no lines" in r.message.lower() for r in caplog.records
        )


# ---------------------------------------------------------------------------
# Fix 3 — parse observability summary + winning-pattern log
# ---------------------------------------------------------------------------
class TestParseObservability:
    def test_pdf_summary_logged(self, tmp_path, monkeypatch, caplog):
        body = ("word " * 80).strip()
        _install_fake_fitz(monkeypatch, _FakeDoc(pages=[_FakePage(body)]))
        pdf = _make_pdf(tmp_path)

        with caplog.at_level(logging.INFO, logger="audiobooker.parser"):
            pdf_mod.parse_pdf(pdf, min_chapter_words=10, profile=get_profile("de"))

        summary = [r.message for r in caplog.records if "Parsed PDF" in r.message]
        assert summary, "a parse summary line must be logged"
        assert "profile=de" in summary[0]

    def test_text_summary_logged(self, tmp_path, caplog):
        body = ("word " * 80).strip()
        f = tmp_path / "book.txt"
        f.write_text(body, encoding="utf-8")

        with caplog.at_level(logging.INFO, logger="audiobooker.parser"):
            text_mod.parse_text(f, profile=get_profile("en"))

        summary = [r.message for r in caplog.records if "Parsed text" in r.message]
        assert summary and "profile=en" in summary[0]

    def test_detect_pattern_logs_winner(self, caplog):
        text = "Chapter 1\nbody\nChapter 2\nbody\nChapter 3\nbody"
        with caplog.at_level(logging.INFO, logger="audiobooker.parser"):
            pat = text_mod.detect_chapter_pattern(text)
        assert pat is not None
        assert any(
            "detected chapter pattern" in r.message.lower()
            for r in caplog.records
        )


# ---------------------------------------------------------------------------
# Fix 4 — scanned-PDF softened wording + word count + force_text override
# ---------------------------------------------------------------------------
class TestScannedPdfSoftenOverride:
    def test_scanned_message_softened_with_word_count(self, tmp_path, monkeypatch):
        # All pages empty -> looks scanned.
        doc = _FakeDoc(pages=[_FakePage(""), _FakePage(""), _FakePage("")])
        _install_fake_fitz(monkeypatch, doc)
        pdf = _make_pdf(tmp_path)

        with pytest.raises(ValueError) as exc:
            pdf_mod.parse_pdf(pdf, min_chapter_words=10)

        msg = str(exc.value)
        # Softened: heuristic wording, not a flat "appears to be a scanned PDF".
        assert "usually a scanned" in msg.lower()
        assert "words total" in msg.lower()
        # The override is documented in the error itself. The message now points
        # at the --force-text CLI flag (added by integration) rather than the
        # Python-API phrasing.
        assert "--force-text" in msg

    def test_force_text_overrides_scanned_rejection(self, tmp_path, monkeypatch, caplog):
        # One sparse page with just enough words to form a chapter.
        body = ("word " * 60).strip()
        doc = _FakeDoc(pages=[_FakePage(body), _FakePage(""), _FakePage("")])
        _install_fake_fitz(monkeypatch, doc)
        pdf = _make_pdf(tmp_path)

        # Without force_text it would be rejected (2/3 pages empty < 0.3? no: 1/3
        # has text == 0.33 >= 0.3, so make it clearly sparse below the threshold).
        doc2 = _FakeDoc(pages=[_FakePage(body)] + [_FakePage("")] * 9)
        _install_fake_fitz(monkeypatch, doc2)
        with pytest.raises(ValueError):
            pdf_mod.parse_pdf(pdf, min_chapter_words=10)

        # With force_text it parses anyway and warns.
        doc3 = _FakeDoc(pages=[_FakePage(body)] + [_FakePage("")] * 9)
        _install_fake_fitz(monkeypatch, doc3)
        with caplog.at_level(logging.WARNING, logger="audiobooker.parser"):
            _, chapters = pdf_mod.parse_pdf(
                pdf, min_chapter_words=10, force_text=True
            )
        assert chapters, "force_text should let a sparse PDF through"
        assert any(
            "force_text=true" in r.message.lower() for r in caplog.records
        )


# ---------------------------------------------------------------------------
# Fix 5 — TXT BOM sniff + empty-file check
# ---------------------------------------------------------------------------
class TestTextBomAndEmpty:
    def test_utf16_le_bom_file_decoded(self, tmp_path):
        """A Notepad 'Unicode' (UTF-16 LE + BOM) file is read, not rejected."""
        f = tmp_path / "unicode.txt"
        body = "Chapter 1\n\n" + ("word " * 60)
        f.write_bytes(body.encode("utf-16"))  # adds a BOM, LE on Windows
        _, chapters = text_mod.parse_text(f)
        assert chapters
        assert "word" in chapters[0].raw_text

    def test_utf16_be_bom_file_decoded(self, tmp_path):
        f = tmp_path / "unicode_be.txt"
        body = "hello world " * 30
        f.write_bytes(b"\xfe\xff" + body.encode("utf-16-be"))
        _, chapters = text_mod.parse_text(f)
        assert chapters
        assert "hello" in chapters[0].raw_text

    def test_utf8_bom_file_decoded_without_bom_artifact(self, tmp_path):
        f = tmp_path / "utf8bom.txt"
        body = "plain ascii body " * 30
        f.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
        _, chapters = text_mod.parse_text(f)
        # The BOM must not leak into the text as a stray ﻿.
        assert "﻿" not in chapters[0].raw_text

    def test_empty_file_raises_clear_message(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")
        with pytest.raises(ValueError, match="empty"):
            text_mod.parse_text(f)

    def test_plain_utf8_still_works(self, tmp_path):
        f = tmp_path / "plain.txt"
        f.write_text("regular utf-8 content " * 20, encoding="utf-8")
        _, chapters = text_mod.parse_text(f)
        assert chapters


# ---------------------------------------------------------------------------
# Fix 6 — language extensibility: failing requested module logs at WARNING
# ---------------------------------------------------------------------------
class TestLanguageExtensibility:
    def test_requested_failing_module_warns(self, monkeypatch, caplog):
        """When a specifically-requested language module fails to import, warn."""
        import importlib
        import pkgutil

        real_import = importlib.import_module

        def fake_import(name, *args, **kwargs):
            if name == "audiobooker.language.zz":
                raise ImportError("boom")
            return real_import(name, *args, **kwargs)

        # Make the discovery scan believe a 'zz' module exists.
        fake_modinfo = pkgutil.ModuleInfo(None, "zz", False)
        real_iter = pkgutil.iter_modules

        def fake_iter(path):
            yield from real_iter(path)
            yield fake_modinfo

        monkeypatch.setattr(importlib, "import_module", fake_import)
        monkeypatch.setattr(pkgutil, "iter_modules", fake_iter)

        with caplog.at_level(logging.WARNING, logger="audiobooker.language"):
            profile_mod._discover_profiles(requested_code="zz")

        assert any(
            "zz" in r.message and r.levelno == logging.WARNING
            for r in caplog.records
        ), "a failing requested language module must warn"

    def test_non_requested_failure_stays_debug(self, monkeypatch, caplog):
        """A failing module that was NOT requested must not warn (stays debug)."""
        import importlib
        import pkgutil

        real_import = importlib.import_module

        def fake_import(name, *args, **kwargs):
            if name == "audiobooker.language.zz":
                raise ImportError("boom")
            return real_import(name, *args, **kwargs)

        fake_modinfo = pkgutil.ModuleInfo(None, "zz", False)
        real_iter = pkgutil.iter_modules

        def fake_iter(path):
            yield from real_iter(path)
            yield fake_modinfo

        monkeypatch.setattr(importlib, "import_module", fake_import)
        monkeypatch.setattr(pkgutil, "iter_modules", fake_iter)

        with caplog.at_level(logging.WARNING, logger="audiobooker.language"):
            profile_mod._discover_profiles(requested_code="en")

        assert not any(
            "zz" in r.message and r.levelno == logging.WARNING
            for r in caplog.records
        )

    def test_register_profile_has_adding_a_language_doc(self):
        doc = (profile_mod.register_profile.__doc__ or "").lower()
        assert "adding a language" in doc


# ---------------------------------------------------------------------------
# Fix 1 (EPUB) — parse_epub accepts a profile parameter and logs it
# ---------------------------------------------------------------------------
class TestEpubProfileParam:
    def test_parse_epub_accepts_profile_kwarg(self):
        import inspect

        params = inspect.signature(epub_mod.parse_epub).parameters
        assert "profile" in params
        assert params["profile"].default is None
