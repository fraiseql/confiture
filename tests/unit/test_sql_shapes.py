"""The shape table: what every analyzer says about the awkward identifiers.

One fixture per shape under ``tests/fixtures/sql_shapes/``; one expected answer
per analyzer. A quoted identifier keeps its case and its spaces — PostgreSQL
treats ``"MyTable"`` and ``mytable`` as different relations, so must every
verdict that names one. DDL inside a function body is the body's business, not
a statement of the file. Widen the table when a shape is added; a row that
regresses fails here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from confiture.core.change_set import classify_statements
from confiture.core.idempotency.patterns import detect_non_idempotent_patterns
from confiture.core.linting.schema_linter import LintConfig, SchemaLinter
from confiture.core.replica.classifier import OperationClassifier

SHAPES = Path(__file__).resolve().parents[1] / "fixtures" / "sql_shapes"

# shape → {analyzer → expected}
EXPECTED: dict[str, dict[str, list]] = {
    "quoted_mixed_case_table": {
        "idempotency": [("CREATE_TABLE", 1)],
        "replica": [("CreateTable", "MyTable"), ("Benign", None)],
        "change_set": [
            ("create_table", "public.MyTable", "additive"),
            ("comment", "public.MyTable", "reversible"),
        ],
        "lint": [("naming_001", "MyTable")],
    },
    "quoted_table_with_space": {
        "idempotency": [("CREATE_TABLE", 1)],
        "replica": [("CreateTable", "My Table"), ("Benign", None)],
        "change_set": [
            ("create_table", "public.My Table", "additive"),
            ("comment", "public.My Table", "reversible"),
        ],
        "lint": [("naming_001", "My Table")],
    },
    "semicolon_in_identifier": {
        "idempotency": [("CREATE_TABLE", 1)],
        "replica": [("CreateTable", "a;b"), ("Benign", None)],
        "change_set": [
            ("create_table", "public.a;b", "additive"),
            ("comment", "public.a;b", "reversible"),
        ],
        "lint": [("naming_001", "a;b")],
    },
    "unnamed_index": {
        "idempotency": [("CREATE_TABLE", 1), ("CREATE_INDEX", 3)],
        "replica": [("CreateTable", "tb_events"), ("Benign", None), ("CreateIndex", "tb_events")],
        "change_set": [
            ("create_table", "public.tb_events", "additive"),
            ("comment", "public.tb_events", "reversible"),
            ("create_index", "public.tb_events", "lock_risky"),
        ],
        "lint": [],
    },
    "qualified_names": {
        "idempotency": [("CREATE_TABLE", 1), ("CREATE_INDEX", 3)],
        "replica": [
            ("CreateTable", "tenant.tb_thing"),
            ("Benign", None),
            ("CreateIndex", "tenant.tb_thing"),
        ],
        "change_set": [
            ("create_table", "tenant.tb_thing", "additive"),
            ("comment", "tenant.tb_thing", "reversible"),
            ("create_index", "tenant.tb_thing.idx_thing_name", "lock_risky"),
        ],
        "lint": [],
    },
    "ddl_inside_dollar_body": {
        "idempotency": [("CREATE_OR_REPLACE_FUNCTION_SHAPE_RISK", 1)],
        "replica": [("ReplaceObject", "public.make_scratch")],
        "change_set": [("replace_function", "public.make_scratch", "reversible")],
        "lint": [("doc_002", "public.make_scratch()")],
    },
    "nested_dollar_tags": {
        "idempotency": [("CREATE_OR_REPLACE_FUNCTION_SHAPE_RISK", 1)],
        "replica": [("ReplaceObject", "public.run_it")],
        "change_set": [("replace_function", "public.run_it", "reversible")],
        "lint": [("doc_002", "public.run_it()")],
    },
    "literal_with_dashes": {
        "idempotency": [("CREATE_TABLE", 1)],
        "replica": [("Benign", "tb_log"), ("CreateTable", "tb_after"), ("Benign", None)],
        "change_set": [
            ("insert", "public.tb_log", "additive"),
            ("create_table", "public.tb_after", "additive"),
            ("comment", "public.tb_after", "reversible"),
        ],
        "lint": [],
    },
}

ANALYZERS = {
    "idempotency": lambda sql: [
        (m.pattern.name, m.line_number) for m in detect_non_idempotent_patterns(sql)
    ],
    "replica": lambda sql: [
        (type(op).__name__, op.table) for op in OperationClassifier().classify(sql)
    ],
    "change_set": lambda sql: [
        (e.kind, e.object, e.tier.value if e.tier else None) for e in classify_statements(sql)
    ],
    "lint": lambda sql: sorted(
        (v.rule_id, v.object_name)
        for r in [SchemaLinter(config=LintConfig(enabled=True)).lint(schema=sql)]
        for v in r.errors + r.warnings + r.info
    ),
}


def test_every_fixture_has_a_row_and_every_row_a_fixture() -> None:
    fixtures = {p.stem for p in SHAPES.glob("*.sql")}
    assert fixtures == set(EXPECTED), fixtures ^ set(EXPECTED)


@pytest.mark.parametrize("analyzer", sorted(ANALYZERS), ids=sorted(ANALYZERS))
@pytest.mark.parametrize("shape", sorted(EXPECTED), ids=sorted(EXPECTED))
def test_shape(shape: str, analyzer: str) -> None:
    sql = (SHAPES / f"{shape}.sql").read_text(encoding="utf-8")
    assert ANALYZERS[analyzer](sql) == EXPECTED[shape][analyzer]
