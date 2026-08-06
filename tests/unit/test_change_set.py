"""The preflight change set — per-change risk classification (#197).

The wire shape and the tier boundaries are the ratified cross-repo contract
(fraisier-core#44, `docs/proposals/migration-risk-contract.md`, contract
version 1). Two properties matter more than any individual mapping:

* a statement is **never silently dropped** — one confiture cannot classify
  still produces an entry, with no ``tier``, so the consumer denies;
* the two parser backends agree, so an install without the ``[ast]`` extra
  classifies the same way.
"""

from __future__ import annotations

import pytest

from confiture.core.change_set import (
    CONTRACT_VERSION,
    ChangeEntry,
    ChangeSet,
    build_change_set,
    classify_statements,
)
from confiture.core.risk_tier import RiskTier

# (sql, kind, tier) — the taxonomy, statement by statement.
_TAXONOMY = [
    # additive: adds a new object, no existing reader can break
    ("CREATE TABLE tb_user (id int);", "create_table", RiskTier.ADDITIVE),
    ("ALTER TABLE tb_user ADD COLUMN nickname text;", "add_column", RiskTier.ADDITIVE),
    ("CREATE INDEX CONCURRENTLY idx ON tb_order (placed_at);", "create_index", RiskTier.ADDITIVE),
    ("CREATE VIEW v AS SELECT 1;", "create_view", RiskTier.ADDITIVE),
    ("CREATE SCHEMA s;", "create_schema", RiskTier.ADDITIVE),
    ("CREATE SEQUENCE sq;", "create_sequence", RiskTier.ADDITIVE),
    ("INSERT INTO tb_z (a) VALUES (1);", "insert", RiskTier.ADDITIVE),
    # reversible: changes existing state, with a down path that restores it
    ("ALTER TABLE tb_user RENAME COLUMN a TO b;", "rename_column", RiskTier.REVERSIBLE),
    ("ALTER TABLE t ALTER COLUMN c SET DEFAULT 1;", "set_column_default", RiskTier.REVERSIBLE),
    ("ALTER TABLE t ALTER COLUMN c DROP DEFAULT;", "drop_column_default", RiskTier.REVERSIBLE),
    ("ALTER TABLE t ALTER COLUMN c DROP NOT NULL;", "drop_not_null", RiskTier.REVERSIBLE),
    (
        "ALTER TABLE t ADD CONSTRAINT ck CHECK (c > 0) NOT VALID;",
        "add_constraint",
        RiskTier.REVERSIBLE,
    ),
    ("CREATE OR REPLACE VIEW v AS SELECT 1;", "replace_view", RiskTier.REVERSIBLE),
    ("GRANT SELECT ON tb_z TO r;", "grant", RiskTier.REVERSIBLE),
    ("REVOKE SELECT ON tb_z FROM r;", "revoke", RiskTier.REVERSIBLE),
    ("COMMENT ON TABLE tb_z IS 'x';", "comment", RiskTier.REVERSIBLE),
    # lock_risky: semantically safe, but takes a lock that can stall a hot table
    ("CREATE INDEX idx ON tb_order (placed_at);", "create_index", RiskTier.LOCK_RISKY),
    ("ALTER TABLE t ADD COLUMN c text NOT NULL DEFAULT '';", "add_column", RiskTier.LOCK_RISKY),
    ("ALTER TABLE t ADD COLUMN c text NOT NULL;", "add_column", RiskTier.LOCK_RISKY),
    ("ALTER TABLE t ADD CONSTRAINT ck CHECK (c > 0);", "add_constraint", RiskTier.LOCK_RISKY),
    ("ALTER TABLE t ALTER COLUMN c SET NOT NULL;", "set_not_null", RiskTier.LOCK_RISKY),
    # destructive: destroys data or an object, recoverable from backup
    ("DROP INDEX idx_x;", "drop_index", RiskTier.DESTRUCTIVE),
    ("DROP VIEW v;", "drop_view", RiskTier.DESTRUCTIVE),
    ("ALTER TABLE t DROP CONSTRAINT ck;", "drop_constraint", RiskTier.DESTRUCTIVE),
    ("TRUNCATE tb_z;", "truncate", RiskTier.DESTRUCTIVE),
    ("DELETE FROM tb_z WHERE id = 1;", "delete", RiskTier.DESTRUCTIVE),
    ("UPDATE tb_z SET a = 1;", "update", RiskTier.DESTRUCTIVE),
    # irreversible: destroys data with no down path that restores it
    ("ALTER TABLE tb_user DROP COLUMN legacy_flag;", "drop_column", RiskTier.IRREVERSIBLE),
    ("DROP TABLE tb_old;", "drop_table", RiskTier.IRREVERSIBLE),
    ("DROP SCHEMA s;", "drop_schema", RiskTier.IRREVERSIBLE),
    ("DROP SEQUENCE sq;", "drop_sequence", RiskTier.IRREVERSIBLE),
]


