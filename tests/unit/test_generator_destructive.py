"""A generated migration says how dangerous each statement is, in the words the change set uses.

The desired state may remove a table or a column, or narrow a type. The
generator writes that DDL for real, and the file carries the risk tier of every
statement as a ``-- confiture:tier <tier>`` directive — the tier
``migrate preflight``'s change-set classifier assigns, so the two never disagree.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest

from confiture.core import sql_lexer
from confiture.core.change_set import classify_statements
from confiture.core.destructive import resolve_policy
from confiture.core.differ import SchemaDiffer
from confiture.core.migration_generator import MigrationGenerator
from confiture.core.risk_tier import worst_tier
from confiture.core.schema_change import (
    ColumnAdded,
    ColumnDropped,
    ColumnTypeChanged,
    SchemaChange,
    SchemaDiff,
    TableDropped,
    column_definition,
)
from confiture.exceptions import DifferError, ValidationError
from tests.unit._schema_changes import spelled
from tests.unit._schema_models import table

VERSION = "20260101000000"


def _generate(tmp_path: Path, *changes: SchemaChange) -> tuple[str, str]:
    up = MigrationGenerator(migrations_dir=tmp_path).generate_sql(
        SchemaDiff(changes=list(changes)), name="reshape", version=VERSION
    )
    down = up.with_name(up.name.replace(".up.sql", ".down.sql"))
    return up.read_text(), down.read_text()


def _tiers(text: str) -> dict[int, str | None]:
    """The tier directive attached to each statement, keyed by the statement's line."""
    return {d.statement_line: d.argument for d in sql_lexer.directives(text) if d.name == "tier"}


def test_a_dropped_column_is_real_ddl_at_tier_irreversible(tmp_path: Path) -> None:
    up, _ = _generate(tmp_path, ColumnDropped("tb_user", spelled("display_name", "TEXT")))
    assert "ALTER TABLE tb_user DROP COLUMN display_name;" in up
    # Data is lost with the column: the change set tiers the drop irreversible, not merely destructive.
    assert list(_tiers(up).values()) == ["irreversible"]


@pytest.mark.parametrize(
    "change",
    [
        TableDropped(table("tb_old")),
        ColumnDropped("tb_user", spelled("display_name", "TEXT")),
        ColumnTypeChanged("tb_user", spelled("score", "BIGINT"), spelled("score", "INTEGER")),
        ColumnAdded("tb_user", spelled("bio", "TEXT")),
    ],
    ids=lambda c: c.to_wire().type,
)
def test_every_statement_carries_the_tier_the_change_set_gives_it(
    tmp_path: Path, change: SchemaChange
) -> None:
    up, down = _generate(tmp_path, change)
    for text in (up, down):
        statements = [
            s for s in sql_lexer.split_statements(sql_lexer.code_text(text).text) if s.strip()
        ]
        if text is up:  # the down file of a change with no rollback holds only its directive
            assert statements, text
        # A statement the classifier cannot tier gets no directive: five tiers, no "unknown".
        classified = [worst_tier(e.tier for e in classify_statements(s)) for s in statements]
        expected = [tier.value for tier in classified if tier is not None]
        assert list(_tiers(text).values()) == expected, text


class TestTheGate:
    """``destructive`` policy at generation: gated marks the file, allow leaves it, forbid refuses."""

    DROP = ColumnDropped("tb_user", spelled("display_name", "TEXT"))
    ADD = ColumnAdded("tb_user", spelled("bio", "TEXT"))

    def _gate(self, text: str) -> list[int | None]:
        return [d.statement_line for d in sql_lexer.directives(text) if d.name == "destructive"]

    def test_gated_marks_the_up_file_on_its_first_statement(self, tmp_path: Path) -> None:
        up = MigrationGenerator(migrations_dir=tmp_path).generate_sql(
            SchemaDiff(changes=[self.ADD, self.DROP]), name="reshape", version=VERSION
        )
        text = up.read_text()
        first = text.index("ALTER TABLE")
        assert self._gate(text) == [text[:first].count("\n") + 1], text

    def test_gated_leaves_an_additive_file_alone(self, tmp_path: Path) -> None:
        up = MigrationGenerator(migrations_dir=tmp_path).generate_sql(
            SchemaDiff(changes=[self.ADD]), name="grow", version=VERSION
        )
        assert self._gate(up.read_text()) == []

    def test_allow_writes_the_ddl_unmarked(self, tmp_path: Path) -> None:
        up = MigrationGenerator(migrations_dir=tmp_path).generate_sql(
            SchemaDiff(changes=[self.DROP]), name="reshape", version=VERSION, destructive="allow"
        )
        text = up.read_text()
        assert "DROP COLUMN display_name;" in text
        assert self._gate(text) == []

    def test_forbid_refuses_to_generate(self, tmp_path: Path) -> None:
        with pytest.raises(DifferError) as excinfo:
            MigrationGenerator(migrations_dir=tmp_path).generate_sql(
                SchemaDiff(changes=[self.DROP]),
                name="reshape",
                version=VERSION,
                destructive="forbid",
            )
        assert excinfo.value.error_code == "DIFFER_401"
        assert "display_name" in str(excinfo.value)
        assert list(tmp_path.iterdir()) == []


