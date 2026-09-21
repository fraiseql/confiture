"""Level 5's detectors must measure rows, not count catalogue entries.

Four of the five detectors on :class:`Level5ExecutionValidator` never looked at
a single row. Their queries select from ``information_schema`` and take
``COUNT(*)`` of *that* — the number of catalogue entries matching the table
name — then report it as a number of violating rows:

    SELECT table_name, column_name, COUNT(*) as null_count
    FROM (SELECT '<t>' as table_name, column_name
          FROM information_schema.columns
          WHERE table_name = '<t>' AND is_nullable = 'NO') not_null_cols
    GROUP BY table_name, column_name;

So every NOT NULL column produced a CRITICAL "found N NULL values", every CHECK
constraint an ERROR "found N violations", and every ``fk_*`` column a CRITICAL
"NULL values after resolution" — on an empty table, and on a perfectly clean
one. ``N`` was the number of schemas that happened to contain a table of that
name: two, in any prep-seed project, because ``prep_seed.tb_x`` and
``catalog.tb_x`` are the pattern. The fifth query named
``information_schema.referential_constraints.column_name``, a column that does
not exist, so it raised and a bare ``except psycopg.Error: pass`` swallowed it —
that detector could never report anything at all.

The unit tests did not catch it because they hand ``fetchall()`` its answer:
they pin the message formatting and never execute the SQL. Only a real database
can fail on this, which is why these tests are here.
"""

from __future__ import annotations

from collections.abc import Generator

import psycopg
import pytest

from confiture.core.seed.validation.prep_seed.level_5_execution import Level5ExecutionValidator

_SCHEMA = "catalog"


@pytest.fixture
def widgets(clean_test_db: psycopg.Connection) -> Generator[psycopg.Connection, None, None]:
    """A prep-seed-shaped catalog: a parent, a child with an ``fk_`` column.

    Deliberately *valid*: every constraint holds and no column that matters is
    NULL. A validator that reports anything here is reporting on the schema.
    """
    conn = clean_test_db
    with conn.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE")
        cur.execute(f"CREATE SCHEMA {_SCHEMA}")
        cur.execute(f"""
            CREATE TABLE {_SCHEMA}.tb_maker (
                pk_maker BIGINT PRIMARY KEY,
                id UUID NOT NULL,
                name TEXT NOT NULL
            )
        """)
        cur.execute(f"""
            CREATE TABLE {_SCHEMA}.tb_widget (
                pk_widget BIGINT PRIMARY KEY,
                id UUID NOT NULL,
                fk_maker BIGINT REFERENCES {_SCHEMA}.tb_maker (pk_maker),
                label TEXT NOT NULL,
                qty INT CONSTRAINT tb_widget_qty_not_negative CHECK (qty >= 0)
            )
        """)
        cur.execute(f"""
            INSERT INTO {_SCHEMA}.tb_maker (pk_maker, id, name) VALUES
                (1, '550e8400-e29b-41d4-a716-446655440000', 'Acme')
        """)
        cur.execute(f"""
            INSERT INTO {_SCHEMA}.tb_widget (pk_widget, id, fk_maker, label, qty) VALUES
                (1, '550e8400-e29b-41d4-a716-446655440010', 1, 'Anvil', 3),
                (2, '550e8400-e29b-41d4-a716-446655440011', 1, 'Rocket', 7)
        """)
    conn.commit()
    yield conn
    with conn.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE")
    conn.commit()


def _validator() -> Level5ExecutionValidator:
    return Level5ExecutionValidator()


TABLES = ["tb_widget", "tb_maker"]


def test_clean_data_yields_no_null_fk_violations(widgets: psycopg.Connection) -> None:
    """Every ``fk_maker`` is set, so there is nothing to report."""
    assert _validator().detect_null_fks(widgets, TABLES) == []


def test_clean_data_yields_no_not_null_violations(widgets: psycopg.Connection) -> None:
    """A NOT NULL column that holds no NULLs is not a violation."""
    assert _validator().detect_not_null_violations(widgets, TABLES) == []


def test_clean_data_yields_no_check_violations(widgets: psycopg.Connection) -> None:
    """A CHECK constraint that holds is not a violation."""
    assert _validator().detect_check_constraint_violations(widgets, TABLES) == []


def test_clean_data_yields_no_fk_violations(widgets: psycopg.Connection) -> None:
    """Every foreign key resolves, so there are no orphaned references."""
    assert _validator().detect_fk_constraint_violations(widgets, TABLES) == []


