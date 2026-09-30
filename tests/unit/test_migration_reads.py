"""Which files a migration reads, resolved as the runtime would (#540, #538)."""

from __future__ import annotations

from pathlib import Path

from confiture.core.migration_reads import reads, reads_under

HEADER = "from pathlib import Path\nfrom confiture.models.migration import Migration\n"


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    for directory in ("db/schema/functions", "db/migrations", "tests/fixtures"):
        (root / directory).mkdir(parents=True)
    (root / "pyproject.toml").write_text("")
    (root / "db/schema/functions/a.sql").write_text("SELECT 1;")
    (root / "db/schema/functions/b.sql").write_text("SELECT 2;")
    (root / "tests/fixtures/rows.csv").write_text("id\n1\n")
    return root


def _migration(root: Path, module_level: str, up_body: str) -> Path:
    body = "\n".join("        " + line for line in up_body.splitlines())
    path = root / "db/migrations/20260101000000_m.py"
    path.write_text(
        f"{HEADER}\n{module_level}\n\nclass M(Migration):\n    def up(self) -> None:\n{body}\n"
    )
    return path


def _under_schema(root: Path, migration: Path) -> list[tuple[int, str, bool]]:
    return [
        (r.line, r.file.relative_to(root).as_posix(), r.exists)
        for r in reads_under(reads(migration), [root / "db/schema"])
        if r.file is not None
    ]


def test_embedded_sql_reads_nothing(tmp_path: Path) -> None:
    root = _project(tmp_path)
    migration = _migration(root, 'DDL = "SELECT 1"', "self.execute(DDL)")

    assert reads(migration) == []


def test_a_schema_file_read_by_path_is_named(tmp_path: Path) -> None:
    root = _project(tmp_path)
    migration = _migration(
        root,
        "",
        'self.execute((Path(__file__).parent.parent / "schema" / "functions" / "a.sql").read_text())',
    )

    assert _under_schema(root, migration) == [(8, "db/schema/functions/a.sql", True)]


def test_a_loop_over_a_module_tuple_names_each_file(tmp_path: Path) -> None:
    root = _project(tmp_path)
    migration = _migration(
        root,
        'SCHEMA = Path(__file__).parent.parent / "schema"\n'
        'FILES = ("functions/a.sql", "functions/b.sql")',
        "for f in FILES:\n    self.execute((SCHEMA / f).read_text())",
    )

    assert _under_schema(root, migration) == [
        (10, "db/schema/functions/a.sql", True),
        (10, "db/schema/functions/b.sql", True),
    ]


def test_a_relative_path_resolves_from_the_project_root(tmp_path: Path) -> None:
    root = _project(tmp_path)
    migration = _migration(root, "", 'self.execute_file("db/schema/functions/a.sql")')

    assert _under_schema(root, migration) == [(8, "db/schema/functions/a.sql", True)]


def test_a_read_of_a_file_already_gone_is_still_named(tmp_path: Path) -> None:
    """Replay of this migration is already broken: the pin is reported, not hidden."""
    root = _project(tmp_path)
    migration = _migration(root, "", 'Path("db/schema/functions/gone.sql").read_text()')

    assert _under_schema(root, migration) == [(8, "db/schema/functions/gone.sql", False)]


def test_a_file_outside_the_directories_is_not_under_them(tmp_path: Path) -> None:
    root = _project(tmp_path)
    migration = _migration(root, "", 'Path("tests/fixtures/rows.csv").read_text()')

    (read,) = reads(migration)
    assert read.file == (root / "tests/fixtures/rows.csv").resolve()
    assert reads_under([read], [root / "db/schema"]) == []


def test_a_path_the_file_does_not_fix_is_unresolved_with_the_reason(tmp_path: Path) -> None:
    root = _project(tmp_path)
    migration = _migration(root, "", "for f in self.files():\n    Path(f).read_text()")

    (read,) = reads(migration)
    assert read.file is None
    assert read.reason is not None and "`f`" in read.reason


def test_a_migration_python_cannot_parse_is_one_unresolved_read(tmp_path: Path) -> None:
    root = _project(tmp_path)
    migration = root / "db/migrations/20260101000000_m.py"
    migration.write_text("def up(:\n")

    (read,) = reads(migration)
    assert read.file is None
    assert read.reason is not None


def test_a_sql_migration_reads_nothing(tmp_path: Path) -> None:
    root = _project(tmp_path)
    migration = root / "db/migrations/20260101000000_m.up.sql"
    migration.write_text("SELECT 1;")

    assert reads(migration) == []
