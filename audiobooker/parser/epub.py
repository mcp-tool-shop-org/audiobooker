"""
EPUB Parser for Audiobooker.

Extracts chapters and metadata from EPUB files using ebooklib.
Converts HTML content to plain text suitable for TTS.
"""

import logging
import re
from pathlib import Path
from typing import Optional
from html.parser import HTMLParser

from audiobooker.models import Chapter
from audiobooker.language.profile import LanguageProfile

logger = logging.getLogger("audiobooker.parser")

# Maximum EPUB file size (200 MB). EPUBs are zip archives that can decompress
# to far more, but the on-disk file is a cheap first guard (PARSER-A-001).
_MAX_EPUB_FILE_BYTES = 200 * 1024 * 1024

# Allowed cover-image extensions. The internal item name is attacker-controlled,
# so its suffix is validated against this allowlist before being used to build
# the on-disk cover path (PARSER-A-005).
_ALLOWED_COVER_EXTS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp"})


def _safe_cover_ext(name: str) -> str:
    """Return the cover image extension if allowlisted, else '.jpg' (PARSER-A-005)."""
    ext = Path(name).suffix.lower()
    return ext if ext in _ALLOWED_COVER_EXTS else ".jpg"


def _decode_item_content(content: bytes, name: str) -> str:
    """
    Decode EPUB item bytes to text, honoring a UTF-16/UTF-8 BOM (PARSER-A-008).

    ebooklib returns raw bytes; blindly decoding as UTF-8 mojibakes UTF-16
    documents. Sniff a BOM first; otherwise default to UTF-8 with replacement,
    logging a warning when replacement characters are introduced.
    """
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
        # "utf-16" consumes the BOM and infers LE/BE from it.
        return content.decode("utf-16")
    if content.startswith(b"\xef\xbb\xbf"):
        return content.decode("utf-8-sig")
    text = content.decode("utf-8", errors="replace")
    if "�" in text:
        logger.warning(
            "Replacement characters introduced while decoding %r as UTF-8 — "
            "the document may use a non-UTF-8 encoding.", name,
        )
    return text


# Tokens that mark a footnote span while text is in flight. They are internal
# to the extractor: process_footnotes consumes them, and _strip_sentinels is the
# unconditional backstop that guarantees none reaches Chapter.raw_text
# (PARSER-AMEND-1).
_FOOTNOTE_TOKEN_RE = re.compile(r"\x02?FOOTNOTE_(?:START|END)\x02?")

# C0 controls that must never reach the TTS engine. \n and \t are the only
# control characters legal in narratable text.
_ILLEGAL_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Markup class/epub:type tokens that identify a real footnote element.
_NOTE_TOKENS = frozenset({
    "noteref", "footnote", "footnotes", "endnote", "endnotes",
    "rearnote", "rearnotes", "note", "notes", "fn", "fnref",
})


def _strip_sentinels(text: str) -> str:
    """Remove footnote sentinels and illegal control characters (PARSER-AMEND-1).

    Defensive and unconditional: whatever route text took to get here, the
    literal token ``FOOTNOTE_START`` and the \\x02 delimiter must never be
    handed to a TTS engine. Applied at every boundary that produces text a
    ``Chapter`` will carry.
    """
    if not text:
        return text
    cleaned = _FOOTNOTE_TOKEN_RE.sub("", text)
    cleaned = _ILLEGAL_CONTROL_RE.sub("", cleaned)
    if cleaned != text:
        logger.debug(
            "Stripped footnote sentinels / control characters from extracted text."
        )
        cleaned = re.sub(r"[^\S\n]{2,}", " ", cleaned)
    return cleaned


