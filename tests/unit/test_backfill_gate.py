"""A change existing rows can refuse is generated around a backfill placeholder (#766).

The placeholder is a ``-- confiture:backfill <target>`` directive the author replaces;
``migrate up`` refuses a file that still carries one (``VALID_010``) and preflight
reports it (``PFLIGHT_BACKFILL_PENDING``). Generated SQL is read back with pglast.
"""

from pathlib import Path

import pglast
import pytest

from confiture.core._pglast_enums import member
from confiture.core.backfill_gate import pending, placeholder
from confiture.core.change_set import classify_statements
from confiture.core.change_set.diff_tiers import tier_of
from confiture.core.differ_sql import DifferSQLGenerator
from confiture.core.migration_generator import MigrationGenerator
from confiture.core.preflight import run_preflight
from confiture.core.risk_tier import RiskTier, worst_tier
from confiture.platform import diff
from confiture.testing.loader import load_migration

_AT = {
    name: member("AlterTableType", name)
    for name in (
        "AT_AddColumn",
        "AT_AddConstraint",
        "AT_ValidateConstraint",
        "AT_SetNotNull",
        "AT_DropConstraint",
        "AT_AlterColumnType",
    )
}
_BY_VALUE = {value: name for name, value in _AT.items()}

OLD = "CREATE TABLE t (id bigint PRIMARY KEY, name text, code text);"


def _up(new: str, old: str = OLD) -> str:
    renderer = DifferSQLGenerator()
    return "".join(renderer.generate_up(change) or "" for change in diff(old, new).changes)


def _subcommands(sql: str) -> list[str]:
    return [
        _BY_VALUE.get(int(cmd.subtype), str(cmd.subtype))
        for raw in pglast.parse_sql(sql)
        for cmd in raw.stmt.cmds
    ]


class TestTheDirective:
    def test_a_placeholder_names_its_target(self) -> None:
        assert pending(placeholder("t.email", "the rows of t where email is NULL")) == ["t.email"]

    def test_none_says_no_row_needs_it(self) -> None:
        assert (
            pending("-- confiture:backfill none\nALTER TABLE t ALTER COLUMN a SET NOT NULL;") == []
        )

    def test_a_directive_inside_a_string_is_not_one(self) -> None:
        assert pending("SELECT '-- confiture:backfill t.a';") == []

    def test_every_placeholder_is_listed_in_file_order(self) -> None:
        sql = placeholder("t.a", "rows") + "SELECT 1;\n" + placeholder("t.b", "rows")
        assert pending(sql) == ["t.a", "t.b"]


