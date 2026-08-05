"""Composition for the git- and database-backed ``migrate validate`` checks (#187).

Split from ``test_validate_flag_composition.py`` because these need doubles: a
git working tree for the accompaniment group, and patched connection factories
for the live checks. The static matrix over there stays dependency-free.

Two defects are pinned here beyond plain composition:

* **The git group short-circuits in JSON mode.** Text mode aggregates
  ``drift_passed`` / ``accompaniment_passed`` / ``grant_passed`` and returns
  once; JSON mode raised ``typer.Exit(1)`` on the first failure, so a failing
  drift check meant accompaniment never ran. The one block that looked like a
  model for composition did not compose in the mode machine consumers use.
* **Each DB-backed handler opened its own connection.** Five of them did, so
  ``--check-signatures --check-live-drift`` connected twice — and over ``--ssh``
  spun up two tunnel subprocesses.
"""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Git-backed checks
# ---------------------------------------------------------------------------


@pytest.fixture
def git_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A committed git repo holding a minimal confiture project."""
    repo = tmp_path / "repo"
    (repo / "db" / "schema").mkdir(parents=True)
    (repo / "db" / "migrations").mkdir(parents=True)
    (repo / "db" / "environments").mkdir(parents=True)
    (repo / "db" / "environments" / "local.yaml").write_text(
        "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/schema\n"
    )
    (repo / "confiture.yaml").write_text(
        textwrap.dedent(
            """\
            name: local
            database_url: postgresql://localhost/test
            include_dirs:
              - path: db/schema
            """
        )
    )
    for cmd in (
        ["git", "init"],
        ["git", "config", "user.email", "t@t.com"],
        ["git", "config", "user.name", "T"],
        ["git", "add", "."],
        ["git", "commit", "-m", "init"],
    ):
        subprocess.run(cmd, cwd=repo, check=True, capture_output=True)
    monkeypatch.chdir(repo)
    return repo


@pytest.fixture
def git_doubles(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch the three git sub-checks; each records that it ran.

    Patched on ``confiture.cli.git_validation`` because ``migrate validate``
    imports them lazily from there.
    """
    state: dict[str, Any] = {"ran": [], "drift_passes": True, "accompaniment_passes": True}

    def fake_flags() -> object:
        return object()

    def fake_drift(**_: Any) -> dict[str, Any]:
        state["ran"].append("drift")
        return {"passed": state["drift_passes"], "changes": []}

    def fake_accompaniment(**_: Any) -> dict[str, Any]:
        state["ran"].append("accompaniment")
        return {"is_valid": state["accompaniment_passes"], "violations": []}

    def fake_grant(**_: Any) -> dict[str, Any]:
        state["ran"].append("grant")
        return {"is_valid": True, "violations": []}

    monkeypatch.setattr("confiture.cli.git_validation.validate_git_flags_in_repo", fake_flags)
    monkeypatch.setattr("confiture.cli.git_validation.validate_git_drift", fake_drift)
    monkeypatch.setattr(
        "confiture.cli.git_validation.validate_migration_accompaniment", fake_accompaniment
    )
    monkeypatch.setattr("confiture.cli.git_validation.validate_grant_accompaniment", fake_grant)
    return state


def _invoke(*flags: str) -> Any:
    return runner.invoke(app, ["migrate", "validate", "-c", "confiture.yaml", *flags])


def test_json_mode_runs_every_git_subcheck_despite_an_early_failure(
    git_project: Path,  # noqa: ARG001
    git_doubles: dict[str, Any],
) -> None:
    """A failing drift check must not stop accompaniment and grant from running."""
    git_doubles["drift_passes"] = False

    result = _invoke(
        "--check-drift",
        "--require-migration",
        "--require-grant-migration",
        "--format",
        "json",
    )

    assert git_doubles["ran"] == ["drift", "accompaniment", "grant"]
    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"


def test_text_mode_runs_every_git_subcheck_despite_an_early_failure(
    git_project: Path,  # noqa: ARG001
    git_doubles: dict[str, Any],
) -> None:
    """Text mode already aggregated; pin it so the JSON fix keeps it that way."""
    git_doubles["drift_passes"] = False

    result = _invoke("--check-drift", "--require-migration", "--require-grant-migration")

    assert git_doubles["ran"] == ["drift", "accompaniment", "grant"]
    assert result.exit_code == 1, result.output


