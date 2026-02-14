"""
Core data models for Audiobooker.

These are the fundamental units that flow through the system:
- Chapter: A section of the book with raw text
- Utterance: A single spoken unit (narrator or character dialogue)
- Character: A voice profile for a speaker
- CastingTable: Maps characters to voices
- ProjectConfig: Project-level settings
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional
import json


class UtteranceType(Enum):
    """Type of utterance for synthesis."""
    NARRATION = "narration"
    DIALOGUE = "dialogue"


@dataclass
class Utterance:
    """
    A single spoken unit in the audiobook.

    This is the atomic unit for synthesis - everything gets compiled
    down to a list of Utterances before rendering.

    Attributes:
        speaker: Character name (e.g., "narrator", "Alice")
        text: The text to speak
        utterance_type: Whether this is narration or dialogue
        emotion: Optional emotion override (e.g., "angry", "whisper")
        chapter_index: Which chapter this belongs to
        line_index: Position within the chapter
    """
    speaker: str
    text: str
    utterance_type: UtteranceType = UtteranceType.NARRATION
    emotion: Optional[str] = None
    chapter_index: int = 0
    line_index: int = 0

    def to_script_line(self) -> str:
        """Convert to voice-soundboard dialogue script format."""
        # Format: [S1:speaker] (emotion) text
        emotion_part = f"({self.emotion}) " if self.emotion else ""
        return f"[S1:{self.speaker}] {emotion_part}{self.text}"

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "speaker": self.speaker,
            "text": self.text,
            "type": self.utterance_type.value,
            "emotion": self.emotion,
            "chapter_index": self.chapter_index,
            "line_index": self.line_index,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Utterance":
        """Deserialize from dictionary."""
        return cls(
            speaker=data["speaker"],
            text=data["text"],
            utterance_type=UtteranceType(data.get("type", "narration")),
            emotion=data.get("emotion"),
            chapter_index=data.get("chapter_index", 0),
            line_index=data.get("line_index", 0),
        )


@dataclass
class Chapter:
    """
    A chapter or section of the book.

    Attributes:
        index: Chapter number (0-indexed)
        title: Chapter title (e.g., "Chapter 1: The Beginning")
        raw_text: Original text content
        utterances: Parsed utterances (populated after compilation)
        source_file: Original source file path
        audio_path: Path to rendered audio (populated after rendering)
        duration_seconds: Audio duration (populated after rendering)
    """
    index: int
    title: str
    raw_text: str
    utterances: list[Utterance] = field(default_factory=list)
    source_file: Optional[str] = None
    audio_path: Optional[Path] = None
    duration_seconds: float = 0.0

    @property
    def word_count(self) -> int:
        """Approximate word count."""
        return len(self.raw_text.split())

    @property
    def estimated_duration_minutes(self) -> float:
        """Estimate duration at ~150 words per minute."""
        return self.word_count / 150

    @property
    def is_compiled(self) -> bool:
        """Check if chapter has been compiled to utterances."""
        return len(self.utterances) > 0

    @property
    def is_rendered(self) -> bool:
        """Check if chapter has been rendered to audio."""
        return self.audio_path is not None and self.audio_path.exists()

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "index": self.index,
            "title": self.title,
            "raw_text": self.raw_text,
            "utterances": [u.to_dict() for u in self.utterances],
            "source_file": self.source_file,
            "audio_path": str(self.audio_path) if self.audio_path else None,
            "duration_seconds": self.duration_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Chapter":
        """Deserialize from dictionary."""
        chapter = cls(
            index=data["index"],
            title=data["title"],
            raw_text=data["raw_text"],
            source_file=data.get("source_file"),
            audio_path=Path(data["audio_path"]) if data.get("audio_path") else None,
            duration_seconds=data.get("duration_seconds", 0.0),
        )
        chapter.utterances = [
            Utterance.from_dict(u) for u in data.get("utterances", [])
        ]
        return chapter


@dataclass
class Character:
    """
    A character/speaker voice profile.

    Attributes:
        name: Character name (case-insensitive key)
        voice: Voice ID from voice-soundboard (e.g., "af_bella")
        emotion: Default emotion for this character
        description: User notes about the character
        line_count: Number of lines (tracked during compilation)
    """
    name: str
    voice: str
    emotion: Optional[str] = None
    description: Optional[str] = None
    line_count: int = 0

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "name": self.name,
            "voice": self.voice,
            "emotion": self.emotion,
            "description": self.description,
            "line_count": self.line_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Character":
        """Deserialize from dictionary."""
        return cls(
            name=data["name"],
            voice=data["voice"],
            emotion=data.get("emotion"),
            description=data.get("description"),
            line_count=data.get("line_count", 0),
        )


@dataclass
class CastingTable:
    """
    Maps characters to voice profiles.

    The casting table is the central configuration for voice assignment.
    It persists across sessions and can be edited by the user.

    Attributes:
        characters: Dict mapping lowercase character names to Character objects
        default_narrator: Voice ID for unmarked narration
        unknown_character_behavior: How to handle unknown speakers
        fallback_voice_id: Ultimate fallback voice when nothing else matches
    """
    characters: dict[str, Character] = field(default_factory=dict)
    default_narrator: str = "narrator"
    unknown_character_behavior: str = "narrator"  # "narrator" | "skip" | "ask"
    fallback_voice_id: str = "af_heart"

    @staticmethod
    def normalize_key(name: str) -> str:
        """Canonical key for speaker lookups (casefold for i18n safety)."""
        return name.casefold().strip()

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
            name: Character name (display form preserved in Character.name)
            voice: Voice ID (e.g., "af_bella", "bm_george")
            emotion: Default emotion
            description: Notes about the character

        Returns:
            The created/updated Character
        """
        key = self.normalize_key(name)
        char = Character(
            name=name,
            voice=voice,
            emotion=emotion,
            description=description,
        )
        self.characters[key] = char
        return char

    def get_voice(self, speaker: str) -> tuple[str, Optional[str]]:
        """
        Get voice ID and emotion for a speaker.

        Args:
            speaker: Speaker name

        Returns:
            Tuple of (voice_id, emotion)
        """
        key = self.normalize_key(speaker)
        if key in self.characters:
            char = self.characters[key]
            return char.voice, char.emotion

        # Fall back to narrator
        if self.default_narrator in self.characters:
            char = self.characters[self.default_narrator]
            return char.voice, char.emotion

        # Ultimate fallback
        return self.fallback_voice_id, None

    def get_voice_mapping(self) -> dict[str, str]:
        """
        Get voice mapping for speak_dialogue.

        Returns:
            Dict mapping speaker names to voice IDs
        """
        return {
            self.normalize_key(char.name): char.voice
            for char in self.characters.values()
        }

    def list_characters(self) -> list[str]:
        """Get list of all character names."""
        return [char.name for char in self.characters.values()]

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "characters": {
                k: v.to_dict() for k, v in self.characters.items()
            },
            "default_narrator": self.default_narrator,
            "unknown_character_behavior": self.unknown_character_behavior,
            "fallback_voice_id": self.fallback_voice_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CastingTable":
        """Deserialize from dictionary."""
        table = cls(
            default_narrator=data.get("default_narrator", "narrator"),
            unknown_character_behavior=data.get("unknown_character_behavior", "narrator"),
            fallback_voice_id=data.get("fallback_voice_id", "af_heart"),
        )
        for key, char_data in data.get("characters", {}).items():
            table.characters[key] = Character.from_dict(char_data)
        return table