class TestWhatIsGenerated:
    def test_a_not_null_column_nothing_fills_is_added_nullable_then_tightened(self) -> None:
        sql = _up(
            "CREATE TABLE t (id bigint PRIMARY KEY, name text, code text, email text NOT NULL);"
        )

        assert pending(sql) == ["t.email"]
        assert _subcommands(sql) == [
            "AT_AddColumn",
            "AT_DropConstraint",
            "AT_AddConstraint",
            "AT_ValidateConstraint",
            "AT_SetNotNull",
            "AT_DropConstraint",
        ]
        (added,) = pglast.parse_sql(sql)[0].stmt.cmds
        assert not any(c.contype.name == "CONSTR_NOTNULL" for c in added.def_.constraints or ())

    @pytest.mark.parametrize(
        "column",
        [
            "email text NOT NULL DEFAULT ''",
            "token uuid NOT NULL DEFAULT gen_random_uuid()",
            "n bigint GENERATED ALWAYS AS IDENTITY",
            "email text",
        ],
    )
    def test_a_column_postgresql_fills_is_added_as_declared(self, column: str) -> None:
        sql = _up(f"CREATE TABLE t (id bigint PRIMARY KEY, name text, code text, {column});")

        assert pending(sql) == []
        assert _subcommands(sql) == ["AT_AddColumn"]

    def test_set_not_null_is_proven_by_a_check_first(self) -> None:
        sql = _up("CREATE TABLE t (id bigint PRIMARY KEY, name text NOT NULL, code text);")

        assert pending(sql) == ["t.name"]
        assert _subcommands(sql) == [
            "AT_DropConstraint",
            "AT_AddConstraint",
            "AT_ValidateConstraint",
            "AT_SetNotNull",
            "AT_DropConstraint",
        ]

    def test_a_unique_key_waits_for_the_rows_that_repeat(self) -> None:
        sql = _up(
            "CREATE TABLE t (id bigint PRIMARY KEY, name text, code text, CONSTRAINT k UNIQUE (code));"
        )

        assert pending(sql) == ["t.k"]
        assert _subcommands(sql) == ["AT_AddConstraint"]

    def test_a_check_waits_for_the_rows_that_fail_it_and_is_validated_apart(self) -> None:
        sql = _up(
            "CREATE TABLE t (id bigint PRIMARY KEY, name text, code text, "
            "CONSTRAINT c CHECK (length(code) < 5));"
        )

        assert pending(sql) == ["t.c"]
        assert _subcommands(sql) == [
            "AT_DropConstraint",
            "AT_AddConstraint",
            "AT_ValidateConstraint",
        ]
        assert pglast.parse_sql(sql)[1].stmt.cmds[0].def_.skip_validation

    @pytest.mark.parametrize(
        ("new_type", "waits"), [("varchar(5)", True), ("integer", True), ("varchar", False)]
    )
    def test_a_retype_waits_only_when_a_value_may_not_fit(self, new_type: str, waits: bool) -> None:
        sql = _up(f"CREATE TABLE t (id bigint PRIMARY KEY, name {new_type}, code text);")

        assert (pending(sql) == ["t.name"]) is waits
        assert _subcommands(sql) == ["AT_AlterColumnType"]

    @pytest.mark.parametrize(
        "new",
        [
            "CREATE TABLE t (id bigint PRIMARY KEY, name text, code text, email text NOT NULL);",
            "CREATE TABLE t (id bigint PRIMARY KEY, name text NOT NULL, code text);",
            "CREATE TABLE t (id bigint PRIMARY KEY, name text, code text, CONSTRAINT c CHECK (code <> ''));",
        ],
    )
    def test_the_tier_is_the_tier_of_what_is_written(self, new: str) -> None:
        (change,) = diff(OLD, new).changes
        written = classify_statements(DifferSQLGenerator().generate_up(change) or "")

        assert tier_of(change) == worst_tier(e.tier for e in written) == RiskTier.LOCK_RISKY


class TestItRunsAgain:
    """Outside a transaction each statement commits, so a retry meets what the last run left (#785)."""

    @pytest.mark.parametrize(
        "new",
        [
            "CREATE TABLE t (id bigint PRIMARY KEY, name text, code text, email text NOT NULL);",
            "CREATE TABLE t (id bigint PRIMARY KEY, name text NOT NULL, code text);",
            "CREATE TABLE t (id bigint PRIMARY KEY, name text, code text, CONSTRAINT c CHECK (code <> ''));",
        ],
    )
    def test_each_constraint_added_not_valid_is_dropped_if_it_exists_first(self, new: str) -> None:
        statements = [raw.stmt for raw in pglast.parse_sql(_up(new))]
        adds = [
            (at, cmd.def_.conname)
            for at, stmt in enumerate(statements)
            for cmd in stmt.cmds
            if int(cmd.subtype) == _AT["AT_AddConstraint"]
        ]

        assert adds
        for at, name in adds:
            (before,) = statements[at - 1].cmds
            assert int(before.subtype) == _AT["AT_DropConstraint"]
            assert (before.name, before.missing_ok) == (name, True)

    def test_the_column_is_added_if_it_does_not_exist(self) -> None:
        sql = _up(
            "CREATE TABLE t (id bigint PRIMARY KEY, name text, code text, email text NOT NULL);"
        )

        (added,) = pglast.parse_sql(sql)[0].stmt.cmds
        assert added.missing_ok


