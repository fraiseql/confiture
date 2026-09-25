"""Help-text enrichment — pin the help-text content.

These tests are intentionally narrow: they assert the strings users
will see in --help, not implementation details.

``TestIdempotentMentionsAstExtra`` was here and is deleted rather than
re-pointed. It required ``--help`` to name the ``[ast]`` extra or pglast,
because ``--idempotent`` needed a parser the reader had to install. 0.50.0
 made pglast a dependency, so there is nothing for the help to warn
about, and the sentence it pinned had become one of the untruths
``tests/unit/docs/test_no_optional_parser.py`` now forbids. A test that
requires a warning about a condition that cannot arise is a test asking for
a false statement.
"""

from __future__ import annotations

from typer.testing import CliRunner

from confiture.cli.main import app
from tests._helpers import strip_ansi as _strip_ansi


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
