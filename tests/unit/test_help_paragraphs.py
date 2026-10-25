"""A command's help re-wraps by paragraph, and an option prints its default once (#751).

Typer keeps a docstring's line breaks after the first paragraph, and Rich then
wraps *inside* each source line, so a narrow terminal reads "…Every table" /
"the seed" / "tree writes…". :func:`confiture.cli.help_text.unwrap` joins the
lines of a sentence before Typer sees them, and leaves alone what is laid out
on purpose: headings, list items, examples, a deeper indent, a ``\\b`` block.
"""

import re

import pytest
from typer.main import get_command
from typer.testing import CliRunner

from confiture.cli.help_text import unwrap
from confiture.cli.main import app
from tests._helpers import strip_ansi


def _commands() -> dict[str, object]:
    found: dict[str, object] = {}

    def walk(cmd: object, prefix: str) -> None:
        for name, sub in sorted((getattr(cmd, "commands", None) or {}).items()):
            path = f"{prefix} {name}".strip()
            found[path] = sub
            walk(sub, path)

    walk(get_command(app), "")
    return found


class TestUnwrap:
    def test_a_sentence_broken_across_lines_is_one_line(self):
        assert unwrap("Summary.\n\nOne sentence\nbroken here\nand here.") == (
            "Summary.\n\nOne sentence broken here and here."
        )

    def test_indented_prose_is_joined_at_its_indent(self):
        assert unwrap("S.\n\nPROCESS:\n  Connects to it,\n  then reads.") == (
            "S.\n\nPROCESS:\n  Connects to it, then reads."
        )

    @pytest.mark.parametrize(
        "paragraph",
        [
            "EXIT CODES:\n  0 - none\n  1 - drift",
            "  - first item\n  - second item",
            "  • first\n  • second",
            "  confiture build\n    ↳ Build it",
            "  confiture a \\\n  --flag",
            "  CORE: --env\n    Essential options",
            "Examples:\n  confiture x\n  confiture y",
            "  ✓ Parses it\n  ✓ Validates it",
            "  📖 Guide: a.md\n  📖 Examples: b.md",
            "  $ confiture x\n  ✓ Converted",
            "  Input: a.sql\n  Output: b.sql",
            "  users.sql    ✓ Converted\n  posts.sql    ✓ Converted",
        ],
    )
    def test_a_laid_out_paragraph_is_kept(self, paragraph: str):
        # A closing paragraph at column 0, so the docstring dedent removes nothing.
        text = f"S.\n\n{paragraph}\n\nEnd."
        assert unwrap(text) == text

    def test_a_continuation_under_a_marker_joins_its_item(self):
        text = "S.\n\n  - first item\n    goes on\n  - second\n\nEnd."
        assert unwrap(text) == "S.\n\n  - first item goes on\n  - second\n\nEnd."

    def test_a_b_paragraph_is_kept(self):
        text = "S.\n\n\b\nkeep\nthese lines"
        assert unwrap(text) == text

    def test_what_follows_a_form_feed_is_untouched(self):
        assert unwrap("S.\n\nA\nB.\n\f\nx\ny") == "S.\n\nA B.\n\f\nx\ny"


def test_every_command_help_is_unwrapped():
    """The tree Typer builds already holds the unwrapped text: one hook, every command."""
    unwrapped = {
        path: cmd.help for path, cmd in _commands().items() if cmd.help != unwrap(cmd.help or "")
    }
    assert not {p for p, h in unwrapped.items() if h}


def test_seed_drift_help_rewraps_at_a_narrow_terminal():
    result = CliRunner().invoke(
        app, ["seed", "drift", "--help"], env={"COLUMNS": "70", "TERMINAL_WIDTH": "70"}
    )
    text = strip_ansi(result.output)
    assert "\n │" not in text.split("Options")[0]  # the description is above the panel
    lines = [line.strip() for line in text.split("Options")[0].splitlines()]
    # The issue's symptom: a line of two words, cut where the source line ended.
    assert "the seed" not in lines
    assert "rows only" not in lines


_DEFAULT_IN_HELP = re.compile(r"\(default:")


def test_no_option_prints_its_default_twice():
    """Typer prints ``[default: x]`` beside a shown default; the help must not say it again."""
    doubled = [
        f"{path} {'/'.join(param.opts)}"
        for path, cmd in _commands().items()
        for param in getattr(cmd, "params", ())
        if getattr(param, "help", None)
        and _DEFAULT_IN_HELP.search(param.help)
        and getattr(param, "show_default", None) is not False
        and param.default not in (None, False, ())
        and not getattr(param, "is_flag", False)
    ]
    assert doubled == []
