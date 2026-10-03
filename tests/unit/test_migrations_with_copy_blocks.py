"""A migration that loads data with ``COPY … FROM stdin`` is read like any other.

The applier streams a ``COPY`` block's rows to the driver (``psql_applier``), so a
migration may carry one. Its rows are psql client protocol, which PostgreSQL's
parser rejects: every analyser that parsed the migration itself reported it
unparseable, or found nothing in it — the grant check found no ``GRANT``, the
replica classifier no ``ALTER``, the idempotency check flagged nothing. Each is
asked the same question with and without the block, and answers alike.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from confiture.core.cor_extractor import find_cor_targets
from confiture.core.idempotency.patterns import detect_non_idempotent_patterns
from confiture.core.migration_analyzer import MigrationAnalyzer
from confiture.core.migration_grant_extractor import MigrationGrantExtractor
from confiture.core.replica.classifier import OperationClassifier
from confiture.core.tview_preflight import touches_tview

MIGRATION = """\
CREATE TABLE app.tb_country (id bigint PRIMARY KEY, label text);
GRANT SELECT ON app.tb_country TO reader;
CREATE INDEX CONCURRENTLY ix_country_label ON app.tb_country (label);
CREATE OR REPLACE FUNCTION app.fn_count() RETURNS bigint LANGUAGE sql
    AS $$ SELECT count(*) FROM app.tb_country $$;
CREATE TABLE app.tv_country AS SELECT id, label FROM app.tb_country;
"""

COPY_BLOCK = """\
COPY app.tb_country (id, label) FROM stdin;
1\tFrance; DROP TABLE x
2\tCôte d'Ivoire
\\.
"""

ANALYSERS: dict[str, Callable[[str], Any]] = {
    "migration_analyzer": lambda sql: MigrationAnalyzer().analyze(sql),
    "grants": lambda sql: MigrationGrantExtractor().extract_grants(sql),
    "creates": lambda sql: MigrationGrantExtractor().extract_creates(sql),
    "replica": lambda sql: [type(op).__name__ for op in OperationClassifier().classify(sql)],
    "idempotency": lambda sql: [m.pattern for m in detect_non_idempotent_patterns(sql)],
    "create_or_replace": lambda sql: [t.name for t in find_cor_targets(sql)],
    "tview_gate": touches_tview,
}


@pytest.mark.parametrize("analyser", sorted(ANALYSERS))
def test_a_copy_block_changes_no_analyser_s_answer(analyser: str) -> None:
    analyse = ANALYSERS[analyser]
    assert analyse(MIGRATION + COPY_BLOCK) == analyse(MIGRATION)