def test_git_check_composes_with_a_static_check(
    git_project: Path,  # noqa: ARG001
    git_doubles: dict[str, Any],
) -> None:
    """``--check-drift --check-imports`` runs both, not whichever comes first."""
    result = _invoke("--check-drift", "--check-imports")

    assert git_doubles["ran"] == ["drift"]
    assert "passed import check" in result.output
    assert result.exit_code == 0, result.output


def test_single_git_check_json_envelope_is_unchanged(
    git_project: Path,  # noqa: ARG001
    git_doubles: dict[str, Any],  # noqa: ARG001
) -> None:
    """The 0.39.0 group envelope survives verbatim for a lone git flag."""
    result = _invoke("--check-drift", "--format", "json")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload == {"status": "passed", "checks": ["drift"]}


# ---------------------------------------------------------------------------
# Database-backed checks share one connection
# ---------------------------------------------------------------------------


def _conn_cm() -> MagicMock:
    """A context-manager double yielding a fake connection."""
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=MagicMock())
    cm.__exit__ = MagicMock(return_value=False)
    return cm


def test_db_backed_checks_open_one_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--check-signatures --check-live-drift`` must connect once, not twice.

    Every place a live connection can be opened is counted, so the assertion
    holds whether the connection comes from a handler or from the shared
    context.
    """
    config = tmp_path / "confiture.yaml"
    config.write_text("name: test\ndatabase_url: postgresql://localhost/test\n")
    schema = tmp_path / "schema.sql"
    schema.write_text("-- no functions\n")

    opened: list[str] = []

    def counting(label: str) -> Any:
        def _factory(*_a: Any, **_k: Any) -> MagicMock:
            opened.append(label)
            return _conn_cm()

        return _factory

    def counting_raw(label: str) -> Any:
        def _factory(*_a: Any, **_k: Any) -> MagicMock:
            opened.append(label)
            return MagicMock()

        return _factory

    monkeypatch.setattr(
        "confiture.core.validation.context.open_connection", counting("context"), raising=False
    )
    monkeypatch.setattr(
        "confiture.core.validation.signature_drift.open_connection", counting("signature_drift")
    )
    monkeypatch.setattr(
        "confiture.core.validation.live_drift.create_connection", counting_raw("live_drift")
    )
    monkeypatch.setattr(
        "confiture.core.validation.live_drift.SchemaDriftDetector",
        MagicMock(
            return_value=MagicMock(
                compare_with_schema_file=MagicMock(
                    return_value=MagicMock(has_critical_drift=False, to_dict=lambda: {})
                )
            )
        ),
    )
    monkeypatch.setattr(
        "confiture.core.live_function_catalog.FunctionIntrospector",
        MagicMock(
            return_value=MagicMock(introspect=MagicMock(return_value=MagicMock(functions=[])))
        ),
    )

    result = runner.invoke(
        app,
        [
            "migrate",
            "validate",
            "--check-signatures",
            "--check-live-drift",
            "--config",
            str(config),
            "--schema",
            str(schema),
        ],
    )

    assert result.exit_code == 0, result.output
    assert len(opened) == 1, f"opened {len(opened)} connections: {opened}"


def test_emit_remediation_fires_exactly_once_when_composed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--emit-remediation`` is a file-writing side effect; composition must not
    run it twice, and must not skip it because another check ran first."""
    (tmp_path / "db" / "migrations").mkdir(parents=True)
    ddl = tmp_path / "db" / "schema"
    ddl.mkdir(parents=True)
    (ddl / "10_fn.sql").write_text(
        "CREATE FUNCTION public.f() RETURNS int AS $$ SELECT 1 $$ LANGUAGE sql SECURITY DEFINER;\n"
    )
    config = tmp_path / "confiture.yaml"
    config.write_text(
        textwrap.dedent(
            """\
            name: test
            database_url: postgresql://localhost/test
            include_dirs:
              - path: db/schema
            security_lint:
              enabled: true
            """
        )
    )
    monkeypatch.chdir(tmp_path)

    calls: list[Path] = []
    real_emit = __import__(
        "confiture.core.validation.security_definer", fromlist=["emit_remediation"]
    ).emit_remediation

    def spy(report: Any, output_path: Path) -> int:
        calls.append(output_path)
        return real_emit(report, output_path)

    monkeypatch.setattr("confiture.core.validation.security_definer.emit_remediation", spy)

    out = tmp_path / "fix.sql"
    result = runner.invoke(
        app,
        [
            "migrate",
            "validate",
            "--check-security-definer",
            "--check-imports",
            "-c",
            str(config),
            "--emit-remediation",
            str(out),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "passed import check" in result.output
    assert len(calls) == 1, f"emit_remediation ran {len(calls)} times"
    assert out.exists()
