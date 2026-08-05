"""``migrate up --auto-detect-baseline`` refuses a ledger it merely cannot see (#188).

Auto-baseline exists to bootstrap a database that has never been migrated: no
ledger, so create one and mark the migrations already present in the schema. It
decides that from ``tracking_table_exists()``, which since 0.41.0 resolves a
bare name through ``search_path`` instead of matching any schema.

That is the correct answer to "can this session read the ledger?" and the wrong
trigger for auto-baseline. A ledger sitting in a schema off ``search_path`` now
reads absent, and without this guard the command would build a *second* ledger
and mark every migration applied in it — on a production database, an incident.
So absence is no longer sufficient: the name must be unused everywhere.

These are unit tests on purpose. The DB-backed twin lives in
``tests/integration/test_ledger_probe.py``, and this repo's CI cannot reach a
database — an integration-only guard over a data-destroying path would gate
nothing on a pull request.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real project tree — Typer resolves db/migrations from the cwd."""
    (tmp_path / "db" / "migrations").mkdir(parents=True)
    (tmp_path / "db" / "migrations" / "20260101120000_t.up.sql").write_text(
        "CREATE TABLE IF NOT EXISTS public.foo (id int);\n"
    )
    (tmp_path / "db" / "schema_history").mkdir(parents=True)
    (tmp_path / "db" / "schema_history" / "20260101120000.sql").write_text(
        "CREATE TABLE public.foo (id int);\n"
    )
    (tmp_path / "confiture.yaml").write_text(
        textwrap.dedent(
            """\
            name: test
            database_url: postgresql://localhost/test
            include_dirs:
              - path: db/schema
            """
        )
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def doubles(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stand-ins for the connection, the migrator and the schema-blind sweep.

    ``elsewhere`` is what the sweep reports. ``calls`` records the two methods
    that would rewrite the ledger, so a refusal can be shown to have refused
    rather than merely printed something.
    """
    state: dict[str, Any] = {"elsewhere": [], "calls": [], "swept": []}

    migrator = MagicMock()
    migrator.tracking_table_exists.return_value = False
    migrator.initialize.side_effect = lambda *a, **k: state["calls"].append("initialize")
    migrator.baseline_through.side_effect = lambda *a, **k: state["calls"].append(
        "baseline_through"
    )
    migrator.get_applied_versions.return_value = []
    state["migrator"] = migrator

    monkeypatch.setattr("confiture.core.connection.create_connection", lambda *a, **k: MagicMock())
    monkeypatch.setattr("confiture.core.migrator.Migrator", lambda *a, **k: migrator)

    def fake_sweep(_conn: Any, table: str) -> list[str]:
        state["swept"].append(table)
        return list(state["elsewhere"])

    monkeypatch.setattr("confiture.core.ledger.find_ledger_relations", fake_sweep)
    return state


def _invoke(*flags: str) -> Any:
    # --no-lock because the advisory-lock key is derived by hashing the real
    # connection, which a MagicMock cannot satisfy. The guard runs well before
    # the lock is taken, so this changes nothing under test.
    return runner.invoke(app, ["migrate", "up", "-c", "confiture.yaml", "--no-lock", *flags])


def test_refuses_when_the_name_exists_in_another_schema(
    project: Path,  # noqa: ARG001 — fixture chdirs
    doubles: dict[str, Any],
) -> None:
    doubles["elsewhere"] = ["staging.tb_confiture"]

    result = _invoke("--auto-detect-baseline")

    assert result.exit_code == 5, result.output
    # The sweep really ran — an empty list here would mean the guard was
    # skipped and this test passed for the wrong reason.
    assert doubles["swept"] == ["tb_confiture"]
    # Both halves of the message: what was searched, and what was found.
    assert "staging.tb_confiture" in result.output
    assert "tb_confiture" in result.output
    # And nothing was written.
    assert doubles["calls"] == [], f"auto-baseline still ran: {doubles['calls']}"


def test_names_every_schema_it_found(
    project: Path,  # noqa: ARG001
    doubles: dict[str, Any],
) -> None:
    """Two copies is the case where guessing costs the most; list them all."""
    doubles["elsewhere"] = ["archive.tb_confiture", "staging.tb_confiture"]

    result = _invoke("--auto-detect-baseline")

    assert result.exit_code == 5, result.output
    assert "archive.tb_confiture" in result.output
    assert "staging.tb_confiture" in result.output


def test_a_genuinely_unused_name_still_auto_baselines(
    project: Path,  # noqa: ARG001
    doubles: dict[str, Any],
) -> None:
    """The guard must not become a blanket refusal.

    Nothing anywhere holds the name, which is the state auto-baseline was
    built for, so it proceeds and marks the snapshot's migrations applied.
    """
    doubles["elsewhere"] = []

    result = _invoke("--auto-detect-baseline")

    assert doubles["swept"] == ["tb_confiture"]
    assert "initialize" in doubles["calls"], result.output
    assert result.exit_code == 0, result.output


def test_without_the_flag_a_ledger_elsewhere_is_not_the_command_s_business(
    project: Path,  # noqa: ARG001
    doubles: dict[str, Any],
) -> None:
    """A plain `migrate up` never self-baselines, so it never needs the sweep."""
    doubles["elsewhere"] = ["staging.tb_confiture"]

    result = _invoke()

    assert doubles["swept"] == []
    assert result.exit_code == 0, result.output
