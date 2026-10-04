"""Drift reports the objects the model holds by existence: one generic pair.

A schema, an extension, a domain, a composite type, a policy, extended statistics and
the other kinds no typed section holds were in the model and compared by ``migrate
diff``, and drift said nothing of them. Now a declared one the database lacks is
``missing_object`` (critical) and one the database holds that the tree does not is
``extra_object`` (info) — of a kind the tree declares, in a schema it declares —
with ``subject.kind`` naming which. The pair is generic on purpose: escalation per
kind is ``subject.kind``'s, and a uniform severity needs no wire name per kind.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import psycopg
import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.drift import DriftType, SchemaDriftDetector
from confiture.core.schema_exporter import load_schema
from confiture.core.schema_model import OTHER_OBJECT_KINDS

runner = CliRunner()

TREE = """
CREATE SCHEMA app;
CREATE DOMAIN app.positive AS integer CHECK (VALUE > 0);
CREATE TYPE app.pair AS (a integer, b integer);
CREATE TABLE app.tb_doc (id bigint PRIMARY KEY, owner text, n app.positive);
ALTER TABLE app.tb_doc ENABLE ROW LEVEL SECURITY;
CREATE POLICY own_docs ON app.tb_doc USING (owner = current_user);
CREATE STATISTICS app.doc_stats ON id, owner FROM app.tb_doc;
"""


def _built(make_database: Callable[[str], str], *statements: str) -> str:
    url = make_database("confiture_other")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(TREE)
        for statement in statements:
            conn.execute(statement)
    return url


def _items(url: str, tree: Path) -> list[tuple[str, str, str | None, str | None]]:
    with psycopg.connect(url) as conn:
        report = SchemaDriftDetector(conn).compare_with_schema_file(str(tree))
    return sorted(
        (
            i.drift_type.value,
            i.severity.value,
            i.subject.kind if i.subject else None,
            i.subject.name if i.subject else None,
        )
        for i in report.drift_items
    )


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    path = tmp_path / "schema.sql"
    path.write_text(TREE)
    return path


def test_a_database_built_from_the_tree_has_no_drift(
    tree: Path, fresh_database_factory: Callable[[str], str]
) -> None:
    assert _items(_built(fresh_database_factory), tree) == []


@pytest.mark.parametrize(
    ("dropped", "kind", "name"),
    [
        ("DROP POLICY own_docs ON app.tb_doc", "policy", "tb_doc.own_docs"),
        ("DROP STATISTICS app.doc_stats", "statistics", "doc_stats"),
        ("DROP TYPE app.pair", "type", "pair"),
    ],
)
def test_a_declared_object_the_database_lacks_is_critical(
    dropped: str, kind: str, name: str, tree: Path, fresh_database_factory: Callable[[str], str]
) -> None:
    url = _built(fresh_database_factory, dropped)
    assert _items(url, tree) == [("missing_object", "critical", kind, name)]


def test_an_object_of_a_declared_kind_the_tree_does_not_hold_is_info(
    tree: Path, fresh_database_factory: Callable[[str], str]
) -> None:
    url = _built(
        fresh_database_factory,
        "CREATE POLICY stray ON app.tb_doc USING (true)",
        "CREATE DOMAIN app.other AS text",
    )
    assert _items(url, tree) == [
        ("extra_object", "info", "domain", "other"),
        ("extra_object", "info", "policy", "tb_doc.stray"),
    ]


def test_a_kind_the_tree_never_declares_is_not_its_business(
    tree: Path, fresh_database_factory: Callable[[str], str]
) -> None:
    url = _built(
        fresh_database_factory,
        "CREATE RULE no_delete AS ON DELETE TO app.tb_doc DO INSTEAD NOTHING",
    )
    assert _items(url, tree) == []


def test_the_default_schema_is_never_extra(
    tree: Path, fresh_database_factory: Callable[[str], str]
) -> None:
    """A test database recreates `public`; a tree that never declares it does not own it."""
    url = _built(fresh_database_factory, "DROP SCHEMA public CASCADE", "CREATE SCHEMA public")
    assert _items(url, tree) == []


def _validator() -> Draft202012Validator:
    """``drift.schema.json``, its ``$ref`` to ``_common.schema.json`` resolved."""
    registry = Registry()
    for name in ("drift.schema.json", "_common.schema.json"):
        resource = Resource.from_contents(load_schema(name), default_specification=DRAFT202012)
        registry = registry.with_resource(uri=name, resource=resource)
    return Draft202012Validator(load_schema("drift.schema.json"), registry=registry)


def test_the_payload_names_the_kind_and_a_schemaless_object_has_no_schema(
    tmp_path: Path, fresh_database_factory: Callable[[str], str]
) -> None:
    """fraisier reads only the flat keys: `object` and `message` name the object and its kind."""
    tree = tmp_path / "schema.sql"
    tree.write_text(TREE + 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";\n')
    url = _built(fresh_database_factory)
    config = tmp_path / "local.yaml"
    config.write_text(f"name: test\ndatabase_url: {url}\n")

    result = runner.invoke(
        app, ["drift", "--config", str(config), "--schema", str(tree), "--format", "json"]
    )
    payload = json.loads(result.stdout)

    _validator().validate(payload)
    (item,) = payload["drift_items"]
    assert (item["type"], item["severity"], item["object"]) == (
        DriftType.MISSING_OBJECT.value,
        "critical",
        "uuid-ossp",
    )
    assert "Extension 'uuid-ossp'" in item["message"]
    assert item["subject"] == {
        "schema": None,
        "relation": None,
        "name": "uuid-ossp",
        "arguments": None,
        "role": None,
        "kind": "extension",
    }


def test_every_kind_the_model_holds_is_published() -> None:
    """``subject.kind`` is an enum in the published schema, so a consumer derives the list."""
    published = load_schema("_common.schema.json")["$defs"]["DriftItem"]["properties"]
    kinds = published["subject"]["properties"]["kind"]["enum"]
    assert set(kinds) == set(OTHER_OBJECT_KINDS)


# ---------------------------------------------------------------------------
# `drift.extra_objects: all` — every stray object, for a deploy gate
# ---------------------------------------------------------------------------


def _all(url: str, tree: Path) -> list[tuple[str, str, str | None, str | None]]:
    with psycopg.connect(url) as conn:
        report = SchemaDriftDetector(conn, extra_objects="all").compare_with_schema_file(str(tree))
    return sorted(
        (
            i.drift_type.value,
            i.severity.value,
            i.subject.kind if i.subject else None,
            i.subject.name if i.subject else None,
        )
        for i in report.drift_items
    )


def test_under_all_a_kind_the_tree_never_declares_is_a_warning(
    tree: Path, fresh_database_factory: Callable[[str], str]
) -> None:
    """The row-level-security case: a rule (or policy) nobody declared appears on a host."""
    url = _built(
        fresh_database_factory,
        "CREATE RULE no_delete AS ON DELETE TO app.tb_doc DO INSTEAD NOTHING",
    )
    assert _items(url, tree) == []
    assert _all(url, tree) == [("extra_object", "warning", "rule", "tb_doc.no_delete")]


def test_under_all_every_extra_object_is_a_warning(
    tree: Path, fresh_database_factory: Callable[[str], str]
) -> None:
    url = _built(fresh_database_factory, "CREATE POLICY stray ON app.tb_doc USING (true)")
    assert _all(url, tree) == [("extra_object", "warning", "policy", "tb_doc.stray")]


def test_under_all_the_default_schema_is_still_not_extra(
    tree: Path, fresh_database_factory: Callable[[str], str]
) -> None:
    url = _built(fresh_database_factory, "DROP SCHEMA public CASCADE", "CREATE SCHEMA public")
    assert _all(url, tree) == []


def test_under_all_a_missing_object_is_what_it_was(
    tree: Path, fresh_database_factory: Callable[[str], str]
) -> None:
    url = _built(fresh_database_factory, "DROP POLICY own_docs ON app.tb_doc")
    assert _all(url, tree) == [("missing_object", "critical", "policy", "tb_doc.own_docs")]


@pytest.mark.parametrize("how", ["flag", "config"])
def test_the_environment_or_the_flag_turns_it_on(
    how: str, tmp_path: Path, tree: Path, fresh_database_factory: Callable[[str], str]
) -> None:
    url = _built(
        fresh_database_factory,
        "CREATE RULE no_delete AS ON DELETE TO app.tb_doc DO INSTEAD NOTHING",
    )
    config = tmp_path / "local.yaml"
    setting = "drift:\n  extra_objects: all\n" if how == "config" else ""
    config.write_text(f"name: test\ndatabase_url: {url}\n{setting}")
    flag = ["--extra-objects", "all"] if how == "flag" else []

    result = runner.invoke(
        app, ["drift", "--config", str(config), "--schema", str(tree), "--format", "json", *flag]
    )
    payload = json.loads(result.stdout)
    _validator().validate(payload)
    assert [(i["type"], i["severity"]) for i in payload["drift_items"]] == [
        ("extra_object", "warning")
    ]
