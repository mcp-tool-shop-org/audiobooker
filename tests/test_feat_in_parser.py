"""Parser input-fidelity features (FEAT-IN-002/003/004/005/006/007).

Real books are messier than the fixtures the parsers were built against. Every
test here is built on a fixture shaped like a book that actually ships:

- FEAT-IN-002  an EPUB whose TOC is stale — it lists chapter 2 before chapter 1
               and never mentions the afterword (a Word -> Calibre export).
- FEAT-IN-003  two otherwise-identical PDFs differing only in whether their
               outline is flat or a Part > Chapter tree.
- FEAT-IN-004  a Project Gutenberg text, legal header and full licence intact.
- FEAT-IN-005  a DOCX with a dramatis-personae table between two chapters.
- FEAT-IN-006  chapter headings in several shapes and two languages.
- FEAT-IN-007  a novel whose only chapter marks are bare numerals, and a
               paginated document whose bare numerals are page numbers.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from audiobooker.language.profile import get_profile
from audiobooker.parser import text as text_mod


# ---------------------------------------------------------------------------
# Optional-extra guards (mirrors tests/test_epub_parsing.py)
# ---------------------------------------------------------------------------
def _has(module: str) -> bool:
    try:
        __import__(module)
        return True
    except ImportError:
        return False


requires_ebooklib = pytest.mark.skipif(
    not _has("ebooklib"),
    reason="ebooklib not installed — install with: pip install ebooklib",
)
requires_pymupdf = pytest.mark.skipif(
    not _has("pymupdf"),
    reason="pymupdf not installed — install with: pip install pymupdf",
)
requires_python_docx = pytest.mark.skipif(
    not _has("docx"),
    reason="python-docx not installed — install with: pip install python-docx",
)


# ---------------------------------------------------------------------------
# Prose the fixtures are built from
# ---------------------------------------------------------------------------
_PROSE = (
    "The lamps along the quay had gone out one by one, and the harbour lay "
    "under a thin skin of ice that cracked whenever the swell came in "
    "beneath it. Mara counted the boats twice and got a different answer "
    "each time, which told her more about her hands than about the boats. "
)


def prose(words: int, seed: str = "") -> str:
    base = (seed + " " + _PROSE).split()
    out: list[str] = []
    while len(out) < words:
        out.extend(base)
    return " ".join(out[:words])


# ===========================================================================
# FEAT-IN-002 — EPUB TOC splitting deletes spine documents the TOC omits
# ===========================================================================
def _build_epub(path: Path, *, toc_order, include_afterword_in_toc: bool):
    """Spine [Part1, Ch1, Ch2, Part2, Ch3, Ch4, Afterword] with a chosen TOC."""
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("feat-in-002")
    book.set_title("The Harbour Bell")
    book.set_language("en")
    book.add_author("A. Novelist")

    made = {}

    def doc(name, title, words, seed):
        item = epub.EpubHtml(title=title, file_name=name, lang="en")
        item.content = (
            f"<html><head><title>{title}</title></head><body>"
            f"<h1>{title}</h1><p>{prose(words, seed)}</p></body></html>"
        )
        book.add_item(item)
        made[name] = item
        return item

    spine = [
        doc("part1.xhtml", "Part One", 120, "part one"),
        doc("ch1.xhtml", "Chapter 1", 240, "chapter one"),
        doc("ch2.xhtml", "Chapter 2", 240, "chapter two"),
        doc("part2.xhtml", "Part Two", 120, "part two"),
        doc("ch3.xhtml", "Chapter 3", 240, "chapter three"),
        doc("ch4.xhtml", "Chapter 4", 240, "chapter four"),
        doc("afterword.xhtml", "Afterword", 220, "afterword"),
    ]
    book.spine = spine

    names = list(toc_order)
    if include_afterword_in_toc:
        names.append("afterword.xhtml")
    book.toc = tuple(
        epub.Link(n, made[n].title, n.replace(".xhtml", "")) for n in names
    )
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(str(path), book)
    return path


_SPINE_ORDER = [
    "part1.xhtml", "ch1.xhtml", "ch2.xhtml",
    "part2.xhtml", "ch3.xhtml", "ch4.xhtml",
]
# A stale TOC: chapter 2 listed before chapter 1, afterword never mentioned.
_STALE_TOC_ORDER = [
    "part1.xhtml", "ch2.xhtml", "ch1.xhtml",
    "part2.xhtml", "ch3.xhtml", "ch4.xhtml",
]


@requires_ebooklib
class TestEpubTocDropsSpineDocuments:
    """FEAT-IN-002."""

    @pytest.fixture
    def stale(self, tmp_path):
        from audiobooker.parser.epub import parse_epub

        path = _build_epub(
            tmp_path / "stale.epub",
            toc_order=_STALE_TOC_ORDER,
            include_afterword_in_toc=False,
        )
        return parse_epub(path, min_chapter_words=50)

    def test_document_the_toc_omits_is_not_deleted(self, stale):
        """220 words of real prose used to vanish with no signal at all."""
        _, chapters = stale
        joined = "\n".join(c.raw_text for c in chapters)
        assert "afterword" in joined.lower(), (
            "the afterword's prose was dropped: "
            f"{[c.source_file for c in chapters]}"
        )
        assert any(c.source_file == "afterword.xhtml" for c in chapters)

    def test_the_dropped_document_is_named_in_a_warning(self, tmp_path, caplog):
        from audiobooker.parser.epub import parse_epub

        path = _build_epub(
            tmp_path / "stale.epub",
            toc_order=_STALE_TOC_ORDER,
            include_afterword_in_toc=False,
        )
        with caplog.at_level(logging.WARNING, logger="audiobooker.parser"):
            parse_epub(path, min_chapter_words=50)
        warnings = " ".join(
            r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
        )
        assert "afterword.xhtml" in warnings, warnings

    def test_chapters_are_narrated_in_spine_order_not_toc_order(self, stale):
        """The spine is the EPUB's reading order; the TOC is navigation."""
        _, chapters = stale
        assert [c.source_file for c in chapters] == _SPINE_ORDER + [
            "afterword.xhtml"
        ]

    def test_the_reordering_is_warned_about(self, tmp_path, caplog):
        from audiobooker.parser.epub import parse_epub

        path = _build_epub(
            tmp_path / "stale.epub",
            toc_order=_STALE_TOC_ORDER,
            include_afterword_in_toc=False,
        )
        with caplog.at_level(logging.WARNING, logger="audiobooker.parser"):
            parse_epub(path, min_chapter_words=50)
        warnings = " ".join(
            r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
        )
        assert "reading order" in warnings.lower(), warnings

    def test_chapter_indexes_stay_contiguous_after_reconciliation(self, stale):
        _, chapters = stale
        assert [c.index for c in chapters] == list(range(len(chapters)))

    def test_toc_titles_are_kept(self, stale):
        _, chapters = stale
        assert [c.title for c in chapters] == [
            "Part One", "Chapter 1", "Chapter 2",
            "Part Two", "Chapter 3", "Chapter 4", "Afterword",
        ]

    def test_a_healthy_toc_is_unchanged_and_silent(self, tmp_path, caplog):
        """No spurious warnings when the TOC agrees with the spine."""
        from audiobooker.parser.epub import parse_epub

        path = _build_epub(
            tmp_path / "healthy.epub",
            toc_order=_SPINE_ORDER,
            include_afterword_in_toc=True,
        )
        with caplog.at_level(logging.WARNING, logger="audiobooker.parser"):
            _, chapters = parse_epub(path, min_chapter_words=50)
        assert [c.source_file for c in chapters] == _SPINE_ORDER + [
            "afterword.xhtml"
        ]
        noisy = [
            r.getMessage() for r in caplog.records
            if r.levelno >= logging.WARNING
        ]
        assert not noisy, noisy

    def test_use_toc_off_is_unaffected(self, tmp_path):
        from audiobooker.parser.epub import parse_epub

        path = _build_epub(
            tmp_path / "stale.epub",
            toc_order=_STALE_TOC_ORDER,
            include_afterword_in_toc=False,
        )
        _, chapters = parse_epub(path, min_chapter_words=50, use_toc="off")
        # The spine path is untouched: every content document, in spine order.
        # (It also emits the EPUB nav document as a short titled chapter —
        # pre-existing behaviour of that path, not something this change
        # introduced.)
        assert [c.source_file for c in chapters][:7] == _SPINE_ORDER + [
            "afterword.xhtml"
        ]


