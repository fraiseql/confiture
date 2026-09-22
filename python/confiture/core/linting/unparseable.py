"""The lint notice for a file pglast cannot parse.

A rule that reads DDL through pglast reports each file the parser rejects as
one ``UNPARSEABLE`` finding and reads the rest: returning no findings for such a
file would let it lint clean.

It is a *finding about a file*, not a report that a rule could not run, which is
why it is a registered rule at ``error`` (#274) and why the report
keeps one per file however many rules discovered it.
"""

from __future__ import annotations

from pathlib import Path

from confiture.core.linting.rule_registry import UNPARSEABLE_RULE_ID
from confiture.core.linting.schema_linter import LintViolation, RuleSeverity
from confiture.core.parser_info import parse_error_line

__all__ = ["UNPARSEABLE_RULE_ID", "unparseable_notice"]


def unparseable_notice(path: Path | None, text: str, exc: BaseException) -> LintViolation:
    """One finding for one file the parser refused.

    ``path`` is ``None`` for a whole-string lint (``SchemaLinter.lint(schema=...)``),
    which has no file to name — the line still indexes the string it was given.
    """
    where = "the schema" if path is None else path.name
    return LintViolation(
        rule_id=UNPARSEABLE_RULE_ID,
        rule_name="Unparseable SQL",
        severity=RuleSeverity.ERROR,
        object_type="file" if path is not None else "schema",
        object_name=where,
        message=f"pglast could not parse {where}: {exc}",
        file_path=None if path is None else str(path),
        line_number=parse_error_line(text, exc),
        suggested_fix="Fix the SQL syntax; the rules that read this file reported nothing about it.",
    )
