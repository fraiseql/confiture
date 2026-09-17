"""A database built from its own DDL has no drift — the campaign's control (#301, #302, #303).

Every phase of the live-drift campaign is "make an item go away". Without a
corpus that is red *for the right reasons today*, an item going away is
indistinguishable from a comparison quietly switching itself off. So this module
holds two things and nothing else:

* :func:`test_a_database_built_from_its_ddl_has_no_drift` — the identity run.
  It reported **28** items on 1.10.1, listed in :data:`WAS_ON_1_10_1`, and
  reports none now.
* the mutation table — one real change per row, each asserting that it adds
  **exactly one** drift item of a stated type and severity. The first rows pass
  today and must keep passing through every change; the rest are red because
  the comparison their marker names does not exist yet.

The mutation rows assert on the *difference* a mutation makes, not on the whole
report, so they are independent of how much of the comparison exists yet. Their
targets are chosen to have nothing in the identity baseline — a row whose
mutation changed an item the baseline already carried would measure the
baseline, not the mutation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest

from confiture.core.drift import DriftReport, SchemaDriftDetector
from confiture.core.psql_applier import apply_sql_via_psql

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "live_drift_corpus"

#: What the identity run produced on 1.10.1, kept because the numbers are the
#: measurement this module exists to have made. Every one of them was on a
#: database applied verbatim from the corpus below.
WAS_ON_1_10_1 = """28 items:
  3 missing_table  + 2 extra_table   DROP TABLE / RENAME TO / SET SCHEMA unfolded
  1 missing_column + 1 extra_column  RENAME COLUMN unfolded
  1 missing_column (legacy_drop)     ALTER TABLE DROP COLUMN unfolded
  1 nullable_mismatch (maybe_null)   ALTER COLUMN SET NOT NULL unfolded
  1 type_mismatch (ratio)            ALTER COLUMN TYPE unfolded
 18 type_mismatch on core.tb_types   two type vocabularies

