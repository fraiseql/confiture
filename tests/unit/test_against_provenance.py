"""Under ``--against``, an ``IF NOT EXISTS`` create of a relation the database lacks is a creation (#692).

Without a database, ``CREATE TABLE IF NOT EXISTS t`` proves nothing: ``t`` may
already exist, and an index on it then locks a table other sessions use. With the
``--against`` database's relations read live (``migration_scope.Present``, plain
data), a ``t`` the database does not hold — once the pending migrations before it
are folded — is created by the statement, and judged as a plain ``CREATE TABLE``
is. Anything the fold cannot read forgets what it knew, so nothing after it is
proven absent; an unqualified name lands in the live ``current_schema()``.
"""

from pathlib import Path

import pytest

from confiture.core.change_set import build_change_set, classify_statements
from confiture.core.migration_scope import Present, leaves, walk
from confiture.core.preflight import pending_starts
from confiture.core.replica.classifier import OperationClassifier
from confiture.core.replica.safety import classify_replica_safety
from confiture.core.risk_tier import RiskTier
from confiture.core.schema_facts import SchemaFacts

INE = "CREATE TABLE IF NOT EXISTS t (id int, c text);\n"
INDEX = "CREATE INDEX ix_t_c ON t (c);"

#: A database holding ``public.big`` and nothing named ``t``.
EMPTY = Present(relations=frozenset({("public", "big")}), current_schema="public")
#: One that holds ``public.t``.
HOLDS_T = Present(
    relations=frozenset({("public", "big"), ("public", "t")}), current_schema="public"
)


def _fresh_before_last(sql: str, start: Present | None) -> bool:
    *_, last = walk(sql, start=start)
    return last.before.fresh(None, "t") is not None


def _replica_safe(sql: str, start: Present | None) -> bool:
    *_, last = OperationClassifier().classify(sql, start=start)
    return classify_replica_safety(last).safety == "safe"


def _tier(sql: str, start: Present | None) -> RiskTier | None:
    return classify_statements(sql, start=start)[-1].tier


# --------------------------------------------------------------------------- scope


def test_without_a_database_if_not_exists_proves_nothing() -> None:
    assert not _fresh_before_last(INE + INDEX, None)


def test_a_relation_the_database_lacks_is_created() -> None:
    assert _fresh_before_last(INE + INDEX, EMPTY)


def test_a_relation_the_database_holds_is_not() -> None:
    assert not _fresh_before_last(INE + INDEX, HOLDS_T)


def test_an_unqualified_name_lands_in_the_live_current_schema() -> None:
    """Never folded to ``public``: ``public.t`` exists, ``app.t`` does not."""
    in_app = Present(relations=frozenset({("public", "t")}), current_schema="app")
    assert _fresh_before_last(INE + INDEX, in_app)
    held_in_app = Present(relations=frozenset({("app", "t")}), current_schema="app")
    assert not _fresh_before_last(INE + INDEX, held_in_app)


def test_a_qualified_name_is_read_as_written() -> None:
    in_app = Present(relations=frozenset({("public", "t")}), current_schema="app")
    sql = "CREATE TABLE IF NOT EXISTS public.t (c text);\nCREATE INDEX ix ON public.t (c);"
    *_, last = walk(sql, start=in_app)
    assert last.before.fresh("public", "t") is None


def test_the_creation_matches_only_as_written() -> None:
    """A loosening fact: ``t`` created never exempts ``public.t``."""
    sql = INE + "CREATE INDEX ix ON public.t (c);"
    assert not _replica_safe(sql, EMPTY)


@pytest.mark.parametrize(
    "create",
    [
        "CREATE TABLE IF NOT EXISTS t AS SELECT 1 AS id;\n",
        "CREATE MATERIALIZED VIEW IF NOT EXISTS t AS SELECT 1 AS id;\n",
    ],
)
def test_a_populated_if_not_exists_create_is_created_too(create: str) -> None:
    assert _fresh_before_last(create + "CREATE INDEX ix ON t (id);", EMPTY)


@pytest.mark.parametrize(
    "before",
    [
        "SELECT make_things();\n",
        "DO $$ BEGIN PERFORM 1; END $$;\n",
        "CALL make_things();\n",
        "EXECUTE prepared;\n",
        "SET search_path = app;\n",
        "SELECT set_config('search_path', 'app', false);\n",
        "CREATE EXTENSION IF NOT EXISTS things;\n",
    ],
)
def test_a_statement_the_fold_cannot_read_forgets_what_was_absent(before: str) -> None:
    assert not _fresh_before_last(before + INE + INDEX, EMPTY)


def test_a_rename_onto_the_name_makes_it_held() -> None:
    assert not _fresh_before_last("ALTER TABLE big RENAME TO t;\n" + INE + INDEX, EMPTY)


