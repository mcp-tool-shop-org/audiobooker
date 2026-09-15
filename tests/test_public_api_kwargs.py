"""FEAT-PROD-008: the documented constructors must accept documented kwargs.

`AudiobookProject.from_epub('book.epub', title='...')` — exactly what every
`from_*` docstring advertises, and exactly what the README's "embed
audiobooker in a GUI or service" invites — raised

    TypeError: got multiple values for keyword argument 'title'

because each constructor passed `title=metadata.get(...)` alongside
`**kwargs`. `from_folder` was the only one that popped instead.

The CLI never passes these, which is why it survived: only the documented
Python API hit it. That is the worst place for it, since the first call in
the public API's own documentation was the one that failed.
"""

from __future__ import annotations

import pathlib
import zipfile

import pytest

from audiobooker.project import AudiobookProject


@pytest.fixture
def txt_book(tmp_path: pathlib.Path) -> pathlib.Path:
    p = tmp_path / "book.txt"
    p.write_text("Chapter 1\n\nHello there friend.\n", encoding="utf-8")
    return p


@pytest.fixture
def chapter_folder(tmp_path: pathlib.Path) -> pathlib.Path:
    d = tmp_path / "chapters"
    d.mkdir()
    (d / "01_one.txt").write_text("The first chapter.\n", encoding="utf-8")
    (d / "02_two.txt").write_text("The second chapter.\n", encoding="utf-8")
    return d


@pytest.fixture
def epub_book(tmp_path: pathlib.Path) -> pathlib.Path:
    p = tmp_path / "book.epub"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="c.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        z.writestr(
            "c.opf",
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
            'version="3.0" unique-identifier="i"><metadata '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            '<dc:identifier id="i">x</dc:identifier>'
            "<dc:title>Metadata Title</dc:title>"
            "<dc:creator>Metadata Author</dc:creator>"
            "<dc:language>en</dc:language></metadata>"
            '<manifest><item id="c1" href="c1.xhtml" '
            'media-type="application/xhtml+xml"/></manifest>'
            '<spine><itemref idref="c1"/></spine></package>',
        )
        z.writestr(
            "c1.xhtml",
            '<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml">'
            "<body><h1>Chapter 1</h1><p>Hello there friend.</p></body></html>",
        )
    return p


class TestConstructorsAcceptDocumentedKwargs:
    def test_from_text(self, txt_book):
        p = AudiobookProject.from_text(txt_book, title="Custom", author="Me")
        assert (p.title, p.author) == ("Custom", "Me")

    def test_from_folder(self, chapter_folder):
        """The one that was always right — a regression guard, and the
        reference implementation the others now mirror."""
        p = AudiobookProject.from_folder(
            chapter_folder, title="Custom", author="Me"
        )
        assert (p.title, p.author) == ("Custom", "Me")

    def test_from_epub(self, epub_book):
        p = AudiobookProject.from_epub(epub_book, title="Custom", author="Me")
        assert (p.title, p.author) == ("Custom", "Me")

    def test_caller_value_beats_file_metadata(self, epub_book):
        """The point of passing it: an explicit title must WIN over what the
        file declares, not merely be accepted."""
        default = AudiobookProject.from_epub(epub_book)
        assert default.title == "Metadata Title", (
            "fixture is not exercising the override — its metadata title "
            "did not survive"
        )
        override = AudiobookProject.from_epub(epub_book, title="Custom")
        assert override.title == "Custom"

    def test_metadata_still_used_when_caller_says_nothing(self, epub_book):
        p = AudiobookProject.from_epub(epub_book)
        assert p.title == "Metadata Title"
        assert p.author == "Metadata Author"
