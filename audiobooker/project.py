"""
AudiobookProject - Main orchestrator for audiobook generation.

Manages the full lifecycle:
1. Load source (EPUB/TXT)
2. Parse chapters
3. Configure casting table
4. Compile to utterances
5. Render chapter audio
6. Assemble final M4B

Project state is persisted to JSON for resumption.
"""

import json
import logging
import os
import re as _re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

logger = logging.getLogger("audiobooker.project")

# Maximum project file size for load() (50 MB)
_MAX_PROJECT_FILE_BYTES = 50 * 1024 * 1024

# Valid fields for AudiobookProject that factory **kwargs may set
_VALID_PROJECT_KWARGS = {
    "title", "author", "source_path", "project_path", "created_at",
    "modified_at", "chapters", "casting", "config", "progress",
    "output_path", "metadata",
}

from audiobooker.errors import CompilationFailedError
from audiobooker.models import (
    BookMetadata,
    Chapter,
    Utterance,
    Character,
    CastingTable,
    ProjectConfig,
    UNSET,
    _looks_absolute,
    portable_path,
    resolve_stored_path,
)



def _sanitize_filename(name: str) -> str:
    """Strip/replace filesystem-unsafe characters from a filename."""
    # Replace common unsafe chars with underscore
    sanitized = _re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    # Collapse runs of underscores/spaces
    sanitized = _re.sub(r"[_ ]{2,}", "_", sanitized).strip("_ ")
    return sanitized or "untitled"


# ---------------------------------------------------------------------------
# CASTING-DEPTH (v2.1): CSV cast-sheet helpers
# ---------------------------------------------------------------------------

def _gender_from_voice(voice: str) -> str:
    """Derive an informational gender label from a voice ID prefix.

    Convention (voice-soundboard): af_/bf_ -> female, am_/bm_ -> male. Anything
    else is "unknown". Used only to populate the CSV ``gender`` column; the
    value is ignored on import.
    """
    v = (voice or "").lower()
    if v.startswith(("af_", "bf_")):
        return "female"
    if v.startswith(("am_", "bm_")):
        return "male"
    return "unknown"


def _csv_float(value, default: float) -> float:
    """Parse an optional CSV float cell, falling back to ``default`` when blank."""
    if value is None or str(value).strip() == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _csv_optional_float(value) -> Optional[float]:
    """Parse a CSV cell whose absence is meaningful (None, not a number).

    ``Character.default_intensity`` is Optional[float]: None means "no
    intensity override", which is a different setting from 0.0. A blank,
    missing or unparseable cell therefore reads back as None.
    """
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _csv_int(value, default: int) -> int:
    """Parse an optional CSV int cell, falling back to ``default`` when blank."""
    if value is None or str(value).strip() == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _csv_aliases(value) -> list[str]:
    """Split a ';'-joined CSV aliases cell into a clean list."""
    if not value:
        return []
    return [a.strip() for a in str(value).split(";") if a.strip()]


# ---------------------------------------------------------------------------
# Project file schema version.
#
# CH-B-001: this sat at 1 through several rounds of added fields, which looked
# like neglect and isn't. The number gates exactly one thing — load() refuses a
# file whose schema_version is HIGHER than this constant — so it is a hard stop
# protecting an OLDER audiobooker from a file it would read WRONGLY. Adding a
# field never triggers that: every reader takes unknown keys with
# `data.get(key, default)` and older readers simply ignore what they don't
# know. Bumping for additive rounds would have made old installs refuse files
# they could open perfectly, so staying at 1 was the correct call each time.
#
# The bump to 2 is the first change that actually earns one. Schema v2 changes
# what EXISTING path fields MEAN (see portable_path in models.py): "book.epub"
# used to be resolved against the process CWD and now resolves against the
# project file's directory, and "~/Music/out.m4b" is new spelling entirely. A
# v1 reader handed a v2 file does not error — it silently opens the wrong file,
# or creates a literal directory named "~". That is precisely the failure the
# guard exists to prevent, so it gets the bump and a real migration in
# _migrate().
#
# Rule for the next person: bump when the meaning of an existing field changes,
# when a field becomes required, or when a field is removed. Do NOT bump to
# advertise new optional fields.
# ---------------------------------------------------------------------------
SCHEMA_VERSION = 2

# Path-valued keys in the project dict, used by the v1 -> v2 migration.
_V1_PATH_KEYS = ("source_path", "output_path")


@dataclass
class RenderProgress:
    """Progress tracking for rendering."""
    current_chapter: int = 0
    total_chapters: int = 0
    current_utterance: int = 0
    total_utterances: int = 0
    status: str = "idle"  # idle | compiling | rendering | assembling | complete | error
    error_message: Optional[str] = None


