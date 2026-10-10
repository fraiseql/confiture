"""The side a tree is once PostgreSQL holds it keeps what only the tree can say.

``schema_sources.materialised_side`` builds the tree on a scratch server and reads
it back, so every slot the catalog answers is PostgreSQL's reading. The catalog
reads a domain, a composite or range type, an aggregate, a policy, a rule and the
other kinds no typed section holds by existence alone: it can say one exists, not
how it is made. The statement a migration creates one with is the tree's, and so
are the notes its read made (two definitions of one object, a name that needs
quotes, an index written before its relation).

The scratch build and the catalog read are replaced here by the model the
catalog gives and the statements it writes, so the merge is tested without a
server.
"""

from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import replace
from typing import Any

import pytest

from confiture.core import schema_sources
from confiture.core.differ import MATERIALISED, SchemaDiffer, Side
from confiture.core.schema_change import ObjectAdded
from confiture.core.schema_model import ObjectRef, SchemaModel, ref_for
from confiture.core.schema_read import SchemaRead, read_text
from confiture.exceptions import DifferError

TREE = """
CREATE DOMAIN posint AS integer CHECK (VALUE > 0);
CREATE TABLE t (id bigint PRIMARY KEY, d posint);
CREATE VIEW v AS SELECT id FROM t;
"""

DOMAIN = ref_for("domain", None, "posint")
VIEW = ref_for("view", None, "v")


class _Scratch:
    """``ExpectedSchemaDB`` with no server: the build is the catalog handed in."""

    def __init__(self, _url: str) -> None:
        pass

    def from_source(self, **_: Any) -> Any:
        return nullcontext(None)


def _catalog(model: SchemaModel, statements: dict[ObjectRef, list]) -> Callable[..., Side]:
    """A ``materialised_side`` whose scratch catalog holds *model* and writes *statements*."""

    def built(read: SchemaRead, **kwargs: Any) -> Side:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(schema_sources, "ExpectedSchemaDB", _Scratch)
            patch.setattr(schema_sources, "read_catalog", lambda *_, **__: model)
            patch.setattr(schema_sources, "catalogued_objects", lambda *_: statements)
            return schema_sources.materialised_side("-- built", "scratch", read=read, **kwargs)

    return built


def _as_catalogued(read: SchemaRead) -> SchemaModel:
    return replace(read.catalogued, source="catalog")


def test_an_object_the_catalog_holds_by_existence_carries_the_trees_statement() -> None:
    read = read_text(TREE)
    side = _catalog(_as_catalogued(read), {})(read)
    assert side.objects[DOMAIN] == read.declared.objects[DOMAIN]


def test_a_statement_the_catalog_gave_is_kept() -> None:
    read = read_text(TREE)
    catalogs = [replace(read.declared.objects[VIEW][0], create_sql="CREATE VIEW v AS SELECT 1")]
    side = _catalog(_as_catalogued(read), {VIEW: catalogs})(read)
    assert side.objects[VIEW] == catalogs


def test_an_object_the_tree_does_not_declare_stays_unstated() -> None:
    read = read_text(TREE)
    built = read_text(TREE + "CREATE DOMAIN other AS text;")
    side = _catalog(_as_catalogued(built), {})(read)
    assert ref_for("domain", None, "other") not in side.objects


def test_the_reads_duplicate_definitions_are_carried() -> None:
    read = read_text(TREE + "CREATE OR REPLACE VIEW v AS SELECT id, d FROM t;")
    side = _catalog(_as_catalogued(read), {})(read)
    assert [w.code for w in side.warnings] == ["DIFFER_402"]


def test_a_name_that_needs_quotes_is_refused_on_the_materialised_side() -> None:
    read = read_text(TREE + 'CREATE TABLE "Quoted" (id int);')
    side = _catalog(_as_catalogued(read), {})(read)
    database = Side(_as_catalogued(read_text("CREATE TABLE t (id bigint PRIMARY KEY);")), {})
    with pytest.raises(DifferError) as refused:
        SchemaDiffer().compare_sides(database, side, replace(MATERIALISED, author="new"))
    assert refused.value.error_code == "DIFFER_403"


def test_a_domain_the_tree_adds_is_an_added_object_with_the_trees_statement() -> None:
    read = read_text(TREE)
    side = _catalog(_as_catalogued(read), {})(read)
    without = "CREATE TABLE t (id bigint PRIMARY KEY); CREATE VIEW v AS SELECT id FROM t;"
    database = Side(_as_catalogued(read_text(without)), {})
    diff = SchemaDiffer().compare_sides(database, side, replace(MATERIALISED, author="new"))
    added = [c for c in diff.changes if isinstance(c, ObjectAdded) and c.ref == DOMAIN]
    assert [c.obj.create_sql for c in added] == [read.declared.objects[DOMAIN][0].create_sql]
    assert [w.code for w in diff.warnings] == []


def test_an_unqualified_object_is_found_in_the_default_schema_it_was_built_in() -> None:
    read = read_text(TREE)
    built = read_text("CREATE SCHEMA app; CREATE DOMAIN app.posint AS integer;")
    side = _catalog(_as_catalogued(built), {})(read, default_schema="app")
    app_domain = ref_for("domain", "app", "posint")
    assert side.objects[app_domain] == read.declared.objects[DOMAIN]


def test_a_tview_option_the_tree_does_not_pin_is_the_trees_not_the_registrys() -> None:
    tree = (
        "CREATE TABLE tb_post (id int PRIMARY KEY);\n"
        "SELECT tviews.pg_tviews_create_or_replace('tv_post', $q$SELECT id FROM tb_post$q$);\n"
    )
    read = read_text(tree)
    (ref,) = read.model.tviews
    registry = replace(read.model.tviews[ref], fillfactor=70)
    built = replace(_as_catalogued(read), tviews={ref: registry})
    side = _catalog(built, {})(read)
    assert side.model.tviews[ref].fillfactor is None
