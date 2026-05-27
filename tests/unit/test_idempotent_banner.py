"""Phase 03 C2: pre-scan banner stating the active idempotency backend.

Text mode prints a one-line status banner. JSON mode reports the
backend via ``payload["meta"]["backend"]`` so pipe-able output stays
clean.
"""

from __future__ import annotations

import json
import re
from unittest.mock import patch

from typer.testing import CliRunner

from confiture.cli.main import app


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _migrations_dir(tmp_path):
    migs = tmp_path / "db" / "migrations"
    migs.mkdir(parents=True)
    (migs / "20260527000000_init.up.sql").write_text(
        "CREATE TABLE IF NOT EXISTS t (id INT);\n"
    )
    return migs


class TestBannerInTextMode:
    """Text mode prints a backend banner to stdout."""

    def test_ast_banner_when_pglast_available(self, tmp_path):
        migs = _migrations_dir(tmp_path)
        runner = CliRunner()
        with patch(
            "confiture.core.idempotency.patterns.is_pglast_available",
            return_value=True,
        ):
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "validate",
                    "--idempotent",
                    "--migrations-dir",
                    str(migs),
                ],
            )
        out = _strip_ansi(result.output)
        assert "AST backend" in out
        assert "pglast" in out

    def test_regex_banner_when_pglast_missing(self, tmp_path):
        migs = _migrations_dir(tmp_path)
        runner = CliRunner()
        with patch(
            "confiture.core.idempotency.patterns.is_pglast_available",
            return_value=False,
        ):
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "validate",
                    "--idempotent",
                    "--migrations-dir",
                    str(migs),
                ],
            )
        out = _strip_ansi(result.output)
        assert "Regex fallback" in out
        # The install hint must appear so the user knows what to do.
        assert "fraiseql-confiture[ast]" in out


class TestBannerInJsonMode:
    """JSON mode pushes the backend into payload["meta"]["backend"], NEVER to stdout."""

    def test_json_mode_no_banner_in_stdout(self, tmp_path):
        migs = _migrations_dir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--migrations-dir",
                str(migs),
                "--format",
                "json",
            ],
        )
        # Stdout must be parseable JSON — any banner text would break this.
        payload = json.loads(result.stdout)
        assert "meta" in payload
        assert payload["meta"]["backend"] in {"ast", "regex"}

    def test_json_mode_reports_ast_when_available(self, tmp_path):
        migs = _migrations_dir(tmp_path)
        runner = CliRunner()
        with patch(
            "confiture.core.idempotency.patterns.is_pglast_available",
            return_value=True,
        ):
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "validate",
                    "--idempotent",
                    "--migrations-dir",
                    str(migs),
                    "--format",
                    "json",
                ],
            )
        payload = json.loads(result.stdout)
        assert payload["meta"]["backend"] == "ast"

    def test_json_mode_reports_regex_when_unavailable(self, tmp_path):
        migs = _migrations_dir(tmp_path)
        runner = CliRunner()
        with patch(
            "confiture.core.idempotency.patterns.is_pglast_available",
            return_value=False,
        ):
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "validate",
                    "--idempotent",
                    "--migrations-dir",
                    str(migs),
                    "--format",
                    "json",
                ],
            )
        payload = json.loads(result.stdout)
        assert payload["meta"]["backend"] == "regex"
