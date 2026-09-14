"""Wave-2 amend regression tests — parser-lang domain.

Every test here is written in the FAILING shape against the pre-amend code:
it asserts the behaviour the fix introduces, so it goes red before the fix and
green after. Wave 1 showed the existing fixtures used shapes that could not
express these defects (the footnote path had literally zero behavioural
coverage), so these are deliberately written against the real observable
output, not against internals that happen to be convenient.

Findings covered:
  parser-1-footnote-wiring        epub.py  footnote sentinels reach the TTS engine
  parser-2-footnote-span-close    epub.py  epub:type spans could never close
  parser-3-i18n-said-patterns     language/profile.py ASCII-only attribution
  parser-4-es-emdash-dialogue     language/es.py missing em-dash dialogue
  parser-5-natural-sort           parser/text.py chapter1 < chapter10
  parser-6-pdf-running-head       parser/pdf.py all-caps running heads
  parser-7-pdf-short-section-log  parser/pdf.py silent short-section drops
  parser-8-toc-monotonicity       epub.py TOC slice positions not monotonic
  parser-9-toc-href-suffix        epub.py unanchored suffix href matching
  parser-10-pron-overrides        text_cleaners.py CJK / backslash overrides
"""

from __future__ import annotations

import logging
import re
import sys
import types
from pathlib import Path

import pytest

from audiobooker.parser import epub as epub_mod
from audiobooker.parser import pdf as pdf_mod
from audiobooker.parser import text as text_mod
from audiobooker.parser import text_cleaners as tc
from audiobooker.language.profile import get_profile


def _has_ebooklib() -> bool:
    try:
        import ebooklib  # noqa: F401
        return True
    except ImportError:
        return False


requires_ebooklib = pytest.mark.skipif(
    not _has_ebooklib(),
    reason="ebooklib not installed — install with: pip install ebooklib",
)


# C0 controls that must never survive into Chapter.raw_text. \n and \t are the
# only legal control characters in narratable text.
_ILLEGAL_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _make_epub(tmp_path: Path, docs: list[tuple[str, str, str]], *, toc=None) -> Path:
    """Write a minimal EPUB.

    Args:
        docs: list of (file_name, chapter_title, full html body string).
        toc: optional explicit book.toc (list of epub.Link); defaults to the
            documents in order.
    """
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("amend-parser-lang")
    book.set_title("Amend Book")
    book.set_language("en")
    book.add_author("Amend Author")

    items = []
    for file_name, ch_title, body in docs:
        ch = epub.EpubHtml(title=ch_title, file_name=file_name, lang="en")
        ch.content = f"<html><body>{body}</body></html>"
        book.add_item(ch)
        items.append(ch)

    book.toc = items if toc is None else toc
    book.spine = ["nav"] + items
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    path = tmp_path / "amend.epub"
    epub.write_epub(str(path), book)
    return path