class TestOneGate:
    """A dropped view, type, enum type or sequence answers to the gate ``DROP TABLE`` does (#335).

    The renderer refused them unless forced, with a "Re-run with --force" that
    ``migrate diff`` has no flag for, while ``migration.destructive`` governed a
    dropped table or column: two gates, one of them unreachable.
    """

    SCHEMA = (
        "CREATE TYPE mood AS ENUM ('sad', 'ok');\n"
        "CREATE SEQUENCE order_seq;\n"
        "CREATE TABLE t (a int);\n"
        "CREATE VIEW v AS SELECT a FROM t;\n"
    )
    DROPS: ClassVar[dict[str, str]] = {
        "DROP_ENUM_TYPE": "DROP TYPE IF EXISTS mood;",
        "DROP_SEQUENCE": "DROP SEQUENCE IF EXISTS order_seq;",
        "DROP_VIEW": "DROP VIEW IF EXISTS v;",
    }

    def _diff(self, kind: str) -> SchemaDiff:
        diff = SchemaDiffer().compare(self.SCHEMA, "CREATE TABLE t (a int);")
        return SchemaDiff(changes=[c for c in diff.changes if c.to_wire().type == kind])

    @pytest.mark.parametrize("kind", sorted(DROPS))
    def test_gated_writes_the_drop_and_marks_the_file(self, tmp_path: Path, kind: str) -> None:
        up = (
            MigrationGenerator(migrations_dir=tmp_path)
            .generate_sql(self._diff(kind), name="shrink", version=VERSION)
            .read_text()
        )
        assert self.DROPS[kind] in up
        assert "--force" not in up
        assert [d.name for d in sql_lexer.directives(up) if d.name == "destructive"] == [
            "destructive"
        ]

    @pytest.mark.parametrize("kind", sorted(DROPS))
    def test_forbid_refuses_it(self, tmp_path: Path, kind: str) -> None:
        with pytest.raises(DifferError) as excinfo:
            MigrationGenerator(migrations_dir=tmp_path).generate_sql(
                self._diff(kind), name="shrink", version=VERSION, destructive="forbid"
            )
        assert excinfo.value.error_code == "DIFFER_401"

    def test_the_python_form_executes_it(self, tmp_path: Path) -> None:
        path = MigrationGenerator(migrations_dir=tmp_path).generate(
            self._diff("DROP_VIEW"), name="shrink", version=VERSION
        )
        text = path.read_text()
        assert 'self.execute("DROP VIEW IF EXISTS v;")' in text
        assert "    destructive = True" in text


class TestPolicy:
    def test_a_flag_wins_over_the_config(self) -> None:
        assert resolve_policy("forbid", allow=True) == "allow"
        assert resolve_policy("allow", forbid=True) == "forbid"
        assert resolve_policy("forbid") == "forbid"

    def test_both_flags_is_a_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            resolve_policy("gated", allow=True, forbid=True)

    def test_an_unknown_config_value_is_a_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="gated, allow, forbid"):
            resolve_policy("maybe")

    def test_the_python_form_declares_the_gate_on_the_class(self, tmp_path: Path) -> None:
        path = MigrationGenerator(migrations_dir=tmp_path).generate(
            SchemaDiff(changes=[TestTheGate.DROP]), name="reshape", version=VERSION
        )
        assert "    destructive = True" in path.read_text()
        (tmp_path / "allow").mkdir()
        allowed = MigrationGenerator(migrations_dir=tmp_path / "allow").generate(
            SchemaDiff(changes=[TestTheGate.DROP]),
            name="reshape",
            version=VERSION,
            destructive="allow",
        )
        assert "destructive = True" not in allowed.read_text()


CURRENT = (
    "CREATE TABLE tb_user (id integer NOT NULL, display_name text DEFAULT 'anon' NOT NULL, "
    "score bigint);\n"
    "CREATE TABLE tb_old (id integer NOT NULL, label text);\n"
)
DESIRED = "CREATE TABLE tb_user (id integer NOT NULL, score integer);\n"


