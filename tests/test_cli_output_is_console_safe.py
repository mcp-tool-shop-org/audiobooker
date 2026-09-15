"""Everything the CLI prints must survive a stock Windows console.

`_configure_output_encoding()` reconfigures stdout/stderr with
``errors="replace"`` rather than forcing UTF-8, and that is the right
call — forcing UTF-8 onto a cp1252 console trades a crash for mojibake,
and a run of ``?`` is the honest degrade.

The consequence is that it is now *silent*. An em-dash in a printed string
no longer raises; it just prints as ``?`` to every Windows user and nobody
finds out. cli.py had collected 45 of them, including one in the headline
number of the attribution report.

So the guard has to be static. This walks the source rather than the
output, because covering every printed string through the CLI would mean
executing every error path.

Comments and docstrings are exempt: they are read in the source, never
written to a stream. cli.py keeps 130 em-dashes in those, deliberately.
"""

from __future__ import annotations

import ast
import pathlib
import tokenize

CLI = pathlib.Path(__file__).resolve().parent.parent / "audiobooker" / "cli.py"

# MEASURED, because the obvious guess is wrong. cp1252 is the Windows
# *ANSI* codepage and it encodes em-dash, en-dash, curly quotes and
# ellipsis without complaint (they live at 0x91-0x97). What a bare
# cmd.exe actually runs is an *OEM* codepage — 437 in en-US, 850 in
# much of western Europe — and those have none of them:
#
#     char                cp1252   cp437   cp850   utf-8
#     em-dash                 ok    FAIL    FAIL      ok
#     curly-right-quote       ok    FAIL    FAIL      ok
#     ellipsis                ok    FAIL    FAIL      ok
#     e-acute                 ok      ok      ok      ok
#
# So cp437 is the bar, not cp1252. Note it is NOT plain ASCII either:
# cp437 carries the accented Latin characters, so a book titled "Café"
# is fine and this test must not flag it.
CONSOLE_ENCODING = "cp437"


def _docstring_spans(tree: ast.AST) -> list[tuple[tuple[int, int],
                                                  tuple[int, int]]]:
    spans = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            d = body[0].value
            spans.append(((d.lineno, d.col_offset),
                          (d.end_lineno, d.end_col_offset)))
    return spans


def _offending_string_literals() -> list[tuple[int, str, str]]:
    src = CLI.read_text(encoding="utf-8")
    spans = _docstring_spans(ast.parse(src))

    def is_docstring(start, end) -> bool:
        return any(s <= start and end <= e for s, e in spans)

    out: list[tuple[int, str, str]] = []
    readline = iter(src.splitlines(True)).__next__
    for tok in tokenize.generate_tokens(readline):
        if tok.type not in (tokenize.STRING, tokenize.FSTRING_MIDDLE):
            continue
        if is_docstring(tok.start, tok.end):
            continue
        bad = sorted({
            ch for ch in tok.string
            if not _encodable(ch)
        })
        if bad:
            out.append((tok.start[0], "".join(bad), tok.string.strip()[:90]))
    return out


def _encodable(ch: str) -> bool:
    try:
        ch.encode(CONSOLE_ENCODING)
        return True
    except UnicodeEncodeError:
        return False


class TestPrintedStringsSurviveCp1252:
    def test_no_cli_string_literal_degrades_on_a_windows_console(self):
        offenders = _offending_string_literals()
        assert not offenders, (
            f"{len(offenders)} string literal(s) in cli.py contain characters "
            f"a {CONSOLE_ENCODING} console cannot render. They will print as "
            "'?' rather than raising, so nothing else will tell you:\n"
            + "\n".join(
                f"  line {ln}: {chars!r} in {text}"
                for ln, chars, text in offenders
            )
            + "\n\nUse ASCII in printed text (' - ' for an em-dash). "
            "Comments and docstrings are exempt and are not checked."
        )

    def test_the_guard_can_actually_fail(self):
        """A gate that cannot go red is worse than no gate. Prove the
        detector sees the characters it exists to catch — and, just as
        important, that it does NOT fire on the ones a console can
        render, or it will push the codebase to pointless ASCII."""
        assert not _encodable("—"), "em-dash"
        assert not _encodable("–"), "en-dash"
        assert not _encodable("’"), "curly right quote"
        assert not _encodable("…"), "ellipsis"

        assert _encodable("é"), "cp437 carries accented Latin; é must pass"
        assert _encodable("ü")
        assert _encodable("-")

        # The premise this whole guard was nearly built on, recorded so
        # nobody re-derives it wrong: the ANSI codepage does encode all
        # of the above, which is why picking cp1252 as the bar would
        # have made this test vacuous.
        assert "—".encode("cp1252") == b"\x97"

    def test_docstrings_are_deliberately_exempt(self):
        """cli.py keeps em-dashes in its prose. If this ever reaches zero,
        the exemption logic has broken and the test above is passing
        vacuously."""
        src = CLI.read_text(encoding="utf-8")
        assert src.count("—") > 50, (
            "cli.py's comments/docstrings lost their em-dashes — the "
            "docstring exemption is probably no longer being applied"
        )
