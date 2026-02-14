"""
Failure report bundle for render errors.

On error, writes a structured JSON report with:
- Chapter index/title
- Utterance index + speaker + excerpt
- Chosen voice + emotion
- Stack trace + stderr excerpts
- Paths to cached audio + manifest
"""

from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class FailedUtterance:
    """Detail about the failing utterance."""
    index: int = -1
    speaker: str = ""
    text_preview: str = ""
    voice_id: str = ""
    emotion: str = ""


@dataclass
class FailedChapter:
    """Detail about a failed chapter."""
    chapter_index: int
    chapter_title: str
    error_message: str
    stack_trace: str = ""
    failed_utterance: Optional[FailedUtterance] = None


@dataclass
class RenderFailureReport:
    """Complete failure report for a render session."""
    timestamp: str = ""
    book_title: str = ""
    total_chapters: int = 0
    rendered_ok: int = 0
    cached_ok: int = 0
    failed_count: int = 0
    failed_chapters: list[FailedChapter] = field(default_factory=list)
    cache_dir: str = ""
    manifest_path: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def add_failure(
        self,
        chapter_index: int,
        chapter_title: str,
        error: Exception,
        utterance_index: int = -1,
        speaker: str = "",
        text_preview: str = "",
        voice_id: str = "",
        emotion: str = "",
    ) -> None:
        """Record a chapter failure."""
        failed_utt = None
        if utterance_index >= 0:
            failed_utt = FailedUtterance(
                index=utterance_index,
                speaker=speaker,
                text_preview=text_preview[:200],
                voice_id=voice_id,
                emotion=emotion,
            )

        self.failed_chapters.append(FailedChapter(
            chapter_index=chapter_index,
            chapter_title=chapter_title,
            error_message=str(error),
            stack_trace=traceback.format_exc(),
            failed_utterance=failed_utt,
        ))
        self.failed_count = len(self.failed_chapters)

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return asdict(self)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    def save(self, path: Optional[Path] = None) -> Path:
        """
        Write report to disk.

        Args:
            path: Output path (default: render_failure_report.json in cache_dir).

        Returns:
            Path to written report.
        """
        if path is None:
            if self.cache_dir:
                path = Path(self.cache_dir) / "render_failure_report.json"
            else:
                path = Path("render_failure_report.json")

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")
        return path

    @classmethod
    def from_dict(cls, data: dict) -> "RenderFailureReport":
        """Load from dictionary."""
        report = cls(
            timestamp=data.get("timestamp", ""),
            book_title=data.get("book_title", ""),
            total_chapters=data.get("total_chapters", 0),
            rendered_ok=data.get("rendered_ok", 0),
            cached_ok=data.get("cached_ok", 0),
            failed_count=data.get("failed_count", 0),
            cache_dir=data.get("cache_dir", ""),
            manifest_path=data.get("manifest_path", ""),
        )
        for fc in data.get("failed_chapters", []):
            fu_data = fc.get("failed_utterance")
            fu = FailedUtterance(**fu_data) if fu_data else None
            report.failed_chapters.append(FailedChapter(
                chapter_index=fc["chapter_index"],
                chapter_title=fc["chapter_title"],
                error_message=fc["error_message"],
                stack_trace=fc.get("stack_trace", ""),
                failed_utterance=fu,
            ))
        return report

    @classmethod
    def load(cls, path: Path) -> "RenderFailureReport":
        """Load report from JSON file."""
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)
