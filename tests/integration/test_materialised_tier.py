"""With a scratch server, the tree is read back from PostgreSQL before it is compared.

The structural tier compares a tree with a database through the parity rules, and
one of them, ``analysed_expressions``, reduces a CHECK, an index expression or a
partial index's predicate to *one exists*: PostgreSQL stores each analysed, so its
text cannot be compared with the text the DDL wrote. Two unnamed CHECKs are then
paired by position, and a changed one is no change.

The materialised tier builds the tree into a scratch database (``ExpectedSchemaDB``)
and reads it with ``live_catalog``, so both sides are PostgreSQL's spelling and the
text compares exactly: a real change in each slot is a change, a spelling is not,
and the payload says which tier ran (``fidelity``).
"""

import json
from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.drift import DriftType, SchemaDriftDetector
from confiture.exceptions import DifferError

runner = CliRunner()

#: A tree whose expressions PostgreSQL re-spells: each comes back parenthesised.
TREE = """
CREATE TABLE t (
    a integer,
    b integer,
    CHECK (a > 0 AND b > 0),
    CHECK (a < 100)
);
CREATE INDEX t_a_idx ON t (a) WHERE a > 0 AND b > 0;
CREATE VIEW v AS SELECT a FROM t WHERE b > 0 AND a > 0;
"""

#: The tree with one slot changed, and the drift each change is. PostgreSQL gives
#: an unnamed CHECK one name in both databases, so a changed one is that name's
#: ``constraint_mismatch``.
CHANGED = {
    "check": (
        TREE.replace("CHECK (a > 0 AND b > 0)", "CHECK (a > 0 AND b > 1)"),
        {DriftType.CONSTRAINT_MISMATCH},
    ),
    "predicate": (
        TREE.replace("WHERE a > 0 AND b > 0;", "WHERE a > 0 AND b > 1;"),
        {DriftType.MISSING_INDEX, DriftType.EXTRA_INDEX},
    ),
}


def _built(make_database: Callable[[str], str], sql: str) -> str:
    url = make_database("confiture_tier")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql)
    return url


def _drift(url: str, tree: Path, scratch_url: str | None):
    with psycopg.connect(url) as conn:
        return SchemaDriftDetector(conn, scratch_url=scratch_url).compare_with_schema_file(
            str(tree)
        )


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    path = tmp_path / "schema.sql"
    path.write_text(TREE)
    return path


def test_a_database_built_from_the_tree_has_no_drift(
    tree: Path, test_db_url: str, fresh_database_factory: Callable[[str], str]
) -> None:
    report = _drift(_built(fresh_database_factory, TREE), tree, test_db_url)
    assert report.drift_items == []
    assert report.fidelity == "materialised"


@pytest.mark.parametrize("slot", sorted(CHANGED))
def test_a_changed_expression_is_drift(
    slot: str, tree: Path, test_db_url: str, fresh_database_factory: Callable[[str], str]
) -> None:
    sql, kinds = CHANGED[slot]
    url = _built(fresh_database_factory, sql)

    materialised = _drift(url, tree, test_db_url)
    structural = _drift(url, tree, None)

    assert {item.drift_type for item in materialised.drift_items} == kinds
    # The control: what the structural tier cannot see is why the other exists.
    assert structural.drift_items == []
    assert structural.fidelity == "structural"


def _config(tmp_path: Path, url: str, scratch_url: str | None = None) -> Path:
    config = tmp_path / "local.yaml"
    scratch = f"scratch_url: {scratch_url}\n" if scratch_url else ""
    config.write_text(f"name: test\ndatabase_url: {url}\n{scratch}")
    return config