class TestTheConstraintTheFileAdded:
    """Dropping a constraint the same file added drops nothing that existed before."""

    ADD = "ALTER TABLE t ADD CONSTRAINT c CHECK (a IS NOT NULL) NOT VALID;\n"

    def _drop_tier(self, sql: str) -> RiskTier | None:
        return classify_statements(sql)[-1].tier

    def test_its_drop_takes_the_tier_of_its_add(self) -> None:
        assert self._drop_tier(self.ADD + "ALTER TABLE t DROP CONSTRAINT c;") is RiskTier.REVERSIBLE

    def test_one_the_file_did_not_add_is_still_destructive(self) -> None:
        assert self._drop_tier("ALTER TABLE t DROP CONSTRAINT c;") is RiskTier.DESTRUCTIVE

    def test_it_matches_only_as_written(self) -> None:
        sql = self.ADD + "ALTER TABLE public.t DROP CONSTRAINT c;"
        assert self._drop_tier(sql) is RiskTier.DESTRUCTIVE

    def test_a_drop_if_exists_before_its_add_is_the_add(self) -> None:
        sql = "ALTER TABLE t DROP CONSTRAINT IF EXISTS c;\n" + self.ADD

        assert classify_statements(sql)[0].tier is RiskTier.REVERSIBLE

    @pytest.mark.parametrize(
        "drop",
        [
            "ALTER TABLE t DROP CONSTRAINT IF EXISTS c CASCADE;\n",
            "ALTER TABLE public.t DROP CONSTRAINT IF EXISTS c;\n",
            "ALTER TABLE t DROP CONSTRAINT IF EXISTS d;\n",
            "ALTER TABLE u DROP CONSTRAINT IF EXISTS c;\n",
        ],
    )
    def test_a_drop_is_paired_only_as_written(self, drop: str) -> None:
        assert classify_statements(drop + self.ADD)[0].tier is RiskTier.DESTRUCTIVE

    def test_a_statement_between_that_is_not_an_alter_table_forgets_it(self) -> None:
        sql = self.ADD + "DO $$ BEGIN NULL; END $$;\nALTER TABLE t DROP CONSTRAINT c;"
        assert self._drop_tier(sql) is RiskTier.DESTRUCTIVE


class TestAVolatileDefault:
    @pytest.mark.parametrize(
        ("column", "tier"),
        [
            ("a uuid DEFAULT gen_random_uuid()", RiskTier.LOCK_RISKY),
            ("a double precision DEFAULT random()", RiskTier.LOCK_RISKY),
            ("a int DEFAULT 1", RiskTier.ADDITIVE),
            ("a timestamptz DEFAULT now()", RiskTier.ADDITIVE),
            ("a timestamptz DEFAULT CURRENT_TIMESTAMP", RiskTier.ADDITIVE),
        ],
    )
    def test_a_volatile_one_rewrites_the_table_and_is_a_lock_risk(
        self, column: str, tier: RiskTier
    ) -> None:
        (entry,) = classify_statements(f"ALTER TABLE t ADD COLUMN {column};")

        assert entry.tier is tier
        if tier is RiskTier.LOCK_RISKY:
            assert entry.lock.rewrites_table

    def test_the_diff_tiers_it_as_the_statement_does(self) -> None:
        (change,) = diff(
            OLD, OLD.replace("code text", "code text, a uuid DEFAULT gen_random_uuid()")
        ).changes

        assert tier_of(change) is RiskTier.LOCK_RISKY


class TestWhoRefusesIt:
    def _generated(self, tmp_path: Path, *, sql: bool = True) -> Path:
        new = "CREATE TABLE t (id bigint PRIMARY KEY, name text, code text, email text NOT NULL);"
        generator = MigrationGenerator(tmp_path)
        write = generator.generate_sql if sql else generator.generate
        return write(diff(OLD, new), "add_email", version="20260101000000", destructive="allow")

    def test_preflight_reports_the_placeholder(self, tmp_path: Path) -> None:
        self._generated(tmp_path)

        issues = [i for i in run_preflight(tmp_path).issues if i.code == "PFLIGHT_BACKFILL_PENDING"]

        assert [(i.migration, i.details) for i in issues] == [
            ("20260101000000", {"targets": ["t.email"]})
        ]
        assert issues[0].severity == "error"

    def test_a_filled_file_is_not_reported(self, tmp_path: Path) -> None:
        up = self._generated(tmp_path)
        up.write_text(
            up.read_text().replace("-- confiture:backfill t.email", "UPDATE t SET email = '';")
        )

        assert not [
            i for i in run_preflight(tmp_path).issues if i.code == "PFLIGHT_BACKFILL_PENDING"
        ]

    def test_a_python_migration_carries_it_as_an_attribute(self, tmp_path: Path) -> None:
        self._generated(tmp_path, sql=False)

        migration = load_migration(version="20260101000000", migrations_dir=tmp_path)

        assert migration.backfill_pending == ("t.email",)

    def test_a_sql_migration_carries_it_too(self, tmp_path: Path) -> None:
        self._generated(tmp_path)

        migration = load_migration(version="20260101000000", migrations_dir=tmp_path)

        assert migration.backfill_pending == ("t.email",)

    def test_the_codes_are_registered(self) -> None:
        from confiture.error_codes import ERROR_CODE_REGISTRY
        from confiture.models.results import PFLIGHT_CODES

        assert ERROR_CODE_REGISTRY.get("VALID_010").exit_code == 5
        assert PFLIGHT_CODES["PFLIGHT_BACKFILL_PENDING"][0] == "error"
