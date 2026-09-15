"""How a chapter is named on screen.

A leaf module, for the same reason ``shell_quote`` is one: ``cli`` prints
chapter references and so does ``renderer.engine``'s dry-run table, and
``cli`` imports ``engine``. ``engine`` also imports ``models`` only under
``TYPE_CHECKING``, deliberately — so the helper cannot live there either
without changing that.

Imports nothing from ``audiobooker``. Keep it that way.
"""

from __future__ import annotations

__all__ = ["chapter_label"]


def chapter_label(index: int) -> str:
    """Name a chapter in BOTH numbering schemes.

    FEAT-UX-007. This CLI carries four: ``-c N`` is 0-based, ``--chapters``
    and ``--exclude-chapters`` take 1-based ranges, the ``chapters``
    listing was 1-based, and ``render --dry-run`` printed a bare index.
    Nothing on screen said which scheme it was using.

    The flags themselves are documented and stay as they are — silently
    changing what ``-c 3`` means would be worse than the ambiguity.
    Instead every printed reference carries both numbers, so no reader has
    to know which command they came from.
    """
    return f"[idx {index}] ch.{index + 1}"
