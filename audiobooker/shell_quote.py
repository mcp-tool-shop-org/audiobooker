"""Quote one argument so a command we PRINT runs when it is pasted.

A leaf module on purpose: both ``cli`` and ``review`` print next-step
commands, and ``cli`` imports ``review``, so the rule cannot live in
either without an import cycle or a second copy. This release replaced
six drifting output-format allowlists with one table; a Windows-vs-POSIX
quoting rule earns the same treatment for the same reason.

Imports nothing from ``audiobooker``. Keep it that way.
"""

from __future__ import annotations

import os
import re
import shlex

# Characters a Windows shell leaves alone. Backslash is included because a
# Windows path is nothing but backslashes and quoting every one of them would
# make the common case uglier without making it safer.
_WIN_SHELL_SAFE = re.compile(r"^[A-Za-z0-9_@%+=:,./\\-]+$")

__all__ = ["quote_arg"]


def quote_arg(value) -> str:
    """Return ``value`` quoted for the local shell.

    ``review-export`` names the review file from the book TITLE, so a book
    called "The Midnight Garden" produced::

        Then import: audiobooker review-import The Midnight Garden_review.txt

    which argparse rejects — and then dumps all 34 subcommands at a user
    who did nothing wrong. Any command we print as a next step has to
    survive being pasted.

    ``shlex.quote`` alone is not the answer on Windows: it is POSIX, it
    treats ``\\`` as unsafe, so every Windows path comes back wrapped in
    SINGLE quotes — which cmd.exe does not treat as quoting at all, and
    which would hand argparse a literal leading apostrophe. So on Windows
    quote only what needs it, the way cmd.exe expects.
    """
    text = str(value)
    if os.name != "nt":
        return shlex.quote(text)
    if text and _WIN_SHELL_SAFE.match(text):
        return text
    return '"' + text.replace('"', '\\"') + '"'