@dataclass
class ProjectConfig:
    """
    Project-level configuration.

    Attributes:
        chapter_pause_ms: Silence between chapters
        narrator_pause_ms: Extra pause after narrator lines
        dialogue_pause_ms: Pause between dialogue lines
        sample_rate: Audio sample rate
        output_format: Default output format
        fallback_voice_id: Voice used when a speaker has no casting entry
        validate_voices_on_render: Check all voice IDs exist before rendering
        estimated_wpm: Words-per-minute for duration estimates (varies by voice/emotion)
        min_chapter_words: Minimum word count for EPUB sections to be kept as chapters
        keep_titled_short_chapters: Keep short EPUB sections that have a title/heading
        language_code: ISO language code for profile selection
        booknlp_mode: NLP speaker resolution: "on"|"off"|"auto" (default "auto")
        emotion_mode: Emotion inference: "off"|"rule"|"auto" (default "rule")
        emotion_confidence_threshold: Minimum confidence to apply inferred emotion
    """
    chapter_pause_ms: int = 2000
    narrator_pause_ms: int = 600
    dialogue_pause_ms: int = 400
    sample_rate: int = 24000
    output_format: str = "m4b"
    fallback_voice_id: str = "af_heart"
    validate_voices_on_render: bool = True
    estimated_wpm: int = 150
    min_chapter_words: int = 50
    keep_titled_short_chapters: bool = True
    language_code: str = "en"
    booknlp_mode: str = "auto"
    emotion_mode: str = "rule"
    emotion_confidence_threshold: float = 0.75

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "chapter_pause_ms": self.chapter_pause_ms,
            "narrator_pause_ms": self.narrator_pause_ms,
            "dialogue_pause_ms": self.dialogue_pause_ms,
            "sample_rate": self.sample_rate,
            "output_format": self.output_format,
            "fallback_voice_id": self.fallback_voice_id,
            "validate_voices_on_render": self.validate_voices_on_render,
            "estimated_wpm": self.estimated_wpm,
            "min_chapter_words": self.min_chapter_words,
            "keep_titled_short_chapters": self.keep_titled_short_chapters,
            "language_code": self.language_code,
            "booknlp_mode": self.booknlp_mode,
            "emotion_mode": self.emotion_mode,
            "emotion_confidence_threshold": self.emotion_confidence_threshold,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectConfig":
        """Deserialize from dictionary."""
        return cls(
            chapter_pause_ms=data.get("chapter_pause_ms", 2000),
            narrator_pause_ms=data.get("narrator_pause_ms", 600),
            dialogue_pause_ms=data.get("dialogue_pause_ms", 400),
            sample_rate=data.get("sample_rate", 24000),
            output_format=data.get("output_format", "m4b"),
            fallback_voice_id=data.get("fallback_voice_id", "af_heart"),
            validate_voices_on_render=data.get("validate_voices_on_render", True),
            estimated_wpm=data.get("estimated_wpm", 150),
            min_chapter_words=data.get("min_chapter_words", 50),
            keep_titled_short_chapters=data.get("keep_titled_short_chapters", True),
            language_code=data.get("language_code", "en"),
            booknlp_mode=data.get("booknlp_mode", "auto"),
            emotion_mode=data.get("emotion_mode", "rule"),
            emotion_confidence_threshold=data.get("emotion_confidence_threshold", 0.75),
        )
