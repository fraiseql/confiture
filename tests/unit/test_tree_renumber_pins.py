"""Renumber never moves a file a migration reads, and ``--compact`` closes gaps in order (#538).

A migration that reads ``db/schema/x/002_a.sql`` at run time pins that path:
rewriting the migration would change its checksum, and not rewriting it breaks
every replay. Which files a migration reads is ``core/migration_reads``'s answer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from confiture.core.builder import files_under
from confiture.core.tree_renumber import TreeRenumber
from confiture.exceptions import ValidationError

HEADER = "from pathlib import Path\nfrom confiture.models.migration import Migration\n"


def _project(tmp_path: Path, *files: str) -> Path:
    root = tmp_path / "project"
    (root / "db/migrations").mkdir(parents=True)
    (root / "pyproject.toml").write_text("")
    for name in files:
        path = root / "db/schema" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"-- {name}\n")
    return root


def _migration(root: Path, module_level: str, up_body: str) -> None:
    body = "\n".join("        " + line for line in up_body.splitlines())
    (root / "db/migrations/20260101000000_m.py").write_text(
        f"{HEADER}\n{module_level}\n\nclass M(Migration):\n    def up(self) -> None:\n{body}\n"
    )


def _renumber(root: Path) -> TreeRenumber:
    return TreeRenumber(root / "db/schema", migrations_dir=root / "db/migrations")


def _tree(root: Path) -> list[str]:
    schema = root / "db/schema"
    return [p.relative_to(schema).as_posix() for p in files_under(schema)]


# ── pins ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("force", [False, True])
def test_a_file_a_migration_reads_by_literal_path_is_never_moved(
    tmp_path: Path, force: bool
) -> None:
    root = _project(tmp_path, "x/002_a.sql")
    _migration(root, "", 'self.execute(Path("db/schema/x/002_a.sql").read_text())')
    renumber = _renumber(root)
    plans = renumber.build_plans(root / "db/schema/x/002_a.sql", root / "db/schema/x/001_a.sql")

    with pytest.raises(ValidationError) as refused:
        renumber.execute(plans, force=force)

    assert refused.value.error_code == "VALID_003"
    assert "20260101000000_m.py" in str(refused.value)
    assert _tree(root) == ["x/002_a.sql"]


def test_a_path_joined_from_a_directory_constant_pins_too(tmp_path: Path) -> None:
    root = _project(tmp_path, "functions/billing/0219_attach.sql")
    _migration(
        root,
        'SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schema"\n'
        'FUNCTION_FILE = "functions/billing/0219_attach.sql"',
        "self.execute((SCHEMA_DIR / FUNCTION_FILE).read_text())",
    )
    renumber = _renumber(root)
    plans = renumber.build_plans(
        root / "db/schema/functions/billing/0219_attach.sql",
        root / "db/schema/functions/billing/0220_attach.sql",
    )

    with pytest.raises(ValidationError) as refused:
        renumber.execute(plans)

    assert refused.value.error_code == "VALID_003"
    assert _tree(root) == ["functions/billing/0219_attach.sql"]


def test_moving_a_directory_that_holds_a_pinned_file_is_refused(tmp_path: Path) -> None:
    root = _project(tmp_path, "10_fn/01_a.sql", "10_fn/02_b.sql")
    _migration(root, "", 'Path("db/schema/10_fn/02_b.sql").read_text()')
    renumber = _renumber(root)
    plans = renumber.build_plans(root / "db/schema/10_fn", root / "db/schema/20_fn")

    with pytest.raises(ValidationError):
        renumber.execute(plans, force=True)

    assert _tree(root) == ["10_fn/01_a.sql", "10_fn/02_b.sql"]


def test_a_file_no_migration_reads_moves(tmp_path: Path) -> None:
    root = _project(tmp_path, "x/002_a.sql", "x/005_b.sql")
    _migration(root, "", 'Path("db/schema/x/002_a.sql").read_text()')
    renumber = _renumber(root)

    renumber.execute(
        renumber.build_plans(root / "db/schema/x/005_b.sql", root / "db/schema/x/003_b.sql")
    )

    assert _tree(root) == ["x/002_a.sql", "x/003_b.sql"]


def test_a_read_it_cannot_resolve_refuses_unless_forced(tmp_path: Path) -> None:
    root = _project(tmp_path, "x/002_a.sql")
    _migration(root, "", "for f in self.files():\n    Path(f).read_text()")
    renumber = _renumber(root)
    plans = renumber.build_plans(root / "db/schema/x/002_a.sql", root / "db/schema/x/001_a.sql")

    with pytest.raises(ValidationError) as refused:
        renumber.execute(plans)
    assert refused.value.error_code == "VALID_004"
    assert _tree(root) == ["x/002_a.sql"]

    result = renumber.execute(plans, force=True)
    assert [read.migration.name for read in result.unresolved_reads] == ["20260101000000_m.py"]
    assert _tree(root) == ["x/001_a.sql"]


def test_without_a_migrations_directory_nothing_is_pinned(tmp_path: Path) -> None:
    root = _project(tmp_path, "x/002_a.sql")
    renumber = TreeRenumber(root / "db/schema", migrations_dir=root / "db/nowhere")

    renumber.execute(
        renumber.build_plans(root / "db/schema/x/002_a.sql", root / "db/schema/x/001_a.sql")
    )

    assert _tree(root) == ["x/001_a.sql"]


# ── compact ──────────────────────────────────────────────────────────────────


def test_compact_closes_the_gaps_files_and_directories_alike(tmp_path: Path) -> None:
    root = _project(tmp_path, "t/01_a.sql", "t/02_b.sql", "t/05_c.sql", "t/07_d/01_x.sql")
    renumber = _renumber(root)
    before = [p.read_text() for p in files_under(root / "db/schema")]

    renumber.execute(renumber.build_compact_plans(root / "db/schema/t"))

    assert _tree(root) == ["t/01_a.sql", "t/02_b.sql", "t/03_c.sql", "t/04_d/01_x.sql"]
    assert [p.read_text() for p in files_under(root / "db/schema")] == before


def test_compact_keeps_the_directory_s_width_and_start(tmp_path: Path) -> None:
    root = _project(tmp_path, "t/0010_a.sql", "t/0030_b.sql", "t/0070_c.sql")
    renumber = _renumber(root)

    renumber.execute(renumber.build_compact_plans(root / "db/schema/t"))

    assert _tree(root) == ["t/0001_a.sql", "t/0002_b.sql", "t/0003_c.sql"]


def test_compact_without_gaps_is_a_no_op(tmp_path: Path) -> None:
    root = _project(tmp_path, "t/01_a.sql", "t/02_b.sql", "t/03_c/01_x.sql")

    assert _renumber(root).build_compact_plans(root / "db/schema/t") == []


def test_compact_that_would_reorder_the_build_is_refused(tmp_path: Path) -> None:
    """``05_c`` → ``02_c`` would sort before the unnumbered sibling ``02x/``."""
    root = _project(tmp_path, "t/01_a.sql", "t/02x/y.sql", "t/05_c.sql")

    with pytest.raises(ValidationError) as refused:
        _renumber(root).build_compact_plans(root / "db/schema/t")

    assert refused.value.error_code == "VALID_005"
    assert _tree(root) == ["t/01_a.sql", "t/02x/y.sql", "t/05_c.sql"]


def test_compact_does_not_move_a_pinned_file(tmp_path: Path) -> None:
    root = _project(tmp_path, "t/01_a.sql", "t/05_c.sql")
    _migration(root, "", 'Path("db/schema/t/05_c.sql").read_text()')
    renumber = _renumber(root)

    with pytest.raises(ValidationError) as refused:
        renumber.execute(renumber.build_compact_plans(root / "db/schema/t"))

    assert refused.value.error_code == "VALID_003"
    assert _tree(root) == ["t/01_a.sql", "t/05_c.sql"]


def test_a_migration_archived_by_a_squash_releases_its_pin(tmp_path: Path) -> None:
    """``migrate squash`` moves the migration to ``archive/``: its reads pin nothing (#539)."""
    root = _project(tmp_path, "x/002_a.sql")
    _migration(root, "", 'self.execute(Path("db/schema/x/002_a.sql").read_text())')
    archive = root / "db/migrations/archive"
    archive.mkdir()
    (root / "db/migrations/20260101000000_m.py").rename(archive / "20260101000000_m.py")
    renumber = _renumber(root)

    renumber.execute(
        renumber.build_plans(root / "db/schema/x/002_a.sql", root / "db/schema/x/001_a.sql")
    )

    assert _tree(root) == ["x/001_a.sql"]
