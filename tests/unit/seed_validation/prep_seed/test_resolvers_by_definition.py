"""Resolvers are found by what the schema defines, and read by their tree (#385).

Levels 3-5 took their resolution functions from file names: ``fn_resolve*.sql``.
A tree that names its files ``019201004_fn_resolve_tb_continent.sql`` had none,
and the report read as a pass. Level 3 then read each file's text with two
regexes, with no table schema to compare against, so it could not report
anything either; and every finding named a path it made up.

A resolver is now a routine the schema defines whose name starts
``fn_resolve``, wherever it is written. Level 3 reads its body through the one
fragment reader and the tables through the one model, and every finding names
the file and line the resolver is written on.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from confiture.core import live_catalog
from confiture.core.schema_sources import parse_schema
from confiture.core.seed.validation.prep_seed.level_3_resolvers import Level3ResolutionValidator
from confiture.core.seed.validation.prep_seed.models import (
    PrepSeedPattern,
    PrepSeedViolation,
    ViolationSeverity,
)
from confiture.core.seed.validation.prep_seed.orchestrator import (
    OrchestrationConfig,
    PrepSeedOrchestrator,
)

TABLES = """\
CREATE TABLE prep_seed.tb_manufacturer (id UUID PRIMARY KEY, name TEXT);
CREATE TABLE prep_seed.tb_product (id UUID PRIMARY KEY, fk_manufacturer_id UUID, name TEXT);
CREATE TABLE catalog.tb_manufacturer (
    id UUID UNIQUE, pk_manufacturer BIGINT PRIMARY KEY, name TEXT
);
CREATE TABLE catalog.tb_product (
    id UUID UNIQUE, pk_product BIGINT PRIMARY KEY, fk_manufacturer BIGINT, name TEXT
);
"""


def _plpgsql(name: str, body: str) -> str:
    return (
        f"CREATE FUNCTION {name}() RETURNS void AS $$\nBEGIN\n{body}\nEND;\n$$ LANGUAGE plpgsql;\n"
    )


def _orchestrator(tmp_path: Path, files: dict[str, str], *, max_level: int = 3):
    schema = tmp_path / "schema"
    for name, content in {"00_tables.sql": TABLES, **files}.items():
        path = schema / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    seeds = tmp_path / "seeds"
    seeds.mkdir(exist_ok=True)
    config = OrchestrationConfig(
        max_level=max_level,
        seeds_dir=seeds,
        schema_dir=schema,
        connection=MagicMock() if max_level > 3 else None,
        stop_on_critical=False,
    )
    return PrepSeedOrchestrator(config)


def _level_3(tmp_path: Path, files: dict[str, str]) -> list[PrepSeedViolation]:
    return _orchestrator(tmp_path, files)._run_level_3()


# -- discovery by definition ---------------------------------------------------


@pytest.mark.parametrize(
    "filename",
    [
        "fn_resolve_tb_product.sql",
        "019201001_fn_resolve_tb_product.sql",
        "functions/product.sql",
    ],
)
def test_a_resolver_is_found_whatever_its_file_is_called(tmp_path: Path, filename: str) -> None:
    source = "-- the product resolver\n" + _plpgsql("fn_resolve_tb_product", "PERFORM 1;")
    resolvers = _orchestrator(tmp_path, {filename: source})._resolvers()
    assert [(r.name, Path(r.file).name, r.line) for r in resolvers] == [
        ("fn_resolve_tb_product", Path(filename).name, 2)
    ]


def test_two_resolvers_in_one_file_are_two(tmp_path: Path) -> None:
    source = _plpgsql("fn_resolve_tb_manufacturer", "PERFORM 1;") + _plpgsql(
        "fn_resolve_tb_product", "PERFORM 1;"
    )
    resolvers = _orchestrator(tmp_path, {"resolvers.sql": source})._resolvers()
    assert [(r.name, r.line) for r in resolvers] == [
        ("fn_resolve_tb_manufacturer", 1),
        ("fn_resolve_tb_product", 6),
    ]


def test_a_file_named_for_a_resolver_that_defines_none_is_not_one(tmp_path: Path) -> None:
    files = {"fn_resolve_tb_product.sql": "CREATE TABLE catalog.tb_other (id UUID);\n"}
    assert _orchestrator(tmp_path, files)._resolvers() == []


def test_level_4_reports_the_same_error_whatever_the_file_is_called(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#385's measurement, inverted: the numbered file is checked like the bare one."""
    monkeypatch.setattr(live_catalog, "relation_exists", lambda *_a, **_k: False)
    reports = []
    for filename in ("fn_resolve_tb_widget.sql", "019201001_fn_resolve_tb_widget.sql"):
        root = tmp_path / filename.removesuffix(".sql")
        orchestrator = _orchestrator(
            root, {filename: _plpgsql("fn_resolve_tb_widget", "PERFORM 1;")}, max_level=4
        )
        reports.append([(v.message, Path(v.file_path).name) for v in orchestrator._run_level_4()])
    assert reports == [
        [("Target table catalog.tb_widget does not exist in database", filename)]
        for filename in ("fn_resolve_tb_widget.sql", "019201001_fn_resolve_tb_widget.sql")
    ]