# ===========================================================================
# FEAT-IN-003 — PDF nested outlines are discarded
# ===========================================================================
def _write_pdf(path: Path, toc: list) -> Path:
    import pymupdf

    doc = pymupdf.open()
    for page_no in range(1, 9):
        page = doc.new_page()
        page.insert_textbox(
            pymupdf.Rect(60, 60, 540, 740), prose(150, f"page {page_no}"),
            fontsize=11,
        )
    doc.set_toc(toc)
    doc.save(str(path))
    doc.close()
    return path


@requires_pymupdf
class TestPdfNestedOutline:
    """FEAT-IN-003 — two PDFs differing ONLY in outline nesting."""

    FLAT = [[1, "Part One", 1], [1, "Chapter 1", 2],
            [1, "Chapter 2", 4], [1, "Chapter 3", 6]]
    NESTED = [[1, "Part One", 1], [2, "Chapter 1", 2],
              [2, "Chapter 2", 4], [2, "Chapter 3", 6]]

    def test_nesting_does_not_change_the_chapters(self, tmp_path):
        from audiobooker.parser.pdf import parse_pdf

        _, flat = parse_pdf(
            _write_pdf(tmp_path / "flat.pdf", self.FLAT), min_chapter_words=20
        )
        _, nested = parse_pdf(
            _write_pdf(tmp_path / "nested.pdf", self.NESTED),
            min_chapter_words=20,
        )
        assert [c.title for c in nested] == [c.title for c in flat]
        assert len(nested) == 4

    def test_nested_outline_does_not_fall_through_to_text_heuristics(
        self, tmp_path, caplog
    ):
        from audiobooker.parser.pdf import parse_pdf

        path = _write_pdf(tmp_path / "nested.pdf", self.NESTED)
        with caplog.at_level(logging.INFO, logger="audiobooker.parser"):
            parse_pdf(path, min_chapter_words=20)
        summary = [
            r.getMessage() for r in caplog.records if "Parsed PDF" in r.getMessage()
        ]
        assert summary and "source=outline" in summary[0], summary

    def test_a_deep_outline_does_not_shred_a_short_book(self, tmp_path):
        """The original top-level-only rule existed to prevent this; keep it."""
        from audiobooker.parser.pdf import parse_pdf

        deep = [[1, "Part One", 1]]
        for page in range(1, 9):
            deep.append([2, f"Chapter {page}", page])
            deep.append([3, f"Scene {page}a", page])
            deep.append([4, f"Beat {page}i", page])
        path = _write_pdf(tmp_path / "deep.pdf", deep)
        _, chapters = parse_pdf(path, min_chapter_words=20)
        # 8 pages: one chapter per page is the shredding shape, not more.
        assert len(chapters) <= 8, [c.title for c in chapters]

    def test_outline_with_only_one_usable_level_still_falls_back(self, tmp_path):
        from audiobooker.parser.pdf import parse_pdf

        path = _write_pdf(tmp_path / "one.pdf", [[1, "The Whole Book", 1]])
        _, chapters = parse_pdf(path, min_chapter_words=20)
        assert len(chapters) == 1


