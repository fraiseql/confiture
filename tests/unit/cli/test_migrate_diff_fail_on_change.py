"""``migrate diff --fail-on-change``: the comparison as a gate (#811).

``migrate diff`` exits 0 whatever it finds, so a release gate had to parse
``--format json``. With ``--fail-on-change`` a change is the gate's answer, ``FINDINGS``
(exit 1), the convention ``drift`` and ``seed drift`` already follow. Not
``--check``: a boolean ``--check`` is a retired spelling of "do not act"
(``test_dry_run_is_one_flag``), and ``drift --fail-on-warning`` is the idiom.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.error_codes import FINDINGS, SUCCESS

runner = CliRunner()
TABLE = "CREATE TABLE tb_line (id bigint PRIMARY KEY);\n"


@pytest.fixture
def sides(tmp_path: Path) -> tuple[Path, Path]:
    old, new = tmp_path / "old.sql", tmp_path / "new.sql"
    old.write_text(TABLE)
    new.write_text(TABLE)
    return old, new


def _diff(old: Path, new: Path, *extra: str):
    return runner.invoke(app, ["migrate", "diff", "--from", str(old), "--to", str(new), *extra])


def test_no_change_passes(sides: tuple[Path, Path]) -> None:
    assert _diff(*sides, "--fail-on-change").exit_code == SUCCESS


def test_a_change_fails_the_gate_and_is_still_reported(sides: tuple[Path, Path]) -> None:
    old, new = sides
    new.write_text(TABLE + "CREATE TABLE tb_trunk (id bigint);\n")
    result = _diff(old, new, "--fail-on-change", "--format", "json")
    assert result.exit_code == FINDINGS, result.output
    assert json.loads(result.stdout)["has_changes"] is True


def test_without_the_flag_a_change_exits_zero(sides: tuple[Path, Path]) -> None:
    old, new = sides
    new.write_text(TABLE + "CREATE TABLE tb_trunk (id bigint);\n")
    assert _diff(old, new).exit_code == SUCCESS
