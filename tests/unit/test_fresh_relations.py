"""An operation on a relation the same migration creates is judged as such (#692).

``CREATE TABLE t (…); CREATE INDEX ix ON t (c);`` blocks no reader or writer: no
session outside the migration can see ``t`` yet. The replica verdict, the
change-set tier, the lock profile and the expand/contract planner read the same
fact from one scope (``migration_scope.Scope.exempts``), so they cannot disagree
(ARCHITECTURE Decision 9). Every case below that could reach a relation that
existed before stays flagged.
"""

import pytest

from confiture.core.change_set import classify_statements
from confiture.core.expand_contract import plan
from confiture.core.replica.classifier import OperationClassifier
from confiture.core.replica.safety import classify_replica_safety
from confiture.core.risk_tier import RiskTier

T = "CREATE TABLE t (id int PRIMARY KEY, c text);\n"

#: A migration that creates ``t``, and one operation on it that reaches nothing else.
EXEMPT_CASES: dict[str, str] = {
    "index": T + "CREATE INDEX ix_t_c ON t (c);",
    "unique index": T + "CREATE UNIQUE INDEX ux_t_c ON t (c);",
    "add column not null default": T + "ALTER TABLE t ADD COLUMN at timestamptz NOT NULL DEFAULT now();",
    "add check": T + "ALTER TABLE t ADD CONSTRAINT ck_c CHECK (c <> '');",
    "set not null": T + "ALTER TABLE t ALTER COLUMN c SET NOT NULL;",
    "type change": T + "ALTER TABLE t ALTER COLUMN c TYPE varchar(10);",
    "drop column": T + "ALTER TABLE t DROP COLUMN c;",
    "rename column": T + "ALTER TABLE t RENAME COLUMN c TO d;",
    "rename table": T + "ALTER TABLE t RENAME TO u;",
    "truncate": T + "TRUNCATE t;",
    "drop table": T + "DROP TABLE t;",
    "foreign key onto a created table": T
    + "CREATE TABLE u (id int, tid int);\n"
    "ALTER TABLE u ADD CONSTRAINT fk_u_t FOREIGN KEY (tid) REFERENCES t (id);",
    "qualified": "CREATE TABLE app.t (id int, c text);\nCREATE INDEX ix ON app.t (c);",
    "matview": "CREATE MATERIALIZED VIEW mv AS SELECT 1 AS id;\n"
    "CREATE UNIQUE INDEX ux_mv ON mv (id);\nREFRESH MATERIALIZED VIEW mv;",
    "table as": "CREATE TABLE t AS SELECT 1 AS id;\nCREATE INDEX ix ON t (id);",
    "tview": "SELECT tviews.pg_tviews_create('tv_a', 'SELECT 1 AS id');\n"
    "CREATE INDEX ix ON tv_a (id);",
}  # fmt: skip

#: A migration whose last operation may reach a relation that existed before.
FLAGGED_CASES: dict[str, str] = {
    "index alone": "CREATE INDEX ix ON t (c);",
    "index on another table": T + "CREATE INDEX ix ON other (c);",
    "index on another schema's t": T + "CREATE INDEX ix ON app.t (c);",
    "index on the qualified spelling": T + "CREATE INDEX ix ON public.t (c);",
    "after a search_path change": T + "SET search_path = app;\nCREATE INDEX ix ON t (c);",
    "after a drop under another spelling": T
    + "DROP TABLE public.t;\nCREATE TABLE public.t (c text);\nCREATE INDEX ix ON t (c);",
    "if not exists": "CREATE TABLE IF NOT EXISTS t (c text);\nCREATE INDEX ix ON t (c);",
    "after a function call": T + "SELECT make_things();\nCREATE INDEX ix ON t (c);",
    "after a DO block": T + "DO $$ BEGIN PERFORM 1; END $$;\nCREATE INDEX ix ON t (c);",
    "partition of an existing table": "CREATE TABLE t PARTITION OF p FOR VALUES IN (1);\n"
    "CREATE INDEX ix ON t (c);",
    "foreign key onto an existing table": T
    + "ALTER TABLE t ADD CONSTRAINT fk FOREIGN KEY (c) REFERENCES existing (c);",
    "truncate cascade": T + "TRUNCATE t CASCADE;",
    "drop of a table holding a key to an existing one": "CREATE TABLE u (tid int REFERENCES existing (id));\n"
    "DROP TABLE u;",
    "create or replace a tview": "SELECT tviews.pg_tviews_create_or_replace('tv_a', 'SELECT 1 AS id');\n"
    "CREATE INDEX ix ON tv_a (id);",
}  # fmt: skip


def _last_replica_safety(sql: str) -> str:
    return classify_replica_safety(OperationClassifier().classify(sql)[-1]).safety


def _last_entry(sql: str):
    return classify_statements(sql)[-1]


@pytest.mark.parametrize("case", sorted(EXEMPT_CASES))
def test_an_operation_on_a_created_relation_is_replica_safe(case: str) -> None:
    assert _last_replica_safety(EXEMPT_CASES[case]) == "safe"


@pytest.mark.parametrize("case", sorted(EXEMPT_CASES))
def test_an_operation_on_a_created_relation_is_additive(case: str) -> None:
    assert _last_entry(EXEMPT_CASES[case]).tier is RiskTier.ADDITIVE


@pytest.mark.parametrize("case", sorted(EXEMPT_CASES))
def test_an_operation_on_a_created_relation_blocks_nothing(case: str) -> None:
    lock = _last_entry(EXEMPT_CASES[case]).lock
    assert lock is not None
    assert not lock.blocks_reads
    assert not lock.blocks_writes


@pytest.mark.parametrize("case", sorted(EXEMPT_CASES))
def test_an_operation_on_a_created_relation_needs_no_expand_contract(case: str) -> None:
    assert plan(EXEMPT_CASES[case]) == []


@pytest.mark.parametrize("case", sorted(FLAGGED_CASES))
def test_an_operation_that_may_reach_an_existing_relation_stays_flagged(case: str) -> None:
    sql = FLAGGED_CASES[case]
    assert _last_replica_safety(sql) != "safe"
    assert _last_entry(sql).tier is not RiskTier.ADDITIVE


def test_an_index_before_its_table_stays_flagged() -> None:
    sql = "CREATE INDEX ix ON t (c);\n" + T
    assert classify_replica_safety(OperationClassifier().classify(sql)[0]).safety != "safe"
    assert classify_statements(sql)[0].tier is not RiskTier.ADDITIVE


def test_the_entry_says_why() -> None:
    entry = _last_entry(EXEMPT_CASES["index"])
    assert entry.detail == "CREATE INDEX — on a relation this migration creates"


def test_the_replica_operation_carries_its_provenance() -> None:
    *_, index = OperationClassifier().classify(EXEMPT_CASES["index"])
    assert index.fresh
    *_, flagged = OperationClassifier().classify(FLAGGED_CASES["index on another table"])
    assert not flagged.fresh
