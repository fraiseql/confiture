"""Every declared option is read (ENG-07, D3).

Wired: ``migrate up --batched/--batch-size/--batch-sleep`` (the session hands
the ``BatchConfig`` to each migration), ``--verbose`` (debug logging),
``bootstrap --no-check`` (refuses to do nothing), ``seed apply --copy-format
--copy-threshold`` (the INSERT→COPY converter). Deleted: ``seed apply
--benchmark`` and ``seed validate --mode``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from tests.unit._doubles import session_double
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.large_tables import BatchConfig
from confiture.models.results import MigrateUpResult

runner = CliRunner()


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "db" / "migrations").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)
    return tmp_path


def _session() -> MagicMock:
    session = session_double()
    session.__enter__.return_value = session
    session.up.return_value = MigrateUpResult(
        success=True, migrations_applied=[], total_execution_time_ms=0
    )
    return session


def test_batched_reaches_the_session(project: Path) -> None:
    session = _session()
    with patch("confiture.core.migrator.MigratorSession", autospec=True, return_value=session):
        result = runner.invoke(
            app,
            [
                "migrate",
                "up",
                "--database-url",
                "postgresql://x/y",
                "--batched",
                "--batch-size",
                "500",
                "--batch-sleep",
                "0.2",
            ],
        )
    assert result.exit_code == 0, result.output
    assert session.up.call_args.kwargs["batch"] == BatchConfig(
        batch_size=500, sleep_between_batches=0.2
    )


def test_without_batched_the_session_gets_no_batch_config(project: Path) -> None:
    session = _session()
    with patch("confiture.core.migrator.MigratorSession", autospec=True, return_value=session):
        runner.invoke(app, ["migrate", "up", "--database-url", "postgresql://x/y"])
    assert session.up.call_args.kwargs["batch"] is None


def test_verbose_turns_on_debug_logging(project: Path) -> None:
    logger = logging.getLogger("confiture")
    before = logger.level
    try:
        session = _session()
        with patch("confiture.core.migrator.MigratorSession", autospec=True, return_value=session):
            result = runner.invoke(
                app, ["migrate", "up", "--database-url", "postgresql://x/y", "--verbose"]
            )
        assert result.exit_code == 0, result.output
        assert logger.level == logging.DEBUG
    finally:
        logger.setLevel(before)


def test_bootstrap_no_check_alone_is_refused(project: Path) -> None:
    (project / "cfg.yaml").write_text("name: x\ndatabase_url: postgresql://x/y\n")
    result = runner.invoke(app, ["bootstrap", "--no-check", "--config", "cfg.yaml"])
    assert result.exit_code == 5, result.output
    assert "--dry-run" in result.output  # the hint names the modes that do something


def test_seed_apply_copy_options_reach_the_applier(project: Path) -> None:
    seeds = project / "db" / "seeds"
    seeds.mkdir()
    (seeds / "001_rows.sql").write_text("INSERT INTO t (id) VALUES (1);\n")
    with (
        patch("confiture.cli.seed.SeedApplier", autospec=True) as applier_cls,
        patch("confiture.cli.helpers.create_connection", return_value=MagicMock()),
    ):
        applier_cls.return_value.apply_sequential.return_value = MagicMock(
            succeeded=1, failed=0, total=1, failed_files=[], seed_profile=None
        )
        result = runner.invoke(
            app,
            [
                "seed",
                "apply",
                "--seeds-dir",
                str(seeds),
                "--sequential",
                "--copy-format",
                "--copy-threshold",
                "100",
                "--database-url",
                "postgresql://x/y",
            ],
        )
    kwargs = applier_cls.call_args.kwargs if applier_cls.call_args else {}
    assert kwargs.get("copy_format") is True, result.output
    assert kwargs.get("copy_threshold") == 100


def test_seed_applier_converts_large_insert_files(tmp_path: Path) -> None:
    from confiture.core.seed.applier import SeedApplier

    (tmp_path / "001_big.sql").write_text(
        "INSERT INTO t (id) VALUES " + ", ".join(f"({i})" for i in range(120)) + ";\n"
    )
    (tmp_path / "002_small.sql").write_text("INSERT INTO t (id) VALUES (1), (2);\n")
    conn = MagicMock()
    with patch("confiture.core.seed.applier.InsertToCopyConverter", autospec=True) as converter_cls:
        converter_cls.return_value.convert.return_value = "COPY t (id) FROM stdin;\n1\n\\.\n"
        applier = SeedApplier(tmp_path, connection=conn, copy_format=True, copy_threshold=100)
        applier.apply_sequential()
    converted = [c.args[0] for c in converter_cls.return_value.convert.call_args_list]
    assert len(converted) == 1 and "(119)" in converted[0]


@pytest.mark.parametrize(
    "argv",
    [["seed", "apply", "--benchmark"], ["seed", "validate", "--mode", "static"]],
    ids=["apply---benchmark", "validate---mode"],
)
def test_removed_options_are_unknown(argv: list[str]) -> None:
    result = runner.invoke(app, argv)
    assert result.exit_code == 2, result.output
    assert "No such option" in result.output


def test_removed_options_are_not_in_help() -> None:
    assert "--benchmark" not in runner.invoke(app, ["seed", "apply", "--help"]).output
    assert "--mode" not in runner.invoke(app, ["seed", "validate", "--help"]).output


def test_prep_seed_table_report_honours_output(tmp_path: Path) -> None:
    from rich.console import Console

    from confiture.cli.prep_seed_formatter import output_table

    report = MagicMock(
        scanned_files=["a.sql"], violation_count=0, has_violations=False, violations=[]
    )
    target = tmp_path / "report.txt"
    output_table(report, target, Console(record=True))
    assert target.exists()
    assert "Prep-Seed Validation Report" in target.read_text()
