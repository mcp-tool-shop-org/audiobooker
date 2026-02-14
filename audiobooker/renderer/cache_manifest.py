"""
Render cache manifest — tracks per-chapter WAV status for resume.

The manifest is the source-of-truth for what has been rendered.
It is atomically written after each chapter completes.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("audiobooker.cache")

MANIFEST_VERSION = 1
MANIFEST_FILENAME = "render_v1.json"


@dataclass
class ChapterCacheEntry:
    """One chapter's cache record."""
    chapter_index: int
    text_hash: str
    casting_hash: str
    render_params_hash: str
    wav_path: str
    duration_s: float = 0.0
    status: str = "pending"   # pending | ok | failed
    error_summary: str = ""
    created_at: str = ""

    def is_valid(self, text_hash: str, casting_hash: str, render_params_hash: str) -> bool:
        """Check if this entry is still valid (hashes match and WAV exists)."""
        if self.status != "ok":
            return False
        if self.text_hash != text_hash:
            return False
        if self.casting_hash != casting_hash:
            return False
        if self.render_params_hash != render_params_hash:
            return False
        if not Path(self.wav_path).exists():
            return False
        return True


@dataclass
class CacheManifest:
    """Top-level manifest for a render session."""
    version: int = MANIFEST_VERSION
    book_title: str = ""
    config_hash: str = ""
    chapters: list[ChapterCacheEntry] = field(default_factory=list)
    last_updated: str = ""

    def get_entry(self, chapter_index: int) -> Optional[ChapterCacheEntry]:
        """Find entry by chapter index."""
        for entry in self.chapters:
            if entry.chapter_index == chapter_index:
                return entry
        return None

    def set_entry(self, entry: ChapterCacheEntry) -> None:
        """Insert or replace entry for a chapter index."""
        for i, existing in enumerate(self.chapters):
            if existing.chapter_index == entry.chapter_index:
                self.chapters[i] = entry
                return
        self.chapters.append(entry)

    def ok_chapters(self) -> list[ChapterCacheEntry]:
        """Return entries with status='ok'."""
        return [e for e in self.chapters if e.status == "ok"]

    def failed_chapters(self) -> list[ChapterCacheEntry]:
        """Return entries with status='failed'."""
        return [e for e in self.chapters if e.status == "failed"]

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> "CacheManifest":
        chapters = [
            ChapterCacheEntry(**ch) for ch in data.get("chapters", [])
        ]
        return cls(
            version=data.get("version", MANIFEST_VERSION),
            book_title=data.get("book_title", ""),
            config_hash=data.get("config_hash", ""),
            chapters=chapters,
            last_updated=data.get("last_updated", ""),
        )


# ---------------------------------------------------------------------------
# Atomic I/O
# ---------------------------------------------------------------------------

def load_manifest(manifest_path: Path) -> Optional[CacheManifest]:
    """Load manifest from disk. Returns None if missing or corrupt."""
    if not manifest_path.exists():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = CacheManifest.from_dict(data)
        if manifest.version > MANIFEST_VERSION:
            logger.warning(
                f"Manifest version {manifest.version} > supported {MANIFEST_VERSION}; ignoring cache"
            )
            return None
        return manifest
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning(f"Corrupt manifest at {manifest_path}: {e}")
        return None


def save_manifest(manifest: CacheManifest, manifest_path: Path) -> None:
    """Atomically write manifest (write tmp → rename)."""
    manifest.last_updated = datetime.now(timezone.utc).isoformat()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = manifest_path.with_suffix(".json.tmp")
    tmp_path.write_text(manifest.to_json(), encoding="utf-8")

    # Atomic rename (on Windows, must remove target first)
    if manifest_path.exists():
        manifest_path.unlink()
    os.rename(str(tmp_path), str(manifest_path))


# ---------------------------------------------------------------------------
# Cache directory layout
# ---------------------------------------------------------------------------

def get_cache_root(project_dir: Path) -> Path:
    """<project_dir>/.audiobooker/cache/"""
    return project_dir / ".audiobooker" / "cache"


def get_chapters_dir(cache_root: Path) -> Path:
    return cache_root / "chapters"


def get_manifests_dir(cache_root: Path) -> Path:
    return cache_root / "manifests"


def get_chapter_wav_path(cache_root: Path, chapter_index: int) -> Path:
    return get_chapters_dir(cache_root) / f"chapter_{chapter_index:04d}.wav"


def get_manifest_path(cache_root: Path) -> Path:
    return get_manifests_dir(cache_root) / MANIFEST_FILENAME
