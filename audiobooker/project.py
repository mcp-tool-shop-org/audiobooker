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

from audiobooker.models import (
    BookMetadata,
    Chapter,
    Utterance,
    Character,
    CastingTable,
    ProjectConfig,
)


def _sanitize_filename(name: str) -> str:
    """Strip/replace filesystem-unsafe characters from a filename."""
    # Replace common unsafe chars with underscore
    sanitized = _re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    # Collapse runs of underscores/spaces
    sanitized = _re.sub(r"[_ ]{2,}", "_", sanitized).strip("_ ")
    return sanitized or "untitled"


# Project file schema version for forward compatibility
SCHEMA_VERSION = 1


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

    # Internal
    _output_dir: Optional[Path] = None

    def __post_init__(self):
        """Initialize output directory and sync config to casting table."""
        if self._output_dir is None and self.source_path:
            self._output_dir = Path(self.source_path).parent / f"{Path(self.source_path).stem}_audio"
        # Keep casting table fallback in sync with project config
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

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"EPUB not found: {path}")

        # F-CORE-B-020: Validate kwargs before using them
        cls._validate_kwargs({k: v for k, v in kwargs.items() if k != "config"})

        # Extract config to pass EPUB parsing thresholds
        config = kwargs.pop("config", ProjectConfig())

        metadata, chapters = parse_epub(
            path,
            min_chapter_words=config.min_chapter_words,
            keep_titled_short_chapters=config.keep_titled_short_chapters,
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
            title=metadata.get("title", path.stem),
            author=metadata.get("author", ""),
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

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {path}")

        # F-CORE-B-020: Validate kwargs
        cls._validate_kwargs({k: v for k, v in kwargs.items() if k != "config"})

        config = kwargs.pop("config", ProjectConfig())

        metadata, chapters = parse_pdf(
            path,
            min_chapter_words=config.min_chapter_words,
        )

        project = cls(
            title=metadata.get("title", path.stem),
            author=metadata.get("author", ""),
            source_path=path,
            chapters=chapters,
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

        # F-CORE-B-020: Validate kwargs
        cls._validate_kwargs({k: v for k, v in kwargs.items() if k != "config"})

        config = kwargs.pop("config", ProjectConfig())
        profile = get_profile(config.language_code)

        metadata, chapters = parse_text(path, profile=profile)

        project = cls(
            title=metadata.get("title", path.stem),
            author=metadata.get("author", ""),
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

        # F-CORE-B-020: Validate kwargs
        cls._validate_kwargs({k: v for k, v in kwargs.items() if k != "config"})

        config = kwargs.pop("config", ProjectConfig(language_code=lang))
        config.language_code = lang
        profile = get_profile(lang)

        metadata, body = extract_frontmatter(text)
        chapter_data = split_into_chapters(body, profile=profile)

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

        def _validated_path(raw: str | None) -> Path | None:
            """Validate a deserialized path is safe to use.

            Trust boundary: source files (EPUBs, TXTs) can live anywhere
            on the filesystem because the user chooses them. We do NOT
            confine to the project directory. We only reject two classes
            of malicious input:
            - '..' traversal components (directory escape)
            - Null bytes (\\x00) which can confuse C-level filesystem calls
            """
            if raw is None:
                return None
            if "\x00" in raw:
                raise ValueError(
                    f"Path {raw!r} contains null bytes"
                )
            # Reject paths with explicit traversal components
            if ".." in Path(raw).parts:
                raise ValueError(
                    f"Path {raw!r} contains '..' traversal components"
                )
            return Path(raw)

        project = cls(
            title=data.get("title", "Untitled"),
            author=data.get("author", ""),
            source_path=_validated_path(data.get("source_path")),
            project_path=path,
            created_at=data.get("created_at", datetime.now().isoformat()),
            modified_at=data.get("modified_at", datetime.now().isoformat()),
            output_path=_validated_path(data.get("output_path")),
        )

        # Load chapters
        project.chapters = [
            Chapter.from_dict(c) for c in data.get("chapters", [])
        ]

        # Load casting table
        if "casting" in data:
            project.casting = CastingTable.from_dict(data["casting"])

        # Load config
        if "config" in data:
            project.config = ProjectConfig.from_dict(data["config"])

        # Load metadata
        if "metadata" in data:
            project.metadata = BookMetadata.from_dict(data["metadata"])

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

        data = {
            "schema_version": SCHEMA_VERSION,
            "title": self.title,
            "author": self.author,
            "source_path": str(self.source_path) if self.source_path else None,
            "created_at": self.created_at,
            "modified_at": self.modified_at,
            "output_path": str(self.output_path) if self.output_path else None,
            "chapters": [c.to_dict() for c in self.chapters],
            "casting": self.casting.to_dict(),
            "config": self.config.to_dict(),
            "metadata": self.metadata.to_dict(),
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
        emotion: Optional[str] = None,
        description: Optional[str] = None,
        speed: float = 1.0,
    ) -> Character:
        """
        Assign a voice to a character.

        Args:
            name: Character name (e.g., "narrator", "Alice")
            voice: Voice ID (e.g., "af_bella", "bm_george")
            emotion: Default emotion
            description: Notes about the character
            speed: Speech speed multiplier (0.5-2.0, default 1.0)

        Returns:
            The created Character
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

    def _validate_voices(self) -> None:
        """
        Check that all referenced voice IDs exist in voice-soundboard.

        Raises:
            VoiceNotFoundError: If any voice IDs are missing.
        """
        from audiobooker.casting.voice_registry import validate_voices, get_available_voices, VoiceNotFoundError

        # Collect all voice IDs: cast characters + fallback
        voice_ids = {char.voice for char in self.casting.characters.values()}
        voice_ids.add(self.config.fallback_voice_id)

        available = get_available_voices()
        missing = validate_voices(voice_ids, available)
        if missing:
            raise VoiceNotFoundError(missing=missing, available_count=len(available))

    # -------------------------------------------------------------------------
    # Pronunciation Overrides (FT-CORE-011)
    # -------------------------------------------------------------------------

    def add_pronunciation(self, word: str, replacement: str) -> None:
        """
        Add a pronunciation override.

        Before utterance creation in compile, the word will be substituted
        with the replacement text (whole-word, case-insensitive).

        Args:
            word: The word to replace (e.g., "Hermione")
            replacement: The phonetic replacement (e.g., "Her-MY-oh-nee")
        """
        if not word or not word.strip():
            raise ValueError("Pronunciation word must not be empty.")
        if not replacement or not replacement.strip():
            raise ValueError("Pronunciation replacement must not be empty.")
        self.config.pronunciation_overrides[word.strip()] = replacement.strip()
        self.modified_at = datetime.now().isoformat()

    def remove_pronunciation(self, word: str) -> None:
        """
        Remove a pronunciation override.

        Args:
            word: The word to remove from overrides

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

        # Create temp file for output
        tmp = tempfile.NamedTemporaryFile(
            suffix=".wav", prefix="audiobooker_preview_", delete=False
        )
        tmp.close()
        output_path = Path(tmp.name)

        engine.synthesize(
            text=text,
            voice=voice,
            output_path=output_path,
            speed=speed,
            emotion=emotion or None,
        )

        return output_path

    # -------------------------------------------------------------------------
    # Batch Casting Import/Export (FT-CORE-007)
    # -------------------------------------------------------------------------

    def export_casting(self, path: Path) -> None:
        """
        Export current casting table to a JSON file.

        Format: JSON array of objects with keys:
        name, voice, emotion, speed, aliases, description.

        Args:
            path: Output file path (should end in .json)
        """
        path = Path(path)
        cast_list = []
        for char in self.casting.characters.values():
            cast_list.append({
                "name": char.name,
                "voice": char.voice,
                "emotion": char.emotion,
                "speed": char.speed,
                "aliases": char.aliases,
                "description": char.description,
            })

        with open(path, "w", encoding="utf-8") as f:
            json.dump(cast_list, f, indent=2, ensure_ascii=False)

        logger.info("Exported casting table (%d characters) to %s", len(cast_list), path)

    def import_casting(self, path: Path) -> None:
        """
        Import casting table from a JSON file, merging with existing cast.

        Format: JSON array of objects with keys:
        name, voice, emotion, speed, aliases, description.
        On conflicts (same character name), the imported entry overwrites.

        Args:
            path: Path to casting JSON file

        Raises:
            FileNotFoundError: If the file doesn't exist
            ValueError: If the JSON format is invalid
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Casting file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            raise ValueError(
                "Casting file must contain a JSON array of character objects. "
                f"Got {type(data).__name__} instead."
            )

        imported = 0
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
                aliases=entry.get("aliases", []),
                description=entry.get("description"),
            )
            key = self.casting.normalize_key(char.name)
            self.casting.characters[key] = char
            imported += 1

        self.modified_at = datetime.now().isoformat()
        logger.info("Imported %d characters from %s", imported, path)

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
        if self.config.pronunciation_overrides:
            text = apply_pronunciation_overrides(
                text, self.config.pronunciation_overrides
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

        if failed_chapters and not dry_run:
            self.progress.status = "error"
            summary = "; ".join(
                f"ch{idx} '{title}': {err}" for idx, title, err in failed_chapters
            )
            self.progress.error_message = (
                f"{len(failed_chapters)} chapter(s) failed to compile: {summary}"
            )
            logger.warning(self.progress.error_message)

        if dry_run:
            return dry_run_result

        # Optional NLP speaker resolution (BookNLP)
        if self.config.booknlp_mode != "off":
            from audiobooker.nlp.speaker_resolver import SpeakerResolver
            resolver = SpeakerResolver(mode=self.config.booknlp_mode)
            resolver.resolve(self.chapters, self.casting)

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
            inferencer = EmotionInferencer(
                mode=self.config.emotion_mode,
                threshold=self.config.emotion_confidence_threshold,
                profile=inference_profile,
            )
            for chapter in self.chapters:
                inferencer.apply_to_utterances(chapter.utterances, chapter.raw_text)

        self.progress.status = "idle"
        self.modified_at = datetime.now().isoformat()
        return None

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

        workers = min(self.config.compile_workers, len(active_chapters))
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

        Returns:
            Path to output file
        """
        from audiobooker.renderer.engine import render_project

        fmt = output_format or self.config.output_format
        if output_path is None:
            output_path = Path(f"{_sanitize_filename(self.title)}.{fmt}")
        else:
            output_path = Path(output_path)

        self.output_path = output_path
        self.progress.status = "rendering"

        # Validate voices before spending time rendering
        if self.config.validate_voices_on_render:
            self._validate_voices()

        # Ensure all non-excluded chapters are compiled
        uncompiled = [c for c in self.chapters if not c.is_compiled and not c.skip]
        if uncompiled:
            self.compile()

        # Render
        result_path = render_project(
            self, output_path, progress_callback,
            engine=engine,
            assembler=assembler,
            resume=resume,
            from_chapter=from_chapter,
            allow_partial=allow_partial,
            jobs=jobs,
            force=force,
            output_format=output_format,
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
        """Ensure output directory exists."""
        if self._output_dir is None:
            self._output_dir = Path(f"{_sanitize_filename(self.title)}_audio")
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

        # Ensure compiled
        if not all(c.is_compiled for c in self.chapters):
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

        Returns:
            Dict with project stats
        """
        return {
            "title": self.title,
            "author": self.author,
            "source": str(self.source_path) if self.source_path else None,
            "chapters": len(self.chapters),
            "total_words": self.total_words,
            "estimated_duration_minutes": round(self.estimated_duration_minutes, 1),
            "characters_cast": len(self.casting.characters),
            "uncast_speakers": list(self.get_uncast_speakers()),
            "compiled": all(c.is_compiled for c in self.chapters),
            "rendered": all(c.is_rendered for c in self.chapters),
            "output": str(self.output_path) if self.output_path else None,
        }

    def __repr__(self) -> str:
        return (
            f"AudiobookProject(title={self.title!r}, "
            f"chapters={len(self.chapters)}, "
            f"words={self.total_words})"
        )