@pytest.mark.parametrize(("sql", "kind", "tier"), _TAXONOMY)
def test_taxonomy_ast(sql: str, kind: str, tier: RiskTier) -> None:
    (entry,) = classify_statements(sql)
    assert (entry.kind, entry.tier) == (kind, tier)


@pytest.mark.parametrize(("sql", "kind", "tier"), _TAXONOMY)
def test_taxonomy_regex_backend_agrees(sql: str, kind: str, tier: RiskTier, monkeypatch) -> None:
    """An install without the [ast] extra must classify identically."""
    monkeypatch.setattr("confiture.core.change_set._HAS_PGLAST", False)
    (entry,) = classify_statements(sql)
    assert (entry.kind, entry.tier) == (kind, tier)


@pytest.mark.parametrize("sql", [case[0] for case in _TAXONOMY])
def test_the_two_backends_produce_identical_entries(sql: str, monkeypatch) -> None:
    """Parity on the whole entry, not just the tier.

    `object` and `detail` are what the operator reads; an install without the
    [ast] extra must not render a different plan.
    """
    via_ast = classify_statements(sql, migration="20260806120000", source="m.up.sql")
    monkeypatch.setattr("confiture.core.change_set._HAS_PGLAST", False)
    via_regex = classify_statements(sql, migration="20260806120000", source="m.up.sql")
    assert via_ast == via_regex, sql


def test_alter_column_type_is_deliberately_unclassified() -> None:
    """Narrowing is irreversible, widening is reversible, and preflight cannot tell.

    The contract's own `v1-missing-tier.json` fixture uses `alter_column_type`
    as its no-tier example. Guessing here would ship a confident wrong answer;
    phase 10's type lattice is what resolves it.
    """
    (entry,) = classify_statements("ALTER TABLE t ALTER COLUMN c TYPE bigint;")
    assert entry.kind == "alter_column_type"
    assert entry.tier is None


@pytest.mark.parametrize("force_regex", [False, True])
def test_an_unrecognised_statement_still_produces_an_entry(force_regex, monkeypatch) -> None:
    """Silently dropping a statement would make a dangerous migration read as empty."""
    if force_regex:
        monkeypatch.setattr("confiture.core.change_set._HAS_PGLAST", False)
    entries = classify_statements("DO $$ BEGIN NULL; END $$;")
    assert entries, "an unclassifiable statement must not vanish"
    assert all(e.tier is None for e in entries)


@pytest.mark.parametrize("force_regex", [False, True])
@pytest.mark.parametrize(
    "sql",
    ["BEGIN;", "COMMIT;", "SET search_path TO public;", "LOCK TABLE t;", "ANALYZE t;"],
)
def test_statements_that_change_nothing_are_not_entries(sql, force_regex, monkeypatch) -> None:
    """Transaction/session control is not a schema change; emitting it would deny every deploy."""
    if force_regex:
        monkeypatch.setattr("confiture.core.change_set._HAS_PGLAST", False)
    assert classify_statements(sql) == []


