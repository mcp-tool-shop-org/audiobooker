"""
Core data models for Audiobooker.

These are the fundamental units that flow through the system:
- Chapter: A section of the book with raw text
- Utterance: A single spoken unit (narrator or character dialogue)
- Character: A voice profile for a speaker
- CastingTable: Maps characters to voices
- ProjectConfig: Project-level settings
"""

import hashlib
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class UtteranceType(Enum):
    """Type of utterance for synthesis."""
    NARRATION = "narration"
    DIALOGUE = "dialogue"
    DIRECTION = "direction"
    PAUSE = "pause"
    FOOTNOTE = "footnote"


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
        intensity: Optional graded strength of the emotion, 0.0-1.0 (CASTING-DEPTH
            v2.1). None preserves the current default behavior (a bare emotion
            renders at the existing 'strong' SSML emphasis). Set by emotion
            inference from the graded EmotionResult.confidence, or by a user via
            the inline (emotion:0.7) script tag.
        chapter_index: Which chapter this belongs to
        line_index: Position within the chapter
    """
    speaker: str
    text: str
    utterance_type: UtteranceType = UtteranceType.NARRATION
    emotion: Optional[str] = None
    intensity: Optional[float] = None
    chapter_index: int = 0
    line_index: int = 0
    start_pos: int = -1
    end_pos: int = -1
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self):
        """CASTING-DEPTH v2.1: validate intensity is within 0.0-1.0 when set.

        None is the default (current behavior preserved); any other value must
        be a number in [0.0, 1.0] so the renderer's emphasis-band mapping has a
        well-defined input.
        """
        if self.intensity is not None:
            if not isinstance(self.intensity, (int, float)) or isinstance(
                self.intensity, bool
            ):
                raise ValueError(
                    f"Utterance intensity must be a number between 0.0 and 1.0, "
                    f"got {self.intensity!r}."
                )
            if not (0.0 <= self.intensity <= 1.0):
                raise ValueError(
                    f"Utterance intensity must be between 0.0 and 1.0, "
                    f"got {self.intensity}."
                )

    def to_script_line(
        self,
        speed: Optional[float] = None,
        pitch_shift: Optional[float] = None,
        emphasis: Optional[float] = None,
    ) -> str:
        """Convert to internal intermediate script format.

        Format: [S1:speaker] (emotion) {speed:X.X} {pitch:X.X} {emphasis:X.X} text

        Args:
            speed: Optional speed hint (from character or global config).
            pitch_shift: Optional pitch shift hint (-1.0 to 1.0).
            emphasis: Optional emphasis hint (0.5 to 2.0).
        """
        emotion_part = f"({self.emotion}) " if self.emotion else ""
        speed_part = f"{{speed:{speed:.1f}}} " if speed is not None and speed != 1.0 else ""
        pitch_part = f"{{pitch:{pitch_shift:.1f}}} " if pitch_shift is not None and pitch_shift != 0.0 else ""
        emphasis_part = f"{{emphasis:{emphasis:.1f}}} " if emphasis is not None and emphasis != 1.0 else ""
        return f"[S1:{self.speaker}] {emotion_part}{speed_part}{pitch_part}{emphasis_part}{self.text}"

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        data = {
            "id": self.id,
            "speaker": self.speaker,
            "text": self.text,
            "type": self.utterance_type.value,
            "emotion": self.emotion,
            "chapter_index": self.chapter_index,
            "line_index": self.line_index,
            "start_pos": self.start_pos,
            "end_pos": self.end_pos,
        }
        # CASTING-DEPTH v2.1: only emit intensity when set, so existing project
        # files (intensity == None) round-trip byte-for-byte unchanged.
        if self.intensity is not None:
            data["intensity"] = self.intensity
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Utterance":
        """Deserialize from dictionary."""
        # F-CORE-B-007: Validate required keys
        for key in ("speaker", "text"):
            if key not in data:
                raise ValueError(
                    f"Utterance data is missing required key '{key}'. "
                    f"Got keys: {', '.join(sorted(data.keys()))}. "
                    "The project file may be corrupted — try re-compiling."
                )
        return cls(
            speaker=data["speaker"],
            text=data["text"],
            utterance_type=UtteranceType(data.get("type", "narration")),
            emotion=data.get("emotion"),
            # CASTING-DEPTH v2.1: legacy files have no "intensity" key -> None,
            # which preserves the current (bare-emotion) behavior.
            intensity=data.get("intensity"),
            chapter_index=data.get("chapter_index", 0),
            line_index=data.get("line_index", 0),
            start_pos=data.get("start_pos", -1),
            end_pos=data.get("end_pos", -1),
            id=data.get("id", str(uuid.uuid4())),
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
    skip: bool = False
    pause_before_ms: Optional[int] = None
    pause_after_ms: Optional[int] = None
    id: str = ""

    def __post_init__(self):
        """Generate stable ID from index + source context if not provided."""
        if not self.id:
            # Hash of index + source_file (or title as fallback context)
            context = f"{self.index}:{self.source_file or self.title}"
            self.id = hashlib.sha256(context.encode()).hexdigest()[:16]

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
        if self.audio_path is None:
            return False
        try:
            return self.audio_path.exists()
        except OSError:
            return False

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "index": self.index,
            "title": self.title,
            "raw_text": self.raw_text,
            "utterances": [u.to_dict() for u in self.utterances],
            "source_file": self.source_file,
            "audio_path": str(self.audio_path) if self.audio_path else None,
            "duration_seconds": self.duration_seconds,
            "skip": self.skip,
            "pause_before_ms": self.pause_before_ms,
            "pause_after_ms": self.pause_after_ms,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Chapter":
        """Deserialize from dictionary."""
        # F-CORE-B-007: Validate required keys
        for key in ("index", "title", "raw_text"):
            if key not in data:
                raise ValueError(
                    f"Chapter data is missing required key '{key}'. "
                    f"Got keys: {', '.join(sorted(data.keys()))}. "
                    "The project file may be corrupted."
                )
        chapter = cls(
            index=data["index"],
            title=data["title"],
            raw_text=data["raw_text"],
            source_file=data.get("source_file"),
            audio_path=Path(data["audio_path"]) if data.get("audio_path") else None,
            duration_seconds=data.get("duration_seconds", 0.0),
            skip=data.get("skip", False),
            pause_before_ms=data.get("pause_before_ms"),
            pause_after_ms=data.get("pause_after_ms"),
            id=data.get("id", ""),
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
    speed: float = 1.0
    pitch_shift: float = 0.0
    emphasis: float = 1.0
    aliases: list[str] = field(default_factory=list)
    # CASTING-DEPTH v2.1: default emotion intensity (0.0-1.0) for this
    # character's lines. None preserves current behavior (a bare emotion).
    default_intensity: Optional[float] = None

    def __post_init__(self):
        """Validate speed, pitch_shift, emphasis, and default_intensity ranges."""
        if self.default_intensity is not None and not (
            0.0 <= self.default_intensity <= 1.0
        ):
            raise ValueError(
                f"Character default_intensity must be between 0.0 and 1.0, "
                f"got {self.default_intensity}. Use None for the default behavior."
            )
        if not (0.5 <= self.speed <= 2.0):
            raise ValueError(
                f"Character speed must be between 0.5 and 2.0, got {self.speed}. "
                "Use 1.0 for normal speed, <1.0 for slower, >1.0 for faster."
            )
        if not (-1.0 <= self.pitch_shift <= 1.0):
            raise ValueError(
                f"Character pitch_shift must be between -1.0 and 1.0, got {self.pitch_shift}. "
                "Use 0.0 for no shift, negative for lower, positive for higher."
            )
        if not (0.5 <= self.emphasis <= 2.0):
            raise ValueError(
                f"Character emphasis must be between 0.5 and 2.0, got {self.emphasis}. "
                "Use 1.0 for normal emphasis."
            )

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        data = {
            "name": self.name,
            "voice": self.voice,
            "emotion": self.emotion,
            "description": self.description,
            "line_count": self.line_count,
            "speed": self.speed,
            "pitch_shift": self.pitch_shift,
            "emphasis": self.emphasis,
            "aliases": self.aliases,
        }
        # CASTING-DEPTH v2.1: only emit default_intensity when set, so existing
        # casting files round-trip unchanged when it is None.
        if self.default_intensity is not None:
            data["default_intensity"] = self.default_intensity
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Character":
        """Deserialize from dictionary."""
        # F-CORE-B-007: Validate required keys
        for key in ("name", "voice"):
            if key not in data:
                raise ValueError(
                    f"Character data is missing required key '{key}'. "
                    f"Got keys: {', '.join(sorted(data.keys()))}. "
                    "Check your casting configuration."
                )
        return cls(
            name=data["name"],
            voice=data["voice"],
            emotion=data.get("emotion"),
            description=data.get("description"),
            line_count=data.get("line_count", 0),
            speed=data.get("speed", 1.0),
            pitch_shift=data.get("pitch_shift", 0.0),
            emphasis=data.get("emphasis", 1.0),
            aliases=data.get("aliases", []),
            # CASTING-DEPTH v2.1: legacy entries have no key -> None (default).
            default_intensity=data.get("default_intensity"),
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
    _UNCAST_VOICE: str = "__uncast__"

    characters: dict[str, Character] = field(default_factory=dict)
    default_narrator: str = "narrator"
    unknown_character_behavior: str = "narrator"  # "narrator" | "skip" | "ask"
    fallback_voice_id: str = "af_heart"

    _VALID_UNKNOWN_BEHAVIORS = ("narrator", "skip", "ask")

    def __post_init__(self):
        """F-CORE-B-014: Validate unknown_character_behavior."""
        if self.unknown_character_behavior not in self._VALID_UNKNOWN_BEHAVIORS:
            raise ValueError(
                f"Invalid unknown_character_behavior: {self.unknown_character_behavior!r}. "
                f"Must be one of: {', '.join(self._VALID_UNKNOWN_BEHAVIORS)}"
            )

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
        speed: float = 1.0,
    ) -> Character:
        """
        Assign a voice to a character.

        Args:
            name: Character name (display form preserved in Character.name)
            voice: Voice ID (e.g., "af_bella", "bm_george")
            emotion: Default emotion
            description: Notes about the character
            speed: Speech speed multiplier (0.5-2.0, default 1.0)

        Returns:
            The created/updated Character
        """
        key = self.normalize_key(name)
        char = Character(
            name=name,
            voice=voice,
            emotion=emotion,
            description=description,
            speed=speed,
        )
        self.characters[key] = char
        return char

    def resolve_alias(self, speaker: str) -> 'Optional[Character]':
        """
        Resolve a speaker name through aliases.

        Checks if the speaker matches any character's alias list
        and returns the primary Character if found.

        Args:
            speaker: Speaker name to resolve

        Returns:
            The matching Character, or None if no alias match
        """
        key = self.normalize_key(speaker)
        for char in self.characters.values():
            for alias in char.aliases:
                if self.normalize_key(alias) == key:
                    return char
        return None

    def get_voice(self, speaker: str) -> tuple[str, Optional[str]]:
        """
        Get voice ID and emotion for a speaker.

        Checks direct character match first, then aliases,
        then falls back based on unknown_character_behavior:
        - "narrator": use narrator voice
        - "skip": use narrator voice (skip handled at render)
        - "ask": return _UNCAST_VOICE sentinel for interactive resolution

        Args:
            speaker: Speaker name

        Returns:
            Tuple of (voice_id, emotion)
        """
        key = self.normalize_key(speaker)
        if key in self.characters:
            char = self.characters[key]
            return char.voice, char.emotion

        # Check aliases
        alias_char = self.resolve_alias(speaker)
        if alias_char is not None:
            return alias_char.voice, alias_char.emotion

        # FT-CAST-008: Interactive casting — return sentinel for uncast speakers
        if self.unknown_character_behavior == "ask":
            return self._UNCAST_VOICE, None

        # Fall back to narrator (normalize key for consistent lookup)
        key = self.normalize_key(self.default_narrator)
        if key in self.characters:
            char = self.characters[key]
            return char.voice, char.emotion

        # Ultimate fallback
        return self.fallback_voice_id, None

    def get_uncast_at_render(self, utterances: list["Utterance"]) -> list[str]:
        """
        FT-CAST-008: Collect all uncast speakers from a render prep pass.

        Scans utterances and returns speaker names whose voice resolves
        to the _UNCAST_VOICE sentinel. Useful for interactive casting mode
        where the UI can prompt the user to assign voices before rendering.

        Args:
            utterances: List of Utterances to scan.

        Returns:
            Sorted list of unique uncast speaker names.
        """
        uncast: set[str] = set()
        for utt in utterances:
            voice, _ = self.get_voice(utt.speaker)
            if voice == self._UNCAST_VOICE:
                uncast.add(utt.speaker)
        return sorted(uncast)

    def get_speed(self, speaker: str) -> float:
        """
        Get speech speed for a speaker.

        Args:
            speaker: Speaker name

        Returns:
            Speed multiplier (1.0 if not configured)
        """
        key = self.normalize_key(speaker)
        if key in self.characters:
            return self.characters[key].speed
        return 1.0

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
        output_profile: Mastering profile for final assembly: "podcast"
            (EBU R128 -16 LUFS, current behavior) or "acx" (ACX retail target,
            loudnorm I=-20:TP=-3:LRA=11). Default "podcast".
        aac_bitrate: Override AAC bitrate for M4B/m4a output (e.g. "192k").
            None uses the assembler default (128k, or 192k under the acx profile).
        mp3_bitrate: Override MP3/Opus bitrate (e.g. "192k"). None uses the
            assembler default.
        use_toc: EPUB table-of-contents driven chapter splitting:
            "auto" (default, use TOC when usable else spine-split), "on", or
            "off" (always spine-split, legacy behavior).
        phoneme_overrides: Phoneme-typed pronunciation entries, kept distinct
            from plain spelling replacements (pronunciation_overrides). Filled
            by import_lexicon from lexicon entries marked type=phoneme.
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
    global_speed: float = 1.0
    pronunciation_overrides: dict[str, str] = field(default_factory=dict)
    clean_text: bool = True
    normalize_text: bool = True
    parallel_compile: bool = False
    compile_workers: int = 4
    user_emotion_rules: dict[str, str] = field(default_factory=dict)
    footnote_behavior: str = "inline"
    output_profile: str = "podcast"
    aac_bitrate: Optional[str] = None
    mp3_bitrate: Optional[str] = None
    # INPUT (v2.1): EPUB table-of-contents driven chapter splitting.
    #   "auto" — use the EPUB's TOC when a usable one exists, otherwise fall
    #            back to the current spine-splitting behavior (default).
    #   "on"   — require/prefer TOC-based splitting.
    #   "off"  — always use spine-splitting (legacy behavior).
    use_toc: str = "auto"
    # INPUT (v2.1): phoneme-typed pronunciation entries kept distinct from
    #   plain spelling replacements (config.pronunciation_overrides). Populated
    #   by import_lexicon from entries whose type column is "phoneme".
    phoneme_overrides: dict[str, str] = field(default_factory=dict)
    # CASTING-DEPTH (v2.1): emotion preset pack that parametrizes the emotion
    #   inferencer's threshold + label set. "neutral" preserves the current
    #   default behavior; "literary" / "dramatic" / "children" tune sensitivity.
    emotion_preset: str = "neutral"

    _VALID_OUTPUT_FORMATS = ("m4b", "mp3", "wav", "ogg", "flac")
    _VALID_BOOKNLP_MODES = ("on", "off", "auto")
    _VALID_EMOTION_MODES = ("off", "rule", "auto")
    _VALID_FOOTNOTE_BEHAVIORS = ("inline", "end", "skip")
    _VALID_OUTPUT_PROFILES = ("podcast", "acx")
    _VALID_USE_TOC = ("auto", "on", "off")
    _VALID_EMOTION_PRESETS = ("neutral", "literary", "dramatic", "children")

    def __post_init__(self):
        """F-CORE-B-015: Validate enum-like string fields."""
        if self.output_format not in self._VALID_OUTPUT_FORMATS:
            raise ValueError(
                f"Invalid output_format: {self.output_format!r}. "
                f"Must be one of: {', '.join(self._VALID_OUTPUT_FORMATS)}"
            )
        if self.booknlp_mode not in self._VALID_BOOKNLP_MODES:
            raise ValueError(
                f"Invalid booknlp_mode: {self.booknlp_mode!r}. "
                f"Must be one of: {', '.join(self._VALID_BOOKNLP_MODES)}"
            )
        if self.emotion_mode not in self._VALID_EMOTION_MODES:
            raise ValueError(
                f"Invalid emotion_mode: {self.emotion_mode!r}. "
                f"Must be one of: {', '.join(self._VALID_EMOTION_MODES)}"
            )
        if self.footnote_behavior not in self._VALID_FOOTNOTE_BEHAVIORS:
            raise ValueError(
                f"Invalid footnote_behavior: {self.footnote_behavior!r}. "
                f"Must be one of: {', '.join(self._VALID_FOOTNOTE_BEHAVIORS)}"
            )
        if not (0.5 <= self.global_speed <= 2.0):
            raise ValueError(
                f"global_speed must be between 0.5 and 2.0, got {self.global_speed}. "
                "Use 1.0 for normal speed."
            )
        if self.output_profile not in self._VALID_OUTPUT_PROFILES:
            raise ValueError(
                f"Invalid output_profile: {self.output_profile!r}. "
                f"Must be one of: {', '.join(self._VALID_OUTPUT_PROFILES)}"
            )
        if self.use_toc not in self._VALID_USE_TOC:
            raise ValueError(
                f"Invalid use_toc: {self.use_toc!r}. "
                f"Must be one of: {', '.join(self._VALID_USE_TOC)}"
            )
        if self.emotion_preset not in self._VALID_EMOTION_PRESETS:
            raise ValueError(
                f"Invalid emotion_preset: {self.emotion_preset!r}. "
                f"Must be one of: {', '.join(self._VALID_EMOTION_PRESETS)}"
            )

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
            "global_speed": self.global_speed,
            "pronunciation_overrides": self.pronunciation_overrides,
            "clean_text": self.clean_text,
            "normalize_text": self.normalize_text,
            "parallel_compile": self.parallel_compile,
            "compile_workers": self.compile_workers,
            "user_emotion_rules": self.user_emotion_rules,
            "footnote_behavior": self.footnote_behavior,
            "output_profile": self.output_profile,
            "aac_bitrate": self.aac_bitrate,
            "mp3_bitrate": self.mp3_bitrate,
            "use_toc": self.use_toc,
            "phoneme_overrides": self.phoneme_overrides,
            "emotion_preset": self.emotion_preset,
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
            global_speed=data.get("global_speed", 1.0),
            pronunciation_overrides=data.get("pronunciation_overrides", {}),
            clean_text=data.get("clean_text", True),
            normalize_text=data.get("normalize_text", True),
            parallel_compile=data.get("parallel_compile", False),
            compile_workers=data.get("compile_workers", 4),
            user_emotion_rules=data.get("user_emotion_rules", {}),
            footnote_behavior=data.get("footnote_behavior", "inline"),
            output_profile=data.get("output_profile", "podcast"),
            aac_bitrate=data.get("aac_bitrate"),
            mp3_bitrate=data.get("mp3_bitrate"),
            use_toc=data.get("use_toc", "auto"),
            phoneme_overrides=data.get("phoneme_overrides", {}),
            # CASTING-DEPTH v2.1: legacy configs default to "neutral".
            emotion_preset=data.get("emotion_preset", "neutral"),
        )


@dataclass
class BookMetadata:
    """
    Audiobook metadata for embedding in output files.

    Attributes:
        cover_art_path: Path to cover art image (extracted from EPUB or user-provided)
        genre: Book genre (e.g., "Fiction", "Science Fiction")
        series: Series name (e.g., "The Lord of the Rings")
        series_index: Position in series (e.g., 1 for first book)
        year: Publication year
        narrator_name: Narrator credit for the audiobook
        publisher: Publisher name
    """
    cover_art_path: Optional[Path] = None
    genre: str = ""
    series: str = ""
    series_index: Optional[int] = None
    year: Optional[int] = None
    narrator_name: str = ""
    publisher: str = ""

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "cover_art_path": str(self.cover_art_path) if self.cover_art_path else None,
            "genre": self.genre,
            "series": self.series,
            "series_index": self.series_index,
            "year": self.year,
            "narrator_name": self.narrator_name,
            "publisher": self.publisher,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BookMetadata":
        """Deserialize from dictionary."""
        return cls(
            cover_art_path=Path(data["cover_art_path"]) if data.get("cover_art_path") else None,
            genre=data.get("genre", ""),
            series=data.get("series", ""),
            series_index=data.get("series_index"),
            year=data.get("year"),
            narrator_name=data.get("narrator_name", ""),
            publisher=data.get("publisher", ""),
        )