def _diff_from_db(tree: Path, config: Path, *extra: str) -> dict:
    result = runner.invoke(
        app,
        ["migrate", "diff", "--from", "db", "--to", str(tree), "--config", str(config),
         "--format", "json", *extra],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_a_changed_view_body_is_a_change_to_migrate_diff(
    tree: Path, test_db_url: str, fresh_database_factory: Callable[[str], str], tmp_path: Path
) -> None:
    url = _built(fresh_database_factory, TREE.replace("WHERE b > 0 AND a > 0", "WHERE b > 1"))
    config = _config(tmp_path, url)

    materialised = _diff_from_db(tree, config, "--scratch-url", test_db_url)
    structural = _diff_from_db(tree, config)

    assert [c["type"] for c in materialised["changes"]] == ["REPLACE_VIEW"]
    assert materialised["fidelity"] == "materialised"
    assert structural["changes"] == []
    assert "fidelity" not in structural


def test_the_environment_names_the_scratch_server(
    tree: Path, test_db_url: str, fresh_database_factory: Callable[[str], str], tmp_path: Path
) -> None:
    url = _built(fresh_database_factory, CHANGED["check"][0])
    config = _config(tmp_path, url, scratch_url=test_db_url)

    result = runner.invoke(
        app, ["drift", "--config", str(config), "--schema", str(tree), "--format", "json"]
    )

    payload = json.loads(result.stdout)
    assert payload["fidelity"] == "materialised"
    assert [item["type"] for item in payload["drift_items"]] == ["constraint_mismatch"]
    assert _diff_from_db(tree, config)["fidelity"] == "materialised"


def test_without_a_scratch_server_drift_says_nothing_new(
    tree: Path, fresh_database_factory: Callable[[str], str], tmp_path: Path
) -> None:
    """The structural tier is the default, and the payload is the one it always was."""
    config = _config(tmp_path, _built(fresh_database_factory, TREE))
    result = runner.invoke(
        app, ["drift", "--config", str(config), "--schema", str(tree), "--format", "json"]
    )
    assert result.exit_code == 0, result.output
    assert "fidelity" not in json.loads(result.stdout)


def test_an_unqualified_name_lands_in_the_default_schema_on_the_scratch_server(
    test_db_url: str, fresh_database_factory: Callable[[str], str], tmp_path: Path
) -> None:
    """``--default-schema app``: the scratch build puts ``t`` where the database has it."""
    tree = "CREATE SCHEMA app;\nCREATE TABLE t (a integer CHECK (a > 0 AND a < 10));\n"
    url = fresh_database_factory("confiture_tier")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("CREATE SCHEMA app")
        conn.execute("CREATE TABLE app.t (a integer CHECK (a > 0 AND a < 10))")
    path = tmp_path / "schema.sql"
    path.write_text(tree)

    with psycopg.connect(url) as conn:
        report = SchemaDriftDetector(conn, scratch_url=test_db_url).compare_with_schema_file(
            str(path), default_schema="app"
        )

    assert report.drift_items == []
    assert report.tables_checked == 1


def test_a_fragment_is_refused_before_it_is_built(
    test_db_url: str, fresh_database_factory: Callable[[str], str], tmp_path: Path
) -> None:
    """An index on a relation the tree does not declare is ``DIFFER_406``, not a build error."""
    url = _built(fresh_database_factory, "CREATE TABLE tv_product (id int, data jsonb);")
    fragment = tmp_path / "fragment.sql"
    fragment.write_text("CREATE INDEX ix_tv_product_id ON tv_product (id);")

    result = runner.invoke(
        app,
        ["migrate", "diff", "--from", "db", "--to", str(fragment),
         "--config", str(_config(tmp_path, url)), "--format", "json",
         "--scratch-url", test_db_url],
    )  # fmt: skip

    assert result.exit_code == 5, result.output
    assert json.loads(result.stdout)["error"]["code"] == "DIFFER_406"


@pytest.mark.parametrize("scratch", [True, False])
def test_drift_refuses_a_fragment_too(
    scratch: bool, test_db_url: str, fresh_database_factory: Callable[[str], str], tmp_path: Path
) -> None:
    url = _built(fresh_database_factory, "CREATE TABLE tv_product (id int, data jsonb);")
    fragment = tmp_path / "fragment.sql"
    fragment.write_text("CREATE INDEX ix_tv_product_id ON tv_product (id);")

    with pytest.raises(DifferError) as refused:
        _drift(url, fragment, test_db_url if scratch else None)

    assert refused.value.error_code == "DIFFER_406"