def test_a_rename_from_a_schema_the_fold_cannot_place_holds_the_name_everywhere() -> None:
    """``big`` is not in the current schema: whichever schema it is in now holds ``t``."""
    in_app = Present(relations=frozenset({("public", "big")}), current_schema="app")
    sql = "ALTER TABLE big RENAME TO t;\nCREATE TABLE IF NOT EXISTS public.t (c text);\n"
    *_, last = walk(sql + "CREATE INDEX ix ON public.t (c);", start=in_app)
    assert last.before.fresh("public", "t") is None


def test_a_drop_makes_it_absent() -> None:
    assert _fresh_before_last("DROP TABLE t;\n" + INE + INDEX, HOLDS_T)


def test_a_drop_under_the_qualified_spelling_makes_it_absent() -> None:
    assert _fresh_before_last("DROP TABLE public.t;\n" + INE + INDEX, HOLDS_T)


def test_a_drop_in_another_schema_does_not() -> None:
    assert not _fresh_before_last("DROP TABLE app.t;\n" + INE + INDEX, HOLDS_T)


def test_dropping_the_schema_makes_its_relations_absent() -> None:
    held = Present(relations=frozenset({("app", "t")}), current_schema="public")
    sql = "DROP SCHEMA app CASCADE;\nCREATE TABLE IF NOT EXISTS app.t (c text);\n"
    *_, last = walk(sql + "CREATE INDEX ix ON app.t (c);", start=held)
    assert last.before.fresh("app", "t") is not None


def test_set_schema_moves_the_name() -> None:
    held = Present(relations=frozenset({("public", "t")}), current_schema="public")
    sql = "ALTER TABLE t SET SCHEMA app;\n" + INE + INDEX
    assert _fresh_before_last(sql, held)
    onto = Present(relations=frozenset({("other", "t")}), current_schema="public")
    sql = "ALTER TABLE other.t SET SCHEMA public;\n" + INE + INDEX
    assert not _fresh_before_last(sql, onto)


@pytest.mark.parametrize(
    "before",
    [
        "CREATE VIEW t AS SELECT 1 AS c;\n",
        "CREATE SEQUENCE t;\n",
        "CREATE INDEX t ON big (id);\n",
        "CREATE TYPE t AS (c text);\n",
        "SELECT 1 AS c INTO t;\n",
    ],
)
def test_a_relation_an_earlier_statement_creates_is_held(before: str) -> None:
    assert not _fresh_before_last(before + INE + INDEX, EMPTY)


def test_a_plain_create_before_it_keeps_its_own_proof() -> None:
    """The ``IF NOT EXISTS`` skips; the table is still the one this migration created."""
    sql = "CREATE TABLE t (c text);\n" + INE + INDEX
    *_, last = walk(sql, start=EMPTY)
    created = last.before.fresh(None, "t")
    assert created is not None
    assert not created.read_live


# --------------------------------------------------------------------------- across files


def test_leaves_folds_a_file() -> None:
    after = leaves("ALTER TABLE big RENAME TO t;\nDROP TABLE gone;", EMPTY)
    assert after is not None
    assert not after.lacks(None, "t")
    assert after.lacks(None, "big")


def test_leaves_forgets_after_what_it_cannot_read() -> None:
    assert leaves("DO $$ BEGIN PERFORM 1; END $$;", EMPTY) is None
    assert leaves("SELECT 1;", None) is None


def _migrations(tmp_path: Path, files: dict[str, str]) -> list[Path]:
    paths = []
    for name, text in files.items():
        path = tmp_path / name
        path.write_text(text)
        paths.append(path)
    return paths


FACTS = SchemaFacts(relations=EMPTY.relations, current_schema="public")


def test_each_pending_file_starts_from_what_the_earlier_ones_leave(tmp_path: Path) -> None:
    files = _migrations(
        tmp_path,
        {
            "001_rename.up.sql": "ALTER TABLE big RENAME TO t;",
            "002_drop.up.sql": "DROP TABLE t;",
            "003_create.up.sql": INE + INDEX,
        },
    )
    starts = pending_starts(files, FACTS)
    assert starts["001_rename.up.sql"] == EMPTY
    assert not starts["002_drop.up.sql"].lacks(None, "t")
    assert starts["003_create.up.sql"].lacks(None, "t")


@pytest.mark.parametrize(
    ("name", "text"),
    [("002_opaque.py", "from confiture import Migration\n"), ("002_broken.up.sql", "CREAT TABLE")],
)
def test_nothing_is_proven_absent_after_a_file_the_fold_cannot_read(
    tmp_path: Path, name: str, text: str
) -> None:
    files = _migrations(tmp_path, {"001_a.up.sql": "SELECT 1;", name: text, "003_c.up.sql": INE})
    starts = pending_starts(files, FACTS)
    assert set(starts) == {"001_a.up.sql", name}


def test_no_live_relations_no_starts(tmp_path: Path) -> None:
    files = _migrations(tmp_path, {"001_a.up.sql": INE + INDEX})
    assert pending_starts(files, SchemaFacts()) == {}
    assert pending_starts(files, SchemaFacts(relations=frozenset())) == {}


