"""A database built from its own DDL has no drift — the campaign's control (#301, #302, #303).

Every phase of the live-drift campaign is "make an item go away". Without a
corpus that is red *for the right reasons today*, an item going away is
indistinguishable from a comparison quietly switching itself off. So this module
holds two things and nothing else:

* :func:`test_a_database_built_from_its_ddl_has_no_drift` — the identity run,
  ``xfail(strict=True)`` until the campaign closes. Strict is the point: the
  xfail is the completion signal, and flipping green without removing it fails.
* the mutation table — one real change per row, each asserting that it adds
  **exactly one** drift item of a stated type and severity. The first rows pass
  today and must keep passing through every phase; the rest are the RED of the
  phase named in their marker.

The mutation rows assert on the *difference* a mutation makes, not on the whole
report, so they are independent of how much of the campaign has landed. Their
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

#: The item list the identity run produces on `main` at f93aa8e9 (1.10.1),
#: measured against a live PostgreSQL 18.4 / pglast 8.4. Written out so that a
#: number moving is visible in the diff of this file.
MEASURED_TODAY = """28 items on a database applied verbatim from this corpus:
  3 missing_table  + 2 extra_table   (DROP TABLE / RENAME TO / SET SCHEMA unfolded — phase 03b)
  1 missing_column + 1 extra_column  (RENAME COLUMN unfolded             — phase 03b)
  1 missing_column (legacy_drop)     (ALTER TABLE DROP COLUMN unfolded   — phase 02)
  1 nullable_mismatch (maybe_null)   (ALTER COLUMN SET NOT NULL unfolded — phase 03)
  1 type_mismatch (ratio)            (ALTER COLUMN TYPE unfolded         — phase 02)
 18 type_mismatch on core.tb_types   (two type vocabularies              — phase 04)

`core.tb_types.c1` (`CHAR`) is *not* among them, and is the corpus' trap for
phase 04: `_types_compatible` folds `char` and `character` today, while
`canonical_type` renders the live `character(1)` as `char(1)` and the DDL's bare
`char` as `char`. A comparator switched over without handling an implicit
typmod makes this column report where it never did.
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


@pytest.mark.xfail(strict=True, reason=f"phases 02, 03, 03b and 04 close this.\n{MEASURED_TODAY}")
def test_a_database_built_from_its_ddl_has_no_drift(built_from_corpus: Built) -> None:
    report = built_from_corpus.drift()
    assert report.drift_items == [], "\n".join(
        f"  {i.severity.value:8s} {i.drift_type.value:20s} {i.object_name}: {i.message}"
        for i in report.drift_items
    )


#: ``(mutation SQL, drift type, severity, object)``. Adding a kind in a later
#: phase is a row, and a row's marker names the phase that turns it green.
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
        marks=pytest.mark.xfail(strict=True, reason="phase 05: views are not compared"),
    ),
    pytest.param(
        "DROP MATERIALIZED VIEW core.mv_widget",
        "missing_matview",
        "critical",
        "core.mv_widget",
        id="drop-matview",
        marks=pytest.mark.xfail(strict=True, reason="phase 05: matviews are not compared"),
    ),
    pytest.param(
        "DROP TRIGGER trg_touch ON core.tb_widget",
        "missing_trigger",
        "critical",
        "core.tb_widget.trg_touch",
        id="drop-trigger",
        marks=pytest.mark.xfail(strict=True, reason="phase 05: triggers are not compared"),
    ),
    pytest.param(
        "DROP FUNCTION core.fn_gone(bigint)",
        "missing_routine",
        "critical",
        "core.fn_gone(bigint)",
        id="drop-routine",
        marks=pytest.mark.xfail(strict=True, reason="phase 05: routines are not compared"),
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