@dataclass
class AudiobookProject:
    """
    Main project class for audiobook generation.

    Example:
        # Create from EPUB
        project = AudiobookProject.from_epub("book.epub")

        # Configure voices
        project.cast("narrator", "bm_george", emotion="calm")
        project.cast("Alice", "af_bella", emotion="warm")

        # Compile and render
        project.compile()
        project.render("output.m4b")

        # Save for later
        project.save("project.audiobooker")
    """
    # Metadata
    title: str = "Untitled"
    author: str = ""
    source_path: Optional[Path] = None
    project_path: Optional[Path] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    modified_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # Content
    chapters: list[Chapter] = field(default_factory=list)
    casting: CastingTable = field(default_factory=CastingTable)
    config: ProjectConfig = field(default_factory=ProjectConfig)

    # Metadata
    metadata: BookMetadata = field(default_factory=BookMetadata)

    # State
    progress: RenderProgress = field(default_factory=RenderProgress)
    output_path: Optional[Path] = None

    # FT-CORE-022: Transient compile observability summary (not persisted).
    # Populated by compile() with speaker-resolution / emotion-inference counts.
    compile_summary: dict = field(default_factory=dict)

    # Internal
    _output_dir: Optional[Path] = None

    def __post_init__(self):
        """Initialize output directory and sync config to casting table."""
        # CH-B-003: pin the in-memory paths to absolute at construction. They
        # arrive as the user typed them ("book.epub" from `audiobooker new
        # book.epub`), and _output_dir below is derived from source_path --
        # so a relative source made every rendered chapter's audio_path
        # CWD-relative too, and the next command run from a different
        # directory could not find a single finished chapter. Absolute in
        # memory, portable on disk (see save()); os.path.abspath rather than
        # Path.resolve() so symlinks are left exactly as the user gave them.
        if self.source_path is not None:
            self.source_path = Path(os.path.abspath(Path(self.source_path)))
        if self.output_path is not None:
            self.output_path = Path(os.path.abspath(Path(self.output_path)))

        if self._output_dir is None and self.source_path:
            self._output_dir = (
                self.source_path.parent / f"{self.source_path.stem}_audio"
            )
        # Keep casting table fallback in sync with project config
        self._sync_fallback_voice()

    def _sync_fallback_voice(self) -> None:
        """F-CORE-4 (wave 2 amend): keep casting.fallback_voice_id in sync
        with config.fallback_voice_id.

        config is the single source of truth; CastingTable keeps its own
        copy of the same value only because CastingTable is also usable
        standalone (no owning ProjectConfig) in tests and casting-only
        workflows, so the field can't simply be removed from it.

        Before this fix, the two copies were synced by ONE line that ran
        only inside __post_init__ (i.e. only at construction with default
        values). load() replaces both self.casting and self.config wholesale
        from the saved JSON AFTER __post_init__ already ran, without
        re-running the sync -- so a project saved after
        `config.fallback_voice_id = "bm_george"` reloads with
        casting.fallback_voice_id still at its old value ("af_heart"):
        _validate_voices() checks "bm_george" (from config) while
        CastingTable.get_voice() actually resolves uncast speakers through
        "af_heart" (from casting) -- validation passes for a voice render
        never uses. Calling this explicitly from load() (after both blocks
        are parsed) and from save() (before serializing) closes both the
        read side and the write side of that gap.
        """
        self.casting.fallback_voice_id = self.config.fallback_voice_id

    # -------------------------------------------------------------------------
    # Render state persistence (FT-CORE-013)
    # -------------------------------------------------------------------------

    def _get_render_state(self) -> dict:
        """Serialize current render progress for persistence."""
        rendered = [c for c in self.chapters if c.is_rendered]
        failed = [c for c in self.chapters if c.audio_path and not c.is_rendered]
        return {
            "last_render_started": self.progress.status if self.progress.status != "idle" else None,
            "chapters_rendered": len(rendered),
            "chapters_failed": len(failed),
            "total_duration_rendered": sum(c.duration_seconds for c in rendered),
            "status": self.progress.status,
            "error_message": self.progress.error_message,
        }

    def _restore_render_state(self, state: dict) -> None:
        """Restore render progress from persisted state."""
        if not state:
            return
        self.progress.status = state.get("status", "idle")
        self.progress.error_message = state.get("error_message")
        # Chapters rendered/failed are derived from chapter data, but we
        # track the persisted counts so status command can show them.
        self.progress.current_chapter = state.get("chapters_rendered", 0)
        self.progress.total_chapters = len(self.chapters)

    def save_render_progress(self) -> None:
        """Save render state to the project file after each chapter completion."""
        if self.project_path:
            self.save(self.project_path)

    # -------------------------------------------------------------------------
    # Factory methods
    # -------------------------------------------------------------------------

    @staticmethod
    def _validate_kwargs(kwargs: dict) -> None:
        """F-CORE-B-020: Reject unknown **kwargs with a helpful error."""
        unknown = set(kwargs.keys()) - _VALID_PROJECT_KWARGS
        if unknown:
            raise TypeError(
                f"Unknown project field(s): {', '.join(sorted(unknown))}. "
                f"Valid fields: {', '.join(sorted(_VALID_PROJECT_KWARGS))}"
            )

    @classmethod
    def from_epub(cls, path: str | Path, **kwargs) -> "AudiobookProject":
        """
        Create project from EPUB file.

        Args:
            path: Path to EPUB file
            **kwargs: Forwarded to AudiobookProject dataclass fields.
                Accepted keys: title, author, config (ProjectConfig),
                casting (CastingTable), and any other AudiobookProject field.

        Returns:
            Initialized AudiobookProject
        """
        from audiobooker.parser.epub import parse_epub
        from audiobooker.language.profile import get_profile

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"EPUB not found: {path}")

        # F-CORE-B-020: Validate kwargs before using them
        cls._validate_kwargs({k: v for k, v in kwargs.items() if k != "config"})

        # Extract config to pass EPUB parsing thresholds
        config = kwargs.pop("config", ProjectConfig())

        # Thread the language profile into the parser so language-specific
        # tokenization/heading rules apply. parse_epub accepts profile= once
        # the parser exposes it; fall back gracefully if it doesn't yet.
        profile = get_profile(config.language_code)
        # INPUT (v2.1): thread config.use_toc so the parser can split on the
        # EPUB's table of contents when available. parse_epub gains use_toc=
        # in the parser module; call defensively so an older parser signature
        # (no use_toc / no profile) still works and preserves spine-splitting.
        try:
            # Relay (wave 2, parser-lang domain): parse_epub now also accepts
            # footnote_behavior= (validated inline/end/skip, default
            # "inline"). Without threading it through, ProjectConfig's own
            # validated/CLI-mapped/documented footnote_behavior field could
            # never actually reach the parser. Only added to this first,
            # most-featureful call -- same convention already used for
            # use_toc above -- since the existing TypeError fallback chain
            # keeps an older parser signature working.
            metadata, chapters = parse_epub(
                path,
                min_chapter_words=config.min_chapter_words,
                keep_titled_short_chapters=config.keep_titled_short_chapters,
                profile=profile,
                use_toc=config.use_toc,
                footnote_behavior=config.footnote_behavior,
            )
        except TypeError:
            try:
                metadata, chapters = parse_epub(
                    path,
                    min_chapter_words=config.min_chapter_words,
                    keep_titled_short_chapters=config.keep_titled_short_chapters,
                    profile=profile,
                )
            except TypeError:
                metadata, chapters = parse_epub(
                    path,
                    min_chapter_words=config.min_chapter_words,
                    keep_titled_short_chapters=config.keep_titled_short_chapters,
                )

        # Reconcile the EPUB's declared language. If the EPUB declares a
        # language and the caller did NOT explicitly request one (config still
        # at the "en" default), adopt the EPUB's language so downstream
        # compilation uses the right profile. If the user DID request a
        # language that conflicts, keep theirs but warn.
        declared = (metadata.get("language") or "").strip().lower()
        if declared:
            declared_code = declared.split("-")[0]  # "en-US" -> "en"
            user_set_lang = config.language_code != "en"
            try:
                get_profile(declared_code)
                known = True
            except ValueError:
                known = False
            if known and not user_set_lang and declared_code != config.language_code:
                logger.info(
                    "Adopting EPUB declared language %r (was %r)",
                    declared_code, config.language_code,
                )
                config.language_code = declared_code
            elif known and user_set_lang and declared_code != config.language_code:
                logger.warning(
                    "EPUB declares language %r but --lang %r was requested; "
                    "using %r.",
                    declared_code, config.language_code, config.language_code,
                )

        # Build BookMetadata from EPUB metadata (FT-CORE-014)
        book_metadata = kwargs.pop("metadata", BookMetadata())
        cover_path_str = metadata.get("cover_art_path")
        if cover_path_str:
            book_metadata.cover_art_path = Path(cover_path_str)
        if metadata.get("publisher"):
            book_metadata.publisher = metadata["publisher"]
        if metadata.get("year"):
            book_metadata.year = metadata["year"]

        project = cls(
            # FEAT-PROD-008: kwargs.pop, not a bare default. A caller
            # passing title=/author= — which every from_* docstring
            # advertises — otherwise collides with these and raises
            # TypeError before the project is ever built. from_folder was
            # the only constructor that got this right.
            title=kwargs.pop("title", metadata.get("title", path.stem)),
            author=kwargs.pop("author", metadata.get("author", "")),
            source_path=path,
            chapters=chapters,
            config=config,
            metadata=book_metadata,
            **kwargs,
        )

        # Auto-add narrator to casting
        project.cast("narrator", "af_heart", emotion="calm", description="Default narrator")

        return project

    @classmethod
    def from_pdf(cls, path: str | Path, **kwargs) -> "AudiobookProject":
        """
        Create project from PDF file (FT-CORE-001).

        Uses PyMuPDF (fitz) for text extraction with chapter boundary
        detection via heading heuristics. Scanned PDFs are rejected
        with a clear OCR suggestion.

        Args:
            path: Path to PDF file.
            **kwargs: Forwarded to AudiobookProject dataclass fields.

        Returns:
            Initialized AudiobookProject.

        Raises:
            ImportError: If pymupdf is not installed.
            FileNotFoundError: If the file doesn't exist.
            ValueError: If the PDF is scanned/image-only or corrupt.
        """
        from audiobooker.parser.pdf import parse_pdf
        from audiobooker.language.profile import get_profile

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {path}")

        # INPUT (v2.1): force plain text extraction even when the PDF looks
        # scanned/image-only (skips the OCR-rejection guard). Pop before kwargs
        # validation since it is a parse option, not an AudiobookProject field.
        force_text = kwargs.pop("force_text", False)

        # F-CORE-B-020: Validate kwargs
        cls._validate_kwargs({k: v for k, v in kwargs.items() if k != "config"})

        config = kwargs.pop("config", ProjectConfig())

        # Thread the language profile into the parser. parse_pdf accepts
        # profile= and force_text=; fall back if an older parser lacks them.
        profile = get_profile(config.language_code)
        try:
            # Relay (wave 2, parser-lang domain): parse_pdf now also accepts
            # keep_titled_short_chapters= (default False = unchanged
            # historical behavior). ProjectConfig has this field (shared with
            # from_epub), so it's threaded through the same way. Only added
            # to this first, most-featureful call; the existing TypeError
            # fallback chain below keeps an older parser signature working.
            metadata, chapters = parse_pdf(
                path,
                min_chapter_words=config.min_chapter_words,
                profile=profile,
                force_text=force_text,
                keep_titled_short_chapters=config.keep_titled_short_chapters,
            )
        except TypeError:
            try:
                metadata, chapters = parse_pdf(
                    path,
                    min_chapter_words=config.min_chapter_words,
                    force_text=force_text,
                )
            except TypeError:
                metadata, chapters = parse_pdf(
                    path,
                    min_chapter_words=config.min_chapter_words,
                )

        project = cls(
            # FEAT-PROD-008: kwargs.pop, not a bare default. A caller
            # passing title=/author= — which every from_* docstring
            # advertises — otherwise collides with these and raises
            # TypeError before the project is ever built. from_folder was
            # the only constructor that got this right.
            title=kwargs.pop("title", metadata.get("title", path.stem)),
            author=kwargs.pop("author", metadata.get("author", "")),
            source_path=path,
            chapters=chapters,
            config=config,
            **kwargs,
        )

        # Auto-add narrator to casting
        project.cast("narrator", "af_heart", emotion="calm", description="Default narrator")

        return project

    @classmethod
    def from_docx(cls, path: str | Path, **kwargs) -> "AudiobookProject":
        """
        Create project from a Word (.docx) file (INPUT v2.1).

        Mirrors from_epub: parser.docx.parse_docx returns the same
        (metadata dict, list[Chapter]) shape, so the metadata reconciliation
        and BookMetadata population below are identical to the EPUB path.

        Args:
            path: Path to the .docx file.
            **kwargs: Forwarded to AudiobookProject dataclass fields.
                Accepted keys: title, author, config (ProjectConfig),
                casting (CastingTable), and any other AudiobookProject field.

        Returns:
            Initialized AudiobookProject.

        Raises:
            ImportError: If python-docx is not installed.
            FileNotFoundError: If the file doesn't exist.
            ValueError: If the document is empty or unreadable.
        """
        from audiobooker.parser.docx import parse_docx
        from audiobooker.language.profile import get_profile

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"DOCX not found: {path}")

        # F-CORE-B-020: Validate kwargs before using them
        cls._validate_kwargs({k: v for k, v in kwargs.items() if k != "config"})

        config = kwargs.pop("config", ProjectConfig())

        # Thread the language profile into the parser. parse_docx accepts
        # profile= per the contract; fall back gracefully if it doesn't yet.
        profile = get_profile(config.language_code)
        try:
            metadata, chapters = parse_docx(
                path,
                min_chapter_words=config.min_chapter_words,
                profile=profile,
            )
        except TypeError:
            metadata, chapters = parse_docx(
                path,
                min_chapter_words=config.min_chapter_words,
            )

        # Build BookMetadata from the parsed metadata (mirror from_epub).
        book_metadata = kwargs.pop("metadata", BookMetadata())
        cover_path_str = metadata.get("cover_art_path")
        if cover_path_str:
            book_metadata.cover_art_path = Path(cover_path_str)
        if metadata.get("publisher"):
            book_metadata.publisher = metadata["publisher"]
        if metadata.get("year"):
            book_metadata.year = metadata["year"]

        project = cls(
            # FEAT-PROD-008: kwargs.pop, not a bare default. A caller
            # passing title=/author= — which every from_* docstring
            # advertises — otherwise collides with these and raises
            # TypeError before the project is ever built. from_folder was
            # the only constructor that got this right.
            title=kwargs.pop("title", metadata.get("title", path.stem)),
            author=kwargs.pop("author", metadata.get("author", "")),
            source_path=path,
            chapters=chapters,
            config=config,
            metadata=book_metadata,
            **kwargs,
        )

        # Auto-add narrator to casting
        project.cast("narrator", "af_heart", emotion="calm", description="Default narrator")

        return project

    @classmethod
    def from_folder(cls, directory: str | Path, **kwargs) -> "AudiobookProject":
        """
        Create project from a folder of per-chapter text files (INPUT v2.1).

        Each .txt/.md file in the folder becomes one chapter, naturally sorted
        by filename (so 01_, 1., and bare numeric prefixes order correctly).
        parser.text.read_folder_chapters returns a list of (title, text) pairs,
        which we build into a project via from_chapters semantics.

        Args:
            directory: Path to the folder of chapter files.
            **kwargs: Forwarded to AudiobookProject dataclass fields.
                Accepted keys: title, author, config (ProjectConfig),
                casting (CastingTable), and any other AudiobookProject field.

        Returns:
            Initialized AudiobookProject.

        Raises:
            FileNotFoundError: If the directory doesn't exist.
            ValueError: If the folder contains no usable chapter files.
        """
        from audiobooker.parser.text import read_folder_chapters
        from audiobooker.language.profile import get_profile

        directory = Path(directory)
        if not directory.exists() or not directory.is_dir():
            raise FileNotFoundError(f"Folder not found: {directory}")

        # F-CORE-B-020: Validate kwargs before using them
        cls._validate_kwargs({k: v for k, v in kwargs.items() if k != "config"})

        config = kwargs.pop("config", ProjectConfig())
        profile = get_profile(config.language_code)

        try:
            chapter_pairs = read_folder_chapters(directory, profile=profile)
        except TypeError:
            chapter_pairs = read_folder_chapters(directory)

        if not chapter_pairs:
            raise ValueError(
                f"No chapter files (.txt/.md) found in folder: {directory}. "
                "Add one text file per chapter, e.g. 01_intro.txt, 02_rising.txt."
            )

        chapter_objects = [
            Chapter(index=i, title=ch_title, raw_text=content)
            for i, (ch_title, content) in enumerate(chapter_pairs)
        ]

        project = cls(
            title=kwargs.pop("title", directory.name),
            author=kwargs.pop("author", ""),
            source_path=directory,
            chapters=chapter_objects,
            config=config,
            **kwargs,
        )

        # Auto-add narrator to casting
        project.cast("narrator", "af_heart", emotion="calm", description="Default narrator")

        return project

    @classmethod
    def from_text(cls, path: str | Path, **kwargs) -> "AudiobookProject":
        """
        Create project from TXT/Markdown file.

        Args:
            path: Path to text file
            **kwargs: Forwarded to AudiobookProject dataclass fields.
                Accepted keys: title, author, config (ProjectConfig),
                casting (CastingTable), and any other AudiobookProject field.

        Returns:
            Initialized AudiobookProject
        """
        from audiobooker.parser.text import parse_text
        from audiobooker.language.profile import get_profile

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Text file not found: {path}")

        # INPUT (v2.1): optional custom chapter-delimiter regex from the CLI.
        # Pop it before kwargs validation since it is a parse option, not an
        # AudiobookProject field.
        chapter_delimiter = kwargs.pop("chapter_delimiter", None)

        # F-CORE-B-020: Validate kwargs
        cls._validate_kwargs({k: v for k, v in kwargs.items() if k != "config"})

        config = kwargs.pop("config", ProjectConfig())
        profile = get_profile(config.language_code)

        metadata, chapters = parse_text(
            path, chapter_delimiter=chapter_delimiter, profile=profile
        )

        project = cls(
            # FEAT-PROD-008: kwargs.pop, not a bare default. A caller
            # passing title=/author= — which every from_* docstring
            # advertises — otherwise collides with these and raises
            # TypeError before the project is ever built. from_folder was
            # the only constructor that got this right.
            title=kwargs.pop("title", metadata.get("title", path.stem)),
            author=kwargs.pop("author", metadata.get("author", "")),
            source_path=path,
            chapters=chapters,
            config=config,
            **kwargs,
        )

        # Auto-add narrator to casting
        project.cast("narrator", "af_heart", emotion="calm", description="Default narrator")

        return project

    @classmethod
    def from_string(
        cls,
        text: str,
        title: str = "Untitled",
        author: str = "",
        lang: str = "en",
        **kwargs,
    ) -> "AudiobookProject":
        """
        Create project from a raw text string (no file needed).

        Args:
            text: Full book text.
            title: Book title.
            author: Book author.
            lang: Language code (default "en").
            **kwargs: Additional project config.

        Returns:
            Initialized AudiobookProject.
        """
        from audiobooker.parser.text import split_into_chapters, extract_frontmatter
        from audiobooker.language.profile import get_profile

        # INPUT (v2.1): optional custom chapter-delimiter regex. Pop before
        # kwargs validation since it is a parse option, not a project field.
        chapter_delimiter = kwargs.pop("chapter_delimiter", None)

        # F-CORE-B-020: Validate kwargs
        cls._validate_kwargs({k: v for k, v in kwargs.items() if k != "config"})

        config = kwargs.pop("config", ProjectConfig(language_code=lang))
        config.language_code = lang
        profile = get_profile(lang)

        metadata, body = extract_frontmatter(text)
        chapter_data = split_into_chapters(
            body, delimiter_pattern=chapter_delimiter, profile=profile
        )

        chapters = [
            Chapter(index=i, title=ch_title, raw_text=content)
            for i, (ch_title, content) in enumerate(chapter_data)
        ]

        project = cls(
            title=metadata.get("title", title),
            author=metadata.get("author", author),
            chapters=chapters,
            config=config,
            **kwargs,
        )

        project.cast("narrator", "af_heart", emotion="calm", description="Default narrator")
        return project

    @classmethod
    def from_chapters(
        cls,
        chapters: list[tuple[str, str]],
        title: str = "Untitled",
        author: str = "",
        lang: str = "en",
        **kwargs,
    ) -> "AudiobookProject":
        """
        Create project from pre-split chapters.

        Args:
            chapters: List of (title, raw_text) tuples.
            title: Book title.
            author: Book author.
            lang: Language code (default "en").
            **kwargs: Additional project config.

        Returns:
            Initialized AudiobookProject.
        """
        # F-CORE-B-020: Validate kwargs
        cls._validate_kwargs({k: v for k, v in kwargs.items() if k != "config"})

        config = kwargs.pop("config", ProjectConfig(language_code=lang))
        config.language_code = lang

        chapter_objects = [
            Chapter(index=i, title=ch_title, raw_text=content)
            for i, (ch_title, content) in enumerate(chapters)
        ]

        project = cls(
            title=title,
            author=author,
            chapters=chapter_objects,
            config=config,
            **kwargs,
        )

        project.cast("narrator", "af_heart", emotion="calm", description="Default narrator")
        return project

    @classmethod
    def _migrate(cls, data: dict, from_version: int) -> dict:
        """Migrate a loaded project dict from an older schema version.

        Migration seam (FT-CORE): dispatched from load() when a project file's
        schema_version is below SCHEMA_VERSION.

        **v1 -> v2 (CH-B-003).** A v1 relative path meant "relative to
        whatever directory the command happened to run from"; a v2 relative
        path means "relative to the project file". There is no transform that
        can recover the v1 anchor — the CWD of the run that wrote the file is
        gone — and re-anchoring on the project file is both the fix and the
        overwhelmingly likely original intent, since the project file is
        written next to the book. So the migration re-interprets rather than
        rewrites, and says which paths changed meaning at WARNING, because for
        the minority of users who ran audiobooker from somewhere else that
        reinterpretation points at a different file and they need to be told
        rather than left to debug a mysteriously missing source. Absolute v1
        paths mean the same thing under both versions and are left alone.

        Args:
            data: The raw project dict as loaded from JSON.
            from_version: The schema version stored in the file.

        Returns:
            The (possibly transformed) project dict.
        """
        logger.info(
            "Upgrading project from schema v%d to v%d", from_version, SCHEMA_VERSION
        )

        if from_version < 2:
            cls._warn_about_reanchored_paths(data)

        data["schema_version"] = SCHEMA_VERSION
        return data

    @staticmethod
    def _warn_about_reanchored_paths(data: dict) -> None:
        """Report every v1 relative path whose anchor moves in v2."""
        reanchored: list[str] = []
        for key in _V1_PATH_KEYS:
            value = data.get(key)
            if isinstance(value, str) and value and not _looks_absolute(value):
                reanchored.append(f"{key}={value!r}")
        for chapter in data.get("chapters") or []:
            if not isinstance(chapter, dict):
                continue
            value = chapter.get("audio_path")
            if isinstance(value, str) and value and not _looks_absolute(value):
                reanchored.append(f"chapter {chapter.get('index')} audio_path={value!r}")

        if reanchored:
            logger.warning(
                "Schema v1 -> v2: %d relative path(s) in this project file are "
                "now resolved against the project file's directory instead of "
                "the current working directory (%s). If this project was "
                "always run from the directory holding the project file, "
                "nothing changes.",
                len(reanchored),
                "; ".join(reanchored),
            )

    @classmethod
    def load(cls, path: str | Path) -> "AudiobookProject":
        """
        Load project from JSON file.

        Args:
            path: Path to .audiobooker project file

        Returns:
            Loaded AudiobookProject
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Project file not found: {path}")

        # F-CORE-B-006: Reject oversized project files
        file_size = path.stat().st_size
        if file_size > _MAX_PROJECT_FILE_BYTES:
            size_mb = file_size / (1024 * 1024)
            raise ValueError(
                f"Project file is too large ({size_mb:.1f} MB, limit is 50 MB). "
                "The file may be corrupted or contain embedded binary data. "
                "Try re-exporting from the original source."
            )

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # CLI-A-007: A valid-JSON-but-wrong-shape file (e.g. a top-level array)
        # would raise a raw AttributeError on data.get(...) below. Reject it
        # with a clear message instead, mirroring the checks in import_casting.
        if not isinstance(data, dict):
            raise ValueError(
                "Project file is not a valid audiobooker project "
                f"(expected a JSON object, got {type(data).__name__})."
            )

        # Check schema version
        schema_version = data.get("schema_version", 1)
        if schema_version > SCHEMA_VERSION:
            raise ValueError(
                f"Project file uses schema v{schema_version}, "
                f"but this version only supports up to v{SCHEMA_VERSION}"
            )
        # Upgrade older project files through the migration seam. Currently a
        # no-op stub, but it establishes the dispatch point so future schema
        # bumps have a single place to add upgrade steps.
        if schema_version < SCHEMA_VERSION:
            data = cls._migrate(data, from_version=schema_version)

        # F-CORE-6 (wave 2 amend): _validated_path used to be defined as a
        # closure right here, which meant Chapter.from_dict's audio_path and
        # BookMetadata.from_dict's cover_art_path (both also deserialized
        # from this same untrusted project file, a few lines below) had no
        # way to reach it and skipped the '..'/null-byte check applied to
        # source_path/output_path. Moved to audiobooker.models (imported at
        # the top of this file) so Chapter/BookMetadata's own from_dict can
        # use the identical check. Behavior here is unchanged.

        # CH-B-003: every stored path resolves against the PROJECT FILE's
        # directory, not the process CWD, so `audiobooker render --resume`
        # finds its already-rendered chapters from wherever it is run.
        base = Path(os.path.abspath(path)).parent

        project = cls(
            title=data.get("title", "Untitled"),
            author=data.get("author", ""),
            source_path=resolve_stored_path(data.get("source_path"), base),
            project_path=path,
            created_at=data.get("created_at", datetime.now().isoformat()),
            modified_at=data.get("modified_at", datetime.now().isoformat()),
            output_path=resolve_stored_path(data.get("output_path"), base),
        )

        # Load chapters
        project.chapters = [
            Chapter.from_dict(c, base) for c in data.get("chapters", [])
        ]

        # Load casting table
        if "casting" in data:
            project.casting = CastingTable.from_dict(data["casting"])

        # Load config
        if "config" in data:
            project.config = ProjectConfig.from_dict(data["config"])

        # F-CORE-4 (wave 2 amend): re-sync casting.fallback_voice_id to the
        # just-loaded config now that both blocks have been parsed -- see
        # _sync_fallback_voice's docstring for why the __post_init__-time
        # sync alone isn't enough once casting/config are replaced here.
        project._sync_fallback_voice()

        # Load metadata
        if "metadata" in data:
            project.metadata = BookMetadata.from_dict(data["metadata"], base)

        # FT-CORE-013: Restore render state
        if "render_state" in data:
            project._restore_render_state(data["render_state"])

        return project

    # -------------------------------------------------------------------------
    # Persistence
    # -------------------------------------------------------------------------

    def save(self, path: Optional[str | Path] = None) -> Path:
        """
        Save project to JSON file.

        Args:
            path: Output path (uses project_path if not specified)

        Returns:
            Path to saved file
        """
        if path is None:
            if self.project_path is None:
                # Generate default path
                if self.source_path:
                    path = self.source_path.with_suffix(".audiobooker")
                else:
                    path = Path(f"{_sanitize_filename(self.title)}.audiobooker")
            else:
                path = self.project_path

        path = Path(path)
        self.project_path = path
        self.modified_at = datetime.now().isoformat()

        # F-CORE-4 (wave 2 amend): re-sync before serializing so a project
        # that had config.fallback_voice_id mutated directly (no save/load
        # round trip yet) is still written out consistent, not just
        # corrected on the NEXT load().
        self._sync_fallback_voice()

        # CH-B-003 + COORD-B-001: paths are stored relative to THIS file where
        # possible, then '~'-relative, then absolute. See portable_path() in
        # models.py for the precedence and why it is that order.
        base = Path(os.path.abspath(path)).parent

        data = {
            "schema_version": SCHEMA_VERSION,
            "title": self.title,
            "author": self.author,
            "source_path": portable_path(self.source_path, base),
            "created_at": self.created_at,
            "modified_at": self.modified_at,
            "output_path": portable_path(self.output_path, base),
            "chapters": [c.to_dict(base) for c in self.chapters],
            "casting": self.casting.to_dict(),
            "config": self.config.to_dict(),
            "metadata": self.metadata.to_dict(base),
            "render_state": self._get_render_state(),
        }

        # F-CORE-B-005: Atomic write — write to .tmp then replace
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(str(tmp_path), str(path))
        except BaseException:
            # Clean up temp file on any failure
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

        # F-CORE-B-013: Log successful save
        logger.info("Project saved to %s (%d chapters)", path, len(self.chapters))

        return path

    # -------------------------------------------------------------------------
    # Casting
    # -------------------------------------------------------------------------

    def cast(
        self,
        name: str,
        voice: str,
        emotion: Optional[str] = UNSET,
        description: Optional[str] = UNSET,
        speed: float = UNSET,
    ) -> Character:
        """
        Assign a voice to a character.

        F-CORE-3 (wave 2 amend): defaults changed from None/None/1.0 to the
        shared UNSET sentinel (audiobooker.models.UNSET) so that a re-cast
        through THIS project-level method also preserves prior tuning,
        matching CastingTable.cast() (see that method's docstring for the
        full rationale). Before this change, AudiobookProject.cast() always
        forwarded concrete None/None/1.0 values, which meant
        CastingTable.cast()'s own UNSET-based fix could never actually
        trigger via the project API -- every project.cast() call looked to
        CastingTable like the caller explicitly passed emotion=None,
        description=None, speed=1.0, wiping tuning on every re-cast anyway.

        Args:
            name: Character name (e.g., "narrator", "Alice")
            voice: Voice ID (e.g., "af_bella", "bm_george")
            emotion: Default emotion. Omit to leave an existing character's
                emotion unchanged; pass None explicitly to clear it.
            description: Notes about the character. Same omit/None-clears
                distinction as emotion.
            speed: Speech speed multiplier (0.5-2.0). Omit to leave an
                existing character's speed unchanged; a brand-new character
                still defaults to 1.0.

        Returns:
            The created/updated Character
        """
        return self.casting.cast(name, voice, emotion, description, speed=speed)

    def list_characters(self) -> list[str]:
        """Get list of all cast characters."""
        return self.casting.list_characters()

    def get_detected_speakers(self) -> set[str]:
        """
        Get all speakers detected in compiled chapters.

        Returns:
            Set of speaker names found in utterances
        """
        speakers = set()
        for chapter in self.chapters:
            for utterance in chapter.utterances:
                speakers.add(utterance.speaker)
        return speakers

    def get_uncast_speakers(self) -> set[str]:
        """
        Get speakers that appear in text but aren't cast.

        Returns:
            Set of uncast speaker names (canonical keys)
        """
        detected = {self.casting.normalize_key(s) for s in self.get_detected_speakers()}
        cast = set(self.casting.characters.keys())
        return detected - cast

    # -------------------------------------------------------------------------
    # Project diff (FT-CORE-018)
    # -------------------------------------------------------------------------

    def diff(self, other: "AudiobookProject") -> dict:
        """
        Compute a structured diff between this project and another.

        Compares chapters (by ID when available, else by index) and
        utterances within matching chapters.

        Args:
            other: The project to compare against.

        Returns:
            Dict with keys:
                added_chapters: list of chapter titles present in *other* but not *self*.
                removed_chapters: list of chapter titles present in *self* but not *other*.
                changed_utterances: list of dicts describing per-field changes:
                    {chapter, index, field, old, new}
        """
        result: dict = {
            "added_chapters": [],
            "removed_chapters": [],
            "changed_utterances": [],
        }

        # Build lookup by chapter ID (fall back to index-based key)
        def _chapter_key(ch: Chapter) -> str:
            return ch.id if ch.id else f"__idx_{ch.index}"

        self_map = {_chapter_key(ch): ch for ch in self.chapters}
        other_map = {_chapter_key(ch): ch for ch in other.chapters}

        self_keys = set(self_map.keys())
        other_keys = set(other_map.keys())

        # Removed = in self but not in other
        for key in sorted(self_keys - other_keys):
            result["removed_chapters"].append(self_map[key].title)

        # Added = in other but not in self
        for key in sorted(other_keys - self_keys):
            result["added_chapters"].append(other_map[key].title)

        # Changed utterances in common chapters
        _COMPARE_FIELDS = ("speaker", "text", "emotion")
        for key in sorted(self_keys & other_keys):
            self_ch = self_map[key]
            other_ch = other_map[key]
            max_len = max(len(self_ch.utterances), len(other_ch.utterances))
            for idx in range(max_len):
                self_utt = self_ch.utterances[idx] if idx < len(self_ch.utterances) else None
                other_utt = other_ch.utterances[idx] if idx < len(other_ch.utterances) else None

                if self_utt is None and other_utt is not None:
                    result["changed_utterances"].append({
                        "chapter": other_ch.title,
                        "index": idx,
                        "field": "__added__",
                        "old": None,
                        "new": other_utt.text[:80],
                    })
                    continue
                if self_utt is not None and other_utt is None:
                    result["changed_utterances"].append({
                        "chapter": self_ch.title,
                        "index": idx,
                        "field": "__removed__",
                        "old": self_utt.text[:80],
                        "new": None,
                    })
                    continue

                for fld in _COMPARE_FIELDS:
                    old_val = getattr(self_utt, fld)
                    new_val = getattr(other_utt, fld)
                    if old_val != new_val:
                        result["changed_utterances"].append({
                            "chapter": self_ch.title,
                            "index": idx,
                            "field": fld,
                            "old": old_val,
                            "new": new_val,
                        })

        return result

    def _validate_voices(self, engine=None) -> None:
        """
        Check that all referenced voice IDs exist in the active voice catalog.

        Args:
            engine: Optional TTS engine. When it advertises ``list_voices()``
                its catalog is authoritative (FT-ENGINE-001); otherwise the
                voice-soundboard catalog is used, exactly as before. Passing
                the engine matters now that the renderer runs this gate for
                every render path -- validating Piper voice IDs against the
                voice-soundboard catalog would be a false failure.

        Raises:
            VoiceNotFoundError: If any voice IDs are missing.
            VoiceBackendIncompatibleError: If the backend IS installed but its
                API has drifted -- an unreadable catalog cannot certify any
                voice ID, so that is surfaced rather than swallowed.
        """
        from audiobooker.casting.voice_registry import (
            VoiceBackendUnavailableError,
            VoiceNotFoundError,
            get_available_voices,
            validate_voices,
        )

        # Collect all voice IDs: cast characters + fallback
        voice_ids = {char.voice for char in self.casting.characters.values()}
        voice_ids.add(self.config.fallback_voice_id)

        try:
            available = get_available_voices(engine)
        except VoiceBackendUnavailableError:
            # Genuine absence of the optional backend is a warn-and-skip, the
            # same policy validate_voices() applies when it queries the
            # catalog itself. Hard-failing here would turn every render on a
            # machine without voice-soundboard into an ImportError raised by
            # *validation* -- which matters now that the renderer runs this
            # gate on all three render paths, not just Project.render().
            logger.warning(
                "voice-soundboard is not installed — skipping voice validation. "
                "Voice IDs will NOT be checked before rendering."
            )
            return

        missing = validate_voices(voice_ids, available)
        if missing:
            raise VoiceNotFoundError(missing=missing, available_count=len(available))

    # -------------------------------------------------------------------------
    # Pronunciation Overrides (FT-CORE-011)
    # -------------------------------------------------------------------------

    def add_pronunciation(self, word: str, replacement: str) -> list[int]:
        """
        Add a pronunciation override.

        Before utterance creation in compile, the word will be substituted
        with the replacement text (whole-word, case-insensitive).

        FEAT-PROD-002 — overrides added AFTER compile
        ---------------------------------------------
        Overrides are applied in ``_preprocess_text``, which only runs during
        compile. Adding one to a finished book therefore used to be a total
        no-op end to end: ``render()``'s gate found nothing uncompiled, every
        chapter's ``chapter_text_hash`` was unchanged so every chapter
        cache-hit, and the name came out of the speakers mispronounced — with
        the CLI reporting success. Hearing a name wrong is the single most
        likely reason anyone re-renders a finished book, and it was the one
        edit the pipeline dropped.

        The fix applies the new override to the ALREADY-COMPILED utterance
        text, in place, right here. That is the shape
        ``text_cleaners.apply_pronunciation_overrides`` itself recommends
        ("the right long-term shape is to apply overrides at RENDER time, on
        utterance text, where attribution has already happened") and it is
        strictly better than clearing the chapters for recompile: a recompile
        would re-derive every utterance from raw text and silently discard
        imported review edits, emotion overrides and mood spans across the
        whole book. Rewriting the text changes ``chapter_text_hash``, so the
        affected chapters miss the cache and re-render while every other
        chapter still hits.

        A word that names a cast character (or one of their aliases) is
        REFUSED, exactly as it is at compile time (PH-B-005) — rewriting it
        would un-cast them.

        Args:
            word: The word to replace (e.g., "Hermione")
            replacement: The phonetic replacement (e.g., "Her-MY-oh-nee")

        Returns:
            The indices of the chapters whose compiled text changed, so a
            caller (``pronunciation add``) can say how much will re-render
            instead of printing a bare success.
        """
        if not word or not word.strip():
            raise ValueError("Pronunciation word must not be empty.")
        if not replacement or not replacement.strip():
            raise ValueError("Pronunciation replacement must not be empty.")
        word = word.strip()
        replacement = replacement.strip()
        self.config.pronunciation_overrides[word] = replacement
        self.modified_at = datetime.now().isoformat()
        return self._apply_override_to_compiled(word, replacement)

    def _apply_override_to_compiled(self, word: str, replacement: str) -> list[int]:
        """Rewrite one override into already-compiled utterance text.

        Returns the indices of the chapters that actually changed. Chapters
        that are not compiled are left alone: ``compile()`` will apply the
        override from ``_preprocess_text`` when it runs.

        Two things are done ONCE here rather than per utterance, because
        ``apply_pronunciation_overrides`` is written for whole-document text
        and both of its diagnostics are per-call:

        * the PH-B-005 protected-name refusal, so a refused override logs one
          ERROR instead of one per utterance in the book;
        * the "override never matched" warning, which would otherwise fire for
          every utterance that simply does not contain the word — measured at
          8 spurious warnings on a 10-utterance two-chapter book, which under
          the CLI's default WARNING level is noise that buries the real one.

        The pre-filter reuses ``_override_pattern`` rather than approximating
        it with a substring test: that helper IS the definition of "this
        override matches this text" (it drops the ``\\b`` anchors for CJK,
        kana, Hangul and Thai keys, where a word boundary can never assert
        anything), so borrowing it is the only way the filter cannot drift
        away from the matcher it is filtering for.
        """
        from audiobooker.models import normalize_speaker_key
        from audiobooker.parser.text_cleaners import (
            _override_pattern,
            apply_pronunciation_overrides,
        )

        if normalize_speaker_key(word) in self.casting.protected_names():
            logger.error(
                f"Pronunciation override {word!r} names a CAST CHARACTER (or "
                f"one of their aliases) and was refused. Rewriting it would "
                f"leave every line they speak unattributed. Set the "
                f"pronunciation on the character instead."
            )
            return []

        try:
            matcher = _re.compile(_override_pattern(word), _re.IGNORECASE)
        except _re.error as e:
            logger.warning(
                f"Pronunciation override {word!r} could not be compiled "
                f"({e}) — no compiled chapters were changed."
            )
            return []

        one = {word: replacement}
        # Passing the (already-cleared) protected set rather than None also
        # silences the _looks_like_proper_noun advisory, which fires on any
        # capitalized key — i.e. on exactly the proper nouns this feature
        # exists for — and would otherwise print once per utterance.
        protected = self.casting.protected_names()
        affected: list[int] = []
        for chapter in self.chapters:
            if not chapter.is_compiled:
                continue
            changed = False
            for utt in chapter.utterances:
                if not matcher.search(utt.text):
                    continue
                new_text = apply_pronunciation_overrides(
                    utt.text, one, protected_names=protected
                )
                if new_text != utt.text:
                    utt.text = new_text
                    changed = True
            if changed:
                affected.append(chapter.index)
        if affected:
            logger.info(
                f"PRONUNCIATION_APPLIED: {word!r} -> {replacement!r} in "
                f"{len(affected)} compiled chapter(s): {affected}"
            )
        return affected

    def remove_pronunciation(self, word: str) -> list[int]:
        """
        Remove a pronunciation override.

        FEAT-PROD-002: removal is the one direction that cannot be undone in
        place — the original spelling is gone from the compiled utterances
        and only ``raw_text`` still holds it. Affected chapters are therefore
        cleared so ``render()``'s compile gate re-derives them (that gate
        tests ``is_compiled``, which is ``len(utterances) > 0``). Scoped to
        chapters whose raw text actually contains the word, so removing an
        override that only ever fired in chapter 3 does not throw away
        chapter 20's review edits.

        Args:
            word: The word to remove from overrides

        Returns:
            The indices of the chapters cleared for recompile.

        Raises:
            KeyError: If the word is not in the overrides
        """
        key = word.strip()
        if key not in self.config.pronunciation_overrides:
            raise KeyError(
                f"No pronunciation override for {word!r}. "
                f"Current overrides: {', '.join(sorted(self.config.pronunciation_overrides.keys())) or '(none)'}"
            )
        del self.config.pronunciation_overrides[key]
        self.modified_at = datetime.now().isoformat()

        # Same matcher the override itself used, so "which chapters did this
        # fire in" gets the same answer going out as it did going in.
        from audiobooker.parser.text_cleaners import _override_pattern

        try:
            pattern = _re.compile(_override_pattern(key), _re.IGNORECASE)
        except _re.error:  # pragma: no cover - key compiled fine on the way in
            pattern = _re.compile(_re.escape(key), _re.IGNORECASE)
        affected: list[int] = []
        for chapter in self.chapters:
            if not chapter.is_compiled:
                continue
            if pattern.search(chapter.raw_text):
                chapter.utterances = []
                affected.append(chapter.index)
        if affected:
            # WARNING, not INFO: review edits, emotion overrides and mood
            # spans live directly on chapter.utterances (review.py writes
            # them there and nowhere else), so clearing a chapter discards
            # them. It is unavoidable — only raw_text still holds the
            # original spelling — but it must not be silent.
            logger.warning(
                f"PRONUNCIATION_REMOVED: {key!r} — chapter(s) {affected} were "
                f"cleared and will recompile from their raw text on the next "
                f"render. Any imported review edits, emotion overrides or "
                f"mood spans in those chapters are discarded; every other "
                f"chapter is untouched."
            )
        return affected

    # -------------------------------------------------------------------------
    # Voice Preview (FT-CORE-005)
    # -------------------------------------------------------------------------

    def preview(
        self,
        text: str,
        voice: str,
        speed: float = 1.0,
        emotion: str = "",
    ) -> Path:
        """
        Render a short text snippet to a temp WAV for voice preview.

        Truncates text to max 500 characters at a sentence boundary.
        Lazily imports the TTS engine.

        Args:
            text: Text to preview (truncated to ~500 chars at sentence boundary)
            voice: Voice ID to use (e.g., "af_bella")
            speed: Speech speed multiplier (0.5-2.0, default 1.0)
            emotion: Optional emotion tag (e.g., "happy", "whisper")

        Returns:
            Path to the rendered WAV file (in a temp directory)
        """
        import tempfile

        # Truncate at sentence boundary within 500 chars
        max_chars = 500
        if len(text) > max_chars:
            # Find last sentence-ending punctuation before the limit
            truncated = text[:max_chars]
            # Search for last sentence ender
            for i in range(len(truncated) - 1, -1, -1):
                if truncated[i] in ".!?":
                    truncated = truncated[: i + 1]
                    break
            else:
                # No sentence boundary found; hard truncate at word boundary
                last_space = truncated.rfind(" ")
                if last_space > 0:
                    truncated = truncated[:last_space]
            text = truncated.strip()

        if not text:
            raise ValueError("Preview text is empty after truncation.")

        # Lazy import of TTS engine
        from audiobooker.renderer.engine import TTSEngine

        engine = TTSEngine()

        # CH-B-012: the temp file is created BEFORE synthesis and never
        # cleaned up, so every preview whose backend raised -- a missing TTS
        # model, an unknown voice id, a dead GPU: the common case while a user
        # is auditioning voices -- left a 0-byte
        # audiobooker_preview_*.wav in the system temp directory forever.
        # (The name itself is fine: mkstemp picks it randomly and creates it
        # 0600, and closing the handle before handing the path to the engine
        # is what makes this work on Windows at all, where the file cannot be
        # reopened while the handle is live.)
        #
        # A successful preview still returns an undeleted file: the caller
        # gets the path in order to play it, so ownership transfers with the
        # return. Only the failure path is ours to clean up.
        fd, name = tempfile.mkstemp(suffix=".wav", prefix="audiobooker_preview_")
        os.close(fd)
        output_path = Path(name)

        try:
            engine.synthesize(
                text=text,
                voice=voice,
                output_path=output_path,
                speed=speed,
                emotion=emotion or None,
            )
        except BaseException:
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise

        return output_path

    # -------------------------------------------------------------------------
    # Batch Casting Import/Export (FT-CORE-007)
    # -------------------------------------------------------------------------

    def _casting_as_list(self) -> list[dict]:
        """Return the casting table as a list-of-dicts (export shape).

        This is the canonical list-of-dicts shape reused by export_casting (JSON
        + CSV branches) and by casting.presets.save_preset (CASTING-DEPTH v2.1).

        F-CORE-1 (wave 2 amend): pitch_shift and emphasis are now always
        included (matching Character.to_dict()'s own convention for those
        two fields -- they always have a concrete, meaningful default of
        0.0/1.0, so there's no "unset" state to omit); default_intensity is
        included only when set, again matching Character.to_dict() exactly,
        so a legacy export with no tuning round-trips byte-for-byte. Before
        this fix, this list dropped all three fields, so a Character with
        pitch_shift=-0.2, emphasis=1.6, default_intensity=0.65 exported to
        JSON came back as 0.0/1.0/None with no error -- and since
        casting.presets.save_preset is fed straight from this same list
        (see cli.py), saved cast presets lost the exact same fields.
        """
        cast_list = []
        for char in self.casting.characters.values():
            entry = {
                "name": char.name,
                "voice": char.voice,
                "emotion": char.emotion,
                "speed": char.speed,
                "pitch_shift": char.pitch_shift,
                "emphasis": char.emphasis,
                "aliases": char.aliases,
                "description": char.description,
            }
            if char.default_intensity is not None:
                entry["default_intensity"] = char.default_intensity
            cast_list.append(entry)
        return cast_list

    def export_casting(self, path: Path, fmt: Optional[str] = None) -> None:
        """
        Export current casting table to a JSON or CSV file.

        JSON format: array of objects with keys name, voice, emotion, speed,
        pitch_shift, emphasis, aliases, description, and default_intensity
        (omitted when unset). (F-CORE-1, wave 2 amend: pitch_shift and
        emphasis added -- previously silently dropped on export.)

        CSV format (CASTING-DEPTH v2.1; extended by wave-3 residual 6):
        columns name, voice, gender, line_count, emotion, speed, emphasis,
        aliases (';'-joined), description, pitch_shift, default_intensity.
        Both formats are now round-trip-complete for a fully-tuned Character
        -- pitch_shift and default_intensity used to be silently dropped by
        the CSV path, so a cast tuned in the app and edited in a spreadsheet
        came back flattened to the Character defaults.

        Args:
            path: Output file path.
            fmt: Explicit format ("json" or "csv"). When None, inferred from the
                file extension (.csv -> CSV, anything else -> JSON).
        """
        path = Path(path)
        resolved = (fmt or path.suffix.lstrip(".")).lower()

        if resolved == "csv":
            self._export_casting_csv(path)
            return

        cast_list = self._casting_as_list()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cast_list, f, indent=2, ensure_ascii=False)

        logger.info("Exported casting table (%d characters) to %s", len(cast_list), path)

    def _export_casting_csv(self, path: Path) -> None:
        """CASTING-DEPTH v2.1: write the casting table as a CSV cast sheet.

        Columns: name, voice, gender, line_count, emotion, speed, emphasis,
        aliases (';'-joined), description, pitch_shift, default_intensity.
        ``gender`` is derived from the voice ID prefix convention (af_/bf_ ->
        female, am_/bm_ -> male) so a spreadsheet editor sees a useful column;
        it is informational only and is ignored on import.

        Wave-3 residual 6: ``pitch_shift`` and ``default_intensity`` are
        APPENDED rather than grouped next to speed/emphasis. Import matches by
        column NAME (csv.DictReader), so position is irrelevant there -- but
        appending keeps every pre-existing column at its historical index for
        anyone who reads the sheet positionally, which is the one way a schema
        change like this can break a user silently. ``default_intensity`` is
        Optional[float]; None is written as an empty cell and read back as
        None (not 0.0, which is a meaningfully different setting).
        """
        import csv

        fieldnames = [
            "name", "voice", "gender", "line_count", "emotion",
            "speed", "emphasis", "aliases", "description",
            "pitch_shift", "default_intensity",
        ]
        rows = 0
        # newline="" per the stdlib csv docs so the writer controls line endings.
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for char in self.casting.characters.values():
                writer.writerow({
                    "name": char.name,
                    "voice": char.voice,
                    "gender": _gender_from_voice(char.voice),
                    "line_count": char.line_count,
                    "emotion": char.emotion or "",
                    "speed": char.speed,
                    "emphasis": char.emphasis,
                    "aliases": ";".join(char.aliases),
                    "description": char.description or "",
                    "pitch_shift": char.pitch_shift,
                    "default_intensity": (
                        "" if char.default_intensity is None
                        else char.default_intensity
                    ),
                })
                rows += 1
        logger.info("Exported casting CSV (%d characters) to %s", rows, path)

    def import_casting(self, path: Path, fmt: Optional[str] = None) -> None:
        """
        Import a casting table from a JSON or CSV file, merging with the cast.

        JSON format: array of objects with keys
        name, voice, emotion, speed, aliases, description.

        CSV format (CASTING-DEPTH v2.1; extended by wave-3 residual 6):
        columns name, voice, gender, line_count, emotion, speed, emphasis,
        aliases (';'-joined), description, pitch_shift, default_intensity.
        Only name + voice are required; every other column is optional and
        tolerated when missing, so a cast sheet exported before the two tuning
        columns existed still imports -- it simply leaves those fields at the
        Character defaults. ``gender`` is informational and ignored.

        On conflicts (same character name), the imported entry overwrites.

        Args:
            path: Path to casting file (.json or .csv).
            fmt: Explicit format ("json" or "csv"). When None, inferred from the
                file extension (.csv -> CSV, anything else -> JSON).

        Raises:
            FileNotFoundError: If the file doesn't exist.
            ValueError: If the file format is invalid.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Casting file not found: {path}")

        resolved = (fmt or path.suffix.lstrip(".")).lower()
        if resolved == "csv":
            self._import_casting_csv(path)
            return

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            raise ValueError(
                "Casting file must contain a JSON array of character objects. "
                f"Got {type(data).__name__} instead."
            )

        # CH-B-007: build the merge in a staging dict and apply it only once
        # every entry has validated. The loop used to write each Character
        # straight into self.casting.characters as it went, so a file whose
        # fifth entry was missing 'voice' raised ValueError with entries one
        # through four already merged -- and the docstring promises callers
        # this raises, so catching it and carrying on (which the CLI does) was
        # the documented path to a half-imported cast. All-or-nothing now.
        staged: dict[str, Character] = {}
        for entry in data:
            if not isinstance(entry, dict):
                raise ValueError(
                    f"Each casting entry must be a dict, got {type(entry).__name__}."
                )
            if "name" not in entry or "voice" not in entry:
                raise ValueError(
                    "Each casting entry must have at least 'name' and 'voice' keys. "
                    f"Got keys: {', '.join(sorted(entry.keys()))}"
                )

            char = Character(
                name=entry["name"],
                voice=entry["voice"],
                emotion=entry.get("emotion"),
                speed=entry.get("speed", 1.0),
                # F-CORE-1 (wave 2 amend): previously missing entirely, so
                # pitch_shift/emphasis silently fell back to Character's
                # defaults (0.0/1.0) and default_intensity to None on every
                # JSON import, even when the source file had real values
                # (see _casting_as_list, which now writes them).
                pitch_shift=entry.get("pitch_shift", 0.0),
                emphasis=entry.get("emphasis", 1.0),
                default_intensity=entry.get("default_intensity"),
                aliases=entry.get("aliases", []),
                description=entry.get("description"),
            )
            staged[self.casting.normalize_key(char.name)] = char

        self.casting.characters.update(staged)
        self.modified_at = datetime.now().isoformat()
        logger.info("Imported %d characters from %s", len(staged), path)

    def _import_casting_csv(self, path: Path) -> None:
        """CASTING-DEPTH v2.1: import a CSV cast sheet, merging into the cast.

        Columns: name, voice, gender, line_count, emotion, speed, emphasis,
        aliases (';'-joined), description, pitch_shift, default_intensity.
        Only name + voice are required; all other columns are optional and
        tolerated when missing/blank. The ``gender`` column is informational
        and is ignored.

        Wave-3 residual 6: this reads BOTH the legacy nine-column header and
        the extended eleven-column one. That falls out of matching by name
        (``csv.DictReader`` + ``row.get``) and of the header check below
        requiring only name + voice -- and it is the actual risk in adding
        columns, so tests/test_feat_f4_cli.py pins the legacy header
        explicitly rather than trusting it to stay true.
        """
        import csv

        staged: dict[str, Character] = {}
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None or not {
                "name", "voice"
            }.issubset({(fn or "").strip() for fn in reader.fieldnames}):
                raise ValueError(
                    "Casting CSV must have at least 'name' and 'voice' columns. "
                    f"Got columns: {', '.join(reader.fieldnames or []) or '(none)'}"
                )

            for row in reader:
                name = (row.get("name") or "").strip()
                voice = (row.get("voice") or "").strip()
                if not name or not voice:
                    # Skip blank/incomplete rows rather than failing the import.
                    continue

                char = Character(
                    name=name,
                    voice=voice,
                    emotion=(row.get("emotion") or "").strip() or None,
                    speed=_csv_float(row.get("speed"), 1.0),
                    emphasis=_csv_float(row.get("emphasis"), 1.0),
                    aliases=_csv_aliases(row.get("aliases")),
                    description=(row.get("description") or "").strip() or None,
                    line_count=_csv_int(row.get("line_count"), 0),
                    # Residual 6: absent on a legacy nine-column sheet, blank
                    # on a hand-edited one — both fall back to the Character
                    # defaults instead of failing the import.
                    pitch_shift=_csv_float(row.get("pitch_shift"), 0.0),
                    default_intensity=_csv_optional_float(
                        row.get("default_intensity")
                    ),
                )
                staged[self.casting.normalize_key(char.name)] = char

        # CH-B-007: staged the same way as the JSON branch. This one skips
        # malformed rows instead of raising, so it had no validation gap --
        # but csv.Error on a truncated file, or an OSError part-way through a
        # large sheet, would still have left the cast half-merged.
        self.casting.characters.update(staged)
        self.modified_at = datetime.now().isoformat()
        logger.info("Imported %d characters from CSV %s", len(staged), path)

    # -------------------------------------------------------------------------
    # Pronunciation Lexicon Import/Export (INPUT v2.1)
    # -------------------------------------------------------------------------

    def export_lexicon(self, path: Path) -> None:
        """
        Export pronunciation overrides to a lexicon file (INPUT v2.1).

        Writes both plain spelling replacements (pronunciation_overrides) and
        phoneme-typed entries (phoneme_overrides) through the parser's
        save_lexicon, which picks CSV vs JSON from the file extension and tags
        phoneme entries with type=phoneme so a later import keeps them distinct.

        Args:
            path: Output file path (.csv or .json).
        """
        from audiobooker.parser.text_cleaners import save_lexicon

        path = Path(path)
        # Build the merged override map. Plain entries carry no type; phoneme
        # entries are tagged so save_lexicon can round-trip the distinction.
        # Prefer the rich {word: {"replacement", "type"}} shape; if the parser's
        # save_lexicon only accepts a flat {word: replacement} map, fall back to
        # that (the phoneme/spelling distinction then lives only in the file's
        # type column when the parser writes one).
        rich: dict[str, dict[str, str]] = {}
        for word, replacement in self.config.pronunciation_overrides.items():
            rich[word] = {"replacement": replacement}
        for word, replacement in self.config.phoneme_overrides.items():
            rich[word] = {"replacement": replacement, "type": "phoneme"}

        try:
            save_lexicon(path, rich)
        except (TypeError, ValueError, AttributeError):
            flat = dict(self.config.pronunciation_overrides)
            flat.update(self.config.phoneme_overrides)
            save_lexicon(path, flat)
        logger.info(
            "Exported lexicon (%d spelling, %d phoneme) to %s",
            len(self.config.pronunciation_overrides),
            len(self.config.phoneme_overrides),
            path,
        )

    def import_lexicon(self, path: Path) -> None:
        """
        Import a pronunciation lexicon, merging into the project's overrides.

        Uses the parser's load_lexicon (CSV columns word,replacement[,type] or
        JSON). Entries marked type=phoneme are merged into config.phoneme_overrides;
        all others merge into config.pronunciation_overrides. On conflicts the
        imported entry overwrites the existing one.

        Args:
            path: Path to lexicon file (.csv or .json).

        Raises:
            FileNotFoundError: If the file doesn't exist.
            ValueError: If the lexicon format is invalid.
        """
        from audiobooker.parser.text_cleaners import load_lexicon

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Lexicon file not found: {path}")

        entries = load_lexicon(path)

        spelling_count = 0
        phoneme_count = 0
        for word, value in entries.items():
            # load_lexicon may return either a plain "replacement" string or a
            # dict carrying a "type"/"replacement". Handle both so phoneme-typed
            # entries land in phoneme_overrides and stay distinct.
            if isinstance(value, dict):
                replacement = value.get("replacement", "")
                entry_type = value.get("type", "")
            else:
                replacement = value
                entry_type = ""

            if not word or not str(word).strip() or not str(replacement).strip():
                continue

            if entry_type == "phoneme":
                self.config.phoneme_overrides[str(word).strip()] = str(replacement).strip()
                phoneme_count += 1
            else:
                self.config.pronunciation_overrides[str(word).strip()] = str(replacement).strip()
                spelling_count += 1

        self.modified_at = datetime.now().isoformat()
        logger.info(
            "Imported lexicon (%d spelling, %d phoneme) from %s",
            spelling_count, phoneme_count, path,
        )

    # -------------------------------------------------------------------------
    # Chapter Management (FT-CORE-002, FT-CORE-003)
    # -------------------------------------------------------------------------

    def exclude_chapter(self, index: int) -> None:
        """
        Mark a chapter as excluded from rendering.

        Args:
            index: Chapter index to exclude

        Raises:
            IndexError: If index is out of range
        """
        if index < 0 or index >= len(self.chapters):
            raise IndexError(f"Chapter index {index} out of range (0-{len(self.chapters) - 1})")
        self.chapters[index].skip = True
        self.modified_at = datetime.now().isoformat()

    def include_chapter(self, index: int) -> None:
        """
        Mark a previously excluded chapter as included.

        Args:
            index: Chapter index to include

        Raises:
            IndexError: If index is out of range
        """
        if index < 0 or index >= len(self.chapters):
            raise IndexError(f"Chapter index {index} out of range (0-{len(self.chapters) - 1})")
        self.chapters[index].skip = False
        self.modified_at = datetime.now().isoformat()

    def merge_chapters(self, start_index: int, end_index: int) -> Chapter:
        """
        Merge a range of chapters into one.

        Concatenates raw_text from chapters[start_index] through chapters[end_index]
        (inclusive), keeps the first chapter's title, and re-indexes all chapters.
        Invalidates cached renders for affected chapters.

        Args:
            start_index: First chapter index to merge (inclusive)
            end_index: Last chapter index to merge (inclusive)

        Returns:
            The merged Chapter

        Raises:
            IndexError: If indices are out of range
            ValueError: If start_index >= end_index
        """
        if start_index < 0 or end_index >= len(self.chapters):
            raise IndexError(
                f"Merge range [{start_index}, {end_index}] out of range "
                f"(0-{len(self.chapters) - 1})"
            )
        if start_index >= end_index:
            raise ValueError(
                f"start_index ({start_index}) must be less than end_index ({end_index})"
            )

        # Collect chapters to merge
        to_merge = self.chapters[start_index:end_index + 1]

        # Build merged chapter
        merged_text = "\n\n".join(ch.raw_text for ch in to_merge)
        merged = Chapter(
            index=start_index,
            title=to_merge[0].title,
            raw_text=merged_text,
            source_file=to_merge[0].source_file,
        )

        # Replace the range with the merged chapter
        self.chapters[start_index:end_index + 1] = [merged]

        # Re-index all chapters
        for i, ch in enumerate(self.chapters):
            ch.index = i
            # Invalidate cached audio for re-indexed chapters
            if i >= start_index:
                ch.audio_path = None
                ch.duration_seconds = 0.0
                ch.utterances = []

        self.modified_at = datetime.now().isoformat()
        return merged

    def split_chapter(self, index: int, at_paragraph: int) -> tuple[Chapter, Chapter]:
        """
        Split a chapter at a paragraph boundary.

        The chapter's raw_text is split at the given paragraph number
        (0-indexed, where paragraphs are separated by blank lines).
        Paragraphs 0..at_paragraph-1 stay in the first chapter,
        at_paragraph..end go to the new second chapter.

        Args:
            index: Chapter index to split
            at_paragraph: Paragraph number to split at (content from this
                paragraph onward goes into the new chapter)

        Returns:
            Tuple of (first_half, second_half) Chapter objects

        Raises:
            IndexError: If chapter index is out of range
            ValueError: If paragraph index is invalid
        """
        if index < 0 or index >= len(self.chapters):
            raise IndexError(f"Chapter index {index} out of range (0-{len(self.chapters) - 1})")

        chapter = self.chapters[index]
        paragraphs = chapter.raw_text.split("\n\n")

        if at_paragraph <= 0 or at_paragraph >= len(paragraphs):
            raise ValueError(
                f"Paragraph index {at_paragraph} out of range. "
                f"Chapter has {len(paragraphs)} paragraphs (valid split range: 1-{len(paragraphs) - 1})"
            )

        # Split text at paragraph boundary
        first_text = "\n\n".join(paragraphs[:at_paragraph])
        second_text = "\n\n".join(paragraphs[at_paragraph:])

        # Create two new chapters
        first = Chapter(
            index=index,
            title=chapter.title,
            raw_text=first_text,
            source_file=chapter.source_file,
        )
        second = Chapter(
            index=index + 1,
            title=f"{chapter.title} (continued)",
            raw_text=second_text,
            source_file=chapter.source_file,
        )

        # Replace original with the two halves
        self.chapters[index:index + 1] = [first, second]

        # Re-index all chapters
        for i, ch in enumerate(self.chapters):
            ch.index = i
            # Invalidate cached audio for affected chapters
            if i >= index:
                ch.audio_path = None
                ch.duration_seconds = 0.0
                ch.utterances = []

        self.modified_at = datetime.now().isoformat()
        return first, second

    def rename_chapter(self, index: int, title: str) -> Chapter:
        """
        Rename a chapter's display title (F-FEAT-F3, v2.1).

        The chapter title is what surfaces in the M4B chapter list and the
        per-chapter file names, so a rename invalidates any cached render for
        that chapter — same invalidation pattern merge_chapters/split_chapter
        use. Text/utterances are NOT reset on a pure rename: the audio is only
        stale because its title-derived metadata/filename changed, so we clear
        audio_path + duration but keep the compiled utterances.

        Args:
            index: Chapter index to rename (0-based).
            title: New chapter title. Must be a non-empty string.

        Returns:
            The renamed Chapter.

        Raises:
            IndexError: If index is out of range.
            ValueError: If title is empty or not a string.
        """
        if index < 0 or index >= len(self.chapters):
            raise IndexError(
                f"Chapter index {index} out of range (0-{len(self.chapters) - 1})"
            )
        if not isinstance(title, str) or not title.strip():
            raise ValueError("Chapter title must be a non-empty string.")

        chapter = self.chapters[index]
        chapter.title = title.strip()
        # A title change invalidates the cached audio (chapter metadata + the
        # per-chapter output filename derive from the title). Mirror the
        # merge/split invalidation, but keep utterances since the text is
        # unchanged — only re-rendering metadata is required.
        chapter.audio_path = None
        chapter.duration_seconds = 0.0

        self.modified_at = datetime.now().isoformat()
        return chapter

    def reorder_chapters(self, new_order: list[int]) -> None:
        """
        Reorder chapters according to a permutation of their current indices
        (F-FEAT-F3, v2.1).

        ``new_order`` must be a permutation of ``range(len(chapters))``:
        ``new_order[k]`` is the *current* index of the chapter that should end
        up at position ``k``. After reordering, every chapter is re-indexed to
        its new position, and any chapter that actually moved has its cached
        audio invalidated (audio_path / duration / utterances cleared), exactly
        as merge_chapters/split_chapter do for affected chapters. Chapters that
        keep their position are left untouched.

        Args:
            new_order: A list that is a permutation of range(len(chapters)).

        Raises:
            ValueError: If new_order is not a valid permutation (wrong length,
                duplicates, or out-of-range indices).
        """
        n = len(self.chapters)
        if not isinstance(new_order, (list, tuple)):
            raise ValueError(
                f"new_order must be a list of indices, got {type(new_order).__name__}."
            )
        if len(new_order) != n:
            raise ValueError(
                f"new_order has {len(new_order)} entries but the project has "
                f"{n} chapter(s); it must be a permutation of 0-{n - 1}."
            )
        if sorted(new_order) != list(range(n)):
            raise ValueError(
                f"new_order must be a permutation of range({n}) "
                f"(each index 0-{n - 1} exactly once); got {new_order!r}."
            )

        # Build the reordered list. new_order[k] is the OLD index landing at k.
        reordered = [self.chapters[old_idx] for old_idx in new_order]
        self.chapters = reordered

        # Re-index and invalidate cached audio for chapters that actually
        # moved (old position != new position). Same invalidation as
        # merge_chapters/split_chapter for affected chapters.
        for new_idx, old_idx in enumerate(new_order):
            ch = self.chapters[new_idx]
            ch.index = new_idx
            if old_idx != new_idx:
                ch.audio_path = None
                ch.duration_seconds = 0.0
                ch.utterances = []

        self.modified_at = datetime.now().isoformat()

    # -------------------------------------------------------------------------
    # Compilation
    # -------------------------------------------------------------------------

    def _preprocess_text(self, text: str) -> str:
        """
        Apply text cleaning and pronunciation overrides (FT-CORE-011, FT-CORE-015).

        Called before utterance creation in compile.

        Args:
            text: Raw chapter text.

        Returns:
            Preprocessed text.
        """
        from audiobooker.parser.text_cleaners import (
            clean_text as run_cleaners,
            apply_pronunciation_overrides,
        )

        # FT-CORE-015: Text cleaning pipeline
        if self.config.clean_text:
            text = run_cleaners(text)

        # FT-CORE-024: Text normalization (numbers, abbreviations, currency)
        if self.config.normalize_text:
            from audiobooker.nlp.normalizer import normalize
            text = normalize(text)

        # FT-CORE-011: Pronunciation overrides
        #
        # PH-B-005: protected_names is the whole point of this call. Overrides
        # run HERE, before compile_chapter, so they rewrite the very text that
        # speaker attribution then runs against -- and the lexicon's primary
        # use case is proper nouns. An override of {'Siobhan': 'shiv-AWN'}
        # turned `said Siobhan, folding the map` into `said shiv-AWN, folding
        # the map`, which attributes to nobody: the character silently stops
        # being cast and renders in the narrator voice for the whole book.
        # apply_pronunciation_overrides grew the guard in wave 4 and it was
        # unit-tested there, but this call site never passed the argument, so
        # the mechanism was inert everywhere it actually mattered.
        if self.config.pronunciation_overrides:
            text = apply_pronunciation_overrides(
                text,
                self.config.pronunciation_overrides,
                protected_names=self.casting.protected_names(),
            )

        return text

    def compile(
        self,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        *,
        dry_run: bool = False,
    ) -> Optional[dict[int, list["Utterance"]]]:
        """
        Compile all chapters to utterances.

        This parses the raw text and detects dialogue vs narration,
        creating a list of Utterances for each chapter.

        Args:
            progress_callback: Callback(current, total, chapter_title)
            dry_run: If True, return utterances without writing them to
                chapters. Returns dict {chapter_index: list[Utterance]}.
                Existing compile behavior unchanged when dry_run=False.

        Returns:
            None when dry_run=False (utterances stored on chapters).
            Dict {chapter_index: list[Utterance]} when dry_run=True.
        """
        from audiobooker.casting.dialogue import compile_chapter
        from audiobooker.language.profile import get_profile

        profile = get_profile(self.config.language_code)

        if not dry_run:
            self.progress.status = "compiling"
            self.progress.total_chapters = len(self.chapters)

        dry_run_result: dict[int, list[Utterance]] = {}
        failed_chapters = []

        # FT-CORE-016: Apply user emotion rules to the inferencer's profile
        # (stored on config, fed in during emotion inference below)

        # Collect non-skipped chapters for compilation
        active_chapters = [
            (i, ch) for i, ch in enumerate(self.chapters) if not ch.skip
        ]
        skipped = len(self.chapters) - len(active_chapters)
        if skipped:
            logger.info("Skipping %d excluded chapter(s)", skipped)

        # FT-CORE-017: Parallel compilation path
        if self.config.parallel_compile and not dry_run and len(active_chapters) > 1:
            self._compile_parallel(
                active_chapters, compile_chapter, profile,
                progress_callback, failed_chapters,
            )
        else:
            # Sequential compilation (original path)
            for i, chapter in active_chapters:
                if not dry_run:
                    self.progress.current_chapter = i + 1
                if progress_callback:
                    progress_callback(i + 1, len(self.chapters), chapter.title)

                # FT-CORE-011/015/024: Preprocess text before compilation
                preprocessed_text = self._preprocess_text(chapter.raw_text)

                # Create a temporary chapter copy for compilation with cleaned text
                compile_chapter_obj = chapter
                if preprocessed_text != chapter.raw_text:
                    from copy import copy
                    compile_chapter_obj = copy(chapter)
                    compile_chapter_obj.raw_text = preprocessed_text

                # F-CORE-B-008: Per-chapter error handling
                try:
                    utterances = compile_chapter(compile_chapter_obj, self.casting, profile=profile)
                    if dry_run:
                        dry_run_result[chapter.index] = utterances
                    else:
                        chapter.utterances = utterances
                except Exception as e:
                    logger.error(
                        "Compilation failed for chapter %d (%s): %s",
                        chapter.index, chapter.title, e,
                    )
                    failed_chapters.append((chapter.index, chapter.title, str(e)))
                    continue

        summary = "; ".join(
            f"ch{idx} '{title}': {err}" for idx, title, err in failed_chapters
        )

        if not dry_run:
            # FT-CORE-022: Capture a small compile summary the CLI can surface
            # (speaker resolution stats + emotions inferred + any NLP errors).
            # Previously the stats returned by resolve()/apply_to_utterances()
            # were discarded, so the user got no observability into what
            # compile actually did. Initialized HERE, before the failure
            # checks below, so a caller that catches the total-failure error
            # still finds the per-chapter causes on the project.
            self.compile_summary = {
                "speakers_resolved": 0,
                "low_confidence": 0,
                "emotions_inferred": 0,
                "emotions_near_miss": 0,
                "nlp_errors": [],
                # CH-B-002: partial failures are survivable but they are not
                # nothing. Total failure raises; anything short of that is
                # recorded here, machine-readable, so a caller can report
                # "38 of 40 chapters compiled" instead of counting utterances
                # and guessing. progress.error_message carries the same
                # information as prose for a human.
                "failed_chapters": [
                    {"index": idx, "title": title, "error": err}
                    for idx, title, err in failed_chapters
                ],
            }

        if failed_chapters and not dry_run:
            self.progress.status = "error"
            self.progress.error_message = (
                f"{len(failed_chapters)} chapter(s) failed to compile: {summary}"
            )
            logger.warning(self.progress.error_message)

        # CH-B-002: a book where EVERY chapter failed is not a compile with
        # some warnings, it is a failed compile, and it must be impossible to
        # mistake for success. Per-chapter tolerance (F-CORE-B-008) is right
        # -- one unparseable chapter should not cost you the other forty --
        # but it was the ONLY behaviour: every exception went into
        # failed_chapters, progress.status was set to "error" and then
        # overwritten with "idle" at the bottom of this method, and compile()
        # returned None exactly as a clean run does. cmd_compile never read
        # progress.error_message, so `audiobooker compile` on a book that
        # produced nothing printed "Compiled 0 utterances" and exited 0.
        # Counted by distinct chapter, never by list length: the parallel
        # path can append the same chapter twice (see _compile_parallel), and
        # "every chapter failed" must mean every chapter, not every entry.
        failed_indices = {idx for idx, _, _ in failed_chapters}
        if failed_chapters and len(failed_indices) >= len(active_chapters):
            self.progress.status = "error"
            self.progress.error_message = (
                f"all {len(failed_indices)} chapter(s) failed to compile: {summary}"
            )
            raise CompilationFailedError(summary, chapter_count=len(failed_indices))

        if dry_run:
            return dry_run_result

        # Optional NLP speaker resolution (BookNLP)
        if self.config.booknlp_mode != "off":
            from audiobooker.nlp.speaker_resolver import SpeakerResolver
            resolver = SpeakerResolver(mode=self.config.booknlp_mode)
            res_stats = resolver.resolve(self.chapters, self.casting)
            self.compile_summary["speakers_resolved"] = res_stats.speakers_resolved
            # Borderline fuzzy matches (accepted, but just over the threshold)
            # are the attributions a human should spot-check. The resolver
            # records them directly in stats.low_confidence.
            self.compile_summary["low_confidence"] = len(res_stats.low_confidence)
            self.compile_summary["nlp_errors"] = list(res_stats.nlp_errors)

        # Optional emotion inference
        if self.config.emotion_mode != "off":
            from audiobooker.nlp.emotion import EmotionInferencer
            # FT-CORE-016: Merge user_emotion_rules into the profile's
            # emotion_hints so the inferencer picks them up via verb matching.
            inference_profile = profile
            if self.config.user_emotion_rules:
                from copy import copy
                inference_profile = copy(profile)
                # Merge user rules (verb -> emotion mappings)
                merged_hints = dict(getattr(inference_profile, "emotion_hints", {}))
                merged_hints.update(self.config.user_emotion_rules)
                inference_profile.emotion_hints = merged_hints
            # CASTING-DEPTH v2.1: thread the emotion preset pack so the
            # inferencer (casting-owned) can parametrize its threshold + label
            # set. Call defensively: a concurrently-evolving inferencer with the
            # older signature (no preset=) still works and keeps "neutral"
            # behavior unchanged.
            inferencer_kwargs = dict(
                mode=self.config.emotion_mode,
                threshold=self.config.emotion_confidence_threshold,
                profile=inference_profile,
            )
            preset = getattr(self.config, "emotion_preset", "neutral")
            if preset and preset != "neutral":
                inferencer_kwargs["preset"] = preset
            try:
                inferencer = EmotionInferencer(**inferencer_kwargs)
            except TypeError:
                inferencer_kwargs.pop("preset", None)
                inferencer = EmotionInferencer(**inferencer_kwargs)
            emotions_inferred = 0
            emotions_near_miss = 0
            for chapter in self.chapters:
                emotions_inferred += inferencer.apply_to_utterances(
                    chapter.utterances, chapter.raw_text
                )
                run_stats = getattr(inferencer, "last_run_stats", None)
                if run_stats is not None:
                    emotions_near_miss += run_stats.near_miss
            self.compile_summary["emotions_inferred"] = emotions_inferred
            self.compile_summary["emotions_near_miss"] = emotions_near_miss

        # CASTING-DEPTH v2.1: apply each character's default_intensity as a
        # fallback for any of its emotional utterances that still have no
        # intensity. This NEVER overrides an intensity already set inline (by a
        # user script tag) or by graded inference — only fills the gap so the
        # renderer's emphasis-band mapping reflects the character's default.
        self._apply_default_intensities()

        # CH-B-002: do not erase a partial failure on the way out. This line
        # unconditionally overwrote the "error" status set above, so the only
        # trace a partially-failed compile left behind was
        # progress.error_message, and it was persisted alongside a status of
        # "idle".
        if not failed_chapters:
            self.progress.status = "idle"
        self.modified_at = datetime.now().isoformat()
        return None

    def _apply_default_intensities(self) -> None:
        """CASTING-DEPTH v2.1: fill in per-character default_intensity.

        For every compiled utterance that HAS an emotion but NO intensity, and
        whose speaker has a Character with a default_intensity set, copy that
        default onto the utterance. An intensity already present (set inline by
        the user or by graded emotion inference) is never overwritten — this is
        a pure gap-fill so the renderer's (emotion, intensity) emphasis mapping
        reflects the character's authored default.
        """
        casting = self.casting
        for chapter in self.chapters:
            for utt in chapter.utterances:
                if utt.intensity is not None or not utt.emotion:
                    continue
                key = casting.normalize_key(utt.speaker)
                char = casting.characters.get(key)
                if char is None:
                    char = casting.resolve_alias(utt.speaker)
                if char is not None and char.default_intensity is not None:
                    utt.intensity = char.default_intensity

    def _compile_parallel(
        self,
        active_chapters: list[tuple[int, Chapter]],
        compile_chapter_fn,
        profile,
        progress_callback,
        failed_chapters: list,
    ) -> None:
        """
        Compile chapters in parallel using ProcessPoolExecutor (FT-CORE-017).

        Gated behind config.parallel_compile since BookNLP may have GPU contention.
        Falls back to sequential on any executor setup failure.
        """
        from concurrent.futures import ProcessPoolExecutor, as_completed

        # CH-B-013: clamp to the machine, not just to the chapter count.
        # `compile_workers` is validated as "a positive integer" in BOTH
        # models.py and config_file.py — the two agree, and what they agree on
        # is a floor with no ceiling. So a config copied from another project,
        # or an honest "more workers = faster" guess, passes validation and
        # spawns that many ProcessPoolExecutor workers, each of which may load
        # BookNLP/spaCy. On a long novel (40-80+ chapters) the chapter-count
        # bound does not help: it IS the large number. Exactly the books this
        # feature exists to speed up are the ones it could thrash.
        #
        # Clamped rather than rejected: a ceiling in the validator would have
        # to be an arbitrary constant, and would wrongly refuse a legitimate
        # value on a 128-core machine. The clamp adapts, and says so when it
        # bites, so the user learns their setting is not being honoured
        # instead of wondering why it did not get faster.
        requested = self.config.compile_workers
        cpu_budget = os.cpu_count() or 4
        workers = min(requested, cpu_budget, len(active_chapters))
        if requested > cpu_budget:
            logger.warning(
                "compile_workers=%d exceeds this machine's %d CPU(s); "
                "using %d. More workers than cores does not compile faster — "
                "each one may load its own NLP model.",
                requested, cpu_budget, workers,
            )
        logger.info(
            "Parallel compilation: %d chapters across %d workers",
            len(active_chapters), workers,
        )

        # Prepare chapter data for workers (preprocess text now)
        compile_tasks: list[tuple[int, Chapter]] = []
        for i, chapter in active_chapters:
            preprocessed_text = self._preprocess_text(chapter.raw_text)
            if preprocessed_text != chapter.raw_text:
                from copy import copy
                ch_copy = copy(chapter)
                ch_copy.raw_text = preprocessed_text
                compile_tasks.append((i, ch_copy))
            else:
                compile_tasks.append((i, chapter))

        # Use ProcessPoolExecutor for CPU-bound compilation
        try:
            with ProcessPoolExecutor(max_workers=workers) as executor:
                future_to_idx = {}
                for idx, ch in compile_tasks:
                    future = executor.submit(
                        compile_chapter_fn, ch, self.casting, profile=profile
                    )
                    future_to_idx[future] = idx

                completed = 0
                for future in as_completed(future_to_idx):
                    idx = future_to_idx[future]
                    completed += 1
                    chapter = self.chapters[idx]
                    self.progress.current_chapter = completed

                    if progress_callback:
                        progress_callback(completed, len(active_chapters), chapter.title)

                    try:
                        utterances = future.result()
                        chapter.utterances = utterances
                    except Exception as e:
                        logger.error(
                            "Parallel compilation failed for chapter %d (%s): %s",
                            chapter.index, chapter.title, e,
                        )
                        failed_chapters.append((chapter.index, chapter.title, str(e)))
        except Exception as e:
            logger.warning(
                "ProcessPoolExecutor failed (%s), falling back to sequential compilation", e
            )
            # CH-B-002 (adjacent): the fallback recompiles EVERY task from
            # scratch, so anything the dying pool recorded is stale. Without
            # this clear, a pool that died after three chapters had already
            # failed left those three in the list even when the sequential
            # retry compiled all of them -- the project came back fully
            # compiled and still reported "3 chapter(s) failed", and with
            # enough duplicates the total-failure check below would fire on a
            # book that compiled fine.
            failed_chapters.clear()
            # Fallback: sequential
            for idx, ch in compile_tasks:
                chapter = self.chapters[idx]
                try:
                    utterances = compile_chapter_fn(ch, self.casting, profile=profile)
                    chapter.utterances = utterances
                except Exception as exc:
                    failed_chapters.append((chapter.index, chapter.title, str(exc)))

    def compile_chapter(self, chapter_index: int) -> list[Utterance]:
        """
        Compile a single chapter to utterances.

        Args:
            chapter_index: Index of chapter to compile

        Returns:
            List of Utterances
        """
        from audiobooker.casting.dialogue import compile_chapter
        from audiobooker.language.profile import get_profile

        profile = get_profile(self.config.language_code)

        if chapter_index < 0 or chapter_index >= len(self.chapters):
            raise IndexError(f"Chapter index {chapter_index} out of range")

        chapter = self.chapters[chapter_index]
        utterances = compile_chapter(chapter, self.casting, profile=profile)
        chapter.utterances = utterances
        return utterances

    # -------------------------------------------------------------------------
    # Rendering
    # -------------------------------------------------------------------------

    def render(
        self,
        output_path: Optional[str | Path] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        *,
        resume: bool = True,
        from_chapter: Optional[int] = None,
        allow_partial: bool = False,
        engine=None,
        assembler=None,
        jobs: int = 1,
        force: bool = False,
        output_format: Optional[str] = None,
        output_profile: Optional[str] = None,
        bitrate: Optional[str] = None,
        split: bool = False,
    ) -> Path:
        """
        Render all chapters and assemble final audiobook.

        Args:
            output_path: Output file path (default: {title}.{format})
            progress_callback: Callback(current, total, status)
            resume: Skip chapters with valid cached audio (default True).
            from_chapter: Start from this chapter index (0-based).
            allow_partial: Assemble even if some chapters failed.
            engine: Injected TTSEngine (for testing).
            assembler: Injected assembly callable (for testing).
            jobs: Number of parallel render workers (default 1).
            force: Bypass casting completeness validation.
            output_format: Override output format ('m4b', 'mp3', 'wav').
            output_profile: Mastering profile ('podcast' | 'acx'). Defaults to
                the project config's output_profile when None.
            bitrate: Override encoder bitrate (e.g. "192k"). None uses the
                profile/assembler default.
            split: If True, emit per-chapter files instead of one combined file.

        Returns:
            Path to output file
        """
        from audiobooker.renderer.engine import render_project

        fmt = output_format or self.config.output_format
        profile = output_profile or self.config.output_profile
        if output_path is None:
            output_path = Path(f"{_sanitize_filename(self.title)}.{fmt}")
        else:
            output_path = Path(output_path)

        # CH-B-003: remember WHERE the render went, not a spelling of it that
        # depends on the caller's CWD at the time. The renderer below is
        # handed `output_path` exactly as given (a relative path still writes
        # to the same place it always did); only the copy this project keeps
        # and persists is pinned.
        self.output_path = Path(os.path.abspath(output_path))
        self.progress.status = "rendering"

        # Validate voices before spending time rendering. Kept HERE (rather
        # than left entirely to the renderer) so the gate still fires before
        # compile() below — fail fast, not after a BookNLP pass.
        if self.config.validate_voices_on_render:
            self._validate_voices(engine=engine)

        # Ensure all non-excluded chapters are compiled
        uncompiled = [c for c in self.chapters if not c.is_compiled and not c.skip]
        if uncompiled:
            self.compile()

        # Render. output_profile/bitrate/split are part of the v2.1 render
        # contract; call defensively so a concurrently-evolving renderer with
        # an older signature degrades gracefully instead of hard-crashing.
        render_kwargs = dict(
            engine=engine,
            assembler=assembler,
            resume=resume,
            from_chapter=from_chapter,
            allow_partial=allow_partial,
            jobs=jobs,
            force=force,
            output_format=output_format,
            output_profile=profile,
            bitrate=bitrate,
            split=split,
            # The renderer runs the same voice gate for callers that reach it
            # directly (cli.py's needs_direct path, batch/make's _process_book).
            # This path already ran it above, so tell the renderer to stand
            # down — otherwise the registry is queried twice per render.
            validate_voices=False,
        )
        try:
            result_path = render_project(
                self, output_path, progress_callback, **render_kwargs
            )
        except TypeError as e:
            # Older renderer signature lacks the v2.1 kwargs — retry without
            # them so existing (podcast/128k) behavior still works.
            if not any(k in str(e) for k in ("output_profile", "bitrate", "split")):
                raise
            for k in ("output_profile", "bitrate", "split"):
                render_kwargs.pop(k, None)
            result_path = render_project(
                self, output_path, progress_callback, **render_kwargs
            )

        self.progress.status = "complete"
        self.modified_at = datetime.now().isoformat()

        return result_path

    def render_chapter(
        self,
        chapter_index: int,
        output_path: Optional[str | Path] = None,
    ) -> Path:
        """
        Render a single chapter to audio.

        Args:
            chapter_index: Index of chapter to render
            output_path: Output file path

        Returns:
            Path to chapter audio file
        """
        from audiobooker.renderer.engine import render_chapter

        if chapter_index < 0 or chapter_index >= len(self.chapters):
            raise IndexError(f"Chapter index {chapter_index} out of range")

        chapter = self.chapters[chapter_index]

        if not chapter.is_compiled:
            self.compile_chapter(chapter_index)

        if output_path is None:
            self._ensure_output_dir()
            output_path = self._output_dir / f"chapter_{chapter_index:03d}.wav"

        return render_chapter(chapter, self.casting, output_path)

    def _ensure_output_dir(self) -> Path:
        """Ensure output directory exists.

        CH-B-003: the title-derived fallback is pinned to an absolute path at
        the moment it is chosen. Same directory as before (it is still
        created next to wherever the command ran), but it stops moving with
        the process, so the chapter audio paths derived from it survive being
        resumed from elsewhere.
        """
        if self._output_dir is None:
            self._output_dir = Path(
                os.path.abspath(f"{_sanitize_filename(self.title)}_audio")
            )
        self._output_dir.mkdir(parents=True, exist_ok=True)
        return self._output_dir

    # -------------------------------------------------------------------------
    # Review (v2.1)
    # -------------------------------------------------------------------------

    def export_for_review(self, output_path: Optional[str | Path] = None) -> Path:
        """
        Export compiled project to human-editable review format.

        The review file allows editing:
        - Speaker names (@OldName -> @NewName)
        - Emotions (@Name (old) -> @Name (new))
        - Deleting unwanted utterances
        - Adding emotions to narration

        Args:
            output_path: Output file path (default: {title}_review.txt)

        Returns:
            Path to review file
        """
        from audiobooker.review import export_for_review

        # Ensure compiled.
        #
        # FEAT-CAST-002: the `if not c.skip` is load-bearing and its absence
        # destroyed review work. compile() deliberately never compiles a
        # skipped chapter, so a predicate over EVERY chapter can never be
        # satisfied once one is excluded — and excluding the front matter so
        # the dedication is not narrated is the first thing anyone does with
        # a real EPUB. Every subsequent export therefore recompiled, and
        # compile() assigns `chapter.utterances = utterances` unconditionally,
        # silently discarding whatever the human had just corrected. Round one
        # of a review survived; round two did not, with exit code 0.
        #
        # Note this only stops the UNNECESSARY recompile. A legitimate one
        # still overwrites review decisions, because nothing marks an
        # utterance as human-reviewed — that is a real gap, and a capability
        # rather than a bug, so it is recorded in the feature audit and not
        # papered over here.
        if not all(c.is_compiled for c in self.chapters if not c.skip):
            self.compile()

        if output_path is not None:
            output_path = Path(output_path)

        return export_for_review(self, output_path)

    def import_reviewed(self, review_path: str | Path) -> dict:
        """
        Import edited review file back into project.

        Updates chapter utterances with any changes made in the review file.

        Args:
            review_path: Path to edited review file

        Returns:
            Dict with import statistics:
            - chapters_updated: Number of chapters updated
            - utterances_imported: Total utterances imported
            - speakers_found: List of unique speakers
        """
        from audiobooker.review import import_reviewed

        review_path = Path(review_path)
        stats = import_reviewed(self, review_path)

        self.modified_at = datetime.now().isoformat()
        return stats

    def preview_review_format(self, chapter_index: int = 0) -> str:
        """
        Preview review format for a single chapter.

        Args:
            chapter_index: Which chapter to preview

        Returns:
            Review format string for that chapter
        """
        from audiobooker.review import preview_review_format

        return preview_review_format(self, chapter_index)

    # -------------------------------------------------------------------------
    # Emotion Management (FT-CORE-016)
    # -------------------------------------------------------------------------

    def list_emotions(self) -> dict[int, dict[str, int]]:
        """
        Return per-chapter emotion summary.

        Returns:
            Dict mapping chapter_index to {emotion: count}.
            Only includes chapters with compiled utterances.
        """
        result: dict[int, dict[str, int]] = {}
        for chapter in self.chapters:
            if not chapter.utterances:
                continue
            emotion_counts: dict[str, int] = {}
            for utt in chapter.utterances:
                label = utt.emotion or "neutral"
                emotion_counts[label] = emotion_counts.get(label, 0) + 1
            result[chapter.index] = emotion_counts
        return result

    def set_mood_span(
        self,
        chapter_index: int,
        start: int,
        end: int,
        emotion: str,
    ) -> str:
        """CASTING-DEPTH v2.1: mark a character span of a chapter with a mood.

        Wraps ``chapter.raw_text[start:end]`` with the scene tags
        ``[scene:<emotion>] ... [/scene]`` that casting/dialogue.py parses (like
        the existing [pause]/[sfx] tags) and applies as an emotion FALLBACK
        inside the span. Precedence is explicit/inline > scene > chapter mood,
        so this never overrides a user-set emotion on a line — it only supplies
        a default for lines that have none. The span is applied at the next
        compile; this method invalidates the chapter's compiled utterances and
        cached audio so a re-compile/re-render is required.

        Args:
            chapter_index: Chapter index (0-based).
            start: Start character offset into the chapter's raw_text (inclusive).
            end: End character offset (exclusive). Must be > start.
            emotion: Mood/emotion label to apply across the span.

        Returns:
            The text fragment that was wrapped (for confirmation messages).

        Raises:
            IndexError: If the chapter index is out of range.
            ValueError: If the offsets are invalid or the emotion is empty.
        """
        if not emotion or not emotion.strip():
            raise ValueError("Mood-span emotion label must not be empty.")
        if chapter_index < 0 or chapter_index >= len(self.chapters):
            raise IndexError(
                f"Chapter index {chapter_index} out of range "
                f"(0-{len(self.chapters) - 1})"
            )
        chapter = self.chapters[chapter_index]
        text_len = len(chapter.raw_text)
        if start < 0 or end > text_len or start >= end:
            raise ValueError(
                f"Invalid mood span [{start}, {end}) for chapter {chapter_index} "
                f"(text length {text_len}); need 0 <= start < end <= length."
            )

        emotion = emotion.strip()
        fragment = chapter.raw_text[start:end]
        chapter.raw_text = (
            chapter.raw_text[:start]
            + f"[scene:{emotion}]"
            + fragment
            + "[/scene]"
            + chapter.raw_text[end:]
        )

        # The span only takes effect on (re)compile; invalidate compiled
        # utterances + cached audio so the next compile/render picks it up.
        chapter.utterances = []
        chapter.audio_path = None
        chapter.duration_seconds = 0.0
        self.modified_at = datetime.now().isoformat()
        return fragment

    def override_emotion(
        self, chapter_index: int, utterance_index: int, emotion: str
    ) -> None:
        """
        Override the emotion on a specific utterance.

        Args:
            chapter_index: Chapter index (0-based).
            utterance_index: Utterance index within the chapter (0-based).
            emotion: New emotion label (e.g., "angry", "whisper", "happy").

        Raises:
            IndexError: If chapter or utterance index is out of range.
            ValueError: If emotion is empty.
        """
        if not emotion or not emotion.strip():
            raise ValueError("Emotion label must not be empty.")
        if chapter_index < 0 or chapter_index >= len(self.chapters):
            raise IndexError(
                f"Chapter index {chapter_index} out of range (0-{len(self.chapters) - 1})"
            )
        chapter = self.chapters[chapter_index]
        if not chapter.utterances:
            raise IndexError(
                f"Chapter {chapter_index} has no compiled utterances. Run compile() first."
            )
        if utterance_index < 0 or utterance_index >= len(chapter.utterances):
            raise IndexError(
                f"Utterance index {utterance_index} out of range "
                f"(0-{len(chapter.utterances) - 1}) in chapter {chapter_index}"
            )
        chapter.utterances[utterance_index].emotion = emotion.strip()
        # Invalidate cached audio for this chapter
        chapter.audio_path = None
        chapter.duration_seconds = 0.0
        self.modified_at = datetime.now().isoformat()

    # -------------------------------------------------------------------------
    # Info & Stats
    # -------------------------------------------------------------------------

    @property
    def total_words(self) -> int:
        """Total word count across all chapters."""
        return sum(c.word_count for c in self.chapters)

    @property
    def estimated_duration_minutes(self) -> float:
        """Estimated total duration in minutes (varies by voice/emotion)."""
        return self.total_words / self.config.estimated_wpm

    @property
    def total_duration_seconds(self) -> float:
        """Actual rendered duration in seconds."""
        return sum(c.duration_seconds for c in self.chapters)

    def info(self) -> dict:
        """
        Get project information summary.

        COORD-B-001: the two path fields are reported in the same portable
        form they are stored in. ``audiobooker status --json`` gets redirected
        into files and pasted into issues at least as often as the project
        file itself is shared, and "~/Music/book.m4b" identifies the location
        just as well as "C:\\Users\\<account>\\Music\\book.m4b" without
        carrying the account name.

        Returns:
            Dict with project stats
        """
        base = (
            Path(os.path.abspath(self.project_path)).parent
            if self.project_path
            else None
        )
        return {
            "title": self.title,
            "author": self.author,
            "source": portable_path(self.source_path, base),
            "chapters": len(self.chapters),
            "total_words": self.total_words,
            "estimated_duration_minutes": round(self.estimated_duration_minutes, 1),
            "characters_cast": len(self.casting.characters),
            "uncast_speakers": list(self.get_uncast_speakers()),
            # Skipped chapters are never compiled or rendered by design, so
            # counting them made an excluded front matter chapter report a
            # fully-compiled, fully-rendered book as neither (FEAT-CAST-002's
            # cosmetic sibling — same confusion, no data loss).
            "compiled": all(c.is_compiled for c in self.chapters if not c.skip),
            "rendered": all(c.is_rendered for c in self.chapters if not c.skip),
            "output": portable_path(self.output_path, base),
        }

    def __repr__(self) -> str:
        return (
            f"AudiobookProject(title={self.title!r}, "
            f"chapters={len(self.chapters)}, "
            f"words={self.total_words})"
        )