# ---------------------------------------------------------------------------
# parser-1-footnote-wiring
# ---------------------------------------------------------------------------
class TestFootnoteSentinelsNeverEscape:
    SUP_HTML = "<p>She was born in the 1<sup>st</sup> century.<sup>1</sup></p>"

    def test_html_to_text_emits_no_sentinel_tokens(self):
        """The coordinator-verified input must not leak FOOTNOTE_* to the caller."""
        out = epub_mod.html_to_text(self.SUP_HTML)
        assert "FOOTNOTE_START" not in out
        assert "FOOTNOTE_END" not in out
        assert "\x02" not in out

    def test_default_cleaner_pipeline_strips_any_surviving_sentinel(self):
        """clean_text() is the default pipeline — it must not pass sentinels through."""
        dirty = "A note\x02FOOTNOTE_START\x02 one \x02FOOTNOTE_END\x02here."
        out = tc.clean_text(dirty)
        assert "FOOTNOTE_START" not in out
        assert "FOOTNOTE_END" not in out
        assert "\x02" not in out

    def test_ordinal_sup_is_not_mangled(self):
        """'1<sup>st</sup>' must read as '1st', not '1 st'."""
        out = epub_mod.html_to_text(self.SUP_HTML)
        assert "1st century" in out
        assert "1 st" not in out

    @requires_ebooklib
    def test_chapter_raw_text_has_no_control_characters(self, tmp_path):
        """Invariant: no chapter raw_text may carry a C0 control besides \\n/\\t."""
        body = (
            "<h1>One</h1><p>"
            + ("word " * 60)
            + 'Footnoted<a epub:type="noteref" href="#n1">1</a>.</p>'
            '<aside epub:type="footnote" id="n1">A note body.</aside>'
        )
        path = _make_epub(tmp_path, [("c1.xhtml", "One", body)])
        _meta, chapters = epub_mod.parse_epub(path, min_chapter_words=10)
        assert chapters
        for ch in chapters:
            bad = _ILLEGAL_CONTROL_RE.findall(ch.raw_text)
            assert not bad, f"control chars {bad!r} in chapter {ch.title!r}"
            assert "FOOTNOTE_" not in ch.raw_text

    @requires_ebooklib
    def test_footnote_behavior_skip_removes_the_note(self, tmp_path):
        """footnote_behavior='skip' must actually delete footnote content."""
        body = (
            "<h1>One</h1><p>"
            + ("word " * 60)
            + 'Text<a epub:type="noteref" href="#n1">42</a>.</p>'
            '<aside epub:type="footnote" id="n1">UNIQUEFOOTNOTEBODY</aside>'
        )
        path = _make_epub(tmp_path, [("c1.xhtml", "One", body)])
        _meta, chapters = epub_mod.parse_epub(
            path, min_chapter_words=10, footnote_behavior="skip"
        )
        joined = "\n".join(c.raw_text for c in chapters)
        assert "UNIQUEFOOTNOTEBODY" not in joined

    @requires_ebooklib
    def test_footnote_behavior_end_collects_the_note(self, tmp_path):
        """footnote_behavior='end' must move notes to the end with a reference."""
        body = (
            "<h1>One</h1><p>"
            + ("word " * 60)
            + 'Text<a epub:type="noteref" href="#n1">42</a>.</p>'
            '<aside epub:type="footnote" id="n1">UNIQUEFOOTNOTEBODY</aside>'
        )
        path = _make_epub(tmp_path, [("c1.xhtml", "One", body)])
        _meta, chapters = epub_mod.parse_epub(
            path, min_chapter_words=10, footnote_behavior="end"
        )
        joined = "\n".join(c.raw_text for c in chapters)
        assert "UNIQUEFOOTNOTEBODY" in joined
        assert re.search(r"Footnote \d+:", joined)

    def test_skip_does_not_eat_ordinal_suffixes(self):
        """'skip' must not delete '<sup>st</sup>' — that is an ordinal, not a note."""
        out = epub_mod.html_to_text(self.SUP_HTML, footnote_behavior="skip")
        assert "1st century" in out


# ---------------------------------------------------------------------------
# parser-2-footnote-span-close
# ---------------------------------------------------------------------------
class TestFootnoteSpanClosing:
    START = epub_mod.HTMLTextExtractor.FOOTNOTE_START
    END = epub_mod.HTMLTextExtractor.FOOTNOTE_END

    def _raw(self, html: str) -> str:
        ex = epub_mod.HTMLTextExtractor()
        ex.feed(html)
        return ex.get_text()

    def test_noteref_anchor_span_opens_and_closes(self):
        """EPUB3's canonical marker is <a epub:type="noteref"> — it must close."""
        raw = self._raw('<p>Prose<a epub:type="noteref" href="#n1">1</a> more.</p>')
        assert raw.count(self.START) == 1
        assert raw.count(self.END) == 1
        assert raw.index(self.START) < raw.index(self.END)

    def test_self_closing_noteref_is_balanced(self):
        raw = self._raw('<p>Prose<a epub:type="noteref" href="#n1"/> more.</p>')
        assert raw.count(self.START) == raw.count(self.END)

    def test_stray_end_tag_cannot_close_an_orphan_span(self):
        """A later </sup> must not close an <a epub:type=noteref> span."""
        raw = self._raw(
            '<p>A<a epub:type="noteref" href="#n">1</a>'
            "B</sup>C legitimate prose D</p>"
        )
        assert raw.count(self.START) == raw.count(self.END)
        # 'skip' must not swallow the legitimate prose that follows.
        cleaned = epub_mod.process_footnotes(raw, "skip")
        assert "legitimate prose" in cleaned

    def test_unclosed_span_is_force_closed(self):
        raw = self._raw('<p>A<aside epub:type="footnote">dangling</p>')
        assert raw.count(self.START) == raw.count(self.END)


