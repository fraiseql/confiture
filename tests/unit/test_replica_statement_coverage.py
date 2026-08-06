"""Every statement reaches a verdict — nothing is silently dropped (issue #206).

`window_safe` is computed from the *presence* of ``PFLIGHT_REPLICA_*`` findings,
so a statement the classifier does not recognise is indistinguishable from a
statement it recognised as safe. Before 0.44.0 both backends returned nothing for
anything outside a seven-operation matrix, which certified `DROP TABLE` as
window-safe.

The guard is structural rather than per-statement: the classifier must return at
least one operation for every statement that changes schema or data, and the
fallback for a statement it cannot map is :class:`Other` — which routes to
``PFLIGHT_REPLICA_UNCLASSIFIED``, a warning, so opacity never hard-blocks.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.replica.classifier import OperationClassifier, Other
from confiture.core.replica.safety import classify_replica_safety

# (sql, expected_safety) — one row per statement class outside the original
# seven-operation matrix. "safe" rows must not emit a finding, or widening the
# classifier would trade a false-safe for a wave of false-unsafes.
COVERAGE = {
    # destructive: an N-1 reader still references the object
    "drop_table": ("DROP TABLE tb_user;", "unsafe"),
    "drop_view": ("DROP VIEW v_user;", "unsafe"),
    "drop_matview": ("DROP MATERIALIZED VIEW mv_user;", "unsafe"),
    "drop_sequence": ("DROP SEQUENCE seq_user;", "unsafe"),
    "drop_schema": ("DROP SCHEMA app;", "unsafe"),
    "drop_function": ("DROP FUNCTION fn_user();", "unsafe"),
    "drop_type": ("DROP TYPE mood;", "unsafe"),
    "drop_extension": ("DROP EXTENSION hstore;", "unsafe"),
    "truncate": ("TRUNCATE tb_user;", "unsafe"),
    "revoke": ("REVOKE SELECT ON tb_user FROM app_reader;", "unsafe"),
    "set_not_null": ("ALTER TABLE tb_user ALTER COLUMN email SET NOT NULL;", "unsafe"),
    "rename_table": ("ALTER TABLE tb_user RENAME TO tb_account;", "unsafe"),
    "rename_enum_value": ("ALTER TYPE mood RENAME VALUE 'ok' TO 'fine';", "unsafe"),
    # replacement: confiture cannot tell whether the new body stays compatible
    "replace_view": ("CREATE OR REPLACE VIEW v_user AS SELECT 1 AS a;", "depends"),
    "replace_function": (
        "CREATE OR REPLACE FUNCTION fn_user() RETURNS int AS $$ SELECT 1 $$ LANGUAGE sql;",
        "depends",
    ),
    # additive or reader-invisible: must stay window-safe
    "add_enum_value": ("ALTER TYPE mood ADD VALUE 'ok';", "safe"),
    "create_view": ("CREATE VIEW v_user AS SELECT 1 AS a;", "safe"),
    "create_sequence": ("CREATE SEQUENCE seq_user;", "safe"),
    "create_schema": ("CREATE SCHEMA app;", "safe"),
    "create_type": ("CREATE TYPE mood AS ENUM ('ok');", "safe"),
    "create_extension": ("CREATE EXTENSION hstore;", "safe"),
    "create_function": (
        "CREATE FUNCTION fn_user() RETURNS int AS $$ SELECT 1 $$ LANGUAGE sql;",
        "safe",
    ),
    "drop_index": ("DROP INDEX idx_user_email;", "safe"),
    "drop_constraint": ("ALTER TABLE tb_user DROP CONSTRAINT ck_user;", "safe"),
    "drop_not_null": ("ALTER TABLE tb_user ALTER COLUMN email DROP NOT NULL;", "safe"),
    "set_default": ("ALTER TABLE tb_user ALTER COLUMN active SET DEFAULT true;", "safe"),
    "change_owner": ("ALTER TABLE tb_user OWNER TO app;", "safe"),
    "grant": ("GRANT SELECT ON tb_user TO app_reader;", "safe"),
    "comment": ("COMMENT ON TABLE tb_user IS 'users';", "safe"),
    "insert": ("INSERT INTO tb_user (id) VALUES (1);", "safe"),
    "update": ("UPDATE tb_user SET active = true;", "safe"),
    "delete": ("DELETE FROM tb_user WHERE id = 1;", "safe"),
}


@pytest.mark.parametrize("name", list(COVERAGE))
def test_statement_reaches_a_verdict(name: str) -> None:
    """No statement in the corpus classifies to an empty list."""
    sql, _safety = COVERAGE[name]
    assert OperationClassifier().classify(sql), f"{name}: classified to nothing"


@pytest.mark.parametrize("name", list(COVERAGE))
def test_statement_safety(name: str) -> None:
    sql, safety = COVERAGE[name]
    ops = OperationClassifier().classify(sql)
    verdicts = {classify_replica_safety(op).safety for op in ops}
    assert verdicts == {safety}, f"{name}: {verdicts} != {{{safety!r}}}"


@pytest.mark.parametrize("name", list(COVERAGE))
def test_backends_agree(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """pglast and regex reach the same verdict for every row."""
    sql, _safety = COVERAGE[name]
    ast_ops = OperationClassifier().classify(sql)

    monkeypatch.setenv("CONFITURE_REPLICA_FORCE_REGEX", "1")
    regex_ops = OperationClassifier().classify(sql)

    assert [classify_replica_safety(op).safety for op in ast_ops] == [
        classify_replica_safety(op).safety for op in regex_ops
    ], name


_PLPGSQL_BODY = """\
CREATE OR REPLACE FUNCTION fn_user() RETURNS int AS $$
BEGIN
  PERFORM 1;
  RETURN 2;
