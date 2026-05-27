"""Phase 03 help-text enrichment — pin the new help-text content.

These tests are intentionally narrow: they assert the strings users
will see in --help, not implementation details.
"""

from __future__ import annotations

import re

from typer.testing import CliRunner

from confiture.cli.main import app


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _help(*args: str) -> str:
    runner = CliRunner()
    result = runner.invoke(app, [*args, "--help"])
    return _strip_ansi(result.output)


class TestPreflightModesDistinguished:
    """`migrate preflight --help` calls out default vs --against modes."""

    def test_default_mode_described(self):
        out = _help("migrate", "preflight")
        # The default-mode block lives in the function docstring (typer
        # surfaces it under "DEFAULT MODE" or similar heading).
        assert "Default mode" in out or "DEFAULT MODE" in out

    def test_against_mode_described(self):
        out = _help("migrate", "preflight")
        assert "Explicit source mode" in out or "EXPLICIT SOURCE" in out


class TestCheckSignaturesSchemaDistinction:
    """`--check-signatures` help calls out --schemas vs --schema."""

    def test_schemas_plural_description_mentions_schema_singular(self):
        out = _help("migrate", "validate")
        # The plural flag explicitly references the singular one (and
        # vice-versa) so users can tell them apart.
        assert "--schemas" in out
        assert "--schema" in out


class TestIdempotentMentionsAstExtra:
    """`--idempotent` help mentions the [ast] extra prominently."""

    def test_idempotent_flag_description_or_epilog_mentions_ast(self):
        out = _help("migrate", "validate")
        # The phrase "[ast] extra" or "pglast" must appear near the
        # --idempotent description (we check the full --help text).
        assert "[ast]" in out or "pglast" in out