class TestDown:
    """The down file undoes what can be undone, and says what cannot."""

    def _pair(self, tmp_path: Path) -> tuple[str, str]:
        diff = SchemaDiffer().compare(CURRENT, DESIRED)
        up = MigrationGenerator(migrations_dir=tmp_path).generate_sql(
            diff, name="shrink", version=VERSION, destructive="allow"
        )
        return up.read_text(), up.with_name(up.name.replace(".up.sql", ".down.sql")).read_text()

    def test_the_differ_carries_the_dropped_columns_definition(self) -> None:
        changes = {c.type: c for c in SchemaDiffer().compare(CURRENT, DESIRED).wire()}
        assert changes["DROP_COLUMN"].old_value == "TEXT NOT NULL DEFAULT 'anon'"
        assert changes["DROP_TABLE"].details == {
            "columns": [
                {"name": "id", "type": "INTEGER", "nullable": False, "default": None},
                {"name": "label", "type": "TEXT", "nullable": True, "default": None},
            ],
            # Empty for this table, present for every table: the down file
            # recreates a dropped table from exactly these details, so one that
            # came back without its foreign keys came back wrong.
            "constraints": [],
        }

    def test_a_dropped_column_comes_back_with_type_default_and_nullability(
        self, tmp_path: Path
    ) -> None:
        _, down = self._pair(tmp_path)
        assert "ALTER TABLE tb_user ADD COLUMN display_name TEXT NOT NULL DEFAULT 'anon';" in down

    def test_a_dropped_table_comes_back_with_its_columns(self, tmp_path: Path) -> None:
        _, down = self._pair(tmp_path)
        assert (
            "CREATE TABLE IF NOT EXISTS tb_old (\n    id INTEGER NOT NULL,\n    label TEXT\n);"
            in down
        )

    def test_a_narrowed_type_widens_back(self, tmp_path: Path) -> None:
        _, down = self._pair(tmp_path)
        assert "ALTER TABLE tb_user ALTER COLUMN score TYPE BIGINT;" in down

    def test_data_loss_is_declared_on_the_up_statement(self, tmp_path: Path) -> None:
        up, _ = self._pair(tmp_path)
        reasons = {
            up.splitlines()[d.statement_line - 1]: d.argument
            for d in sql_lexer.directives(up)
            if d.name == "irreversible" and d.statement_line is not None
        }
        assert reasons == {
            "DROP TABLE tb_old;": "data",
            "ALTER TABLE tb_user DROP COLUMN display_name;": "data",
        }

    def test_no_python_comment_ever_lands_in_a_sql_file(self, tmp_path: Path) -> None:
        up, down = self._pair(tmp_path)
        assert not [line for line in (up + down).splitlines() if line.startswith("#")]

    def test_a_change_with_no_rollback_says_so_at_tier_irreversible(self, tmp_path: Path) -> None:
        # A dropped table that declared no columns: nothing to recreate it from.
        change = TableDropped(table("ghost"))
        up = MigrationGenerator(migrations_dir=tmp_path).generate_sql(
            SchemaDiff(changes=[change]), name="ghost", version=VERSION, destructive="allow"
        )
        down = up.with_name(up.name.replace(".up.sql", ".down.sql")).read_text()
        irreversible = [d for d in sql_lexer.directives(down) if d.name == "irreversible"]
        assert [d.argument for d in irreversible] == ["no rollback derived for DROP_TABLE ghost"]
        assert "WARNING" not in down and "#" not in down
        assert [d.argument for d in sql_lexer.directives(up.read_text()) if d.name == "tier"] == [
            "irreversible"
        ]


def test_the_generator_never_writes_a_python_comment_into_sql() -> None:
    """The ``# WARNING: Cannot auto-generate`` lines are gone from the package, for good."""
    root = Path(__file__).resolve().parents[2] / "python" / "confiture"
    offenders = [
        str(p.relative_to(root))
        for p in root.rglob("*.py")
        if "Cannot auto-generate" in p.read_text() or '"# WARNING' in p.read_text()
    ]
    assert offenders == []


@pytest.mark.parametrize(
    ("default", "rendered"),
    [
        ("'anon'::text", "CAST('anon' AS text)"),
        ("now()", "now()"),
        ("concat('x', 'y')", "concat('x', 'y')"),
        ("3", "3"),
    ],
)
def test_a_default_survives_to_the_column_definition(default: str, rendered: str) -> None:
    """What pg_dump writes as a default comes back as SQL, arguments and casts included."""
    table = SchemaDiffer().parse_schema(f"CREATE TABLE t (a text DEFAULT {default});").tables[0]
    assert column_definition(table.columns[0]) == f"TEXT DEFAULT {rendered}"


class TestAnUnnamedConstraintsDown:
    """The down of an added unnamed constraint is the generator's directive, with its reason (#335)."""

    def test_the_down_file_says_why_in_a_directive(self, tmp_path: Path) -> None:
        diff = SchemaDiffer().compare(
            "CREATE TABLE t (id int);", "CREATE TABLE t (id int CHECK (id > 0));"
        )
        up = MigrationGenerator(migrations_dir=tmp_path).generate_sql(
            diff, name="check", version=VERSION
        )
        down = up.with_name(up.name.replace(".up.sql", ".down.sql")).read_text()
        reasons = [d.argument for d in sql_lexer.directives(down) if d.name == "irreversible"]
        assert reasons == [
            "no rollback derived for ADD_CHECK_CONSTRAINT t: the constraint is unnamed, "
            "and PostgreSQL chooses its name when it is added"
        ]
        assert "WARNING" not in down
