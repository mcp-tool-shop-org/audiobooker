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
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

from audiobooker.models import (
    Chapter,
    Utterance,
    Character,
    CastingTable,
    ProjectConfig,
)


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
    # Factory methods
    # -------------------------------------------------------------------------

    @classmethod
    def from_epub(cls, path: str | Path, **kwargs) -> "AudiobookProject":
        """
        Create project from EPUB file.

        Args:
            path: Path to EPUB file
            **kwargs: Additional project config

        Returns:
            Initialized AudiobookProject
        """
        from audiobooker.parser.epub import parse_epub

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"EPUB not found: {path}")

        # Extract config to pass EPUB parsing thresholds
        config = kwargs.get("config", ProjectConfig())

        metadata, chapters = parse_epub(
            path,
            min_chapter_words=config.min_chapter_words,
            keep_titled_short_chapters=config.keep_titled_short_chapters,
        )

        project = cls(
            title=metadata.get("title", path.stem),
            author=metadata.get("author", ""),
            source_path=path,
            chapters=chapters,
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
            **kwargs: Additional project config

        Returns:
            Initialized AudiobookProject
        """
        from audiobooker.parser.text import parse_text
        from audiobooker.language.profile import get_profile

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Text file not found: {path}")

        config = kwargs.get("config", ProjectConfig())
        profile = get_profile(config.language_code)

        metadata, chapters = parse_text(path, profile=profile)

        project = cls(
            title=metadata.get("title", path.stem),
            author=metadata.get("author", ""),
            source_path=path,
            chapters=chapters,
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

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Check schema version
        schema_version = data.get("schema_version", 1)
        if schema_version > SCHEMA_VERSION:
            raise ValueError(
                f"Project file uses schema v{schema_version}, "
                f"but this version only supports up to v{SCHEMA_VERSION}"
            )

        project = cls(
            title=data.get("title", "Untitled"),
            author=data.get("author", ""),
            source_path=Path(data["source_path"]) if data.get("source_path") else None,
            project_path=path,
            created_at=data.get("created_at", datetime.now().isoformat()),
            modified_at=data.get("modified_at", datetime.now().isoformat()),
            output_path=Path(data["output_path"]) if data.get("output_path") else None,
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
                    path = Path(f"{self.title}.audiobooker")
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
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

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
    ) -> Character:
        """
        Assign a voice to a character.

        Args:
            name: Character name (e.g., "narrator", "Alice")
            voice: Voice ID (e.g., "af_bella", "bm_george")
            emotion: Default emotion
            description: Notes about the character

        Returns:
            The created Character
        """
        return self.casting.cast(name, voice, emotion, description)

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
    # Compilation
    # -------------------------------------------------------------------------

    def compile(
        self,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> None:
        """
        Compile all chapters to utterances.

        This parses the raw text and detects dialogue vs narration,
        creating a list of Utterances for each chapter.

        Args:
            progress_callback: Callback(current, total, chapter_title)
        """
        from audiobooker.casting.dialogue import compile_chapter
        from audiobooker.language.profile import get_profile

        profile = get_profile(self.config.language_code)

        self.progress.status = "compiling"
        self.progress.total_chapters = len(self.chapters)

        for i, chapter in enumerate(self.chapters):
            self.progress.current_chapter = i + 1
            if progress_callback:
                progress_callback(i + 1, len(self.chapters), chapter.title)

            # Compile chapter to utterances
            utterances = compile_chapter(chapter, self.casting, profile=profile)
            chapter.utterances = utterances

        self.progress.status = "idle"
        self.modified_at = datetime.now().isoformat()

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
    ) -> Path:
        """
        Render all chapters and assemble final audiobook.

        Args:
            output_path: Output file path (default: {title}.m4b)
            progress_callback: Callback(current, total, status)
            resume: Skip chapters with valid cached audio (default True).
            from_chapter: Start from this chapter index (0-based).
            allow_partial: Assemble even if some chapters failed.
            engine: Injected TTSEngine (for testing).
            assembler: Injected assembly callable (for testing).

        Returns:
            Path to output file
        """
        from audiobooker.renderer.engine import render_project

        if output_path is None:
            output_path = Path(f"{self.title}.{self.config.output_format}")
        else:
            output_path = Path(output_path)

        self.output_path = output_path
        self.progress.status = "rendering"

        # Validate voices before spending time rendering
        if self.config.validate_voices_on_render:
            self._validate_voices()

        # Ensure all chapters are compiled
        uncompiled = [c for c in self.chapters if not c.is_compiled]
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
            self._output_dir = Path(f"{self.title}_audio")
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
