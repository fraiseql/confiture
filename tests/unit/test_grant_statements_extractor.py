"""Unit tests for the richer ``extract_grant_statements`` API (issue #162).

The semantic grant-accompaniment engine (issue #162) needs more than the
table-only ``extract_grants`` shape: it must recognize GRANT **and** REVOKE
across table / schema-wide / sequence / function objects, and — crucially —
must NEVER silently drop a privilege change it can't represent. Anything
parse-clean-but-unmodeled lands in ``GrantExtraction.unrepresentable`` (D9),
so the gate degrades to file-presence rather than passing a grant that never
reaches production.

Both backends (pglast primary, regex fallback) are exercised. pglast is the
ground truth; the regex fallback is intentionally weaker for non-table
objects and leans on the unrepresentable channel rather than guessing.
"""

from __future__ import annotations

import pytest

from confiture.core.migration_grant_extractor import (
    _ALL_FUNCTION_PRIVILEGES,
    _ALL_SCHEMA_PRIVILEGES,
    _ALL_SEQUENCE_PRIVILEGES,
    _ALL_TABLE_PRIVILEGES,
    GrantStatement,
    MigrationGrantExtractor,
)


def _keys(stmts: list[GrantStatement]) -> set[tuple]:
    """Reduce statements to their comparable match keys (privilege-level)."""
    return {
        (s.action, s.objtype, s.target_kind, s.schema, s.object, s.grantee, s.privilege)
        for s in stmts
    }


def _regex(monkeypatch: pytest.MonkeyPatch) -> MigrationGrantExtractor:
    monkeypatch.setattr("confiture.core.migration_grant_extractor._HAS_PGLAST", False)
    return MigrationGrantExtractor()


# ---------------------------------------------------------------------------
# GRANT / REVOKE on tables — both backends, full parity
# ---------------------------------------------------------------------------


def test_grant_table_pglast() -> None:
    result = MigrationGrantExtractor().extract_grant_statements("GRANT SELECT ON s.t TO r;")
    assert _keys(result.statements) == {("GRANT", "TABLE", "OBJECT", "s", "t", "r", "SELECT")}
    assert result.unrepresentable == []