# ---------------------------------------------------------------------------
# parser-3-i18n-said-patterns
# ---------------------------------------------------------------------------
def _attributes(profile, text: str) -> set[str]:
    """Names that the profile's said-patterns extract from text."""
    found = set()
    for pat in profile.build_said_patterns():
        for m in pat.finditer(text):
            found.add(m.group(1).strip())
    return found


class TestAttributionIsNotAsciiOnly:
    def test_german_umlaut_name_attributes(self):
        de = get_profile("de")
        assert "Mueller" in _attributes(de, "sagte Mueller")   # already worked
        assert "Müller" in _attributes(de, "sagte Müller")     # did not

    @pytest.mark.parametrize(
        "code, text, name",
        [
            ("en", '"Yes," said Holmes.', "Holmes"),
            ("de", "»Ja«, sagte Müller.", "Müller"),
            ("fr", "« Oui », dit Séverine.", "Séverine"),
            ("es", "—Sí —dijo Muñoz.", "Muñoz"),
            ("it", "«Sì», disse Niccolò.", "Niccolò"),
            ("pt", "— Sim — disse Conceição.", "Conceição"),
            ("ja", "「はい」と太郎は言った。", "太郎"),
        ],
    )
    def test_native_script_name_per_shipped_profile(self, code, text, name):
        profile = get_profile(code)
        assert name in _attributes(profile, text), (
            f"{code}: no said-pattern matched {name!r} in {text!r}"
        )

    def test_japanese_patterns_do_not_require_whitespace(self):
        """Japanese is written without spaces — a \\s+ separator can never match."""
        ja = get_profile("ja")
        assert _attributes(ja, "太郎は言った"), "ja attribution must not need spaces"

    def test_english_name_pattern_is_unchanged(self):
        """The English patterns must stay byte-for-byte what they were."""
        en = get_profile("en")
        pats = [p.pattern for p in en.build_said_patterns()]
        expected_name = (
            r"(?:(?:Mr\.|Mrs\.|Ms\.|Dr\.|Miss|Captain|Lord|Lady|Sir|the|Old|Young)\s+)?"
            r"[A-Z][a-z]+"
        )
        assert any(expected_name in p for p in pats)
        assert len(pats) == 3


# ---------------------------------------------------------------------------
# parser-4-es-emdash-dialogue
# ---------------------------------------------------------------------------
class TestSpanishAndGermanDialogueMarkers:
    def test_spanish_ships_an_em_dash_marker(self):
        es = get_profile("es")
        opens = [o for o, _c in es.dialogue_quotes]
        assert "—" in opens, "Spanish must ship the line-leading em dash"

    def test_german_ships_the_reversed_guillemet(self):
        de = get_profile("de")
        pairs = set(de.dialogue_quotes) | set(de.smart_quotes)
        assert ("»", "«") in pairs, "standard German uses »…«"

    @pytest.mark.parametrize(
        "code, text",
        [
            ("es", "—Ven aquí —dijo ella.\nLuego se marchó.\n"),
            ("de", "»Komm her«, sagte sie.\n"),
            ("fr", "« Viens ici », dit-elle.\n"),
            ("it", "«Vieni qui», disse lei.\n"),
            ("pt", "— Vem cá — disse ela.\nDepois saiu.\n"),
            ("ja", "「こっちに来て」と彼女は言った。\n"),
            ("en", '"Come here," she said.\n'),
        ],
    )
    def test_dominant_convention_detects_dialogue(self, code, text):
        from audiobooker.casting.dialogue import detect_dialogue

        profile = get_profile(code)
        segs = detect_dialogue(text, profile=profile)
        assert any(is_d for _c, is_d, _s, _e in segs), (
            f"{code}: no dialogue detected in its dominant convention"
        )