# ===========================================================================
# FEAT-IN-005 — DOCX tables are deleted
# ===========================================================================
def _build_docx(path: Path, *, merged: bool = False) -> Path:
    import docx

    d = docx.Document()
    d.core_properties.title = "The Harbour Bell"
    d.add_heading("Chapter 1", level=1)
    d.add_paragraph(prose(120, "chapter one"))
    d.add_paragraph("The following table lists the principal players.")

    table = d.add_table(rows=3, cols=2)
    rows = [
        ("Mara Quill", "harbourmaster of Ashgate"),
        ("Tomas Reyne", "keeper of the bell"),
        ("Inspector Halloway", "sent up from the capital"),
    ]
    for cell_row, (name, role) in zip(table.rows, rows):
        cell_row.cells[0].text = name
        cell_row.cells[1].text = role
    if merged:
        merged_cell = table.rows[0].cells[0].merge(table.rows[0].cells[1])
        merged_cell.text = "DRAMATIS PERSONAE"

    d.add_paragraph("She read the list twice before she believed it.")
    d.add_heading("Chapter 2", level=1)
    d.add_paragraph(prose(120, "chapter two"))
    d.save(str(path))
    return path


@requires_python_docx
class TestDocxTables:
    """FEAT-IN-005."""

    def test_table_cells_are_narrated(self, tmp_path):
        from audiobooker.parser.docx import parse_docx

        _, chapters = parse_docx(
            _build_docx(tmp_path / "book.docx"), min_chapter_words=20
        )
        joined = "\n".join(c.raw_text for c in chapters)
        for cell in ("Mara Quill", "harbourmaster of Ashgate",
                     "Inspector Halloway", "sent up from the capital"):
            assert cell in joined, f"{cell!r} was deleted with the table"

    def test_table_lands_where_the_author_put_it(self, tmp_path):
        """A dangling 'The following table lists…' with nothing after it."""
        from audiobooker.parser.docx import parse_docx

        _, chapters = parse_docx(
            _build_docx(tmp_path / "book.docx"), min_chapter_words=20
        )
        body = chapters[0].raw_text
        lead_in = body.index("The following table lists")
        table_at = body.index("Mara Quill")
        after = body.index("She read the list twice")
        assert lead_in < table_at < after, body

    def test_a_table_does_not_start_a_chapter(self, tmp_path):
        from audiobooker.parser.docx import parse_docx

        _, chapters = parse_docx(
            _build_docx(tmp_path / "book.docx"), min_chapter_words=20
        )
        assert [c.title for c in chapters] == ["Chapter 1", "Chapter 2"]

    def test_rows_are_terminated_so_tts_does_not_run_them_together(
        self, tmp_path
    ):
        from audiobooker.parser.docx import parse_docx

        _, chapters = parse_docx(
            _build_docx(tmp_path / "book.docx"), min_chapter_words=20
        )
        assert "harbourmaster of Ashgate." in chapters[0].raw_text

    def test_merged_cells_are_not_read_twice(self, tmp_path):
        from audiobooker.parser.docx import parse_docx

        _, chapters = parse_docx(
            _build_docx(tmp_path / "merged.docx", merged=True),
            min_chapter_words=20,
        )
        body = chapters[0].raw_text
        assert body.count("DRAMATIS PERSONAE") == 1, body

    def test_table_count_is_reported(self, tmp_path, caplog):
        from audiobooker.parser.docx import parse_docx

        with caplog.at_level(logging.INFO, logger="audiobooker.parser"):
            parse_docx(_build_docx(tmp_path / "book.docx"), min_chapter_words=20)
        summary = [
            r.getMessage() for r in caplog.records
            if "Parsed DOCX" in r.getMessage()
        ]
        assert summary and "tables=1" in summary[0], summary