`core.tb_types.c1` (`CHAR`) was *not* among them, and is the corpus' trap for a
comparator: `_types_compatible` folded `char` and `character`, while
`canonical_type` renders the live `character(1)` as `char(1)`. A switch that did
not give a bare `char` its implicit length would have traded eighteen false
positives for one new one.
"""


def corpus_sql() -> str:
    """The whole corpus as one text, in the order the applier reads it."""
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(CORPUS.glob("*.sql")))


@dataclass(frozen=True)
class Built:
    """A database built from the corpus, and the schema file to compare it with."""

    url: str
    schema_file: Path

    def drift(self) -> DriftReport:
        with psycopg.connect(self.url) as conn:
            return SchemaDriftDetector(conn).compare_with_schema_file(str(self.schema_file))

    def apply(self, sql: str) -> None:
        apply_sql_via_psql(self.url, sql=sql)


@pytest.fixture
def built_from_corpus(fresh_database: str, tmp_path: Path) -> Built:
    """The corpus applied to a throwaway database, with no mutation."""
    sql = corpus_sql()
    apply_sql_via_psql(fresh_database, sql=sql)
    schema_file = tmp_path / "schema_corpus.sql"
    schema_file.write_text(sql, encoding="utf-8")
    return Built(url=fresh_database, schema_file=schema_file)


def _keys(report: DriftReport) -> list[tuple[str, str, str]]:
    return sorted(
        (item.drift_type.value, item.severity.value, item.object_name)
        for item in report.drift_items
    )


def test_a_database_built_from_its_ddl_has_no_drift(built_from_corpus: Built) -> None:
    report = built_from_corpus.drift()
    assert report.drift_items == [], "\n".join(
        f"  {i.severity.value:8s} {i.drift_type.value:20s} {i.object_name}: {i.message}"
        for i in report.drift_items
    )


#: ``(mutation SQL, drift type, severity, object)``. A kind of comparison is a
#: row, and a row's marker names the comparison that does not exist yet.
MUTATIONS = [
    pytest.param(
        "ALTER TABLE core.tb_other DROP COLUMN id",
        "missing_column",
        "critical",
        "core.tb_other.id",
        id="drop-column",
    ),
    pytest.param(
        "ALTER TABLE core.tb_other ALTER COLUMN label TYPE VARCHAR(100)",
        "type_mismatch",
        "warning",
        "core.tb_other.label",
        id="retype-column",
    ),
    pytest.param(
        "ALTER TABLE core.tb_other ALTER COLUMN label DROP NOT NULL",
        "nullable_mismatch",
        "warning",
        "core.tb_other.label",
        id="drop-not-null",
    ),
    pytest.param(
        "DROP TABLE core.tb_other",
        "missing_table",
        "critical",
        "core.tb_other",
        id="drop-table",
    ),
    pytest.param(
        "DROP INDEX core.ix_widget_serial",
        "missing_index",
        "warning",
        "core.tb_widget.ix_widget_serial",
        id="drop-index",
    ),
    pytest.param(
        "CREATE TABLE core.tb_surprise (id BIGINT PRIMARY KEY)",
        "extra_table",
        "warning",
        "core.tb_surprise",
        id="extra-table",
    ),
    pytest.param(
        "DROP VIEW core.v_widget",
        "missing_view",
        "critical",
        "core.v_widget",
        id="drop-view",
    ),
    pytest.param(
        "DROP MATERIALIZED VIEW core.mv_widget",
        "missing_matview",
        "critical",
        "core.mv_widget",
        id="drop-matview",
    ),
    pytest.param(
        "DROP TRIGGER trg_touch ON core.tb_widget",
        "missing_trigger",
        "critical",
        "core.tb_widget.trg_touch",
        id="drop-trigger",
    ),
    pytest.param(
        "DROP FUNCTION core.fn_gone(bigint)",
        "missing_routine",
        "critical",
        "core.fn_gone(bigint)",
        id="drop-routine",
    ),
    pytest.param(
        "CREATE VIEW core.v_handmade AS SELECT 1 AS one",
        "extra_view",
        "info",
        "core.v_handmade",
        id="extra-view",
    ),
    pytest.param(
        "CREATE FUNCTION core.fn_handmade() RETURNS int LANGUAGE sql AS $$ SELECT 1 $$",
        "extra_routine",
        "info",
        "core.fn_handmade()",
        id="extra-routine",
    ),
]


@pytest.mark.parametrize(("mutation", "drift_type", "severity", "object_name"), MUTATIONS)
def test_one_mutation_reports_exactly_one_item(
    built_from_corpus: Built,
    mutation: str,
    drift_type: str,
    severity: str,
    object_name: str,
) -> None:
    before = _keys(built_from_corpus.drift())
    built_from_corpus.apply(mutation)
    after = _keys(built_from_corpus.drift())

    added = [key for key in after if key not in before]
    removed = [key for key in before if key not in after]

    assert added == [(drift_type, severity, object_name)], (
        f"{mutation}\n  added:   {added}\n  removed: {removed}"
    )
    assert removed == [], f"{mutation} removed baseline items: {removed}"


def test_an_extra_object_makes_fail_on_warning_exit_one(built_from_corpus: Built) -> None:
    """``has_drift`` counts an INFO item, and ``confiture drift --fail-on-warning``
    exits 1 on ``has_drift``. So a hand-made view in a schema the DDL declares
    fails that flag — as a hand-made *index* already did, since ``extra_index``
    has always been INFO. Pinned rather than discovered in a deploy.
    """
    built_from_corpus.apply("CREATE VIEW core.v_handmade AS SELECT 1 AS one")
    report = built_from_corpus.drift()
    assert report.has_drift is True
    assert report.has_critical_drift is False
    assert report.info_count == 1


def test_a_pristine_database_counts_the_objects_it_compared(built_from_corpus: Built) -> None:
    report = built_from_corpus.drift()
    assert report.drift_items == []
    assert report.objects_checked > 0, report.to_dict()