END;
$$ LANGUAGE plpgsql;
"""


@pytest.mark.parametrize("force_regex", [False, True], ids=["ast", "regex"])
def test_function_body_is_one_statement(force_regex: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    """A dollar-quoted body is not split on its internal semicolons.

    The regex backend used to shred it and silently drop the fragments. Now that
    an unrecognised fragment becomes `Other`, shredding would emit a spurious
    UNCLASSIFIED finding for every function in a migration — trading #206's
    false-safe for exactly the false-unsafe wave it warned about.
    """
    if force_regex:
        monkeypatch.setenv("CONFITURE_REPLICA_FORCE_REGEX", "1")

    ops = OperationClassifier().classify(_PLPGSQL_BODY)
    assert len(ops) == 1, [type(op).__name__ for op in ops]
    assert not any(isinstance(op, Other) for op in ops)


def test_unrecognised_statement_falls_back_to_other() -> None:
    """A statement outside the matrix produces `Other`, never an empty list.

    This is the property that closes the *class* of bug rather than one instance:
    a statement type nobody thought about still denies.
    """
    ops = OperationClassifier().classify("CREATE STATISTICS st_user ON a, b FROM tb_user;")
    assert ops, "unrecognised statement classified to nothing"
    assert all(isinstance(op, Other) for op in ops)
    assert classify_replica_safety(ops[0]).safety == "depends"


@pytest.mark.parametrize("name", list(COVERAGE))
def test_window_safe_end_to_end(name: str, tmp_path) -> None:
    """The verdict reaches `migrate preflight --format json`'s `window_safe`."""
    sql, safety = COVERAGE[name]
    migrations = tmp_path / name
    migrations.mkdir()
    (migrations / "20260806120000_case.up.sql").write_text(sql)

    result = CliRunner().invoke(
        app,
        ["migrate", "preflight", "--migrations-dir", str(migrations), "--format", "json"],
    )
    payload = json.loads(result.stdout)
    assert payload["window_safe"] is (safety == "safe"), name


def test_add_enum_value_is_window_safe_and_non_transactional(tmp_path) -> None:
    """#199's `ADD VALUE` criterion, as three properties that must hold together.

    Adding an enum value is online-safe, so it must not gate a window — but it
    cannot run inside a transaction block below PostgreSQL 12, so preflight has
    to keep saying so. Reporting only one of the two would be misleading in
    either direction.
    """
    migrations = tmp_path / "enum"
    migrations.mkdir()
    (migrations / "20260806120000_v.up.sql").write_text("ALTER TYPE mood ADD VALUE 'ok';")
    (migrations / "20260806120000_v.down.sql").write_text("SELECT 1;")

    result = CliRunner().invoke(
        app,
        ["migrate", "preflight", "--migrations-dir", str(migrations), "--format", "json"],
    )
    payload = json.loads(result.stdout)

    assert payload["window_safe"] is True
    assert not [i for i in payload["issues"] if i["code"].startswith("PFLIGHT_REPLICA_")]
    assert [i for i in payload["issues"] if i["code"] == "PFLIGHT_NON_TRANSACTIONAL"]
    assert [c for c in payload["change_set"]["changes"] if c["tier"] == "additive"]


def test_drop_table_is_not_window_safe(tmp_path) -> None:
    """#206's headline reproduction, pinned."""
    migrations = tmp_path / "drop"
    migrations.mkdir()
    (migrations / "20260806120000_drop.up.sql").write_text("DROP TABLE tb_user;")

    result = CliRunner().invoke(
        app,
        ["migrate", "preflight", "--migrations-dir", str(migrations), "--format", "json"],
    )
    payload = json.loads(result.stdout)

    assert payload["window_safe"] is False
    assert [i for i in payload["issues"] if i["code"].startswith("PFLIGHT_REPLICA_")]