@pytest.mark.parametrize("force_regex", [False, True])
def test_dollar_quoted_body_is_one_statement(force_regex, monkeypatch) -> None:
    """A `;` inside a function body must not split the statement (regex backend)."""
    if force_regex:
        monkeypatch.setattr("confiture.core.change_set._HAS_PGLAST", False)
    sql = "CREATE OR REPLACE FUNCTION f() RETURNS int AS $$ SELECT 1; $$ LANGUAGE sql;"
    entries = classify_statements(sql)
    assert [(e.kind, e.tier) for e in entries] == [("replace_function", RiskTier.REVERSIBLE)]


@pytest.mark.parametrize("force_regex", [False, True])
def test_object_is_schema_qualified(force_regex, monkeypatch) -> None:
    if force_regex:
        monkeypatch.setattr("confiture.core.change_set._HAS_PGLAST", False)
    (entry,) = classify_statements("ALTER TABLE tb_user ADD COLUMN nickname text;")
    assert entry.object == "public.tb_user.nickname"
    (qualified,) = classify_statements("ALTER TABLE app.tb_user DROP COLUMN x;")
    assert qualified.object == "app.tb_user.x"


@pytest.mark.parametrize("force_regex", [False, True])
def test_create_index_object_names_the_index(force_regex, monkeypatch) -> None:
    if force_regex:
        monkeypatch.setattr("confiture.core.change_set._HAS_PGLAST", False)
    (entry,) = classify_statements("CREATE INDEX idx_placed_at ON tb_order (placed_at);")
    assert entry.object == "public.tb_order.idx_placed_at"


@pytest.mark.parametrize("force_regex", [False, True])
def test_multiple_objects_in_one_drop_each_get_an_entry(force_regex, monkeypatch) -> None:
    if force_regex:
        monkeypatch.setattr("confiture.core.change_set._HAS_PGLAST", False)
    entries = classify_statements("DROP TABLE a, b;")
    assert [e.object for e in entries] == ["public.a", "public.b"]


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("COMMENT ON COLUMN app.tb_user.nickname IS 'x';", "app.tb_user.nickname"),
        ("DROP TRIGGER trg ON app.tb_user;", "app.tb_user.trg"),
        ("DROP FUNCTION app.f(int);", "app.f"),
        ("DROP SCHEMA app;", "app"),
    ],
)
@pytest.mark.parametrize("force_regex", [False, True])
def test_three_part_names_keep_their_schema(sql, expected, force_regex, monkeypatch) -> None:
    """`schema.table.child` must not report the *table* as the schema."""
    if force_regex:
        monkeypatch.setattr("confiture.core.change_set._HAS_PGLAST", False)
    (entry,) = classify_statements(sql)
    assert entry.object == expected


def test_statement_order_is_preserved() -> None:
    sql = "CREATE TABLE a (id int);\nDROP TABLE b;\nTRUNCATE c;"
    assert [e.kind for e in classify_statements(sql)] == ["create_table", "drop_table", "truncate"]


# --------------------------------------------------------------------------- #
# Wire shape
# --------------------------------------------------------------------------- #


def test_contract_version_is_one() -> None:
    assert CONTRACT_VERSION == 1
    assert ChangeSet(changes=()).to_dict() == {"contract_version": 1, "changes": []}


def test_entry_omits_absent_optional_fields() -> None:
    """An absent `tier` is the contract's "unclassified"; a null would be noise."""
    entry = ChangeEntry(kind="alter_column_type", object="public.t.c")
    assert entry.to_dict() == {"kind": "alter_column_type", "object": "public.t.c"}


