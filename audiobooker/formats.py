"""The one table of output audio formats.

F-7a3c91e2. Before this module there were SIX disagreeing allowlists across
three files, and they disagreed in ways that broke the product in both
directions:

  cli.py:437/698/1161   m4b, mp3, wav
  cli.py:872 (podcast)  m4b, m4a, mp3, wav
  models.py             m4b, mp3, wav, ogg, flac
  renderer/engine.py    m4b, m4a, mp3, wav, opus, ogg, flac
  README.md             M4B, MP3, Opus, FLAC

Opus and FLAC have had dedicated, working assemblers the whole time and are
advertised in the README, but ``--format`` refused both — ``opus`` was not
even accepted by the config validator, so the capability was unreachable by
its own name at every layer above the engine.

Meanwhile ``wav``, one of only three formats ``--format`` did accept, had no
assembler branch at all. It fell through the dispatch's ``else`` to the M4B
assembler and wrote AAC-in-MP4 bytes to a path ending ``.wav``. It was also
absent from the ffmpeg preflight set while routing to an assembler that
requires ffmpeg, so ``--format wav`` on a machine without ffmpeg rendered the
entire book — every second of it paid for — and only then failed at assembly,
which is the exact waste the preflight exists to prevent.

So: one table, derived everywhere, and a ``wav`` that means WAV.

This module is a LEAF. It imports nothing from ``audiobooker`` so that the
CLI, the config validator and the renderer can all derive from it without an
import cycle. Adding a format here is the only edit needed to offer it.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AudioFormat:
    """One output format the renderer can actually produce."""

    name: str
    extension: str
    #: Attribute name of the assembler in ``audiobooker.renderer.output``.
    assembler: str
    needs_ffmpeg: bool
    lossless: bool
    description: str
    #: Other spellings that resolve to this format.
    aliases: tuple[str, ...] = field(default_factory=tuple)
    #: False for formats that are only reachable with another flag (``m4a``
    #: is the per-chapter product of ``--split``, not a whole-book format).
    whole_book: bool = True


_FORMAT_LIST: tuple[AudioFormat, ...] = (
    AudioFormat(
        name="m4b", extension=".m4b", assembler="assemble_m4b",
        needs_ffmpeg=True, lossless=False,
        description="AAC audiobook with chapter markers (the default)",
    ),
    AudioFormat(
        name="mp3", extension=".mp3", assembler="assemble_mp3",
        needs_ffmpeg=True, lossless=False,
        description="MP3, the most widely playable format",
    ),
    AudioFormat(
        name="opus", extension=".opus", assembler="assemble_opus",
        needs_ffmpeg=True, lossless=False, aliases=("ogg",),
        description="Opus in Ogg — the best quality per byte",
    ),
    AudioFormat(
        name="flac", extension=".flac", assembler="assemble_flac",
        needs_ffmpeg=True, lossless=True,
        description="Lossless FLAC, for archiving",
    ),
    AudioFormat(
        name="wav", extension=".wav", assembler="assemble_wav",
        needs_ffmpeg=True, lossless=True,
        description="Uncompressed WAV, for editing in a DAW",
    ),
    AudioFormat(
        name="m4a", extension=".m4a", assembler="assemble_m4a_split",
        needs_ffmpeg=True, lossless=False, whole_book=False,
        description="One AAC file per chapter (implies --split)",
    ),
)

FORMATS: dict[str, AudioFormat] = {f.name: f for f in _FORMAT_LIST}

_ALIASES: dict[str, str] = {
    alias: f.name for f in _FORMAT_LIST for alias in f.aliases
}

#: Everything a config file or the engine may legally carry, aliases included.
ALL_FORMAT_NAMES: frozenset[str] = frozenset(FORMATS) | frozenset(_ALIASES)

#: What ``--format`` offers for a whole book. Sorted for a stable --help.
BOOK_FORMATS: tuple[str, ...] = tuple(
    sorted(f.name for f in _FORMAT_LIST if f.whole_book)
)

#: Per-episode formats for the podcast feed. Episodes are separate files, so
#: ``m4a`` applies here where it is not a whole-book format. This is a strict
#: SUPERSET of the set ``podcast --format`` accepted before (m4b, m4a, mp3,
#: wav) — narrowing a published choice list would break working commands, so
#: unifying the allowlists only ever widens them.
PODCAST_FORMATS: tuple[str, ...] = tuple(sorted(FORMATS))

#: Formats whose assembly shells out to ffmpeg — the preflight set. Derived,
#: so a format can never be added without the preflight learning about it.
FFMPEG_FORMATS: frozenset[str] = frozenset(
    name
    for name in ALL_FORMAT_NAMES
    if FORMATS[_ALIASES.get(name, name)].needs_ffmpeg
)


def canonical(name: str) -> str:
    """Resolve an alias to its canonical format name (``ogg`` -> ``opus``)."""
    key = (name or "").strip().lower()
    return _ALIASES.get(key, key)


def get(name: str) -> AudioFormat:
    """The :class:`AudioFormat` for ``name``, resolving aliases.

    Raises:
        KeyError: if the name is not a known format.
    """
    return FORMATS[canonical(name)]


def needs_ffmpeg(name: str) -> bool:
    """Whether assembling ``name`` requires ffmpeg. Unknown names: True.

    Unknown defaults to True deliberately — the preflight's job is to fail
    early and clearly, and claiming a format needs no ffmpeg when nobody
    knows is how ``wav`` skipped the check and wasted a whole render.
    """
    try:
        return get(name).needs_ffmpeg
    except KeyError:
        return True


def describe_choices(names: tuple[str, ...] = BOOK_FORMATS) -> str:
    """One-line ``--help`` text listing each format and what it is for."""
    return "; ".join(f"{n} = {FORMATS[n].description}" for n in names)