# ---------------------------------------------------------------------------
# parser-5-natural-sort
# ---------------------------------------------------------------------------
class TestNaturalSortWholeStem:
    @pytest.mark.parametrize(
        "stems, expected",
        [
            (
                ["chapter1", "chapter10", "chapter11", "chapter2", "chapter12"],
                ["chapter1", "chapter2", "chapter10", "chapter11", "chapter12"],
            ),
            (
                ["part-1", "part-10", "part-2"],
                ["part-1", "part-2", "part-10"],
            ),
            (
                ["10 of 12", "2 of 12", "1 of 12"],
                ["1 of 12", "2 of 12", "10 of 12"],
            ),
        ],
    )
    def test_numbers_anywhere_in_the_stem_sort_numerically(self, stems, expected):
        assert sorted(stems, key=text_mod._natural_sort_key) == expected

    def test_leading_numbered_files_still_sort_before_unnumbered(self):
        stems = ["appendix", "1_intro", "10_end", "2_middle"]
        ordered = sorted(stems, key=text_mod._natural_sort_key)
        assert ordered == ["1_intro", "2_middle", "10_end", "appendix"]

    def test_folder_input_orders_chapter_n_correctly(self, tmp_path):
        for n in (1, 2, 10, 11, 12):
            (tmp_path / f"chapter{n}.txt").write_text(f"body {n}", encoding="utf-8")
        chapters = text_mod.read_folder_chapters(tmp_path)
        assert [c for _t, c in chapters] == [
            "body 1", "body 2", "body 10", "body 11", "body 12",
        ]


# ---------------------------------------------------------------------------
# parser-6 / parser-7 — PDF heading + short-section logging
# ---------------------------------------------------------------------------
class _FakePage:
    def __init__(self, text):
        self._text = text

    def get_text(self, _mode):
        return self._text


class _FakeDoc:
    def __init__(self, pages, metadata=None, toc=None):
        self._pages = pages
        self.metadata = metadata or {}
        self._toc = toc
        self.closed = False

    def __len__(self):
        return len(self._pages)

    def __getitem__(self, i):
        return self._pages[i]

    def get_toc(self, *_a, **_k):
        if self._toc is None:
            return []
        return self._toc

    def close(self):
        self.closed = True


def _install_fake_fitz(monkeypatch, doc):
    fake = types.ModuleType("fitz")
    fake.open = lambda *_a, **_k: doc
    monkeypatch.setitem(sys.modules, "fitz", fake)


def _make_pdf(tmp_path, name="book.pdf"):
    p = tmp_path / name
    p.write_bytes(b"%PDF-1.4 fake")
    return p