def test_entry_serialises_the_tier_as_its_snake_case_wire_value() -> None:
    entry = ChangeEntry(
        kind="drop_column",
        object="public.tb_user.legacy_flag",
        migration="20260804120100",
        tier=RiskTier.IRREVERSIBLE,
        detail="DROP COLUMN legacy_flag",
    )
    assert entry.to_dict() == {
        "kind": "drop_column",
        "object": "public.tb_user.legacy_flag",
        "migration": "20260804120100",
        "tier": "irreversible",
        "detail": "DROP COLUMN legacy_flag",
    }


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #


def test_build_change_set_reads_the_migrations_tree(tmp_path) -> None:
    migs = tmp_path / "migrations"
    migs.mkdir()
    (migs / "20260804120000_add_nickname.up.sql").write_text(
        "ALTER TABLE tb_user ADD COLUMN nickname text;\n"
    )
    (migs / "20260804120100_drop_legacy.up.sql").write_text(
        "ALTER TABLE tb_user DROP COLUMN legacy_flag;\n"
    )

    change_set = build_change_set(migs)

    assert change_set.contract_version == CONTRACT_VERSION
    assert [(c.kind, c.migration, c.tier) for c in change_set.changes] == [
        ("add_column", "20260804120000", RiskTier.ADDITIVE),
        ("drop_column", "20260804120100", RiskTier.IRREVERSIBLE),
    ]


def test_migration_is_the_version_prefix_not_the_filename(tmp_path) -> None:
    """`issues[].migration` carries the bare version; the two must not disagree."""
    migs = tmp_path / "migrations"
    migs.mkdir()
    (migs / "20260804120000_add_nickname.up.sql").write_text("CREATE TABLE t (id int);\n")
    (entry,) = build_change_set(migs).changes
    assert entry.migration == "20260804120000"


def test_python_migrations_are_listed_as_unclassified(tmp_path) -> None:
    """Omitting them would shrink the set silently — the one failure this must prevent."""
    migs = tmp_path / "migrations"
    migs.mkdir()
    (migs / "20260804120200_backfill.py").write_text("# opaque to the SQL classifier\n")
    (migs / "__init__.py").write_text("")

    (entry,) = build_change_set(migs).changes

    assert entry.tier is None
    assert entry.migration == "20260804120200"
    assert "20260804120200_backfill.py" in entry.object


def test_empty_tree_is_a_classified_empty_set(tmp_path) -> None:
    """`changes: []` means "looked, nothing to change" — never "did not look"."""
    migs = tmp_path / "migrations"
    migs.mkdir()
    assert build_change_set(migs).to_dict() == {"contract_version": 1, "changes": []}


def test_missing_tree_is_a_classified_empty_set(tmp_path) -> None:
    assert build_change_set(tmp_path / "nope").to_dict() == {"contract_version": 1, "changes": []}


def test_versions_filter_scopes_the_set(tmp_path) -> None:
    migs = tmp_path / "migrations"
    migs.mkdir()
    (migs / "20260804120000_a.up.sql").write_text("CREATE TABLE a (id int);\n")
    (migs / "20260804120100_b.up.sql").write_text("CREATE TABLE b (id int);\n")
    change_set = build_change_set(migs, versions=["20260804120100"])
    assert [c.migration for c in change_set.changes] == ["20260804120100"]


def test_worst_tier_over_the_set(tmp_path) -> None:
    migs = tmp_path / "migrations"
    migs.mkdir()
    (migs / "20260804120000_a.up.sql").write_text(
        "CREATE TABLE a (id int);\nALTER TABLE a DROP COLUMN b;\n"
    )
    assert build_change_set(migs).worst_tier is RiskTier.IRREVERSIBLE


def test_unreadable_sql_is_an_unclassified_entry_not_an_empty_set(tmp_path) -> None:
    """A file the parser chokes on must deny, not read as "nothing changes"."""
    migs = tmp_path / "migrations"
    migs.mkdir()
    (migs / "20260804120000_broken.up.sql").write_text("THIS IS NOT SQL AT ALL (((;\n")
    change_set = build_change_set(migs)
    assert change_set.changes
    assert all(c.tier is None for c in change_set.changes)
