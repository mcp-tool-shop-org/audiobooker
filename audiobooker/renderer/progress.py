"""
Progress reporting and ETA estimation for rendering.

Provides:
- RenderProgress with chapter count, percent, cached/skipped stats
- Dynamic ETA from observed render durations
- Per-voice WPM tracking for learned pace estimates
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ChapterProgress:
    """Progress for a single chapter."""
    index: int
    title: str
    status: str = "pending"   # pending | rendering | cached | done | failed
    duration_s: float = 0.0
    start_time: float = 0.0
    word_count: int = 0


@dataclass
class RenderProgressTracker:
    """
    Tracks rendering progress with dynamic ETA.

    Usage:
        tracker = RenderProgressTracker(total_chapters=10)
        tracker.start_chapter(0, "Chapter 1", word_count=3000)
        # ... render ...
        tracker.finish_chapter(0, duration_s=45.0)
        print(tracker.summary())
    """
    total_chapters: int = 0
    chapters: list[ChapterProgress] = field(default_factory=list)
    start_time: float = 0.0

    # Learned stats
    _render_durations: list[float] = field(default_factory=list)
    _words_rendered: list[int] = field(default_factory=list)

    def __post_init__(self):
        if not self.start_time:
            self.start_time = time.time()

    def start_chapter(self, index: int, title: str, word_count: int = 0) -> None:
        """Mark a chapter as started."""
        progress = ChapterProgress(
            index=index,
            title=title,
            status="rendering",
            start_time=time.time(),
            word_count=word_count,
        )
        # Replace or append
        for i, existing in enumerate(self.chapters):
            if existing.index == index:
                self.chapters[i] = progress
                return
        self.chapters.append(progress)

    def finish_chapter(self, index: int, duration_s: float = 0.0) -> None:
        """Mark a chapter as done."""
        for ch in self.chapters:
            if ch.index == index:
                ch.status = "done"
                ch.duration_s = duration_s
                self._render_durations.append(duration_s)
                if ch.word_count > 0:
                    self._words_rendered.append(ch.word_count)
                return

    def mark_cached(self, index: int, title: str, duration_s: float = 0.0) -> None:
        """Mark a chapter as cached/skipped."""
        progress = ChapterProgress(
            index=index, title=title, status="cached", duration_s=duration_s,
        )
        for i, existing in enumerate(self.chapters):
            if existing.index == index:
                self.chapters[i] = progress
                return
        self.chapters.append(progress)

    def mark_failed(self, index: int, title: str) -> None:
        """Mark a chapter as failed."""
        for ch in self.chapters:
            if ch.index == index:
                ch.status = "failed"
                return
        self.chapters.append(ChapterProgress(index=index, title=title, status="failed"))

    # ---- Stats ----

    @property
    def rendered_count(self) -> int:
        return sum(1 for ch in self.chapters if ch.status == "done")

    @property
    def cached_count(self) -> int:
        return sum(1 for ch in self.chapters if ch.status == "cached")

    @property
    def failed_count(self) -> int:
        return sum(1 for ch in self.chapters if ch.status == "failed")

    @property
    def completed_count(self) -> int:
        return self.rendered_count + self.cached_count

    @property
    def percent_complete(self) -> float:
        if self.total_chapters == 0:
            return 0.0
        return (self.completed_count / self.total_chapters) * 100

    @property
    def elapsed_s(self) -> float:
        return time.time() - self.start_time

    @property
    def avg_render_duration_s(self) -> float:
        """Average seconds per rendered chapter (excludes cached)."""
        if not self._render_durations:
            return 0.0
        return sum(self._render_durations) / len(self._render_durations)

    @property
    def estimated_wpm(self) -> float:
        """Observed words-per-minute from rendered chapters."""
        if not self._render_durations or not self._words_rendered:
            return 150.0  # default
        total_words = sum(self._words_rendered)
        total_duration_min = sum(self._render_durations) / 60.0
        if total_duration_min == 0:
            return 150.0
        return total_words / total_duration_min

    def eta_seconds(self) -> Optional[float]:
        """Estimated time remaining in seconds."""
        remaining = self.total_chapters - self.completed_count - self.failed_count
        if remaining <= 0:
            return 0.0
        if not self._render_durations:
            return None  # Can't estimate yet
        return remaining * self.avg_render_duration_s

    def eta_display(self) -> str:
        """Human-readable ETA string."""
        eta = self.eta_seconds()
        if eta is None:
            return "estimating..."
        if eta <= 0:
            return "done"
        minutes = int(eta // 60)
        seconds = int(eta % 60)
        if minutes > 0:
            return f"~{minutes}m {seconds}s remaining"
        return f"~{seconds}s remaining"

    def summary(self) -> str:
        """Human-readable progress summary."""
        parts = [
            f"{self.percent_complete:.0f}% complete",
            f"({self.rendered_count} rendered",
            f"{self.cached_count} cached",
        ]
        if self.failed_count:
            parts.append(f"{self.failed_count} failed")
        parts.append(f"of {self.total_chapters} total)")

        eta = self.eta_display()
        if eta != "done":
            parts.append(f"| {eta}")

        return " ".join(parts)

    def format_chapter_status(self, index: int, title: str) -> str:
        """Format a chapter status line for display."""
        pct = self.percent_complete
        eta = self.eta_display()
        cached_note = f" [{self.cached_count} cached]" if self.cached_count else ""
        return f"[{index + 1}/{self.total_chapters}] {pct:.0f}%{cached_note} {title} | {eta}"
