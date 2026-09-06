"""``typer.Exit`` crosses every command boundary intact (ENG-08).

``typer.Exit`` is a ``RuntimeError``. A command that validates its inputs with
``raise typer.Exit(n)`` *inside* the ``try`` whose ``except Exception`` is its
error boundary swallows its own exit: the boundary prints ``Error: n`` (the
exit code, as a message), re-classifies it and exits with a different code —
or, in JSON mode, emits a result payload whose ``error`` is the string ``"1"``.
Exit codes follow ``docs/reference/exit-codes.md``: 5 for invalid input.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "db" / "migrations").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.parametrize(
    ("argv", "stdin", "expected"),
    [
        (["migrate", "status", "--format", "xml"], None, 5),
        (["init"], "n\n", 0),
        (["migrate", "diff", "old.sql", "new.sql", "--format", "xml"], None, 5),
        (["migrate", "diff", "missing_old.sql", "missing_new.sql"], None, 5),
    ],
    ids=["status-bad-format", "init-declined", "diff-bad-format", "diff-missing-input"],
)
def test_exit_code_survives_the_boundary(
    project: Path, argv: list[str], stdin: str | None, expected: int
) -> None:
    (project / "old.sql").write_text("CREATE TABLE a (id int);\n")
    (project / "new.sql").write_text("CREATE TABLE a (id int, b int);\n")

    result = runner.invoke(app, argv, input=stdin)

    assert result.exit_code == expected, result.output
    for bogus in ("Error: 0", "Error: 1", "Error: 2"):
        assert bogus not in result.output, result.output


def test_json_mode_emits_no_bogus_payload(project: Path) -> None:
    result = runner.invoke(
        app, ["migrate", "diff", "missing_old.sql", "missing_new.sql", "--format", "json"]
    )

    assert result.exit_code == 5, result.output
    payload = json.loads(result.stdout)
    # The error envelope, not a result row whose error is the string "1".
    assert payload["error"]["code"] == "VALID_001", payload
    assert "missing_old.sql" in payload["error"]["message"], payload
