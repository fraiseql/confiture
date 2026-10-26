"""A generated Python migration runs in the mode its SQL pair would (#698).

``migrate up`` runs a ``.up.sql`` in autocommit when ``runs_in_one_transaction``
says it must; a Python migration runs the way its class's ``transactional``
attribute says. The generator writes that attribute from the same predicate, so
the two forms of one diff run under one rule.
"""

import ast
import importlib.util
import sys
from pathlib import Path

import pglast
import pytest

from confiture.core._migrator.loader import load_migration_class
from confiture.core.differ import SchemaDiffer
from confiture.core.idempotency.python_migration_extractor import (
    extract_sql_from_python_migration,
)
from confiture.core.migration_analyzer import runs_in_one_transaction
from confiture.core.migration_generator import MigrationGenerator
from confiture.core.schema_change import SchemaDiff, TableAdded
from confiture.core.sql_lexer import parse_file, split_statements
from confiture.models.sql_file_migration import _detect_transactional
from tests.unit._schema_changes import spelled
from tests.unit._schema_models import table

REPO = Path(__file__).resolve().parents[2]
VERSION = "20260101000000"

TABLE = "CREATE TABLE t (id bigint PRIMARY KEY, c text);\n"

_EXPECTED_USERS = '''"""Migration: step

Version: 20260101000000
"""

from confiture.models.migration import Migration


class Step(Migration):
    """Migration: step."""

    version = "20260101000000"
    name = "step"

    def up(self) -> None:
        """Apply migration."""
        self.execute("""-- confiture:creates users
CREATE TABLE users (
    id integer NOT NULL,
    email text
);""")

    def down(self) -> None:
        """Rollback migration."""
        self.execute("DROP TABLE users;")
'''