class HTMLTextExtractor(HTMLParser):
    """
    Extract plain text from HTML, preserving paragraph structure.

    Handles:
    - Block elements (p, div, h1-h6) -> newlines
    - Inline elements -> preserved
    - Whitespace normalization
    - Footnote elements (aside, epub:type="noteref"/"footnote") -> tagged markers

    Footnote spans are tracked on a STACK of open tag names and closed by the
    matching end tag (PARSER-AMEND-2). The previous implementation opened a
    span for any element carrying ``epub:type="noteref"`` but only ever
    decremented on ``aside``/``sup``, so EPUB3's canonical
    ``<a epub:type="noteref">`` marker opened a span that could never close —
    and a stray later ``</sup>`` could close the orphan at an arbitrary point,
    making ``footnote_behavior="skip"`` delete legitimate prose.
    """

    # Sentinel markers for footnote spans (FT-CORE-019)
    FOOTNOTE_START = "\x02FOOTNOTE_START\x02"
    FOOTNOTE_END = "\x02FOOTNOTE_END\x02"

    # Block-level elements that should have newlines
    BLOCK_TAGS = {
        "p", "div", "h1", "h2", "h3", "h4", "h5", "h6",
        "li", "tr", "blockquote", "pre", "br", "hr", "table",
    }

    # Tags to skip entirely. <footer> is NOT here: chapter-end notes belong
    # in the narration (route real footnotes through footnote_behavior /
    # aside+epub:type). <nav> is skipped but logged. Unclosed skip tags are
    # force-closed in get_text() so they cannot eat the rest of the document.
    SKIP_TAGS = {"script", "style", "head", "meta", "link", "nav"}
    # HTML5 void elements never fire handle_endtag unless written self-closing.
    # Incrementing skip_depth on <link>/<meta> leaks skip mode through </head>
    # and deletes the body (F-dbe7d4d5). Treat them as empty — they have no
    # narratable children.
    VOID_SKIP_TAGS = {"meta", "link"}

    # Table cells: join with ", " and terminate each row with a full stop,
    # mirroring parser.docx._table_to_speakable. Minified XHTML has no
    # whitespace between <td>s, so we cannot wait for source spaces.
    CELL_TAGS = {"td", "th", "dt", "dd"}
    _ROW_END_PUNCT = (".", "!", "?", ":", ";")

    # Tags that always indicate footnote content (FT-CORE-019)
    FOOTNOTE_TAGS = {"aside"}

    # Tags that are a footnote marker about as often as they are ordinary
    # inline markup ("the 1<sup>st</sup> century", math exponents). Classified
    # by their own content when the span closes, so 'skip' can never delete an
    # ordinal suffix.
    AMBIGUOUS_FOOTNOTE_TAGS = {"sup"}

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self.skip_depth = 0
        self._pending_newline = False
        self._pending_space = False
        # Open footnote elements, innermost last (PARSER-AMEND-2).
        self._footnote_stack: list[str] = []
        self._span_start_index: Optional[int] = None
        self._span_explicit = False
        # Table-cell join state. A stack so a nested table inside a cell
        # does not leak separators into the parent row.
        self._cell_had_text: list[bool] = []
        self._pending_cell_sep = False
        self._row_has_cell = False
        self._logged_nav = False

    # -- footnote classification -------------------------------------------

    def _classify_footnote(self, tag: str, attrs: list) -> Optional[str]:
        """Return "explicit", "ambiguous", or None for a start tag."""
        attrs_dict = {
            (k or "").lower(): (v or "")
            for k, v in attrs
        }
        blob = f"{attrs_dict.get('epub:type', '')} {attrs_dict.get('class', '')}"
        tokens = {t for t in re.split(r"[\s_\-]+", blob.lower()) if t}
        if tokens & _NOTE_TOKENS:
            return "explicit"
        if tag in self.FOOTNOTE_TAGS:
            return "explicit"
        if tag in self.AMBIGUOUS_FOOTNOTE_TAGS:
            return "ambiguous"
        return None

    @staticmethod
    def _looks_like_note_marker(content: str) -> bool:
        """A bare <sup> is a note reference only if it carries no letters."""
        stripped = _FOOTNOTE_TOKEN_RE.sub("", content).strip()
        if not stripped:
            return True
        return not any(ch.isalpha() for ch in stripped)

    def _close_footnote_span(self) -> None:
        start = self._span_start_index
        explicit = self._span_explicit
        self._span_start_index = None
        self._span_explicit = False
        if start is None:
            return
        content = "".join(self._parts[start:])
        if not explicit and not self._looks_like_note_marker(content):
            # Ordinary inline markup — emit as plain text, no sentinels.
            return
        self._parts.insert(start, self.FOOTNOTE_START)
        self._parts.append(self.FOOTNOTE_END)

    # -- HTMLParser hooks ---------------------------------------------------

    def _emit_cell_separator(self) -> None:
        """Join the previous cell to this one with ', ' (no source whitespace)."""
        self._pending_newline = False
        self._pending_space = False
        if not self._parts:
            return
        last = self._parts[-1]
        if last.endswith((", ", ",", "\n")):
            return
        if last.endswith(" "):
            self._parts[-1] = last.rstrip() + ", "
            return
        self._parts.append(", ")

    def _terminate_row(self) -> None:
        """End a table row with a full stop so TTS does not run rows together."""
        self._pending_cell_sep = False
        if self._row_has_cell and self._parts:
            last = self._parts[-1].rstrip()
            if last and not last.endswith(self._ROW_END_PUNCT):
                self._parts.append(".")
        self._row_has_cell = False
        self._pending_newline = True
        self._pending_space = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            if tag in self.VOID_SKIP_TAGS:
                return
            if tag == "nav" and not self._logged_nav:
                logger.info(
                    "Skipping HTML <nav> element (navigation / table of contents)."
                )
                self._logged_nav = True
            self.skip_depth += 1
            return

        if tag in self.CELL_TAGS:
            if self._pending_cell_sep:
                self._emit_cell_separator()
                self._pending_cell_sep = False
            self._cell_had_text.append(False)
            return

        if tag == "tr":
            self._pending_cell_sep = False
            self._row_has_cell = False
            self._pending_newline = True
            return

        if tag == "dl":
            self._pending_cell_sep = False
            self._row_has_cell = False
            self._pending_newline = True
            return

        kind = self._classify_footnote(tag, attrs)
        if kind is not None:
            explicit = kind == "explicit"
            if not self._footnote_stack:
                self._span_start_index = len(self._parts)
                self._span_explicit = explicit
            else:
                self._span_explicit = self._span_explicit or explicit
            self._footnote_stack.append(tag)
            return

        if tag in self.BLOCK_TAGS:
            self._pending_newline = True

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.VOID_SKIP_TAGS:
            return
        if tag in self.SKIP_TAGS:
            self.skip_depth = max(0, self.skip_depth - 1)
            return

        if tag in self.CELL_TAGS:
            had_text = self._cell_had_text.pop() if self._cell_had_text else False
            if had_text:
                self._pending_cell_sep = True
                self._row_has_cell = True
            return

        if tag in ("tr", "dl"):
            self._terminate_row()
            return

        # Close the matching OPEN footnote element (and anything malformed
        # nested inside it). A tag that is not on the stack closes nothing —
        # that is what stops a stray </sup> truncating an open noteref span.
        if tag in self._footnote_stack:
            idx = len(self._footnote_stack) - 1 - self._footnote_stack[::-1].index(tag)
            del self._footnote_stack[idx:]
            if not self._footnote_stack:
                self._close_footnote_span()
            return

        if tag in self.BLOCK_TAGS:
            self._pending_newline = True

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        """Self-closing elements (``<a epub:type="noteref"/>``) open and close."""
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag.lower())

    def handle_data(self, data: str) -> None:
        if self.skip_depth > 0:
            return

        if not data.strip():
            # Whitespace-only run: remember that a space belongs here rather
            # than emitting one unconditionally.
            if data:
                self._pending_space = True
            return

        lead_space = data[:1].isspace()
        trail_space = data[-1:].isspace()
        text = " ".join(data.split())

        if self._pending_newline:
            self._parts.append("\n\n")
            self._pending_newline = False
            self._pending_space = False
        elif (
            (self._pending_space or lead_space)
            and self._parts
            and not self._parts[-1].endswith((" ", "\n"))
        ):
            self._parts.append(" ")

        self._pending_space = trail_space
        self._parts.append(text)
        if self._cell_had_text:
            self._cell_had_text[-1] = True

    def get_text(self) -> str:
        """Get extracted text with normalized whitespace."""
        # Force-close a span left open by malformed markup, so an unbalanced
        # START can never escape (PARSER-AMEND-2).
        self._footnote_stack.clear()
        if self._span_start_index is not None:
            self._close_footnote_span()
        # Same backstop for skip_depth: an unclosed <script>/<nav>/<style>
        # must not keep the extractor in skip mode (the already-consumed
        # inner text of a still-open skip tag is gone, but any caller that
        # feeds more HTML after get_text, and the trailing-row terminator,
        # see a clean slate).
        if self.skip_depth:
            logger.debug(
                "Force-closing skip_depth=%d left open by malformed markup.",
                self.skip_depth,
            )
            self.skip_depth = 0
        if self._row_has_cell:
            self._terminate_row()

        text = "".join(self._parts)
        # Normalize multiple newlines
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Clean up extra horizontal whitespace, including around line breaks
        text = re.sub(r"[^\S\n]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        return text.strip()


def process_footnotes(text: str, behavior: str = "inline") -> str:
    """
    Process footnote markers in extracted text (FT-CORE-019).

    Footnotes are delimited by FOOTNOTE_START / FOOTNOTE_END sentinels
    placed by HTMLTextExtractor.

    Args:
        text: Text containing footnote sentinels.
        behavior: "inline" (read in place), "end" (collect at chapter end),
                  "skip" (remove entirely).

    Returns:
        Processed text with footnotes handled according to behavior.
    """
    start = HTMLTextExtractor.FOOTNOTE_START
    end = HTMLTextExtractor.FOOTNOTE_END

    if start not in text:
        return text

    if behavior == "skip":
        # Remove all footnote content
        result = re.sub(
            re.escape(start) + r"(.*?)" + re.escape(end),
            "",
            text,
            flags=re.DOTALL,
        )
        return re.sub(r" {2,}", " ", result).strip()

    if behavior == "end":
        # Collect footnotes, replace inline with reference numbers
        footnotes: list[str] = []
        counter = 0

        def _collect(m: re.Match) -> str:
            nonlocal counter
            counter += 1
            content = m.group(1).strip()
            footnotes.append(f"Footnote {counter}: {content}")
            return f" [{counter}] "

        result = re.sub(
            re.escape(start) + r"(.*?)" + re.escape(end),
            _collect,
            text,
            flags=re.DOTALL,
        )
        if footnotes:
            result = result.rstrip() + "\n\n" + "\n".join(footnotes)
        return result

    # behavior == "inline" — just strip the sentinels, keep content in place
    result = text.replace(start, "").replace(end, "")
    return result


def html_to_text(html_content: str, *, footnote_behavior: str = "inline") -> str:
    """
    Convert HTML to plain text.

    Footnote spans found during extraction are resolved here according to
    ``footnote_behavior`` ("inline" / "end" / "skip"), and the result is passed
    through :func:`_strip_sentinels` unconditionally, so the internal
    ``FOOTNOTE_*`` tokens can never reach a caller (PARSER-AMEND-1). Before
    this, ``process_footnotes`` was defined but called from nowhere, and the
    raw sentinels were handed straight to the TTS engine for any EPUB using
    ``<sup>`` or ``<aside>`` — which is essentially every real EPUB.

    Args:
        html_content: HTML string
        footnote_behavior: How to resolve footnote spans — "inline" (read in
            place, the default and the historical content-preserving choice),
            "end" (collect at the end of the text with numbered references),
            or "skip" (remove entirely).

    Returns:
        Plain text with paragraph structure preserved
    """
    extractor = HTMLTextExtractor()
    try:
        extractor.feed(html_content)
    except Exception as e:
        # F-CORE-B-012: Log instead of silently swallowing
        logger.warning("HTML parsing failed, falling back to tag stripping: %s", e)
        text = re.sub(r"<[^>]+>", " ", html_content)
        text = " ".join(text.split())
        return _strip_sentinels(text)
    text = extractor.get_text()
    text = process_footnotes(text, footnote_behavior)
    return _strip_sentinels(text)


def _compose_extracted_title(
    title: str,
    profile: Optional[LanguageProfile],
) -> str:
    """Run a heading through compose_chapter_title when it matches a profile."""
    from audiobooker.parser.text import compose_chapter_title, _get_chapter_patterns

    for pat in _get_chapter_patterns(profile):
        try:
            compiled = re.compile(pat, re.IGNORECASE)
        except re.error:
            continue
        match = compiled.match(title)
        if match:
            return compose_chapter_title(title, match)
    return title


def extract_title_from_html(
    html_content: str,
    *,
    profile: Optional[LanguageProfile] = None,
) -> Optional[str]:
    """
    Try to extract chapter title from HTML content.

    Looks for h1, h2, h3 tags at the start of content. Nested markup inside
    the heading (the normal EPUB/Calibre case: ``<h1><span>…</span></h1>``)
    is flattened through :func:`html_to_text` so the title is not dropped.
    When the flattened heading matches a language-profile chapter pattern,
    :func:`compose_chapter_title` is applied so spine titles and TOC titles
    share one rule.
    """
    # Capture inner HTML, not a single text node. Backreference the heading
    # level so ``<h1>…</h1>`` cannot swallow a later ``</h2>``.
    patterns = [
        r"<h([1-3])\b[^>]*>(.*?)</h\1>",
        r"<title\b[^>]*>(.*?)</title>",
    ]

    for pattern in patterns:
        match = re.search(
            pattern, html_content[:2000], re.IGNORECASE | re.DOTALL,
        )
        if match:
            inner = match.group(match.lastindex or 1)
            # Flatten nested tags; a heading fragment is not a full document.
            title = html_to_text(inner)
            title = re.sub(r"\s+", " ", title).strip()
            if title and len(title) < 200:
                return _compose_extracted_title(title, profile)

    return None


def _flatten_toc(toc) -> list[tuple[str, str]]:
    """Flatten a (possibly nested) ebooklib TOC into ordered (title, href) pairs.

    ebooklib's ``book.toc`` is a list whose entries are either ``epub.Link``
    objects or ``(epub.Section, [children])`` tuples. Sections are containers;
    we descend into their children and only emit leaf links that point at a
    document href. Order is preserved (depth-first, document order).
    """
    flat: list[tuple[str, str]] = []

    def _walk(entries) -> None:
        for entry in entries:
            # (Section, children) tuple — descend into children.
            if isinstance(entry, tuple):
                section, children = entry[0], entry[1] if len(entry) > 1 else []
                # A Section may itself carry an href (rare); emit it if present.
                href = getattr(section, "href", None)
                title = getattr(section, "title", None)
                if href:
                    flat.append(((title or "").strip(), href))
                if children:
                    _walk(children)
            else:
                href = getattr(entry, "href", None)
                title = getattr(entry, "title", None)
                if href:
                    flat.append(((title or "").strip(), href))

    try:
        _walk(toc or [])
    except Exception as e:  # defensive: malformed TOC must not crash parsing
        logger.debug("TOC flattening failed: %s", e)
        return []
    return flat


def _split_href(href: str) -> tuple[str, Optional[str]]:
    """Split an EPUB href into (document path, anchor) — anchor is None if absent."""
    if "#" in href:
        doc, anchor = href.split("#", 1)
        return doc, (anchor or None)
    return href, None


# Match an element bearing id="X" or name="X" (anchor targets) in raw HTML.
def _anchor_pos(html_content: str, anchor: str) -> Optional[int]:
    """Return the character offset of an anchor's element in HTML, or None."""
    # id="anchor" or name="anchor" (single or double quoted)
    pat = re.compile(
        r"""<[^>]*\b(?:id|name)\s*=\s*['"]""" + re.escape(anchor) + r"""['"]""",
        re.IGNORECASE,
    )
    m = pat.search(html_content)
    return m.start() if m else None


def _posix_name(name: str) -> str:
    """Normalize a manifest/href path to comparable POSIX segments."""
    normalized = (name or "").replace("\\", "/")
    # Collapse '.' segments; keep '..' as-is (it is never a legal manifest name).
    segments = [s for s in normalized.split("/") if s not in ("", ".")]
    return "/".join(segments)


# Sentinel: a TOC href that matches more than one manifest document.
_AMBIGUOUS_HREF = object()


def _match_doc_name(doc_name: str, docs_by_name: dict):
    """Resolve a TOC href's document path to a manifest entry name.

    Matching is anchored on path SEGMENT boundaries (PARSER-AMEND-9). The
    previous ``name.endswith(doc_name) or doc_name.endswith(name)`` test was
    unanchored, so the href ``ch1.xhtml`` happily bound to the manifest entry
    ``OEBPS/xch1.xhtml`` and narrated the wrong document under the right title.
    When more than one manifest entry matches, the TOC is reported as
    ambiguous rather than guessed at by dict-iteration order.

    Returns the manifest name, ``None`` if nothing matches, or
    ``_AMBIGUOUS_HREF``.
    """
    target = _posix_name(doc_name)
    if not target:
        return None
    if doc_name in docs_by_name:
        return doc_name

    exact = [n for n in docs_by_name if _posix_name(n) == target]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return _AMBIGUOUS_HREF

    suffix = [
        n for n in docs_by_name
        if _posix_name(n).endswith("/" + target) or target.endswith("/" + _posix_name(n))
    ]
    if len(suffix) == 1:
        return suffix[0]
    if len(suffix) > 1:
        return _AMBIGUOUS_HREF
    return None


def _chapters_from_toc(
    toc_entries: list[tuple[str, str]],
    *,
    min_chapter_words: int,
    keep_titled_short_chapters: bool,
    docs_by_name: dict,
    footnote_behavior: str = "inline",
    profile: Optional[LanguageProfile] = None,
) -> Optional[list[Chapter]]:
    """Build chapters from flattened TOC entries (FT-PARSE-003).

    For each TOC entry, resolve its document + optional anchor, slice the
    document's HTML between consecutive anchors that target the same document,
    convert each slice to text, and use the TOC title. Returns None if the TOC
    does not resolve to at least two usable chapters (caller falls back to
    spine splitting).
    """
    # Resolve each entry to (title, doc_name, anchor). Drop entries whose
    # document isn't a known document item.
    resolved: list[tuple[str, str, Optional[str]]] = []
    for title, href in toc_entries:
        doc_name, anchor = _split_href(href)
        # Normalize: hrefs may be relative with directories; match on whole
        # POSIX path segments (PARSER-AMEND-9), never on a bare suffix.
        item = docs_by_name.get(doc_name)
        if item is None:
            matched = _match_doc_name(doc_name, docs_by_name)
            if matched is _AMBIGUOUS_HREF:
                logger.info(
                    "EPUB TOC href %r matches more than one manifest document — "
                    "the TOC is ambiguous, falling back to spine/document splitting.",
                    href,
                )
                return None
            if matched is None:
                continue
            item = docs_by_name[matched]
            doc_name = matched
        resolved.append((title, doc_name, anchor))

    if len(resolved) < 2:
        return None

    chapters: list[Chapter] = []
    chapter_index = 0

    # Group consecutive entries by document so we can slice multi-anchor docs.
    i = 0
    n = len(resolved)
    while i < n:
        title, doc_name, anchor = resolved[i]
        item = docs_by_name[doc_name]
        content = item.get_content()
        if isinstance(content, bytes):
            content = _decode_item_content(content, doc_name)

        # Collect all consecutive entries that point at THIS same document.
        same_doc: list[tuple[str, Optional[str]]] = [(title, anchor)]
        j = i + 1
        while j < n and resolved[j][1] == doc_name:
            same_doc.append((resolved[j][0], resolved[j][2]))
            j += 1

        # Compute slice boundaries within the HTML for each entry.
        # An entry with an anchor starts at that anchor's position; the first
        # entry (no anchor or anchor missing) starts at 0. Each slice ends where
        # the next same-doc anchor begins, or at end of document.
        entries_with_pos: list[tuple[int, int, str]] = []
        for k, (_t, a) in enumerate(same_doc):
            pos = 0
            if a:
                found = _anchor_pos(content, a)
                if found is not None:
                    pos = found
                elif k > 0:
                    # Anchor not found mid-document — abandon TOC slicing for
                    # safety; fall back to spine (return None).
                    return None
            entries_with_pos.append((pos, k, _t))

        # PARSER-AMEND-8: a TOC may list anchors out of document order. The
        # boundaries were previously used as-computed, so content[start:end]
        # with end < start silently produced '' — a 0-word chapter that
        # survived the filter because it was titled — and filed the first
        # section's prose under the wrong title. Order the slices by their
        # real position and verify the boundaries increase before slicing.
        ordered = sorted(entries_with_pos, key=lambda e: (e[0], e[1]))
        if [e[1] for e in ordered] != [e[1] for e in entries_with_pos]:
            logger.info(
                "EPUB TOC entries for %r are out of document order — "
                "reordering %d section(s) by anchor position.",
                doc_name, len(ordered),
            )
        positions = [e[0] for e in ordered]
        titles = [e[2] for e in ordered]

        # Intra-document sibling of FEAT-IN-002: a TOC that names an anchor
        # mid-file used to start the first slice at that anchor and silently
        # delete the dedication / epigraph / kicker sitting at html[0:pos].
        first_pos = positions[0] if positions else 0
        if first_pos > 0:
            prefix_html = content[:first_pos]
            prefix_text = html_to_text(
                prefix_html, footnote_behavior=footnote_behavior,
            )
            prefix_words = len(prefix_text.split())
            if prefix_words > 0:
                logger.warning(
                    "EPUB document %r has %d word(s) before the first TOC "
                    "anchor; that preamble is not named in the table of "
                    "contents and would have been dropped. Recovering it. "
                    "If it is not part of the book, exclude it with "
                    "'chapters exclude'.",
                    doc_name, prefix_words,
                )
                prefix_title = extract_title_from_html(
                    prefix_html, profile=profile,
                )
                stand_alone = (
                    prefix_words >= min_chapter_words
                    or bool(prefix_title and keep_titled_short_chapters)
                )
                if stand_alone:
                    chapters.append(Chapter(
                        index=chapter_index,
                        title=prefix_title or f"Chapter {chapter_index + 1}",
                        raw_text=_strip_sentinels(prefix_text),
                        source_file=doc_name,
                    ))
                    chapter_index += 1
                else:
                    # Too short to stand alone — narrate it with the first
                    # named section rather than drop it.
                    positions[0] = 0

        for k, entry_title in enumerate(titles):
            start = positions[k]
            end = positions[k + 1] if k + 1 < len(positions) else len(content)
            if end < start:
                # Unreachable after the sort above; a hard stop rather than a
                # silently empty slice if that ever changes.
                logger.warning(
                    "EPUB TOC produced a non-monotonic slice in %r (%d > %d) — "
                    "falling back to spine/document splitting.",
                    doc_name, start, end,
                )
                return None
            slice_html = content[start:end]
            text = html_to_text(slice_html, footnote_behavior=footnote_behavior)
            word_count = len(text.split())

            if word_count == 0:
                logger.info(
                    "Dropping empty TOC section: %r (0 words)",
                    entry_title or doc_name,
                )
                continue

            if word_count < min_chapter_words:
                if entry_title and keep_titled_short_chapters:
                    logger.info(
                        "Keeping short titled TOC section: %r (%d words < %d)",
                        entry_title, word_count, min_chapter_words,
                    )
                else:
                    logger.info(
                        "Skipping short TOC section: %r (%d words < %d)",
                        entry_title or doc_name, word_count, min_chapter_words,
                    )
                    continue

            chap_title = entry_title or f"Chapter {chapter_index + 1}"
            chapters.append(Chapter(
                index=chapter_index,
                title=chap_title,
                raw_text=_strip_sentinels(text),
                source_file=doc_name,
            ))
            chapter_index += 1

        i = j

    if len(chapters) < 2:
        return None
    return chapters


def _spine_document_names(book) -> list[tuple[str, bool]]:
    """``(document name, is_linear)`` in spine (reading) order.

    The spine is the EPUB's normative reading order — it is what an e-reader
    pages through, and ``linear="no"`` marks content it does NOT page through
    in the main flow. Navigation documents are excluded. Falls back to manifest
    document order (everything linear) when the book has no resolvable spine.
    """
    import ebooklib
    from ebooklib import epub as _epub

    entries: list[tuple[str, bool]] = []
    seen: set[str] = set()
    for spine_item in getattr(book, "spine", None) or []:
        if isinstance(spine_item, tuple):
            item_id = spine_item[0]
            linear = str(spine_item[1]).lower() != "no" if len(spine_item) > 1 else True
        else:
            item_id, linear = spine_item, True
        try:
            item = book.get_item_with_id(item_id)
        except Exception:  # defensive: malformed spine must not abort parsing
            item = None
        if item is None or isinstance(item, _epub.EpubNav):
            continue
        name = item.get_name()
        if name and name not in seen:
            seen.add(name)
            entries.append((name, linear))

    if entries:
        return entries

    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        if isinstance(item, _epub.EpubNav):
            continue
        name = item.get_name()
        if name and name not in seen:
            seen.add(name)
            entries.append((name, True))
    return entries


def _document_chapter(
    item,
    *,
    index: int,
    min_chapter_words: int,
    keep_titled_short_chapters: bool,
    footnote_behavior: str,
    profile: Optional[LanguageProfile] = None,
) -> Optional[Chapter]:
    """Build one Chapter from a whole spine document, or None if too short."""
    content = item.get_content()
    if isinstance(content, bytes):
        content = _decode_item_content(content, item.get_name())

    text = html_to_text(content, footnote_behavior=footnote_behavior)
    word_count = len(text.split())
    title = extract_title_from_html(content, profile=profile)

    if word_count < min_chapter_words:
        if title and keep_titled_short_chapters:
            logger.info(
                "Keeping short titled section: %r (%d words < %d threshold)",
                title, word_count, min_chapter_words,
            )
        else:
            logger.info(
                "Skipping short section: %r (%d words < %d threshold)",
                title or item.get_name(), word_count, min_chapter_words,
            )
            return None

    return Chapter(
        index=index,
        title=title or f"Chapter {index + 1}",
        raw_text=_strip_sentinels(text),
        source_file=item.get_name(),
    )


def _reconcile_toc_with_spine(
    book,
    chapters: list[Chapter],
    *,
    min_chapter_words: int,
    keep_titled_short_chapters: bool,
    footnote_behavior: str,
    profile: Optional[LanguageProfile] = None,
) -> list[Chapter]:
    """Put TOC-derived chapters back in reading order and recover orphans.

    FEAT-IN-002. ``_chapters_from_toc`` builds purely from resolved TOC
    entries and never cross-checks them against the spine, so a stale or
    hand-edited TOC — extremely common after a Word → Calibre or a Scrivener
    export — silently did two harmful things:

    * a spine document the TOC never mentions was DELETED. An afterword's 220
      words of real prose simply did not appear in the audiobook, and nothing
      was logged at any level, not even under ``--debug``.
    * a TOC that lists chapter 2 before chapter 1 narrated them in that order.
      The spine, not the TOC, is the EPUB's normative reading order; the TOC is
      navigation.

    Both are fixed against the spine: chapters are emitted in spine order, and
    a document with no TOC entry is recovered into its own chapter at its spine
    position (not appended at the end — a copyright page belongs at the front,
    an afterword at the back). Each correction is warned about, naming the
    documents involved, and the warning says how to drop a recovered document
    that really is not part of the book.

    A recovered document goes through exactly the short-section policy the
    spine fallback path applies (``min_chapter_words`` /
    ``keep_titled_short_chapters``), and ``linear="no"`` spine entries are
    left out — a TOC that omits those omitted them on purpose.
    """
    import ebooklib

    spine_entries = _spine_document_names(book)
    if not spine_entries:
        return chapters
    spine_names = [name for name, _ in spine_entries]
    in_spine = set(spine_names)

    by_doc: dict[str, list[Chapter]] = {}
    for chapter in chapters:
        by_doc.setdefault(chapter.source_file, []).append(chapter)

    # A TOC document missing from the spine cannot be positioned; those keep
    # their original relative order at the end rather than being guessed at.
    unpositioned = [name for name in by_doc if name not in in_spine]

    docs_by_name = {
        it.get_name(): it
        for it in book.get_items_of_type(ebooklib.ITEM_DOCUMENT)
    }

    ordered: list[Chapter] = []
    recovered: list[str] = []
    for name, linear in spine_entries:
        if name in by_doc:
            ordered.extend(by_doc.pop(name))
            continue
        item = docs_by_name.get(name)
        if item is None:
            continue
        if not linear:
            # linear="no" is content the reader does not page through in the
            # main flow; a TOC that omits it omitted it on purpose.
            logger.info(
                "Leaving non-linear document %r out of the chapter list.", name,
            )
            continue
        built = _document_chapter(
            item,
            index=len(ordered),
            min_chapter_words=min_chapter_words,
            keep_titled_short_chapters=keep_titled_short_chapters,
            footnote_behavior=footnote_behavior,
            profile=profile,
        )
        if built is not None:
            recovered.append(name)
            ordered.append(built)

    for name in unpositioned:
        ordered.extend(by_doc.pop(name, []))

    # Did the spine actually move anything the TOC had placed?
    was = [c.source_file for c in chapters if c.source_file in in_spine]
    now = [c.source_file for c in ordered if c.source_file not in recovered]
    if was != now:
        logger.warning(
            "The table of contents in this EPUB lists its documents in a "
            "different order than the spine (the book's own reading order): "
            "TOC order %s vs reading order %s. Using the reading order — a "
            "stale TOC would otherwise narrate the chapters out of sequence.",
            was, now,
        )

    if recovered:
        logger.warning(
            "%d document(s) in this EPUB are not listed in its table of "
            "contents and would have been dropped: %s. They have been "
            "recovered as chapters at their reading-order position. If they "
            "really are not part of the book, exclude them with "
            "'chapters exclude', or pass use_toc='off' to split on the spine "
            "alone.",
            len(recovered), ", ".join(recovered),
        )

    for position, chapter in enumerate(ordered):
        chapter.index = position
    return ordered


def parse_epub(
    path: Path,
    min_chapter_words: int = 50,
    keep_titled_short_chapters: bool = True,
    *,
    profile: Optional[LanguageProfile] = None,
    use_toc: str = "auto",
    footnote_behavior: str = "inline",
) -> tuple[dict, list[Chapter]]:
    """
    Parse an EPUB file into chapters.

    Args:
        path: Path to EPUB file
        min_chapter_words: Minimum word count for a section to be kept.
        keep_titled_short_chapters: Keep short sections that have a heading/title.
        footnote_behavior: How footnote spans are rendered — "inline" (read in
            place, the default), "end" (collected at the end of the chapter
            with numbered references), or "skip" (removed). Mirrors
            ``ProjectConfig.footnote_behavior``. Whatever the value, no
            footnote sentinel ever reaches ``Chapter.raw_text``
            (PARSER-AMEND-1).
        profile: Language profile (used for the parse summary; EPUB chapter
            boundaries come from the book's own spine/document structure rather
            than heading-pattern detection, so this does not change splitting).
        use_toc: How to use the EPUB's table of contents for chapter
            boundaries (FT-PARSE-003). One of:
            - ``"auto"`` (default): use the TOC when it yields at least two
              usable chapters; otherwise fall back to spine/document splitting.
            - ``"on"``: same as auto — prefer the TOC, fall back to spine if it
              is unusable.
            - ``"off"``: ignore the TOC and always split on spine documents
              (the historical behavior).
            The spine fallback is byte-for-byte identical to the pre-FT-PARSE-003
            behavior, so the no-usable-TOC case is unchanged.

    Returns:
        Tuple of (metadata dict, list of Chapters)

    Raises:
        ImportError: If ebooklib is not installed
        FileNotFoundError: If file doesn't exist
    """
    try:
        import ebooklib
        from ebooklib import epub
    except ImportError:
        raise ImportError(
            "ebooklib is required for EPUB parsing. "
            "Install with: pip install ebooklib"
        )

    _VALID_USE_TOC = ("auto", "on", "off")
    if use_toc not in _VALID_USE_TOC:
        raise ValueError(
            f"Invalid use_toc: {use_toc!r}. Must be one of: {', '.join(_VALID_USE_TOC)}"
        )

    _VALID_FOOTNOTE_BEHAVIOR = ("inline", "end", "skip")
    if footnote_behavior not in _VALID_FOOTNOTE_BEHAVIOR:
        raise ValueError(
            f"Invalid footnote_behavior: {footnote_behavior!r}. "
            f"Must be one of: {', '.join(_VALID_FOOTNOTE_BEHAVIOR)}"
        )

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"EPUB not found: {path}")

    # Size guard (PARSER-A-001): mirror the PDF/text parsers.
    file_size = path.stat().st_size
    if file_size > _MAX_EPUB_FILE_BYTES:
        size_mb = file_size / (1024 * 1024)
        raise ValueError(
            f"EPUB file is too large ({size_mb:.1f} MB, limit is 200 MB). "
            "Consider splitting the EPUB into smaller parts."
        )

    # F-CORE-B-003: Wrap read_epub with error handling for corrupt/DRM files
    from zipfile import BadZipFile
    try:
        book = epub.read_epub(str(path))
    except BadZipFile:
        raise ValueError(
            f"Cannot open '{path.name}' — the file appears to be corrupt or "
            "is not a valid EPUB (bad zip archive). Try re-downloading the file "
            "or opening it in Calibre to verify it."
        )
    except KeyError as e:
        raise ValueError(
            f"Cannot parse '{path.name}' — the EPUB is missing expected content: {e}. "
            "This can happen with DRM-protected books. Use Calibre to inspect "
            "or re-export the EPUB."
        ) from e
    except Exception as e:
        raise ValueError(
            f"Failed to read '{path.name}': {e}. "
            "The file may be DRM-protected, corrupt, or in an unsupported format. "
            "Try opening it in Calibre first to verify it's readable."
        ) from e

    # Extract metadata
    metadata = {}

    # Title
    title_list = book.get_metadata("DC", "title")
    if title_list:
        metadata["title"] = title_list[0][0]

    # Author
    creator_list = book.get_metadata("DC", "creator")
    if creator_list:
        metadata["author"] = creator_list[0][0]

    # Language
    lang_list = book.get_metadata("DC", "language")
    if lang_list:
        metadata["language"] = lang_list[0][0]

    # Publisher
    publisher_list = book.get_metadata("DC", "publisher")
    if publisher_list:
        metadata["publisher"] = publisher_list[0][0]

    # Date/Year
    date_list = book.get_metadata("DC", "date")
    if date_list:
        date_str = date_list[0][0]
        # Try to extract year from date string (ISO format or plain year)
        year_match = re.match(r"(\d{4})", date_str)
        if year_match:
            metadata["year"] = int(year_match.group(1))

    # Cover art extraction (FT-CORE-014)
    cover_image_data = None
    cover_image_ext = None
    try:
        # Try ITEM_COVER first
        cover_items = list(book.get_items_of_type(ebooklib.ITEM_COVER))
        if cover_items:
            cover_image_data = cover_items[0].get_content()
            cover_image_ext = _safe_cover_ext(cover_items[0].get_name())
        else:
            # Fall back to first image item
            image_items = list(book.get_items_of_type(ebooklib.ITEM_IMAGE))
            # Look for items with "cover" in the name
            for img in image_items:
                name_lower = img.get_name().lower()
                if "cover" in name_lower:
                    cover_image_data = img.get_content()
                    cover_image_ext = _safe_cover_ext(img.get_name())
                    break
            # If no cover-named image, use the first image as fallback
            if cover_image_data is None and image_items:
                cover_image_data = image_items[0].get_content()
                cover_image_ext = _safe_cover_ext(image_items[0].get_name())
    except Exception as e:
        logger.warning("Failed to extract cover art: %s", e)

    if cover_image_data is not None:
        # Write cover art next to the EPUB
        cover_path = path.parent / f"{path.stem}_cover{cover_image_ext}"
        try:
            cover_path.write_bytes(cover_image_data)
            metadata["cover_art_path"] = str(cover_path)
            logger.info("Extracted cover art to %s", cover_path)
        except OSError as e:
            logger.warning("Could not save cover art: %s", e)

    # FT-PARSE-003: TOC-driven splitting. When use_toc is 'auto'/'on' and the
    # book's TOC resolves to >= 2 usable chapters, build chapters from the TOC
    # (titles + anchor-sliced text). Otherwise fall back to the spine/document
    # splitting below, which is byte-for-byte identical to the historical
    # behavior. 'off' skips the TOC entirely.
    chapters: list[Chapter] = []
    split_pattern = "spine/structure"

    if use_toc in ("auto", "on"):
        toc_entries = _flatten_toc(getattr(book, "toc", None))
        if len(toc_entries) >= 2:
            docs_by_name = {
                it.get_name(): it
                for it in book.get_items_of_type(ebooklib.ITEM_DOCUMENT)
            }
            toc_chapters = _chapters_from_toc(
                toc_entries,
                min_chapter_words=min_chapter_words,
                keep_titled_short_chapters=keep_titled_short_chapters,
                docs_by_name=docs_by_name,
                footnote_behavior=footnote_behavior,
                profile=profile,
            )
            if toc_chapters:
                # FEAT-IN-002: the TOC decides titles and anchor slicing; the
                # SPINE decides reading order and what exists at all.
                chapters = _reconcile_toc_with_spine(
                    book,
                    toc_chapters,
                    min_chapter_words=min_chapter_words,
                    keep_titled_short_chapters=keep_titled_short_chapters,
                    footnote_behavior=footnote_behavior,
                    profile=profile,
                )
                split_pattern = "toc"
                logger.info(
                    "Using EPUB table of contents for chapter boundaries "
                    "(%d entries -> %d chapters).",
                    len(toc_entries), len(chapters),
                )
            else:
                logger.info(
                    "EPUB table of contents was not usable for splitting "
                    "(too few resolvable entries) — falling back to spine/document "
                    "structure.",
                )

    # Spine-ordered fallback. The previous ITEM_DOCUMENT walk used manifest /
    # add-item order, so use_toc='off' narrated chapters out of reading order,
    # included linear='no' documents, and served the nav document as a chapter
    # titled with the book name. _spine_document_names already skips EpubNav
    # and reports linear; _document_chapter is the same helper reconcile uses.
    if not chapters:
        docs_by_name = {
            it.get_name(): it
            for it in book.get_items_of_type(ebooklib.ITEM_DOCUMENT)
        }
        for name, linear in _spine_document_names(book):
            if not linear:
                logger.info(
                    "Leaving non-linear document %r out of the chapter list.",
                    name,
                )
                continue
            item = docs_by_name.get(name)
            if item is None:
                continue
            built = _document_chapter(
                item,
                index=len(chapters),
                min_chapter_words=min_chapter_words,
                keep_titled_short_chapters=keep_titled_short_chapters,
                footnote_behavior=footnote_behavior,
                profile=profile,
            )
            if built is not None:
                chapters.append(built)

    # F-CORE-B-004: Raise if no readable chapters found
    if not chapters:
        logger.warning("No readable chapters found in '%s'", path.name)
        raise ValueError(
            f"No readable chapters found in '{path.name}'. "
            "The EPUB may be DRM-protected, use an unsupported format, "
            "or contain only very short sections. "
            f"(Current minimum: {min_chapter_words} words per chapter — "
            "try lowering min_chapter_words in ProjectConfig if the book has short sections.)"
        )

    # Single-chapter EPUBs are usually genuine (one big document), but warn so
    # the user can tell detection apart from a one-section file.
    if len(chapters) == 1:
        logger.warning(
            "Only one chapter found in '%s' — the whole book is being treated as "
            "a single chapter. If it should have multiple chapters, the EPUB may "
            "store them in one document; check the file in Calibre.",
            path.name,
        )

    # Parse-observability summary (PARSER-C). EPUB splits on either the table of
    # contents (pattern=toc) or document/spine structure (pattern=spine/structure),
    # so the reported pattern reflects which path produced the chapters
    # (FT-PARSE-003).
    profile_code = profile.code if profile is not None else "en"
    logger.info(
        "Parsed EPUB '%s': %d chapter(s), profile=%s, pattern=%s",
        path.name, len(chapters), profile_code, split_pattern,
    )

    return metadata, chapters