# -- level 3 reads the tree -------------------------------------------------------


CORRECT = "INSERT INTO catalog.tb_product (id, fk_manufacturer, name)\n" + (
    "SELECT p.id, m.pk_manufacturer, p.name\n"
    "FROM prep_seed.tb_product p\n"
    "LEFT JOIN catalog.tb_manufacturer m ON m.id = p.fk_manufacturer_id;"
)


def test_a_resolver_inserting_into_the_wrong_schema_is_drift(tmp_path: Path) -> None:
    body = "INSERT INTO tenant.tb_product (id, name)\nSELECT id, name FROM prep_seed.tb_product;"
    violations = _level_3(tmp_path, {"fn.sql": _plpgsql("fn_resolve_tb_product", body)})
    drift = [v for v in violations if v.pattern is PrepSeedPattern.SCHEMA_DRIFT_IN_RESOLVER]
    assert len(drift) == 1
    assert drift[0].severity is ViolationSeverity.CRITICAL
    assert "tenant.tb_product" in drift[0].message
    assert "catalog.tb_product" in (drift[0].suggestion or "")
    assert (Path(drift[0].file_path).name, drift[0].line_number) == ("fn.sql", 3)


def test_a_resolver_missing_a_join_misses_the_fk(tmp_path: Path) -> None:
    body = (
        "INSERT INTO catalog.tb_product (id, fk_manufacturer, name)\n"
        "SELECT id, NULL, name FROM prep_seed.tb_product;"
    )
    violations = _level_3(tmp_path, {"fn.sql": _plpgsql("fn_resolve_tb_product", body)})
    assert [(v.pattern, v.severity, v.line_number) for v in violations] == [
        (PrepSeedPattern.MISSING_FK_TRANSFORMATION, ViolationSeverity.ERROR, 3)
    ]
    assert "fk_manufacturer_id" in violations[0].message


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(CORRECT, id="alias"),
        pytest.param(
            'INSERT INTO catalog."tb_product" AS t (id, fk_manufacturer, name)\n'
            "SELECT p.id, cat.pk_manufacturer, p.name\n"
            "FROM prep_seed.tb_product AS p\n"
            "JOIN catalog.tb_manufacturer AS cat ON p.fk_manufacturer_id = cat.id;",
            id="quoted-target",
        ),
        pytest.param(
            "INSERT INTO catalog.tb_product (id, fk_manufacturer, name)\n"
            "SELECT p.id, m.pk_manufacturer, p.name\n"
            "FROM prep_seed.tb_product p, catalog.tb_manufacturer m\n"
            "WHERE m.id = p.fk_manufacturer_id;",
            id="comma-join",
        ),
        pytest.param(
            "WITH makers AS (SELECT id, pk_manufacturer FROM catalog.tb_manufacturer)\n"
            "INSERT INTO catalog.tb_product (id, fk_manufacturer, name)\n"
            "SELECT p.id, mk.pk_manufacturer, p.name\n"
            "FROM prep_seed.tb_product p\n"
            "JOIN makers mk ON mk.id = p.fk_manufacturer_id;",
            id="cte",
        ),
        pytest.param(
            "INSERT INTO catalog.tb_product (id, fk_manufacturer, name)\n"
            "SELECT p.id,\n"
            "  (SELECT m.pk_manufacturer FROM catalog.tb_manufacturer m"
            " WHERE m.id = p.fk_manufacturer_id),\n"
            "  p.name\n"
            "FROM prep_seed.tb_product p\n"
            "JOIN prep_seed.tb_manufacturer pm USING (name);",
            id="subquery-and-using",
        ),
    ],
)
def test_a_correct_resolver_is_clean_in_every_shape(tmp_path: Path, body: str) -> None:
    violations = _level_3(tmp_path, {"fn.sql": _plpgsql("fn_resolve_tb_product", body)})
    assert violations == []