def test_an_empty_table_yields_nothing(widgets: psycopg.Connection) -> None:
    """The shape that exposed this: no rows at all, four detectors, no findings."""
    with widgets.cursor() as cur:
        cur.execute(f"DELETE FROM {_SCHEMA}.tb_widget")
        cur.execute(f"DELETE FROM {_SCHEMA}.tb_maker")
    widgets.commit()
    validator = _validator()
    assert validator.detect_null_fks(widgets, TABLES) == []
    assert validator.detect_not_null_violations(widgets, TABLES) == []
    assert validator.detect_check_constraint_violations(widgets, TABLES) == []
    assert validator.detect_fk_constraint_violations(widgets, TABLES) == []


def test_a_null_fk_is_found_and_counted(widgets: psycopg.Connection) -> None:
    """A resolution that missed its join leaves ``fk_maker`` NULL."""
    with widgets.cursor() as cur:
        cur.execute(f"""
            INSERT INTO {_SCHEMA}.tb_widget (pk_widget, id, fk_maker, label, qty) VALUES
                (3, '550e8400-e29b-41d4-a716-446655440012', NULL, 'Orphan', 1),
                (4, '550e8400-e29b-41d4-a716-446655440013', NULL, 'Stray', 1)
        """)
    widgets.commit()

    violations = _validator().detect_null_fks(widgets, TABLES)
    assert len(violations) == 1, violations
    assert "fk_maker" in violations[0].message
    assert "2" in violations[0].message, violations[0].message


def test_a_check_violation_under_not_valid_is_found(widgets: psycopg.Connection) -> None:
    """``NOT VALID`` is how a violating row outlives its CHECK constraint."""
    with widgets.cursor() as cur:
        cur.execute(f"""
            INSERT INTO {_SCHEMA}.tb_widget (pk_widget, id, fk_maker, label, qty)
            VALUES (5, '550e8400-e29b-41d4-a716-446655440014', 1, 'Freebie', 0)
        """)
        cur.execute(f"""
            ALTER TABLE {_SCHEMA}.tb_widget
            ADD CONSTRAINT tb_widget_qty_billable CHECK (qty > 0) NOT VALID
        """)
    widgets.commit()

    violations = _validator().detect_check_constraint_violations(widgets, TABLES)
    assert len(violations) == 1, violations
    assert "tb_widget_qty_billable" in violations[0].message
    assert "1" in violations[0].message, violations[0].message


def test_an_orphaned_reference_under_not_valid_is_found(widgets: psycopg.Connection) -> None:
    """A NOT VALID foreign key can hold references to rows that do not exist."""
    with widgets.cursor() as cur:
        cur.execute(f"""
            CREATE TABLE {_SCHEMA}.tb_part (
                pk_part BIGINT PRIMARY KEY,
                fk_widget BIGINT
            )
        """)
        cur.execute(f"INSERT INTO {_SCHEMA}.tb_part (pk_part, fk_widget) VALUES (1, 999)")
        cur.execute(f"""
            ALTER TABLE {_SCHEMA}.tb_part
            ADD CONSTRAINT tb_part_fk_widget_fkey
            FOREIGN KEY (fk_widget) REFERENCES {_SCHEMA}.tb_widget (pk_widget) NOT VALID
        """)
    widgets.commit()

    violations = _validator().detect_fk_constraint_violations(widgets, ["tb_part"])
    assert len(violations) == 1, violations
    assert "fk_widget" in violations[0].message
    assert "tb_widget" in violations[0].message
    assert "1" in violations[0].message, violations[0].message


def test_an_orphaned_reference_to_a_table_on_search_path_is_found(
    widgets: psycopg.Connection,
) -> None:
    """``pg_get_constraintdef`` leaves a parent ``search_path`` finds unqualified;
    the count still reaches that parent, and the message still names it."""
    with widgets.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS public.tb_region CASCADE")
        cur.execute("CREATE TABLE public.tb_region (pk_region BIGINT PRIMARY KEY)")
        cur.execute("INSERT INTO public.tb_region VALUES (1)")
        cur.execute(f"""
            CREATE TABLE {_SCHEMA}.tb_depot (
                pk_depot BIGINT PRIMARY KEY,
                fk_region BIGINT
            )
        """)
        cur.execute(f"INSERT INTO {_SCHEMA}.tb_depot VALUES (1, 1), (2, 7), (3, 8)")
        cur.execute(f"""
            ALTER TABLE {_SCHEMA}.tb_depot
            ADD CONSTRAINT tb_depot_fk_region_fkey
            FOREIGN KEY (fk_region) REFERENCES public.tb_region (pk_region) NOT VALID
        """)
    widgets.commit()
    try:
        violations = _validator().detect_fk_constraint_violations(widgets, ["tb_depot"])
        assert len(violations) == 1, violations
        assert "referencing tb_region" in violations[0].message
        assert "found 2 orphaned" in violations[0].message, violations[0].message
    finally:
        with widgets.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS public.tb_region CASCADE")
        widgets.commit()


