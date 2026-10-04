"""``--format csv`` on stdout is the CSV, byte for byte (#602).

It was printed through a Rich console: ``[legacy]`` read as a markup tag and
vanished, and a row longer than the console wrapped onto a second line when
stdout was a pipe. A CSV's bytes do not depend on where they are written.
"""

import csv
import io
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.formatters.common import csv_text, print_csv, save_csv
from confiture.cli.main import app

HEADERS = ["name", "type"]
ROWS = [["[tree_001]", "int[]"], ["db/[legacy]/x.sql", "[bold]x"], ["w" * 200, "y"]]


def _written(headers: list[str], rows: list[list[str]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerows(rows)
    return buffer.getvalue()


def test_the_printed_csv_is_what_csv_writes(capsys: pytest.CaptureFixture[str]) -> None:
    print_csv(HEADERS, ROWS)
    assert capsys.readouterr().out == _written(HEADERS, ROWS)


def test_the_saved_csv_is_the_printed_one(tmp_path: Path) -> None:
    save_csv(HEADERS, ROWS, tmp_path / "out.csv")
    assert (tmp_path / "out.csv").read_bytes().decode() == csv_text(HEADERS, ROWS)


def test_migrate_status_reads_back_as_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("CONFITURE_DATABASE_URL", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    migrations = tmp_path / "db" / "migrations"
    migrations.mkdir(parents=True)
    name = "add_[legacy]_column_to_a_table_whose_name_is_long_enough_to_wrap_a_row"
    (migrations / f"20260101000000_{name}.up.sql").write_text("SELECT 1;\n")

    result = CliRunner().invoke(
        app, ["migrate", "status", "--migrations-dir", str(migrations), "--format", "csv"]
    )

    assert list(csv.reader(io.StringIO(result.stdout))) == [
        ["version", "name", "status"],
        ["20260101000000", name, "unknown"],
    ]