def test_grant_table_regex(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _regex(monkeypatch).extract_grant_statements("GRANT SELECT ON s.t TO r;")
    assert _keys(result.statements) == {("GRANT", "TABLE", "OBJECT", "s", "t", "r", "SELECT")}
    assert result.unrepresentable == []


def test_revoke_table_pglast() -> None:
    result = MigrationGrantExtractor().extract_grant_statements("REVOKE SELECT ON foo FROM r;")
    assert _keys(result.statements) == {
        ("REVOKE", "TABLE", "OBJECT", "public", "foo", "r", "SELECT")
    }


def test_revoke_table_regex(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _regex(monkeypatch).extract_grant_statements("REVOKE SELECT ON foo FROM r;")
    assert _keys(result.statements) == {
        ("REVOKE", "TABLE", "OBJECT", "public", "foo", "r", "SELECT")
    }


def test_multi_privilege_multi_grantee_fanout() -> None:
    result = MigrationGrantExtractor().extract_grant_statements(
        "GRANT SELECT, INSERT ON s.t TO r1, r2;"
    )
    assert _keys(result.statements) == {
        ("GRANT", "TABLE", "OBJECT", "s", "t", "r1", "SELECT"),
        ("GRANT", "TABLE", "OBJECT", "s", "t", "r1", "INSERT"),
        ("GRANT", "TABLE", "OBJECT", "s", "t", "r2", "SELECT"),
        ("GRANT", "TABLE", "OBJECT", "s", "t", "r2", "INSERT"),
    }


# ---------------------------------------------------------------------------
# ALL expansion per object type
# ---------------------------------------------------------------------------


def test_grant_all_table_expands() -> None:
    result = MigrationGrantExtractor().extract_grant_statements("GRANT ALL ON s.t TO r;")
    assert {s.privilege for s in result.statements} == set(_ALL_TABLE_PRIVILEGES)


def test_grant_all_sequence_expands() -> None:
    result = MigrationGrantExtractor().extract_grant_statements("GRANT ALL ON SEQUENCE s.seq TO r;")
    assert {s.privilege for s in result.statements} == set(_ALL_SEQUENCE_PRIVILEGES)
    assert all(s.objtype == "SEQUENCE" for s in result.statements)


def test_grant_all_function_expands() -> None:
    result = MigrationGrantExtractor().extract_grant_statements(
        "GRANT ALL ON FUNCTION s.fn(int) TO r;"
    )
    assert {s.privilege for s in result.statements} == set(_ALL_FUNCTION_PRIVILEGES)


def test_grant_all_schema_expands() -> None:
    result = MigrationGrantExtractor().extract_grant_statements("GRANT ALL ON SCHEMA s TO r;")
    assert {s.privilege for s in result.statements} == set(_ALL_SCHEMA_PRIVILEGES)
    assert all(
        s.objtype == "SCHEMA" and s.object is None and s.schema == "s" for s in result.statements
    )


def test_grant_all_explicit_list_equivalence() -> None:
    """GRANT ALL must yield the same key set as the explicit privilege list."""
    all_form = MigrationGrantExtractor().extract_grant_statements("GRANT ALL ON s.t TO r;")
    explicit = MigrationGrantExtractor().extract_grant_statements(
        "GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON s.t TO r;"
    )
    assert _keys(all_form.statements) == _keys(explicit.statements)


# ---------------------------------------------------------------------------
# Sequence / function / schema objects (pglast)
# ---------------------------------------------------------------------------


def test_sequence_grant_pglast() -> None:
    result = MigrationGrantExtractor().extract_grant_statements(
        "GRANT USAGE ON SEQUENCE s.seq TO r;"
    )
    assert _keys(result.statements) == {("GRANT", "SEQUENCE", "OBJECT", "s", "seq", "r", "USAGE")}


def test_function_grant_includes_signature() -> None:
    """Overloads must be distinguishable: the arg signature is part of the key."""
    a = MigrationGrantExtractor().extract_grant_statements(
        "GRANT EXECUTE ON FUNCTION s.fn(int) TO r;"
    )
    b = MigrationGrantExtractor().extract_grant_statements(
        "GRANT EXECUTE ON FUNCTION s.fn(text) TO r;"
    )
    assert _keys(a.statements) != _keys(b.statements)
    # int and integer normalize identically (pglast canonicalizes to int4).
    c = MigrationGrantExtractor().extract_grant_statements(
        "GRANT EXECUTE ON FUNCTION s.fn(integer) TO r;"
    )
    assert _keys(a.statements) == _keys(c.statements)


def test_function_args_unspecified_is_unrepresentable() -> None:
    """`GRANT EXECUTE ON FUNCTION s.fn` (no parens) can't pin an overload."""
    result = MigrationGrantExtractor().extract_grant_statements(
        "GRANT EXECUTE ON FUNCTION s.fn TO r;"
    )
    assert result.statements == []
    assert any(u.reason == "unmodeled_objtype" for u in result.unrepresentable) or any(
        "overload" in u.detail.lower() or "signature" in u.detail.lower()
        for u in result.unrepresentable
    )


def test_schema_grant_pglast() -> None:
    result = MigrationGrantExtractor().extract_grant_statements("GRANT USAGE ON SCHEMA s TO r;")
    assert _keys(result.statements) == {("GRANT", "SCHEMA", "OBJECT", "s", None, "r", "USAGE")}


# ---------------------------------------------------------------------------
# Schema-wide (ALL ... IN SCHEMA)
# ---------------------------------------------------------------------------


def test_all_tables_in_schema_pglast() -> None:
    result = MigrationGrantExtractor().extract_grant_statements(
        "GRANT SELECT ON ALL TABLES IN SCHEMA s TO r;"
    )
    assert _keys(result.statements) == {
        ("GRANT", "TABLE", "ALL_IN_SCHEMA", "s", None, "r", "SELECT")
    }


def test_all_sequences_in_schema_pglast() -> None:
    result = MigrationGrantExtractor().extract_grant_statements(
        "GRANT USAGE ON ALL SEQUENCES IN SCHEMA s TO r;"
    )
    assert _keys(result.statements) == {
        ("GRANT", "SEQUENCE", "ALL_IN_SCHEMA", "s", None, "r", "USAGE")
    }


def test_all_in_schema_does_not_match_individual_object() -> None:
    """A schema-wide grant is a distinct key from an individual-object grant."""
    wide = MigrationGrantExtractor().extract_grant_statements(
        "GRANT SELECT ON ALL TABLES IN SCHEMA s TO r;"
    )
    one = MigrationGrantExtractor().extract_grant_statements("GRANT SELECT ON s.t TO r;")
    assert _keys(wide.statements).isdisjoint(_keys(one.statements))


# ---------------------------------------------------------------------------
# D12 — grantee case folding is consistent across backends
# ---------------------------------------------------------------------------


def test_grantee_case_folding_unquoted_pglast() -> None:
    upper = MigrationGrantExtractor().extract_grant_statements("GRANT SELECT ON s.t TO Reporter;")
    lower = MigrationGrantExtractor().extract_grant_statements("GRANT SELECT ON s.t TO reporter;")
    assert _keys(upper.statements) == _keys(lower.statements)
    assert next(iter(upper.statements)).grantee == "reporter"


def test_grantee_case_folding_unquoted_regex(monkeypatch: pytest.MonkeyPatch) -> None:
    ext = _regex(monkeypatch)
    upper = ext.extract_grant_statements("GRANT SELECT ON s.t TO Reporter;")
    lower = ext.extract_grant_statements("GRANT SELECT ON s.t TO reporter;")
    assert _keys(upper.statements) == _keys(lower.statements)
    assert next(iter(upper.statements)).grantee == "reporter"


def test_grantee_quoted_preserves_case() -> None:
    result = MigrationGrantExtractor().extract_grant_statements(
        'GRANT SELECT ON s.t TO "Reporter";'
    )
    assert next(iter(result.statements)).grantee == "Reporter"


def test_grantee_public_literal_both_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    pglast_result = MigrationGrantExtractor().extract_grant_statements(
        "GRANT SELECT ON s.t TO public;"
    )
    regex_result = _regex(monkeypatch).extract_grant_statements("GRANT SELECT ON s.t TO PUBLIC;")
    assert next(iter(pglast_result.statements)).grantee == "PUBLIC"
    assert next(iter(regex_result.statements)).grantee == "PUBLIC"


# ---------------------------------------------------------------------------
# grant_option is exposed but EXCLUDED from the match key
# ---------------------------------------------------------------------------


def test_grant_option_excluded_from_match_key() -> None:
    plain = MigrationGrantExtractor().extract_grant_statements("GRANT SELECT ON s.t TO r;")
    with_opt = MigrationGrantExtractor().extract_grant_statements(
        "GRANT SELECT ON s.t TO r WITH GRANT OPTION;"
    )
    # Equal as keys (grant_option is compare=False) ...
    assert set(plain.statements) == set(with_opt.statements)
    # ... but the flag is still readable for Phase 3's "differs only by" check.
    assert next(iter(plain.statements)).grant_option is False
    assert next(iter(with_opt.statements)).grant_option is True


# ---------------------------------------------------------------------------
# D9 — the unrepresentable channel (the load-bearing safety property)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "GRANT CONNECT ON DATABASE foo TO r;",
        "GRANT USAGE ON LANGUAGE plpgsql TO r;",
        "GRANT USAGE ON TYPE s.mytype TO r;",
        "GRANT USAGE ON FOREIGN DATA WRAPPER fdw TO r;",
        "GRANT ALL ON TABLESPACE ts TO r;",
    ],
)
def test_unmodeled_objtype_is_unrepresentable_pglast(sql: str) -> None:
    result = MigrationGrantExtractor().extract_grant_statements(sql)
    assert result.statements == []
    assert any(u.reason == "unmodeled_objtype" for u in result.unrepresentable)


