"""A git ref is read as ``confiture build`` reads the working tree (#686).

Each shape below is a repository whose ``HEAD`` is a clean checkout: the files the
build selects from the working tree, in build order and with their text, are what
the ref read must give, file by file.
"""

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from confiture.core.builder import SchemaBuilder
from confiture.core.git import GitRepository
from confiture.core.git_schema import GitSchemaBuilder
from confiture.core.linting.inventory import label_for

_URL = 'database_url: "postgresql://localhost/test"\n'


@dataclass(frozen=True)
class Shape:
    """A repository: where the project sits in it, its env file, and its files."""

    env: str
    files: dict[str, str | bytes]
    project: str = "."
    root_name: str = "repo"
    extra: dict[str, str] = field(default_factory=dict)


SHAPES: dict[str, Shape] = {
    "hex": Shape(
        "include_dirs:\n  - db/schema\nbuild:\n  sort_mode: hex\n",
        {"db/schema/9_a.sql": "CREATE TABLE a (id int);\n", "db/schema/10_b.sql": "-- b\n"},
    ),
    "shared_order_merge": Shape(
        "include_dirs:\n  - path: db/b\n    order: 0\n  - path: db/a\n    order: 0\n",
        {"db/a/2_x.sql": "-- a/2_x\n", "db/b/1_y.sql": "-- b/1_y\n"},
    ),
    "recursive_false": Shape(
        "include_dirs:\n  - path: db/schema\n    recursive: false\n",
        {"db/schema/a.sql": "-- a\n", "db/schema/sub/b.sql": "-- sub/b\n"},
    ),
    "include_pattern": Shape(
        "include_dirs:\n  - path: db/schema\n    include: ['**/*.sql', '**/*.ddl']\n",
        {"db/schema/a.sql": "-- a\n", "db/schema/b.ddl": "-- b.ddl\n"},
    ),
    "exclude_pattern": Shape(
        "include_dirs:\n  - path: db/schema\n    exclude: ['legacy/**']\n",
        {"db/schema/a.sql": "-- a\n", "db/schema/legacy/z.sql": "-- legacy z\n"},
    ),
    "exclude_dirs": Shape(
        "include_dirs:\n  - db/schema\nexclude_dirs:\n  - db/schema/legacy\n",
        {"db/schema/a.sql": "-- a\n", "db/schema/legacy/z.sql": "-- legacy z\n"},
    ),
    "overlapping_entries": Shape(
        "include_dirs:\n  - db/schema\n  - db/schema/10_tables\n",
        {"db/schema/00_a.sql": "-- a\n", "db/schema/10_tables/t.sql": "-- t\n"},
    ),
    "subdirectory_project": Shape(
        "include_dirs:\n  - db/schema\n",
        {"backend/db/schema/a.sql": "-- a\n"},
        project="backend",
    ),
    "sibling_include_dir": Shape(
        "include_dirs:\n  - db/schema\n  - path: ../shared\n    order: 10\n",
        {"backend/db/schema/a.sql": "-- a\n", "shared/s.sql": "-- shared s\n"},
        project="backend",
    ),
    "non_ascii_name": Shape(
        "include_dirs:\n  - db/schema\n",
        {"db/schema/01_a.sql": "-- a\n", "db/schema/10_é.sql": "-- é\n"},
    ),
    "seed_anchor": Shape(
        "include_dirs:\n  - schema\n  - path: data\n    order: 10\n",
        {"schema/a.sql": "-- a\n", "data/seed_users.sql": "-- seed users\n"},
        root_name="seeds",
    ),
    "distinct_orders": Shape(
        "include_dirs:\n  - path: db/indexes\n    order: 900\n  - path: db/tables\n    order: 0\n",
        {"db/tables/t.sql": "CREATE TABLE t (id int);\n", "db/indexes/i.sql": "-- i\n"},
    ),
    "seed_dir": Shape(
        "include_dirs:\n  - db/schema\n  - path: db/seeds\n    order: 10\n",
        {"db/schema/a.sql": "-- a\n", "db/seeds/s.sql": "-- seed\n"},
    ),
    "export_ignore": Shape(
        "include_dirs:\n  - db/schema\n",
        {"db/schema/a.sql": "-- a\n", "db/schema/b.sql": "-- b\n"},
        extra={".gitattributes": "db/schema/b.sql export-ignore\n"},
    ),
    "crlf": Shape(
        "include_dirs:\n  - db/schema\n",
        {"db/schema/a.sql": b"-- a\r\nCREATE TABLE a (id int);\r\n"},
        extra={".gitattributes": "*.sql -text\n"},
    ),
}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _init(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t.com")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "core.autocrlf", "false")


def _commit(root: Path) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "commit")


def _write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def make_repo(tmp_path: Path, shape: Shape) -> Path:
    """Commit *shape* in a new repository; return its project directory."""
    root = tmp_path / shape.root_name
    _init(root)
    project = root / shape.project
    _write(project / "db" / "environments" / "local.yaml", _URL + shape.env)
    for name, content in {**shape.files, **shape.extra}.items():
        _write(root / name, content)
    _commit(root)
    return project


def _ref_vs_build(project: Path) -> tuple[list[tuple], list[tuple]]:
    """The ref read at ``HEAD`` and the build's selection, as ``(file, label, text)`` triples."""
    at_ref = GitSchemaBuilder("local", project).segments_at_ref("HEAD")
    files = SchemaBuilder("local", project).find_sql_files()
    return (
        [(segment.file, segment.label, segment.text) for segment in at_ref],
        [(file, label_for(file, project), file.read_text()) for file in files],
    )


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_ref_read_is_the_build_selection(tmp_path: Path, name: str) -> None:
    at_ref, built = _ref_vs_build(make_repo(tmp_path, SHAPES[name]))
    assert at_ref == built


def test_staged_read_is_the_index(tmp_path: Path) -> None:
    project = make_repo(tmp_path, SHAPES["exclude_pattern"])
    _write(project / "db/schema/a.sql", "-- staged A\n")
    _git(project, "add", "db/schema/a.sql")
    _write(project / "db/schema/a.sql", "-- unstaged B\n")

    tree = GitRepository(project).staged_tree_oid()
    at_index = GitSchemaBuilder("local", project).build_schema_at_ref(tree)

    assert "-- staged A" in at_index
    assert "-- unstaged B" not in at_index
