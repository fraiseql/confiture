"""The lint notice for a file pglast cannot parse (Phase 05, ANA-02).

A rule that reads DDL through pglast used to return no findings for a file the
parser rejected, so a broken file linted clean. Each rule now reports the file
once, as an ``UNPARSEABLE`` notice, and reads the rest.
"""

from __future__ import annotations

from pathlib import Path

from confiture.core.linting.schema_linter import LintViolation, RuleSeverity
from confiture.core.parser_info import parse_error_line

UNPARSEABLE_RULE_ID = "UNPARSEABLE"


def unparseable_notice(path: Path, text: str, exc: BaseException) -> LintViolation:
    return LintViolation(
        rule_id=UNPARSEABLE_RULE_ID,
        rule_name="Unparseable SQL",
        severity=RuleSeverity.INFO,
        object_type="file",
        object_name=path.name,
        message=f"pglast could not parse {path.name}: {exc}",
        file_path=str(path),
        line_number=parse_error_line(text, exc),
        suggested_fix="Fix the SQL syntax; rules cannot see past a parse error.",
    )
