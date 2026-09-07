"""``extract_sql_from_python_source``: analyze text as the file it will be.

Staged mode and the grant check hand the extractor a blob that is not on
disk. Before 0.46.0 both wrote it to a temp file and analyzed that, so
``Path(__file__)`` resolved into the temp directory and every
migration-relative read went missing. The primitive takes the text and the
path the text belongs to.
"""

from __future__ import annotations

import ast
from pathlib import Path

from confiture.cli.idempotency import _collect_idempotency_report
from confiture.core.idempotency import IdempotencyValidator, extract_sql_from_python_source

_READS_NEXT_TO_ITSELF = """\
from pathlib import Path
from confiture.models.migration import Migration

_SCHEMA = Path(__file__).resolve().parent.parent / "schema"


class M(Migration):
    version = "20260101000050"
    name = "staged"

    def up(self) -> None:
        self.execute((_SCHEMA / "fn.sql").read_text())

    def down(self) -> None:
        pass
"""


def _project(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "project"
    (root / "db" / "schema").mkdir(parents=True)
    (root / "db" / "migrations").mkdir(parents=True)
    (root / "pyproject.toml").write_text("")
    (root / "db" / "schema" / "fn.sql").write_text("CREATE TABLE gadget (id int);")
    migration = root / "db" / "migrations" / "20260101000050_staged.py"
    return root, migration


def test_text_is_analyzed_at_the_path_it_belongs_to(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    root, migration = _project(tmp_path)
    monkeypatch.chdir(tmp_path)
    # Nothing on disk at `migration`: the text is the staged blob.

    result = extract_sql_from_python_source(
        _READS_NEXT_TO_ITSELF, path=migration, project_root=root
    )

    assert result.warnings == []
    assert [s.sql for s in result.snippets] == ["CREATE TABLE gadget (id int);"]


def test_staged_content_reads_relative_to_the_real_migration(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The CLI's staged path: the working tree differs from the index blob."""
    _root, migration = _project(tmp_path)
    migration.write_text("# working tree: edited after staging\n")
    monkeypatch.chdir(tmp_path)

    report = _collect_idempotency_report(
        [], [migration], IdempotencyValidator(), staged_content={migration: _READS_NEXT_TO_ITSELF}
    )

    assert report.warnings == []
    assert [v.pattern.value for v in report.violations] == ["CREATE_TABLE"]
    assert report.violations[0].source_line == 12


def test_no_caller_materializes_a_temp_file_any_more() -> None:
    """The primitive exists so nothing needs to; a temp file re-creates the bug."""
    import confiture.cli.helpers as helpers
    import confiture.core.grant_accompaniment as grants

    for module in (helpers, grants):
        source = Path(module.__file__).read_text(encoding="utf-8")  # type: ignore[arg-type]
        names = {
            alias.name
            for node in ast.walk(ast.parse(source))
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert "tempfile" not in names and "TemporaryDirectory" not in names, module.__name__


def test_the_evaluator_never_imports_or_executes() -> None:
    """The module's whole promise, pinned: no eval, exec, importlib or __import__."""
    import confiture.core.idempotency.static_eval as static_eval

    package = Path(static_eval.__file__).parent  # type: ignore[arg-type]
    source = "\n".join(p.read_text(encoding="utf-8") for p in sorted(package.glob("*.py")))
    tree = ast.parse(source)
    forbidden = {"eval", "exec", "compile", "__import__"}
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not (calls & forbidden), calls & forbidden
    assert "importlib" not in imports and "subprocess" not in imports