def test_build_change_set_reads_each_files_start(tmp_path: Path) -> None:
    _migrations(tmp_path, {"001_a.up.sql": INE + INDEX})
    static = build_change_set(tmp_path)
    live = build_change_set(tmp_path, starts={"001_a.up.sql": EMPTY})
    assert static.changes[-1].tier is RiskTier.LOCK_RISKY
    assert live.changes[-1].tier is RiskTier.ADDITIVE


# --------------------------------------------------------------------------- verdicts


def test_the_replica_verdict_reads_it() -> None:
    assert _replica_safe(INE + INDEX, EMPTY)
    assert not _replica_safe(INE + INDEX, HOLDS_T)
    assert not _replica_safe(INE + INDEX, None)


def test_the_change_set_reads_it() -> None:
    assert _tier(INE + INDEX, EMPTY) is RiskTier.ADDITIVE
    assert _tier(INE + INDEX, HOLDS_T) is RiskTier.LOCK_RISKY
    assert _tier(INE + INDEX, None) is RiskTier.LOCK_RISKY


def test_the_entry_says_the_database_lacks_it() -> None:
    entry = classify_statements(INE + INDEX, start=EMPTY)[-1]
    assert entry.detail == (
        "CREATE INDEX — on a relation this migration creates (the database does not hold it)"
    )


def test_a_cascade_reaches_past_the_created_relation() -> None:
    sql = INE + "TRUNCATE t CASCADE;"
    assert not _replica_safe(sql, EMPTY)
    assert _tier(sql, EMPTY) is not RiskTier.ADDITIVE


# --------------------------------------------------------------------------- no database


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "against_provenance"


def test_without_against_the_payload_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """The static payload of a set of ``IF NOT EXISTS`` creates, recorded before #692's 04-E.

    ``parser`` names the installed pglast and is left out; everything else is byte-for-byte.
    """
    import json

    from typer.testing import CliRunner

    from confiture.cli.main import app

    for name in ("CONFITURE_DATABASE_URL", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    result = CliRunner().invoke(
        app,
        [
            "migrate",
            "preflight",
            "--migrations-dir",
            str(FIXTURE / "migrations"),
            "--format",
            "json",
            "--no-config",
        ],
    )
    payload = json.loads(result.stdout)
    payload.pop("parser")
    recorded = (FIXTURE / "static.json").read_text(encoding="utf-8")
    assert json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n" == recorded


# --------------------------------------------------------------------------- TVIEW (#786)

TVIEW = "SELECT tviews.pg_tviews_create_or_replace('tv_t', 'SELECT id, c FROM tb_t');\n"
TVIEW_INDEX = "CREATE INDEX ix_tv_t_c ON tv_t (c);"


def _tview_fresh_before_last(sql: str, start: Present | None) -> bool:
    *_, last = walk(sql, start=start)
    return last.before.fresh(None, "tv_t") is not None


def test_without_a_database_create_or_replace_proves_nothing() -> None:
    assert not _tview_fresh_before_last(TVIEW + TVIEW_INDEX, None)
    assert _tier(TVIEW + TVIEW_INDEX, None) is RiskTier.LOCK_RISKY


def test_create_or_replace_of_a_tview_the_database_lacks_is_a_creation() -> None:
    assert _tview_fresh_before_last(TVIEW + TVIEW_INDEX, EMPTY)
    assert _tier(TVIEW + TVIEW_INDEX, EMPTY) is RiskTier.ADDITIVE
    assert _replica_safe(TVIEW + TVIEW_INDEX, EMPTY)


def test_create_or_replace_of_a_tview_the_database_holds_is_a_replacement() -> None:
    holds = Present(relations=EMPTY.relations | {("public", "tv_t")}, current_schema="public")
    assert not _tview_fresh_before_last(TVIEW + TVIEW_INDEX, holds)
    assert not _replica_safe(TVIEW + TVIEW_INDEX, holds)


def test_create_or_replace_matches_the_live_current_schema() -> None:
    in_app = Present(relations=frozenset({("public", "tv_t")}), current_schema="app")
    assert _tview_fresh_before_last(TVIEW + TVIEW_INDEX, in_app)
    qualified = TVIEW.replace("'tv_t'", "'public.tv_t'")
    *_, last = walk(qualified + TVIEW_INDEX, start=in_app)
    assert last.before.fresh("public", "tv_t") is None


def test_a_second_create_or_replace_in_the_file_replaces_what_the_first_created() -> None:
    assert not _tview_fresh_before_last(TVIEW + TVIEW + TVIEW_INDEX, EMPTY)


def test_an_earlier_pending_file_that_creates_the_tview_holds_it() -> None:
    assert not _tview_fresh_before_last(TVIEW + TVIEW_INDEX, leaves(TVIEW, EMPTY))