def test_a_sql_language_resolver_is_read(tmp_path: Path) -> None:
    source = (
        "CREATE FUNCTION fn_resolve_tb_product() RETURNS void LANGUAGE sql AS $$\n"
        "INSERT INTO catalog.tb_product (id, fk_manufacturer, name)\n"
        "SELECT id, NULL, name FROM prep_seed.tb_product;\n"
        "$$;\n"
    )
    violations = _level_3(tmp_path, {"fn.sql": source})
    assert [(v.pattern, v.line_number) for v in violations] == [
        (PrepSeedPattern.MISSING_FK_TRANSFORMATION, 2)
    ]


@pytest.mark.parametrize(
    ("source", "why"),
    [
        pytest.param(
            _plpgsql("fn_resolve_tb_product", "EXECUTE 'INSERT INTO ' || 'catalog.tb_product';"),
            "built at run time",
            id="dynamic",
        ),
        pytest.param(
            _plpgsql("fn_resolve_tb_product", "INSERT INTO catalog.tb_product SELEC 1;"),
            "did not return its body",
            id="refused-body",
        ),
        pytest.param(
            "CREATE FUNCTION fn_resolve_tb_product() RETURNS void AS $$ pass $$"
            " LANGUAGE plpython3u;\n",
            "plpython3u",
            id="other-language",
        ),
    ],
)
def test_what_level_3_cannot_read_is_a_finding(tmp_path: Path, source: str, why: str) -> None:
    violations = _level_3(tmp_path, {"fn.sql": source})
    assert [(v.pattern, v.severity) for v in violations] == [
        (PrepSeedPattern.RESOLVER_NOT_READ, ViolationSeverity.WARNING)
    ]
    assert "not checked" in violations[0].message
    assert why in violations[0].message
    assert Path(violations[0].file_path).name == "fn.sql"


def test_a_fragment_that_did_not_parse_is_a_finding(tmp_path: Path) -> None:
    """The reader parsed the body but not one statement in it: that statement is named."""
    (resolver,) = _orchestrator(
        tmp_path, {"fn.sql": _plpgsql("fn_resolve_tb_product", "PERFORM 1;")}
    )._resolvers()
    # A body's lines count the schema's joined text: two past the CREATE is line 3.
    unread_at = resolver.body.obj.statement_line + 2
    body = replace(resolver.body, unread=((unread_at, "syntax error at or near x"),))
    violations = Level3ResolutionValidator(parse_schema(TABLES)).validate(
        replace(resolver, body=body)
    )
    assert [(v.pattern, v.line_number) for v in violations] == [
        (PrepSeedPattern.RESOLVER_NOT_READ, 3)
    ]
    assert "1 statement(s) could not be parsed: syntax error at or near x" in violations[0].message


def test_no_finding_names_a_path_it_made_up(tmp_path: Path) -> None:
    body = "INSERT INTO tenant.tb_product (id, name)\nSELECT id, name FROM prep_seed.tb_product;"
    violations = _level_3(tmp_path, {"sub/deep.sql": _plpgsql("fn_resolve_tb_product", body)})
    assert violations
    assert {Path(v.file_path).name for v in violations} == {"deep.sql"}


# -- nothing discovered is not a pass -----------------------------------------------


def test_no_resolver_at_level_3_is_a_warning(tmp_path: Path) -> None:
    report = _orchestrator(tmp_path, {}).run()
    missing = [
        v for v in report.violations if v.pattern is PrepSeedPattern.MISSING_RESOLVER_FUNCTION
    ]
    assert len(missing) == 1
    assert missing[0].severity is ViolationSeverity.WARNING
    assert "no resolution function found in" in missing[0].message


def test_no_resolver_below_level_3_says_nothing(tmp_path: Path) -> None:
    report = _orchestrator(tmp_path, {}, max_level=2).run()
    assert not [
        v for v in report.violations if v.pattern is PrepSeedPattern.MISSING_RESOLVER_FUNCTION
    ]