# ===========================================================================
# FEAT-IN-006 — chapter titles are mis-composed
# ===========================================================================
class TestChapterTitleComposition:
    """FEAT-IN-006 — the capture group is the chapter NUMBER, not the title."""

    @pytest.mark.parametrize(
        "lang,heading,expected",
        [
            # The reported cases.
            ("en", "Chapter 1", "Chapter 1"),
            ("en", "CHAPTER TWENTY-ONE", "CHAPTER TWENTY-ONE"),
            ("es", "Capítulo Uno", "Capítulo Uno"),
            # Must not regress.
            ("en", "Chapter 1: The Harbour", "Chapter 1: The Harbour"),
            ("en", "Chapter 7 - The Bell", "Chapter 7 - The Bell"),
            ("en", "Part II", "Part II"),
            ("en", "# One", "One"),
            ("en", "## Two", "Two"),
            ("en", "1. The Harbour", "Chapter 1: The Harbour"),
            # A localized heading must not be re-worded in English.
            ("es", "Capítulo Uno: El Puerto", "Capítulo Uno: El Puerto"),
            ("fr", "Chapitre 3", "Chapitre 3"),
            ("it", "Capitolo 4", "Capitolo 4"),
            ("de", "Kapitel 5", "Kapitel 5"),
            ("pt", "Capítulo 6", "Capítulo 6"),
        ],
    )
    def test_heading_line_becomes_the_chapter_title(self, lang, heading, expected):
        profile = get_profile(lang)
        body = (
            f"{heading}\n\n{prose(60, 'a')}\n\n"
            f"{heading.replace('1', '2').replace('ONE', 'TWO')}\n\n"
            f"{prose(60, 'b')}"
        )
        chapters = text_mod.split_into_chapters(body, profile=profile)
        assert chapters, "no chapters were produced"
        assert chapters[0][0] == expected

    def test_pdf_uses_the_same_composer(self):
        from audiobooker.parser.pdf import _is_chapter_heading

        assert _is_chapter_heading("Chapter 1") == "Chapter 1"
        assert _is_chapter_heading("Chapter 1: The Bell") == "Chapter 1: The Bell"

    @requires_python_docx
    def test_docx_uses_the_same_composer(self):
        from audiobooker.parser.docx import (
            _compile_chapter_patterns, _heading_from_patterns,
        )

        patterns = _compile_chapter_patterns(get_profile("es"))
        assert _heading_from_patterns("Capítulo Uno", patterns) == "Capítulo Uno"

    def test_compose_is_safe_for_a_pattern_with_no_groups(self):
        import re

        line = "PROLOGUE"
        match = re.compile(r"^PROLOGUE$").match(line)
        assert text_mod.compose_chapter_title(line, match) == "PROLOGUE"


