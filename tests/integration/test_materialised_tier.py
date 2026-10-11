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

import pglast
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


@pytest.mark.parametrize("scratch", [True, False], ids=["flag", "no-flag"])
def test_check_live_drift_reads_the_scratch_url_flag(
    scratch: bool,
    tree: Path,
    test_db_url: str,
    fresh_database_factory: Callable[[str], str],
    tmp_path: Path,
) -> None:
    """``migrate validate --scratch-url`` reaches ``--check-live-drift`` as ``drift``'s does (#723)."""
    config = _config(tmp_path, _built(fresh_database_factory, CHANGED["check"][0]))
    extra = ("--scratch-url", test_db_url) if scratch else ()
    result = runner.invoke(
        app,
        ["migrate", "validate", "--check-live-drift", "--config", str(config),
         "--schema", str(tree), "--format", "json", *extra],
    )  # fmt: skip

    # The changed CHECK is critical drift, so the gate fails only when it sees it.
    assert (result.exit_code != 0) is scratch, result.output
    assert ("constraint_mismatch" in result.stdout) is scratch, result.stdout


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


#: Objects the catalog reads by existence alone, beside a column typed with one.
#: A rule is reported and never written (``-- WARNING: no SQL derived``), at either
#: fidelity, so it is the one change left once the migration is applied.
EXISTENCE_ONLY = """
CREATE DOMAIN posint AS integer CHECK (VALUE > 0);
CREATE TYPE pair AS (a int, b int);
CREATE TYPE span AS RANGE (subtype = int4);
CREATE AGGREGATE total(int) (sfunc = int4pl, stype = int);
CREATE TABLE t (id bigint PRIMARY KEY, c text, d posint);
ALTER TABLE t ENABLE ROW LEVEL SECURITY;
CREATE POLICY p_read ON t FOR SELECT USING (true);
CREATE RULE no_delete AS ON DELETE TO t DO INSTEAD NOTHING;
"""

#: What each existence-only object is created with in the generated migration.
CREATED_WITH = {
    "CreateDomainStmt",
    "CompositeTypeStmt",
    "CreateRangeStmt",
    "DefineStmt",
    "CreatePolicyStmt",
}