def _recorder():
    script = REPO / "scripts" / "refresh_model_goldens.py"
    spec = importlib.util.spec_from_file_location("refresh_model_goldens", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # a dataclass resolves its annotations through it
    spec.loader.exec_module(module)
    return module


_RECORDER = _recorder()
_FILE_TREES = {tree.name: tree for tree in _RECORDER.TREES if tree.env is None}


def _tree_text(name: str) -> str:
    tree = _FILE_TREES[name]
    return "\n".join([tree.preamble, *((REPO / f).read_text() for f in tree.files)])


# Every pair the diff goldens record, and every tree read from files diffed from nothing.
CORPUS: dict[str, tuple[str, str]] = {
    **{pair: (_tree_text(old), _tree_text(new)) for pair, old, new in _RECORDER.PAIRS},
    **{name: ("", _tree_text(name)) for name in _FILE_TREES},
}


def _python(tmp_path: Path, diff: SchemaDiff) -> Path:
    return MigrationGenerator(migrations_dir=tmp_path).generate(
        diff, name="step", version=VERSION, destructive="allow"
    )


def _transactional(path: Path) -> bool:
    return load_migration_class(path).transactional


def _mode_of(tmp_path: Path, old: str, new: str) -> bool:
    return _transactional(_python(tmp_path, SchemaDiffer().compare(old, new)))


class TestTheClassDeclaresItsMode:
    def test_a_concurrent_index_makes_the_class_non_transactional(self, tmp_path: Path) -> None:
        assert _mode_of(tmp_path, TABLE, TABLE + "CREATE INDEX ix_c ON t (c);\n") is False

    def test_a_dropped_index_makes_the_class_non_transactional(self, tmp_path: Path) -> None:
        assert _mode_of(tmp_path, TABLE + "CREATE INDEX ix_c ON t (c);\n", TABLE) is False

    def test_an_index_on_an_undeclared_table_makes_the_class_non_transactional(
        self, tmp_path: Path
    ) -> None:
        """The statement follows a comment naming the table it assumes; it is still concurrent."""
        assert _mode_of(tmp_path, TABLE, TABLE + "CREATE INDEX ix_u ON u (c);\n") is False

    def test_a_paired_matview_index_makes_the_class_non_transactional(self, tmp_path: Path) -> None:
        matview = TABLE + "CREATE MATERIALIZED VIEW mv AS SELECT id, c FROM t;\n"
        assert _mode_of(tmp_path, matview, matview + "CREATE INDEX ix_mv ON mv (c);\n") is False

    def test_an_enum_label_makes_the_class_non_transactional(self, tmp_path: Path) -> None:
        """A later statement may use the label, which PostgreSQL refuses before commit (55P04)."""
        old = "CREATE TYPE mood AS ENUM ('a');\n"
        assert _mode_of(tmp_path, old, "CREATE TYPE mood AS ENUM ('a', 'b');\n") is False

    def test_a_transactional_diff_writes_no_transactional_line(self, tmp_path: Path) -> None:
        path = _python(tmp_path, SchemaDiffer().compare("", TABLE + "ALTER TABLE t ADD d int;\n"))
        assert _transactional(path) is True
        assigned = {
            target.id
            for node in ast.walk(ast.parse(path.read_text()))
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        assert "transactional" not in assigned

    def test_an_unparseable_up_keeps_the_runners_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``migrate up`` reports the statement when it runs, as it does for a SQL pair."""

        def refuse(_sql: str) -> bool:
            raise pglast.parser.ParseError("refused", 1)

        monkeypatch.setattr("confiture.core.migration_generator.runs_in_one_transaction", refuse)
        assert _mode_of(tmp_path, TABLE, TABLE + "CREATE INDEX ix_c ON t (c);\n") is True


def test_the_template_of_a_transactional_diff(tmp_path: Path) -> None:
    users = table("users", spelled("id", "integer", nullable=False), spelled("email", "text"))
    diff = SchemaDiff(changes=[TableAdded(users)])
    assert _python(tmp_path, diff).read_text() == _EXPECTED_USERS


def test_the_template_declares_both_attributes_on_their_own_lines(tmp_path: Path) -> None:
    """A gated, non-transactional file carries ``destructive`` then ``transactional``."""
    path = MigrationGenerator(migrations_dir=tmp_path).generate(
        SchemaDiffer().compare(
            TABLE + "CREATE INDEX ix_c ON t (c);\nCREATE TABLE gone (id int);\n", TABLE
        ),
        name="step",
        version=VERSION,
        destructive="gated",
    )
    body = path.read_text()
    assert (
        '    name = "step"\n'
        "    destructive = True  # data is lost: migrate up needs --allow-destructive\n"
        "    transactional = False  # a statement here cannot run in a transaction:"
        " migrate up runs it in autocommit\n"
        "\n"
        "    def up(self) -> None:\n"
    ) in body
    migration = load_migration_class(path)
    assert (migration.destructive, migration.transactional) == (True, False)


@pytest.mark.parametrize("case", sorted(CORPUS))
def test_the_class_agrees_with_its_sql_pair(case: str, tmp_path: Path) -> None:
    old, new = CORPUS[case]
    diff = SchemaDiffer().compare(old, new)
    if not diff.has_changes():
        pytest.skip(f"{case}: no change")
    generator = MigrationGenerator(migrations_dir=tmp_path)
    python = generator.generate(diff, name="py", version=VERSION, destructive="allow")
    up = generator.generate_sql(diff, name="sql", version=VERSION, destructive="allow")
    assert _transactional(python) is _detect_transactional(up)


@pytest.mark.parametrize("case", sorted(CORPUS))
def test_a_down_that_needs_autocommit_has_an_up_that_does(case: str, tmp_path: Path) -> None:
    """The class's mode is read from the up; its down runs in it, so the up must say so."""
    old, new = CORPUS[case]
    diff = SchemaDiffer().compare(old, new)
    if not diff.has_changes():
        pytest.skip(f"{case}: no change")
    up = MigrationGenerator(migrations_dir=tmp_path).generate_sql(
        diff, name="sql", version=VERSION, destructive="allow"
    )
    down = up.with_name(up.name.replace(".up.sql", ".down.sql")).read_text()
    if not runs_in_one_transaction(down):
        assert not runs_in_one_transaction(up.read_text())


def test_the_corpus_holds_both_modes(tmp_path: Path) -> None:
    """The parity above would hold trivially over files of one mode."""
    modes = set()
    for case, (old, new) in CORPUS.items():
        diff = SchemaDiffer().compare(old, new)
        if diff.has_changes():
            work = tmp_path / case
            work.mkdir()
            modes.add(_transactional(_python(work, diff)))
    assert modes == {True, False}


def _bundled(path: Path) -> list[str]:
    """Every ``execute`` text holding a statement no transaction may hold beside another.

    Under autocommit PostgreSQL still runs a multi-statement string as one implicit
    block, which ``CREATE INDEX CONCURRENTLY`` refuses. The one exception is a run of
    ``ALTER TYPE … ADD VALUE``: several apply in one block on PostgreSQL 12 and later.
    """
    extracted = extract_sql_from_python_migration(path)
    assert extracted.warnings == []
    bundled = []
    for snippet in extracted.snippets:
        statements = split_statements(snippet.sql)
        if len(statements) < 2 or all(runs_in_one_transaction(s) for s in statements):
            continue
        kinds = {type(raw.stmt).__name__ for raw in parse_file(snippet.sql).statements}
        if kinds != {"AlterEnumStmt"}:
            bundled.append(snippet.sql)
    return bundled


@pytest.mark.parametrize("case", sorted(CORPUS))
def test_a_statement_no_transaction_may_hold_is_alone_in_its_execute(
    case: str, tmp_path: Path
) -> None:
    """``transactional = False`` is enough only while each such statement has its ``execute``.

    An enum's change writes its labels in one ``execute`` and nothing else beside them.
    """
    old, new = CORPUS[case]
    diff = SchemaDiffer().compare(old, new)
    if not diff.has_changes():
        pytest.skip(f"{case}: no change")
    assert _bundled(_python(tmp_path, diff)) == []


def test_a_bundled_concurrent_statement_is_seen(tmp_path: Path) -> None:
    path = tmp_path / f"{VERSION}_planted.py"
    path.write_text(
        "from confiture.models.migration import Migration\n\n\n"
        "class Planted(Migration):\n"
        f'    version = "{VERSION}"\n'
        '    name = "planted"\n'
        "    transactional = False\n\n"
        "    def up(self) -> None:\n"
        '        self.execute("CREATE INDEX CONCURRENTLY ix ON t (c);\\nSELECT 1;")\n'
        "        self.execute(\"ALTER TYPE m ADD VALUE 'b';\\nALTER TYPE m ADD VALUE 'c';\")\n"
    )
    assert _bundled(path) == ["CREATE INDEX CONCURRENTLY ix ON t (c);\nSELECT 1;"]
