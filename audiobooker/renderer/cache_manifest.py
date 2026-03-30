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
        """Check if this entry is still valid (hashes match, WAV exists, and is non-empty)."""
        if self.status != "ok":
            return False
        if self.text_hash != text_hash:
            return False
        if self.casting_hash != casting_hash:
            return False
        if self.render_params_hash != render_params_hash:
            return False
        wav = Path(self.wav_path)
        if not wav.exists():
            return False
        # F-RENDER-B-007: Verify file is non-empty
        if wav.stat().st_size == 0:
            logger.warning(f"Cached WAV is empty (0 bytes): {self.wav_path}")
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
    _index: dict[int, int] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self):
        """Build internal index for O(1) lookups."""
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        """Rebuild the chapter_index → list position mapping."""
        self._index = {entry.chapter_index: i for i, entry in enumerate(self.chapters)}

    def get_entry(self, chapter_index: int) -> Optional[ChapterCacheEntry]:
        """Find entry by chapter index (O(1) via internal dict index)."""
        pos = self._index.get(chapter_index)
        if pos is not None:
            return self.chapters[pos]
        return None

    def set_entry(self, entry: ChapterCacheEntry) -> None:
        """Insert or replace entry for a chapter index."""
        pos = self._index.get(entry.chapter_index)
        if pos is not None:
            self.chapters[pos] = entry
        else:
            self._index[entry.chapter_index] = len(self.chapters)
            self.chapters.append(entry)

    def ok_chapters(self) -> list[ChapterCacheEntry]:
        """Return entries with status='ok'."""
        return [e for e in self.chapters if e.status == "ok"]

    def failed_chapters(self) -> list[ChapterCacheEntry]:
        """Return entries with status='failed'."""
        return [e for e in self.chapters if e.status == "failed"]

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("_index", None)
        return d

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
    """Atomically write manifest (write tmp → rename via .bak for crash safety)."""
    manifest.last_updated = datetime.now(timezone.utc).isoformat()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    # F-RENDER-B-006: Log manifest saves
    logger.debug(
        f"Saving manifest: {manifest_path} "
        f"({len(manifest.ok_chapters())} ok, {len(manifest.failed_chapters())} failed)"
    )

    tmp_path = manifest_path.with_suffix(".json.tmp")
    bak_path = manifest_path.with_suffix(".json.bak")
    tmp_path.write_text(manifest.to_json(), encoding="utf-8")

    try:
        # On Windows, rename fails if target exists. Use .bak to avoid
        # the gap between unlink() and rename() where a crash loses data.
        if manifest_path.exists():
            # Move existing to .bak (safe — old data preserved)
            if bak_path.exists():
                bak_path.unlink()
            os.rename(str(manifest_path), str(bak_path))
        # Move .tmp to target
        os.rename(str(tmp_path), str(manifest_path))
        # Success — remove .bak
        if bak_path.exists():
            bak_path.unlink()
    except OSError:
        # If target is missing and .bak exists, recover from .bak
        if not manifest_path.exists() and bak_path.exists():
            os.rename(str(bak_path), str(manifest_path))
        raise


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