def _generated(tree: Path, config: Path, tmp_path: Path, name: str, *extra: str) -> tuple:
    migrations = tmp_path / name
    result = runner.invoke(
        app,
        ["migrate", "diff", "--from", "db", "--to", str(tree), "--config", str(config),
         "--format", "json", "--generate", "--name", name,
         "--migrations-dir", str(migrations), *extra],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    (up,) = migrations.glob("*.up.sql")
    return json.loads(result.stdout), up.read_text()


def _statement_kinds(sql: str) -> set[str]:
    """Every statement *sql* runs, a ``DO`` block's body included."""
    kinds: set[str] = set()
    for raw in pglast.parse_sql(sql):
        stmt = raw.stmt
        if type(stmt).__name__ == "DoStmt":
            body = next(arg.arg.sval for arg in stmt.args if arg.defname == "as")
            inner = body.split("BEGIN", 1)[1].rsplit("EXCEPTION", 1)[0]
            kinds |= _statement_kinds(inner)
        kinds.add(type(stmt).__name__)
    return kinds


def _changed(payload: dict) -> list[tuple[str, str]]:
    """``(type, object)`` of each change, the schema the catalog spells left off."""
    return sorted((c["type"], c["details"].replace("public.", "")) for c in payload["changes"])


def test_a_tree_adding_existence_only_objects_generates_them_under_scratch(
    test_db_url: str, fresh_database_factory: Callable[[str], str], tmp_path: Path
) -> None:
    url = _built(fresh_database_factory, "CREATE TABLE t (id bigint PRIMARY KEY, c text);")
    tree = tmp_path / "schema.sql"
    tree.write_text(EXISTENCE_ONLY)
    config = _config(tmp_path, url)

    structural, _ = _generated(tree, config, tmp_path, "structural")
    materialised, up = _generated(tree, config, tmp_path, "scratch", "--scratch-url", test_db_url)

    assert _changed(materialised) == _changed(structural)
    assert {"ADD_DOMAIN", "ADD_TYPE", "ADD_AGGREGATE", "ADD_POLICY", "ADD_RULE"} <= {
        c["type"] for c in materialised["changes"]
    }
    assert materialised["warnings"] == []
    assert _statement_kinds(up) >= CREATED_WITH

    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(up)
    remaining = [("ADD_RULE", "ADD RULE t.no_delete")]
    assert _changed(_diff_from_db(tree, config)) == remaining
    assert _changed(_diff_from_db(tree, config, "--scratch-url", test_db_url)) == remaining


def test_a_name_that_needs_quotes_is_refused_under_scratch_too(
    test_db_url: str, fresh_database_factory: Callable[[str], str], tmp_path: Path
) -> None:
    url = _built(fresh_database_factory, "CREATE TABLE t (id bigint PRIMARY KEY);")
    tree = tmp_path / "schema.sql"
    tree.write_text('CREATE TABLE t (id bigint PRIMARY KEY);\nCREATE TABLE "Quoted" (id int);\n')

    result = runner.invoke(
        app,
        ["migrate", "diff", "--from", "db", "--to", str(tree),
         "--config", str(_config(tmp_path, url)), "--format", "json",
         "--scratch-url", test_db_url],
    )  # fmt: skip

    assert result.exit_code == 5, result.output
    assert json.loads(result.stdout)["error"]["code"] == "DIFFER_403"


def test_a_duplicate_definition_warns_under_scratch_too(
    test_db_url: str, fresh_database_factory: Callable[[str], str], tmp_path: Path
) -> None:
    url = _built(fresh_database_factory, "CREATE TABLE t (id bigint PRIMARY KEY);")
    tree = tmp_path / "schema.sql"
    tree.write_text(
        "CREATE TABLE t (id bigint PRIMARY KEY);\n"
        "CREATE VIEW v AS SELECT 1 AS a;\n"
        "CREATE OR REPLACE VIEW v AS SELECT 1 AS a, 2 AS b;\n"
    )
    config = _config(tmp_path, url)

    payload = _diff_from_db(tree, config, "--scratch-url", test_db_url)

    assert [w["code"] for w in payload["warnings"]] == ["DIFFER_402"]


_TABLE = "CREATE TABLE t (id bigint PRIMARY KEY);\n"

#: (database, tree, a change without a scratch server, a change with one) — #708.
#: Without one, what an object *is* is compared, and an analysed expression in it
#: (a CHECK, a policy's USING, a rule's action) only for presence, as a table's
#: CHECK is (``analysed_expressions``); with one, everything PostgreSQL stores.
REDEFINED = {
    "domain base type": (
        "CREATE DOMAIN posint AS integer CHECK (VALUE > 0);",
        "CREATE DOMAIN posint AS bigint CHECK (VALUE > 0);",
        True, True,
    ),
    "domain NOT NULL": (
        "CREATE DOMAIN posint AS integer CHECK (VALUE > 0);",
        "CREATE DOMAIN posint AS integer NOT NULL CHECK (VALUE > 0);",
        True, True,
    ),
    "domain CHECK text": (
        "CREATE DOMAIN posint AS integer CHECK (VALUE > 0);",
        "CREATE DOMAIN posint AS integer CHECK (VALUE > 1);",
        False, True,
    ),
    "domain spelled another way": (
        "CREATE DOMAIN posint AS integer CHECK (VALUE > 0);",
        "create domain posint as int4 check (value>0);",
        False, False,
    ),
    "composite attribute type": (
        "CREATE TYPE pair AS (a integer, b text);",
        "CREATE TYPE pair AS (a integer, b integer);",
        True, True,
    ),
    "range subtype": (
        "CREATE TYPE span AS RANGE (subtype = integer);",
        "CREATE TYPE span AS RANGE (subtype = bigint);",
        True, True,
    ),
    "policy command": (
        _TABLE + "CREATE POLICY p ON t FOR SELECT USING (true);",
        _TABLE + "CREATE POLICY p ON t FOR UPDATE USING (true);",
        True, True,
    ),
    "policy USING text": (
        _TABLE + "CREATE POLICY p ON t USING (id > 0);",
        _TABLE + "CREATE POLICY p ON t USING (id > 1);",
        False, True,
    ),
    "policy spelled another way": (
        _TABLE + "CREATE POLICY p ON t AS PERMISSIVE FOR ALL TO PUBLIC USING (id > 0);",
        _TABLE + "CREATE POLICY p ON t USING (id > 0);",
        False, False,
    ),
    "rule event": (
        _TABLE + "CREATE RULE r AS ON INSERT TO t DO INSTEAD NOTHING;",
        _TABLE + "CREATE RULE r AS ON UPDATE TO t DO INSTEAD NOTHING;",
        True, True,
    ),
}  # fmt: skip


@pytest.mark.parametrize("scratch", [False, True], ids=["structural", "materialised"])
@pytest.mark.parametrize("case", sorted(REDEFINED))
def test_a_redefined_object_is_compared_against_a_database(
    case: str,
    scratch: bool,
    test_db_url: str,
    fresh_database_factory: Callable[[str], str],
    tmp_path: Path,
) -> None:
    database, declared, structural, materialised = REDEFINED[case]
    url = _built(fresh_database_factory, database)
    tree = tmp_path / "schema.sql"
    tree.write_text(declared + "\n")
    extra = ("--scratch-url", test_db_url) if scratch else ()

    payload = _diff_from_db(tree, _config(tmp_path, url), *extra)

    changed = [change for change in payload["changes"] if change["type"].startswith("REPLACE_")]
    assert bool(changed) is (materialised if scratch else structural), payload["changes"]


def test_a_redefined_domain_is_drift(
    test_db_url: str, fresh_database_factory: Callable[[str], str], tmp_path: Path
) -> None:
    database, declared, _, _ = REDEFINED["domain base type"]
    url = _built(fresh_database_factory, database)
    tree = tmp_path / "schema.sql"
    tree.write_text(declared + "\n")

    for scratch_url in (None, test_db_url):
        report = _drift(url, tree, scratch_url)
        assert {
            (i.drift_type.value, i.severity.value, i.subject.kind if i.subject else None)
            for i in report.drift_items
        } == {("object_definition_mismatch", "warning", "domain")}


#: A materialized view whose query and unique index both drifted (#701): the tree…
MATVIEW_TREE = """
CREATE TABLE t (id bigint PRIMARY KEY, c text);
CREATE MATERIALIZED VIEW mv AS SELECT id, c FROM t WHERE c IS NOT NULL;
CREATE UNIQUE INDEX ux_mv ON mv (id);
"""
#: …and the database: another query, and no index.
MATVIEW_DATABASE = """
CREATE TABLE t (id bigint PRIMARY KEY, c text);
CREATE MATERIALIZED VIEW mv AS SELECT id, c FROM t;
"""


def _findings(report) -> set[tuple[str, str, str]]:
    return {(i.drift_type.value, i.severity.value, i.object_name) for i in report.drift_items}


@pytest.fixture
def matview_tree(tmp_path: Path) -> Path:
    path = tmp_path / "matview.sql"
    path.write_text(MATVIEW_TREE)
    return path


def test_a_redefined_matview_that_lost_its_unique_index_is_critical_drift(
    matview_tree: Path, test_db_url: str, fresh_database_factory: Callable[[str], str]
) -> None:
    url = _built(fresh_database_factory, MATVIEW_DATABASE)

    materialised = _drift(url, matview_tree, test_db_url)
    structural = _drift(url, matview_tree, None)

    assert _findings(materialised) == {
        ("missing_index", "critical", "public.mv.ux_mv"),
        ("view_definition_mismatch", "warning", "public.mv"),
    }
    assert materialised.fidelity == "materialised"
    # The tiers agree on the index: the scratch server no longer hides it. Only the
    # materialised tier compares the query (#719).
    assert _findings(structural) == {("missing_index", "critical", "public.mv.ux_mv")}


def test_the_drift_command_fails_on_it_with_a_scratch_server(
    matview_tree: Path,
    test_db_url: str,
    fresh_database_factory: Callable[[str], str],
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, _built(fresh_database_factory, MATVIEW_DATABASE))
    result = runner.invoke(
        app,
        ["drift", "--config", str(config), "--schema", str(matview_tree),
         "--scratch-url", test_db_url, "--format", "json"],
    )  # fmt: skip

    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    assert payload["has_drift"] is True
    assert payload["fidelity"] == "materialised"
    assert [(i["type"], i["severity"]) for i in payload["drift_items"]] == [
        ("missing_index", "critical"),
        ("view_definition_mismatch", "warning"),
    ]


def test_check_live_drift_fails_on_it_with_scratch_url_in_the_environment(
    matview_tree: Path,
    test_db_url: str,
    fresh_database_factory: Callable[[str], str],
    tmp_path: Path,
) -> None:
    """What a deploy gate runs: the environment names the scratch server."""
    url = _built(fresh_database_factory, MATVIEW_DATABASE)
    config = _config(tmp_path, url, scratch_url=test_db_url)
    result = runner.invoke(
        app,
        ["migrate", "validate", "--check-live-drift", "--config", str(config),
         "--schema", str(matview_tree), "--format", "json"],
    )  # fmt: skip

    assert result.exit_code != 0, result.output
    assert "ux_mv" in result.stdout
    assert "missing_index" in result.stdout


def test_its_hashes_are_the_ones_check_body_views_reports(
    matview_tree: Path,
    test_db_url: str,
    fresh_database_factory: Callable[[str], str],
    tmp_path: Path,
) -> None:
    """``expected``/``actual`` name the queries as the check that prints them does (#719)."""
    url = _built(fresh_database_factory, MATVIEW_DATABASE)
    (item,) = [
        i
        for i in _drift(url, matview_tree, test_db_url).drift_items
        if i.drift_type is DriftType.VIEW_DEFINITION_MISMATCH
    ]
    result = runner.invoke(
        app,
        ["migrate", "validate", "--check-body-views", "--config", str(_config(tmp_path, url)),
         "--schema", str(matview_tree), "--scratch-url", test_db_url, "--format", "json"],
    )  # fmt: skip

    (found,) = json.loads(result.stdout)["body_drifts"]
    assert (item.expected, item.actual) == (found["source_hash"], found["db_hash"])


def test_a_redefined_matview_with_an_invalid_unique_index_is_the_critical_pair_live(
    test_db_url: str, fresh_database_factory: Callable[[str], str], tmp_path: Path
) -> None:
    """A failed concurrent build over duplicates leaves the matview's unique index INVALID."""
    unique = "CREATE UNIQUE INDEX ux_mv ON mv (c);\n"
    tree = tmp_path / "matview.sql"
    tree.write_text(MATVIEW_TREE.replace("CREATE UNIQUE INDEX ux_mv ON mv (id);\n", unique))
    url = _built(
        fresh_database_factory,
        "CREATE TABLE t (id bigint PRIMARY KEY, c text);\n"
        "INSERT INTO t VALUES (1, 'a'), (2, 'a');\n"
        "CREATE MATERIALIZED VIEW mv AS SELECT id, c FROM t;\n",
    )
    with psycopg.connect(url, autocommit=True) as conn, pytest.raises(psycopg.Error):
        conn.execute(unique.replace("INDEX", "INDEX CONCURRENTLY"))

    report = _drift(url, tree, test_db_url)

    assert _findings(report) == {
        ("missing_index", "critical", "public.mv.ux_mv"),
        ("extra_index", "info", "public.mv.ux_mv"),
        ("view_definition_mismatch", "warning", "public.mv"),
    }
    missing = next(i for i in report.drift_items if i.drift_type is DriftType.MISSING_INDEX)
    assert "INVALID" in missing.message


def test_migrate_diff_still_recreates_it_once(
    matview_tree: Path,
    test_db_url: str,
    fresh_database_factory: Callable[[str], str],
    tmp_path: Path,
) -> None:
    """The recreate writes the index; the index changes it carries are drift's to read."""
    config = _config(tmp_path, _built(fresh_database_factory, MATVIEW_DATABASE))
    payload = _diff_from_db(matview_tree, config, "--scratch-url", test_db_url)
    assert [c["type"] for c in payload["changes"]] == ["REPLACE_MATVIEW"]