# ===========================================================================
# FEAT-IN-007 — bare Roman / Arabic section headings
# ===========================================================================
_ROMANS = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
           "XI", "XII"]


def bare_numeral_book(n=12, words_per_chapter=2600, roman=True) -> str:
    """A novel whose only chapter marks are bare numerals."""
    out = ["THE HARBOUR BELL", "by A. Novelist", ""]
    for i in range(n):
        out += ["", _ROMANS[i] if roman else str(i + 1), ""]
        for p in range(max(1, words_per_chapter // 65)):
            out += [prose(65, f"s{i}p{p}"), ""]
    return "\n".join(out)


def page_numbered_text(pages=180, words_per_page=310) -> str:
    """A flat export whose only bare numerals are PAGE numbers (~310 words
    per page — the discriminator the detector relies on)."""
    out: list[str] = []
    for p in range(1, pages + 1):
        for k in range(words_per_page // 62):
            out += [prose(62, f"p{p}l{k}"), ""]
        out += ["", str(p), ""]
    return "\n".join(out)


class TestBareNumeralHeadings:
    """FEAT-IN-007."""

    def test_bare_roman_sections_are_detected(self):
        chapters = text_mod.split_into_chapters(bare_numeral_book(roman=True))
        titles = [t for t, _ in chapters]
        assert "I" in titles and "XII" in titles, titles
        assert len(chapters) >= 12, titles

    def test_bare_arabic_sections_are_detected(self):
        chapters = text_mod.split_into_chapters(bare_numeral_book(roman=False))
        titles = [t for t, _ in chapters]
        assert "1" in titles and "12" in titles, titles

    def test_short_numbered_sections_are_still_detected(self):
        book = bare_numeral_book(n=12, words_per_chapter=700, roman=False)
        chapters = text_mod.split_into_chapters(book)
        assert len(chapters) >= 12, [t for t, _ in chapters]

    def test_page_numbers_are_not_mistaken_for_chapters(self):
        """The regression this guard exists for — 180 pages, no chapters."""
        chapters = text_mod.split_into_chapters(page_numbered_text(180))
        assert len(chapters) == 1, [t for t, _ in chapters][:10]

    def test_a_short_paginated_document_is_also_safe(self):
        chapters = text_mod.split_into_chapters(page_numbered_text(40))
        assert len(chapters) == 1, [t for t, _ in chapters][:10]

    def test_real_headings_always_beat_bare_numerals(self):
        """The tier is last-resort: it must never compete with a real pattern."""
        lines = []
        for i in range(1, 9):
            lines += ["", f"Chapter {i}", ""]
            for k in range(6):
                lines += [prose(60, f"c{i}l{k}"), ""]
                if k == 3:
                    lines += ["", str(i), ""]  # a page number inside the chapter
        chapters = text_mod.split_into_chapters("\n".join(lines))
        assert [t for t, _ in chapters][-1] == "Chapter 8", [
            t for t, _ in chapters
        ]

    def test_non_consecutive_numerals_are_rejected(self):
        """Verse or figure numbers do not run 1, 2, 3 from the top."""
        out = []
        for value in (4, 9, 2, 17, 6):
            out += ["", str(value), ""]
            for k in range(12):
                out += [prose(62, f"v{value}l{k}"), ""]
        chapters = text_mod.split_into_chapters("\n".join(out))
        assert len(chapters) == 1, [t for t, _ in chapters]

    def test_the_fallback_says_it_fired(self):
        import io

        logger = logging.getLogger("audiobooker.parser")
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.WARNING)
        logger.addHandler(handler)
        try:
            text_mod.split_into_chapters(bare_numeral_book(roman=True))
        finally:
            logger.removeHandler(handler)
        assert "bare-numeral" in stream.getvalue(), stream.getvalue()


# ===========================================================================
# FEAT-IN-004 — Project Gutenberg boilerplate is narrated
# ===========================================================================
def gutenberg_book(n_chapters: int = 10) -> str:
    head = [
        "The Project Gutenberg eBook of The Harbour Bell, by A. Novelist",
        "",
        "This eBook is for the use of anyone anywhere in the United States and",
        "most other parts of the world at no cost and with almost no",
        "restrictions whatsoever. You may copy it, give it away or re-use it",
        "under the terms of the Project Gutenberg License included with this",
        "eBook or online at www.gutenberg.org.",
        "",
        "Title: The Harbour Bell",
        "Author: A. Novelist",
        "Release date: January 1, 2001 [eBook #12345]",
        "",
        "*** START OF THE PROJECT GUTENBERG EBOOK THE HARBOUR BELL ***",
        "",
    ]
    body: list[str] = []
    for i in range(1, n_chapters + 1):
        body += ["", f"Chapter {i}", ""]
        for _ in range(6):
            body += [prose(40, f"chapter {i}"), ""]
    tail = [
        "",
        "*** END OF THE PROJECT GUTENBERG EBOOK THE HARBOUR BELL ***",
        "",
        "*** START: FULL LICENSE ***",
        "",
        "THE FULL PROJECT GUTENBERG LICENSE",
        "PLEASE READ THIS BEFORE YOU DISTRIBUTE OR USE THIS WORK",
        "",
        "To protect the Project Gutenberg-tm mission of promoting the free",
        "distribution of electronic works, by using or distributing this work",
        "you indicate that you have read, understand and accept all the terms",
        "of this license and intellectual property agreement.",
        "",
        "*** END: FULL LICENSE ***",
    ]
    return "\n".join(head + body + tail)


class TestGutenbergBoilerplate:
    """FEAT-IN-004."""

    def test_the_legal_header_is_not_narrated(self):
        chapters = text_mod.split_into_chapters(gutenberg_book())
        joined = "\n".join(body for _, body in chapters)
        assert "most other parts of the world" not in joined

    def test_the_licence_does_not_fuse_into_the_last_chapter(self):
        """It has no heading of its own, so 'chapters exclude' cannot reach it."""
        chapters = text_mod.split_into_chapters(gutenberg_book())
        last = chapters[-1][1]
        assert "END OF THE PROJECT GUTENBERG" not in last
        assert "FULL PROJECT GUTENBERG LICENSE" not in last

    def test_only_the_real_chapters_survive(self):
        chapters = text_mod.split_into_chapters(gutenberg_book(10))
        assert [t for t, _ in chapters] == [
            f"Chapter {i}" for i in range(1, 11)
        ]

    def test_parse_text_gets_it_too(self, tmp_path):
        path = tmp_path / "pg12345.txt"
        path.write_text(gutenberg_book(), encoding="utf-8")
        _, chapters = text_mod.parse_text(path)
        assert len(chapters) == 10
        assert "www.gutenberg.org" not in "\n".join(c.raw_text for c in chapters)

    def test_the_older_this_marker_spelling_is_handled(self):
        book = gutenberg_book().replace(
            "OF THE PROJECT GUTENBERG EBOOK", "OF THIS PROJECT GUTENBERG EBOOK"
        )
        chapters = text_mod.split_into_chapters(book)
        assert len(chapters) == 10

    def test_text_without_markers_is_untouched(self):
        plain = "Chapter 1\n\n" + prose(80) + "\n\nChapter 2\n\n" + prose(80)
        assert text_mod.strip_gutenberg_boilerplate(plain) == plain

    def test_a_marker_with_no_real_body_does_not_delete_the_book(self):
        """A mention of the markers must never empty the file."""
        text = (
            "*** START OF THE PROJECT GUTENBERG EBOOK X ***\n"
            "only a handful of words here\n"
            "*** END OF THE PROJECT GUTENBERG EBOOK X ***\n"
        )
        assert text_mod.strip_gutenberg_boilerplate(text) == text

    def test_an_end_marker_alone_still_trims_the_tail(self):
        body = "Chapter 1\n\n" + prose(300) + "\n"
        text = (
            body
            + "*** END OF THE PROJECT GUTENBERG EBOOK X ***\n"
            + "licence text that must not be read aloud\n" * 20
        )
        out = text_mod.strip_gutenberg_boilerplate(text)
        assert "must not be read aloud" not in out
        assert "Chapter 1" in out