class TestPdfHeadingHeuristic:
    def test_all_caps_line_ending_in_punctuation_is_not_a_heading(self):
        pats = pdf_mod._compile_chapter_patterns(None)
        assert pdf_mod._is_chapter_heading("AND THEN HE LEFT.", pats) is None

    def test_long_all_caps_line_is_not_a_heading(self):
        pats = pdf_mod._compile_chapter_patterns(None)
        long_line = "HE WALKED OUT INTO THE COLD GREY MORNING"
        assert pdf_mod._is_chapter_heading(long_line, pats) is None

    def test_all_caps_prose_inside_a_paragraph_is_not_promoted(
        self, tmp_path, monkeypatch
    ):
        """'HE SLAMMED THE DOOR' mid-paragraph must not become a chapter."""
        body = "word " * 80
        page = f"Chapter 1\n\n{body}\nHE SLAMMED THE DOOR\n{body}"
        _install_fake_fitz(monkeypatch, _FakeDoc(pages=[_FakePage(page)]))
        _meta, chapters = pdf_mod.parse_pdf(_make_pdf(tmp_path), min_chapter_words=10)
        assert len(chapters) == 1, [c.title for c in chapters]
        assert "HE SLAMMED THE DOOR" in chapters[0].raw_text

    def test_repeated_running_head_does_not_split_every_page(self, tmp_path, monkeypatch):
        """A print running head on every page must not yield one chapter per page."""
        body = "word " * 80
        pages = [f"THE GREAT GATSBY\n{body}" for _ in range(12)]
        _install_fake_fitz(monkeypatch, _FakeDoc(pages=[_FakePage(p) for p in pages]))
        _meta, chapters = pdf_mod.parse_pdf(_make_pdf(tmp_path), min_chapter_words=10)
        assert len(chapters) <= 2, (
            f"running head produced {len(chapters)} chapters"
        )

    def test_pdf_outline_is_preferred_over_text_heuristics(self, tmp_path, monkeypatch):
        body = "word " * 80
        pages = [f"ALPHA\n{body}", f"BETA\n{body}"]
        toc = [[1, "Real One", 1], [1, "Real Two", 2]]
        _install_fake_fitz(
            monkeypatch, _FakeDoc(pages=[_FakePage(p) for p in pages], toc=toc)
        )
        _meta, chapters = pdf_mod.parse_pdf(_make_pdf(tmp_path), min_chapter_words=10)
        assert [c.title for c in chapters] == ["Real One", "Real Two"]

    def test_heading_count_is_logged(self, tmp_path, monkeypatch, caplog):
        body = "word " * 80
        pages = [f"Chapter 1\n{body}\nChapter 2\n{body}"]
        _install_fake_fitz(monkeypatch, _FakeDoc(pages=[_FakePage(p) for p in pages]))
        with caplog.at_level(logging.INFO, logger="audiobooker.parser"):
            pdf_mod.parse_pdf(_make_pdf(tmp_path), min_chapter_words=10)
        assert any("heading" in r.message.lower() for r in caplog.records)


class TestPdfShortSectionLogging:
    def test_short_section_drop_is_logged(self, tmp_path, monkeypatch, caplog):
        """parse_epub logs 'Skipping short section' — parse_pdf logged nothing."""
        long_body = "word " * 80
        page = f"Chapter 1\nA short dedication.\nChapter 2\n{long_body}"
        _install_fake_fitz(monkeypatch, _FakeDoc(pages=[_FakePage(page)]))
        with caplog.at_level(logging.INFO, logger="audiobooker.parser"):
            pdf_mod.parse_pdf(_make_pdf(tmp_path), min_chapter_words=20)
        assert any(
            "skipping short section" in r.message.lower() for r in caplog.records
        ), "a dropped short section must be logged, not vanish silently"

    def test_keep_titled_short_chapters_keeps_the_prologue(self, tmp_path, monkeypatch):
        long_body = "word " * 80
        page = f"Chapter 1\nA short dedication.\nChapter 2\n{long_body}"
        _install_fake_fitz(monkeypatch, _FakeDoc(pages=[_FakePage(page)]))
        _meta, chapters = pdf_mod.parse_pdf(
            _make_pdf(tmp_path),
            min_chapter_words=20,
            keep_titled_short_chapters=True,
        )
        assert any("dedication" in c.raw_text for c in chapters)


