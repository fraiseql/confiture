"""``confiture lint`` prints an object's name as data, never as markup or a terminal command (#488).

A quoted identifier may hold ``[link=…]`` or an ESC. Rendered as Rich markup,
the first becomes a live hyperlink; written raw, the second is an escape
sequence the terminal obeys (a title, a hyperlink, a cleared screen).
"""

from __future__ import annotations

import io

from rich.console import Console

from confiture.cli.lint_formatter import format_table
from confiture.models.lint import LintReport, LintSeverity, Violation

_LINK = '"[bold red]PWN[/bold red] [link=https://evil.example]click[/link]"'
_ESC = '"esc\x1b]0;TITLE\x07"'


def _printed(location: str, *, file: str | None = "db/schema/t.sql") -> str:
    violation = Violation(
        rule_name="Quoted Identifier",
        severity=LintSeverity.ERROR,
        message=f"{location} needs quotes",
        location=location,
        suggested_fix=f"rename {location}",
        rule_id="naming_004",
        file=file,
        line=3,
    )
    report = LintReport(
        violations=[violation],
        schema_name="s",
        tables_checked=1,
        columns_checked=1,
        errors_count=1,
        warnings_count=0,
        info_count=0,
        execution_time_ms=1,
    )
    out = io.StringIO()
    console = Console(file=out, force_terminal=True, color_system="truecolor", width=400)
    format_table(report, console)
    return out.getvalue()


def test_a_name_holding_markup_is_printed_as_written() -> None:
    printed = _printed(_LINK)

    assert "\x1b]8;" not in printed  # no hyperlink
    assert "[link=https://evil.example]" in printed


def test_a_name_holding_markup_is_printed_as_written_without_a_file() -> None:
    printed = _printed(_LINK, file=None)

    assert "\x1b]8;" not in printed
    assert "[link=https://evil.example]" in printed


def test_an_escape_in_a_name_never_reaches_the_terminal() -> None:
    printed = _printed(_ESC)

    assert "\x1b]0;" not in printed
    assert "\\x1b]0;TITLE" in printed