# ---------------------------------------------------------------------------
# The cycles, end to end.
#
# The mocked unit tests for these pinned a `side_effect` list to the exact
# sequence of `execute()` calls, so they broke whenever the SQL changed and
# passed however wrong it was. What matters is that a clean prep-seed database
# comes back with nothing to report, which is precisely what
# `examples/06-prep-seed-validation` could not do.
# ---------------------------------------------------------------------------


@pytest.fixture
def prep_seed_project(
    clean_test_db: psycopg.Connection, tmp_path: pytest.TempPathFactory
) -> Generator[tuple[psycopg.Connection, list[str]], None, None]:
    """A whole, valid prep-seed cycle: UUID prep table, resolver, BIGINT catalog."""
    conn = clean_test_db
    with conn.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE")
        cur.execute("DROP SCHEMA IF EXISTS prep_seed CASCADE")
        cur.execute(f"CREATE SCHEMA {_SCHEMA}")
        cur.execute("CREATE SCHEMA prep_seed")
        cur.execute("""
            CREATE TABLE prep_seed.tb_maker (
                id UUID PRIMARY KEY,
                name TEXT NOT NULL
            )
        """)
        cur.execute(f"""
            CREATE TABLE {_SCHEMA}.tb_maker (
                pk_maker BIGSERIAL PRIMARY KEY,
                id UUID NOT NULL UNIQUE,
                name TEXT NOT NULL
            )
        """)
        cur.execute(f"""
            CREATE FUNCTION fn_resolve_tb_maker() RETURNS void AS $$
                INSERT INTO {_SCHEMA}.tb_maker (id, name)
                SELECT id, name FROM prep_seed.tb_maker
                ON CONFLICT (id) DO NOTHING;
            $$ LANGUAGE sql;
        """)
    conn.commit()

    seed = tmp_path / "01_makers.sql"  # type: ignore[operator]
    seed.write_text(
        "INSERT INTO prep_seed.tb_maker (id, name) VALUES\n"
        "    ('550e8400-e29b-41d4-a716-446655440000', 'Acme'),\n"
        "    ('550e8400-e29b-41d4-a716-446655440001', 'Widget Inc');\n"
    )

    yield conn, [str(seed)]

    with conn.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE")
        cur.execute("DROP SCHEMA IF EXISTS prep_seed CASCADE")
        cur.execute("DROP FUNCTION IF EXISTS fn_resolve_tb_maker()")
    conn.commit()


def test_a_valid_cycle_reports_nothing(
    prep_seed_project: tuple[psycopg.Connection, list[str]],
) -> None:
    """Load, resolve, validate — and find nothing, because nothing is wrong."""
    conn, seeds = prep_seed_project
    violations = _validator().execute_full_cycle(
        connection=conn,
        seed_files=seeds,
        resolution_functions=["fn_resolve_tb_maker"],
        tables=["tb_maker"],
    )
    assert violations == [], [v.message for v in violations]

    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {_SCHEMA}.tb_maker")
        row = cur.fetchone()
    assert row is not None
    assert row[0] == 2, "the resolver should have populated the catalog table"


def test_a_valid_cycle_reports_nothing_in_comprehensive_mode(
    prep_seed_project: tuple[psycopg.Connection, list[str]],
) -> None:
    """The mode that added three constraint detectors, all of which always fired.

    This is the assertion `examples/06-prep-seed-validation` failed: eight
    violations — four CRITICAL — on a two-table schema holding valid data.
    """
    conn, seeds = prep_seed_project
    violations = _validator().execute_full_cycle_comprehensive(
        connection=conn,
        seed_files=seeds,
        resolution_functions=["fn_resolve_tb_maker"],
        tables=["tb_maker"],
    )
    assert violations == [], [v.message for v in violations]