# ---------------------------------------------------------------------------
# parser-8-toc-monotonicity
# ---------------------------------------------------------------------------
@requires_ebooklib
class TestTocMonotonicity:
    def test_out_of_order_toc_yields_no_empty_chapter(self, tmp_path):
        from ebooklib import epub

        body = (
            '<h1>Doc</h1>'
            '<div id="a"><p>' + ("alpha " * 60) + "</p></div>"
            '<div id="b"><p>' + ("beta " * 60) + "</p></div>"
        )
        # TOC lists the SECOND anchor first — positions are not monotonic.
        toc = [
            epub.Link("c1.xhtml#b", "Beta", "beta"),
            epub.Link("c1.xhtml#a", "Alpha", "alpha"),
        ]
        path = _make_epub(tmp_path, [("c1.xhtml", "Doc", body)], toc=toc)
        _meta, chapters = epub_mod.parse_epub(path, min_chapter_words=5)
        for ch in chapters:
            assert ch.raw_text.split(), f"empty chapter {ch.title!r} survived"
        # And prose must not be filed under the wrong title.
        for ch in chapters:
            if ch.title == "Alpha":
                assert "beta" not in ch.raw_text
            if ch.title == "Beta":
                assert "alpha" not in ch.raw_text


# ---------------------------------------------------------------------------
# parser-9-toc-href-suffix
# ---------------------------------------------------------------------------
class TestTocHrefResolution:
    def _docs(self, names):
        class _Item:
            def __init__(self, name, text):
                self._name = name
                self._text = text

            def get_name(self):
                return self._name

            def get_content(self):
                return self._text.encode("utf-8")

        return {n: _Item(n, f"<p>{n} " + ("word " * 60) + "</p>") for n in names}

    def test_suffix_match_does_not_cross_a_name_boundary(self):
        """href 'ch1.xhtml' must not bind to 'OEBPS/xch1.xhtml'."""
        docs = self._docs(["OEBPS/xch1.xhtml", "OEBPS/ch1.xhtml", "OEBPS/ch2.xhtml"])
        entries = [("One", "ch1.xhtml"), ("Two", "ch2.xhtml")]
        chapters = epub_mod._chapters_from_toc(
            entries,
            min_chapter_words=5,
            keep_titled_short_chapters=True,
            docs_by_name=docs,
        )
        assert chapters is not None
        by_title = {c.title: c for c in chapters}
        assert "xch1" not in by_title["One"].raw_text
        assert by_title["One"].source_file == "OEBPS/ch1.xhtml"

    def test_ambiguous_href_is_treated_as_unusable(self):
        """Two manifest entries ending in the same name must not be guessed at."""
        docs = self._docs(["OEBPS/a/ch1.xhtml", "OEBPS/b/ch1.xhtml", "OEBPS/ch2.xhtml"])
        entries = [("One", "ch1.xhtml"), ("Two", "ch2.xhtml")]
        chapters = epub_mod._chapters_from_toc(
            entries,
            min_chapter_words=5,
            keep_titled_short_chapters=True,
            docs_by_name=docs,
        )
        assert chapters is None, "an ambiguous href must fall back to spine splitting"


# ---------------------------------------------------------------------------
# parser-10-pron-overrides
# ---------------------------------------------------------------------------
class TestPronunciationOverrides:
    def test_cjk_key_substitutes(self):
        out = tc.apply_pronunciation_overrides(
            "東京へ行く", {"東京": "トウキョウ"}
        )
        assert out == "トウキョウへ行く"

    def test_backslash_replacement_is_literal_not_a_template(self):
        out = tc.apply_pronunciation_overrides("say Xyz now", {"Xyz": r"\ps\g<0>"})
        assert out == r"say \ps\g<0> now"

    def test_ascii_word_boundary_still_applies(self):
        out = tc.apply_pronunciation_overrides("cat category", {"cat": "feline"})
        assert out == "feline category"

    def test_zero_substitution_override_warns(self, caplog):
        with caplog.at_level(logging.WARNING, logger="audiobooker.parser"):
            tc.apply_pronunciation_overrides("nothing here", {"Zzzz": "zed"})
        assert any("Zzzz" in r.message for r in caplog.records), (
            "an override that never fired must warn"
        )