@pytest.mark.parametrize(
    "sql",
    [
        "GRANT CONNECT ON DATABASE foo TO r;",
        "GRANT USAGE ON LANGUAGE plpgsql TO r;",
        "GRANT USAGE ON FOREIGN DATA WRAPPER fdw TO r;",
    ],
)
def test_unmodeled_objtype_is_unrepresentable_regex(
    sql: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _regex(monkeypatch).extract_grant_statements(sql)
    assert result.statements == []
    assert any(u.reason == "unmodeled_objtype" for u in result.unrepresentable)


def test_alter_default_privileges_is_unrepresentable_pglast() -> None:
    result = MigrationGrantExtractor().extract_grant_statements(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA s GRANT SELECT ON TABLES TO r;"
    )
    assert result.statements == []
    assert any(u.reason == "alter_default_privileges" for u in result.unrepresentable)


def test_alter_default_privileges_is_unrepresentable_regex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _regex(monkeypatch).extract_grant_statements(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA s GRANT SELECT ON TABLES TO r;"
    )
    assert result.statements == []
    assert any(u.reason == "alter_default_privileges" for u in result.unrepresentable)


def test_column_level_privileges_is_unrepresentable_pglast() -> None:
    result = MigrationGrantExtractor().extract_grant_statements(
        "GRANT SELECT (col1, col2) ON s.t TO r;"
    )
    assert result.statements == []
    assert any(u.reason == "column_privileges" for u in result.unrepresentable)


def test_column_level_privileges_is_unrepresentable_regex(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _regex(monkeypatch).extract_grant_statements("GRANT SELECT (col1, col2) ON s.t TO r;")
    assert result.statements == []
    assert any(u.reason == "column_privileges" for u in result.unrepresentable)


def test_dynamic_sql_is_unrepresentable() -> None:
    sql = "DO $$ BEGIN EXECUTE format('GRANT SELECT ON %I TO r', 't'); END $$;"
    result = MigrationGrantExtractor().extract_grant_statements(sql)
    assert result.statements == []
    assert any(u.reason == "dynamic_sql" for u in result.unrepresentable)


def test_unmodeled_does_not_swallow_a_neighbouring_table_grant() -> None:
    """A modeled grant alongside an unmodeled one must still be extracted."""
    sql = "GRANT CONNECT ON DATABASE foo TO r;\nGRANT SELECT ON s.t TO r;"
    result = MigrationGrantExtractor().extract_grant_statements(sql)
    assert _keys(result.statements) == {("GRANT", "TABLE", "OBJECT", "s", "t", "r", "SELECT")}
    assert any(u.reason == "unmodeled_objtype" for u in result.unrepresentable)


# ---------------------------------------------------------------------------
# Legacy extract_grants must stay byte-compatible (D6)
# ---------------------------------------------------------------------------


def test_extract_grants_still_table_only_and_grant_only() -> None:
    ext = MigrationGrantExtractor()
    # REVOKE absent from legacy shape.
    assert ext.extract_grants("REVOKE SELECT ON foo FROM r;") == []
    # Sequence/schema/function absent from legacy shape.
    assert ext.extract_grants("GRANT USAGE ON SEQUENCE s.seq TO r;") == []
    assert ext.extract_grants("GRANT USAGE ON SCHEMA s TO r;") == []
    # Table grant still works, unchanged shape.
    assert ext.extract_grants("GRANT SELECT ON s.t TO r;") == [
        ("s", "t", "r", frozenset({"SELECT"}))
    ]
