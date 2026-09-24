"""Detecting a data assertion inside a migration's `up()` (#311).

`confiture migrate preflight` replays pending `up()` bodies against a
schema-only database, where every table is empty. A `RAISE EXCEPTION` guarded
on a row count therefore raises there every time, and a deploy gated on the
preflight aborts — for a migration whose actual work was correct. It happened
twice to one backend, three days apart.

The detector is deliberately narrow. Three things must all hold:

1. a `RAISE` at ERROR level (`RAISE EXCEPTION`, not NOTICE or WARNING);
2. reached from an `IF` whose condition reads a variable;
3. that variable assigned by a `SELECT ... INTO` over a **user relation**.

Point 3 is what keeps it honest. A `RAISE EXCEPTION` guarded on a
`pg_catalog` or `information_schema` lookup is *correct* on a schema-only
database — the schema is there, so the query answers truthfully. Flagging it
would be telling the author to break a working guard.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from confiture.core.data_assertions import find_data_assertions

HERE = Path("db/migrations/20260101000000_x.up.sql")

INCIDENT = """
DO $$
DECLARE v_ok int;
BEGIN
  SELECT count(*) INTO v_ok FROM catalog.tb_printoptim_field
   WHERE identifier IN ('meter_a4_color', 'volume_a4_color');
  IF v_ok <> 2 THEN
    RAISE EXCEPTION 'expected 2 fields, got %', v_ok;
  END IF;
END $$;
"""


class TestTheIncident:
    def test_it_is_found(self) -> None:
        found = find_data_assertions(INCIDENT, HERE)

        assert len(found) == 1

    def test_it_names_the_variable_the_relation_and_the_line(self) -> None:
        (f,) = find_data_assertions(INCIDENT, HERE)

        assert f.variable == "v_ok"
        assert f.relation == "catalog.tb_printoptim_field"
        # Line 8 of INCIDENT, counted in the FILE: the `RAISE`, not the
        # `DECLARE` and not the `IF`, because the RAISE is what has to move.
        assert INCIDENT.splitlines()[f.line - 1].strip().startswith("RAISE EXCEPTION")
        assert f.line == 8
        assert f.file == HERE

    def test_the_same_shape_inside_create_function(self) -> None:
        """A migration that defines a function with the guard in its body."""
        sql = """
        CREATE OR REPLACE FUNCTION app.fn_check() RETURNS void LANGUAGE plpgsql AS $$
        DECLARE n bigint;
        BEGIN
          SELECT count(*) INTO n FROM app.tb_widget;
          IF n = 0 THEN RAISE EXCEPTION 'no widgets'; END IF;
        END $$;
        """
        found = find_data_assertions(sql, HERE)

        assert [f.variable for f in found] == ["n"]


class TestWhatItMustNotFlag:
    def test_a_catalog_lookup_is_safe_on_a_schema_only_database(self) -> None:
        """The schema IS present there, so this guard answers truthfully."""
        sql = """
        DO $$
        DECLARE has_col bool;
        BEGIN
          SELECT count(*) > 0 INTO has_col FROM information_schema.columns
           WHERE table_name = 'tb_widget' AND column_name = 'bio';
          IF NOT has_col THEN RAISE EXCEPTION 'expected tb_widget.bio'; END IF;
        END $$;
        """
        assert find_data_assertions(sql, HERE) == []

    def test_a_pg_catalog_lookup_is_safe_too(self) -> None:
        sql = """
        DO $$
        DECLARE n int;
        BEGIN
          SELECT count(*) INTO n FROM pg_catalog.pg_class WHERE relname = 'tb_widget';
          IF n <> 1 THEN RAISE EXCEPTION 'missing table'; END IF;
        END $$;
        """
        assert find_data_assertions(sql, HERE) == []

    def test_a_raise_notice_is_not_an_abort(self) -> None:
        """It logs and carries on — the preflight survives it."""
        sql = """
        DO $$
        DECLARE n int;
        BEGIN
          SELECT count(*) INTO n FROM app.tb_widget;
          IF n = 0 THEN RAISE NOTICE 'no widgets yet'; END IF;
        END $$;
        """
        assert find_data_assertions(sql, HERE) == []

    def test_a_raise_not_guarded_on_data_is_not_flagged(self) -> None:
        """An unconditional guard, or one on a parameter, says nothing about rows."""
        sql = """
        CREATE OR REPLACE FUNCTION app.fn_x(p int) RETURNS void LANGUAGE plpgsql AS $$
        BEGIN
          IF p < 0 THEN RAISE EXCEPTION 'p must be non-negative'; END IF;
        END $$;
        """
        assert find_data_assertions(sql, HERE) == []

    def test_plain_ddl_is_not_plpgsql_and_is_skipped(self) -> None:
        sql = "CREATE TABLE app.tb_widget (id bigint PRIMARY KEY);\nALTER TABLE app.tb_widget ADD COLUMN bio text;\n"

        assert find_data_assertions(sql, HERE) == []

    def test_a_select_into_without_a_guard_is_not_flagged(self) -> None:
        """Reading a count and doing nothing with it aborts nothing."""
        sql = """
        DO $$
        DECLARE n int;
        BEGIN
          SELECT count(*) INTO n FROM app.tb_widget;
          RAISE NOTICE 'widgets: %', n;
        END $$;
        """
        assert find_data_assertions(sql, HERE) == []


class TestMixedFiles:
    def test_ddl_around_the_block_does_not_hide_it(self) -> None:
        """A real migration is DDL with a DO block somewhere in the middle."""
        sql = (
            "CREATE TABLE app.tb_widget (id bigint PRIMARY KEY);\n"
            + INCIDENT
            + "\nALTER TABLE app.tb_widget ADD COLUMN bio text;\n"
        )
        found = find_data_assertions(sql, HERE)

        assert [f.variable for f in found] == ["v_ok"]

    def test_two_blocks_are_two_findings(self) -> None:
        found = find_data_assertions(INCIDENT + INCIDENT, HERE)

        assert len(found) == 2

    def test_lines_are_counted_in_the_file_not_in_the_statement(self) -> None:
        """Two blocks must not both claim the same line.

        `parse_plpgsql` is handed one statement at a time, so every `lineno` in
        the tree it returns counts from that statement's first line. Reported
        raw, both blocks below claim line 7. A scan of 3996 of this repo's SQL
        files is what surfaced it — one file, the same line twice.
        """
        doubled = INCIDENT + INCIDENT
        found = find_data_assertions(doubled, HERE)

        lines = [f.line for f in found]
        assert len(set(lines)) == 2, f"both blocks reported the same line: {lines}"
        for line in lines:
            assert doubled.splitlines()[line - 1].strip().startswith("RAISE EXCEPTION")

    def test_unparseable_sql_does_not_crash(self) -> None:
        """A findings pass must never be the thing that fails the command."""
        assert find_data_assertions("this is not sql at all (((", HERE) == []

    def test_copy_data_before_a_block_neither_crashes_nor_moves_it(self) -> None:
        """COPY rows are psql's to stream, not SQL: `b2b9437a-28df` is scanner junk.

        A migration that loads reference rows inline crashed the scan outright —
        the statement splitter handed the rows to the scanner.
        """
        copied = (
            "COPY app.t (id) FROM stdin;\nb2b9437a-28df-4ec4-8e4a-2bbdc241330b\n\\.\n" + INCIDENT
        )
        (found,) = find_data_assertions(copied, HERE)
        assert copied.splitlines()[found.line - 1].strip().startswith("RAISE EXCEPTION")

    def test_a_body_that_was_meant_to_be_read_and_was_not_is_flagged(self) -> None:
        """A file pglast rejects is a finding in this repo, never a green tick.

        A heuristic warning cannot fail a gate, so what it owes the reader
        instead is to say the body was not read — the difference between "no
        assertions here" and "no idea".
        """
        from confiture.core.data_assertions import scan_sql

        scan = scan_sql("DO $$ BEGIN IF THEN nonsense ;; END $$;", HERE)

        assert scan.unparseable is True
        assert scan.assertions == []

    def test_a_clean_file_is_not_marked_unparseable(self) -> None:
        from confiture.core.data_assertions import scan_sql

        scan = scan_sql("CREATE TABLE app.t (id bigint);", HERE)

        assert scan.unparseable is False

    def test_non_plpgsql_garbage_is_not_an_unread_body(self) -> None:
        """The signal is about bodies, not about every unparseable token run.

        Marking arbitrary text "unanalysed" would make the signal meaningless
        on the psql scripts this repo actually ships.
        """
        from confiture.core.data_assertions import scan_sql

        assert scan_sql("this is not sql at all (((", HERE).unparseable is False

    def test_a_leading_comment_does_not_shift_the_line(self) -> None:
        """PL/pgSQL counts from the BODY, not from the statement.

        Those coincide only when nothing precedes the opening `$$`. With a
        banner comment above it, a statement-relative base points the finding
        at the comment line - which is what a scan of this repo's real SQL
        showed, on every block in it.
        """
        sql = "-- banner\n-- more\n" + INCIDENT.lstrip("\n")
        (f,) = find_data_assertions(sql, HERE)

        assert sql.splitlines()[f.line - 1].strip().startswith("RAISE EXCEPTION")


class TestAgainstThisRepositorysOwnSql:
    """Measured, not assumed: the whole tracked SQL corpus.

    A detector for a construct nobody writes on purpose is easy to make
    plausible and hard to trust. These run it over every `.sql` file the repo
    tracks - roughly 4000 - which is what caught both line-number bugs.
    """

    @staticmethod
    def _corpus() -> list[Path]:
        roots = (Path("db"), Path("examples"), Path("tests/fixtures"))
        return [p for r in roots if r.exists() for p in sorted(r.rglob("*.sql"))]

    def test_no_file_crashes_the_scan(self) -> None:
        from confiture.core.data_assertions import scan_sql

        crashed = []
        for path in self._corpus():
            try:
                scan_sql(path.read_text(errors="replace"), path)
            except Exception as exc:  # Reason: the assertion IS that none escape
                crashed.append(f"{path}: {type(exc).__name__}: {exc}")

        assert crashed == [], "a findings pass must never fail the command:\n" + "\n".join(crashed)

    def test_every_reported_line_actually_holds_a_raise(self) -> None:
        """The line-number claim, checked against the files themselves."""
        from confiture.core.data_assertions import scan_sql

        wrong = []
        total = 0
        for path in self._corpus():
            text = path.read_text(errors="replace")
            lines = text.splitlines()
            for f in scan_sql(text, path).assertions:
                total += 1
                if not (1 <= f.line <= len(lines)) or "RAISE" not in lines[f.line - 1].upper():
                    wrong.append(f"{path}:{f.line}")

        assert total > 0, "corpus produced no findings - this test is proving nothing"
        assert wrong == [], (
            f"{len(wrong)} of {total} findings point at a line with no RAISE: {wrong[:5]}"
        )

    def test_the_schema_tree_itself_is_clean(self) -> None:
        """No false positive on `db/schema/` - plain DDL, no data assertions."""
        from confiture.core.data_assertions import scan_sql

        found = [
            f
            for path in sorted(Path("db/schema").rglob("*.sql"))
            for f in scan_sql(path.read_text(), path).assertions
        ]

        assert found == [], f"false positives on this repo's own schema: {found}"


class TestTheRaiseLevelIsNotGuessed:
    """The ERROR level is read from the compiler, not written down as 21.

    `elog_level` is a PostgreSQL server constant, and the lesson of #192 is
    that a literal ordinal for a PostgreSQL enum is a silent failure waiting
    for the next major: `_AT_DROP_COLUMN = 14` stopped matching on pglast 8 and
    the `elif` chains fell through, turning replica-unsafe migrations into
    `window_safe: true`.
    """

    def test_the_level_is_derived_by_compiling_a_probe(self) -> None:
        from confiture.core.data_assertions import _error_elog_level

        level = _error_elog_level()

        assert isinstance(level, int)
        assert level > 0

    def test_notice_and_exception_resolve_differently(self) -> None:
        """If they ever collided, every RAISE NOTICE would read as an abort."""
        from confiture.core.data_assertions import _elog_level_of

        assert _elog_level_of("RAISE EXCEPTION 'x';") != _elog_level_of("RAISE NOTICE 'x';")


@pytest.mark.parametrize(
    "relation",
    ["app.tb_widget", "tb_widget", "public.tb_widget"],
    ids=["schema-qualified", "bare", "public"],
)
def test_any_user_relation_counts(relation: str) -> None:
    """Qualified or not, a user table is empty on a schema-only database."""
    sql = f"""
    DO $$
    DECLARE n int;
    BEGIN
      SELECT count(*) INTO n FROM {relation};
      IF n = 0 THEN RAISE EXCEPTION 'empty'; END IF;
    END $$;
    """
    found = find_data_assertions(sql, HERE)

    assert len(found) == 1, f"{relation} not detected"


class TestPythonMigrations:
    """A `.py` migration's SQL comes from the static evaluator, not a regex.

    `core/idempotency/static_eval` (#213) is the one place that answers "what
    text does this `self.execute(...)` hand over". It resolves every form that
    is a pure function of the file's own text and refuses the rest with a
    reason and a remedy — and it never imports, executes, `eval`s or `compile`s
    the migration.
    """

    @staticmethod
    def _write(tmp_path: Path, body: str) -> Path:
        path = tmp_path / "20260101000000_add_thing.py"
        path.write_text(body)
        return path

    def test_an_inline_assertion_is_found(self, tmp_path: Path) -> None:
        from confiture.core.data_assertions import scan_migration

        path = self._write(
            tmp_path,
            '''from confiture.models.migration import Migration


class AddThing(Migration):
    version = "20260101000000"
    name = "add_thing"

    def up(self) -> None:
        self.execute("""
            DO $$
            DECLARE n int;
            BEGIN
              SELECT count(*) INTO n FROM app.tb_widget;
              IF n = 0 THEN RAISE EXCEPTION 'no widgets'; END IF;
            END $$;
        """)
''',
        )

        scan = scan_migration(path)

        assert [f.variable for f in scan.assertions] == ["n"]
        assert scan.assertions[0].relation == "app.tb_widget"

    def test_it_points_at_the_execute_call(self, tmp_path: Path) -> None:
        """A line inside a string literal is not a line in the file."""
        from confiture.core.data_assertions import scan_migration

        path = self._write(
            tmp_path,
            '''from confiture.models.migration import Migration

GUARD = """
DO $$
DECLARE n int;
BEGIN
  SELECT count(*) INTO n FROM app.tb_widget;
  IF n = 0 THEN RAISE EXCEPTION 'no widgets'; END IF;
END $$;
"""


class AddThing(Migration):
    version = "20260101000000"
    name = "add_thing"

    def up(self) -> None:
        self.execute(GUARD)
''',
        )

        (found,) = scan_migration(path).assertions

        call_line = path.read_text().splitlines()[found.line - 1]
        assert "self.execute(GUARD)" in call_line

    def test_a_plain_ddl_migration_is_clean(self, tmp_path: Path) -> None:
        from confiture.core.data_assertions import scan_migration

        path = self._write(
            tmp_path,
            """from confiture.models.migration import Migration


class AddThing(Migration):
    version = "20260101000000"
    name = "add_thing"

    def up(self) -> None:
        self.execute("ALTER TABLE app.tb_widget ADD COLUMN bio text")
""",
        )

        scan = scan_migration(path)

        assert scan.assertions == []
        assert scan.unparseable is False

    def test_a_refused_call_is_unanalysed_not_clean(self, tmp_path: Path) -> None:
        """Truly dynamic SQL — a loop variable, per the pinned-reach contract."""
        from confiture.core.data_assertions import scan_migration

        path = self._write(
            tmp_path,
            """from confiture.models.migration import Migration


class AddThing(Migration):
    version = "20260101000000"
    name = "add_thing"

    def up(self) -> None:
        for table in ("a", "b"):
            self.execute(f"ALTER TABLE {table} ADD COLUMN bio text")
""",
        )

        scan = scan_migration(path)

        assert scan.assertions == []
        assert scan.unparseable is True, "a refused call must not read as clean"


class TestSchemaOnlyIsNotEmpty:
    """A schema-only copy is not an *empty* database (#311, downstream report).

    `pg_dump --schema-only | psql` leaves every **user** table empty, but the
    catalogue is fully populated — it describes the schema that was just
    created. So anything derived from `pg_class`, `pg_namespace` or their kin
    has rows at preflight time, and a `RAISE EXCEPTION` guarded on a count over
    it is *correct*.

    The downstream reporter built this same detector independently, measured
    **76 findings across 295 migrations**, checked samples, found them false,
    and threw it away — for exactly this reason. Their case:

        SELECT count(*) INTO v FROM _v_statistics_privileges;  -- from pg_class
        IF v <> 7 THEN RAISE EXCEPTION ...                     -- fine at preflight

    A direct `FROM pg_catalog.…` was already excluded. What was not is a
    relation the migration itself builds *from* the catalogue, whose name says
    nothing about where its rows come from.
    """

    def test_a_temp_table_built_from_the_catalogue_is_not_flagged(self) -> None:
        sql = """
        CREATE TEMP TABLE _v_statistics_privileges AS
          SELECT relname, relacl FROM pg_catalog.pg_class WHERE relkind = 'r';

        DO $$
        DECLARE v int;
        BEGIN
          SELECT count(*) INTO v FROM _v_statistics_privileges;
          IF v <> 7 THEN RAISE EXCEPTION 'expected 7 privileges, got %', v; END IF;
        END $$;
        """
        assert find_data_assertions(sql, HERE) == []

    def test_a_view_over_the_catalogue_is_not_flagged(self) -> None:
        sql = """
        CREATE VIEW app.v_tables AS SELECT relname FROM pg_class WHERE relkind = 'r';

        DO $$
        DECLARE v int;
        BEGIN
          SELECT count(*) INTO v FROM app.v_tables;
          IF v = 0 THEN RAISE EXCEPTION 'no tables'; END IF;
        END $$;
        """
        assert find_data_assertions(sql, HERE) == []

    def test_derivation_is_transitive(self) -> None:
        """Two hops from the catalogue is still the catalogue."""
        sql = """
        CREATE TEMP TABLE _a AS SELECT relname FROM pg_class;
        CREATE TEMP TABLE _b AS SELECT relname FROM _a;

        DO $$
        DECLARE v int;
        BEGIN
          SELECT count(*) INTO v FROM _b;
          IF v = 0 THEN RAISE EXCEPTION 'empty'; END IF;
        END $$;
        """
        assert find_data_assertions(sql, HERE) == []

    def test_a_table_filled_from_the_catalogue_by_insert_is_not_flagged(self) -> None:
        """The sources can arrive after the CREATE."""
        sql = """
        CREATE TEMP TABLE _c (relname text);
        INSERT INTO _c SELECT relname FROM pg_catalog.pg_class;

        DO $$
        DECLARE v int;
        BEGIN
          SELECT count(*) INTO v FROM _c;
          IF v = 0 THEN RAISE EXCEPTION 'empty'; END IF;
        END $$;
        """
        assert find_data_assertions(sql, HERE) == []

    def test_a_temp_table_built_from_a_user_table_IS_flagged(self) -> None:
        """The other half. A copy of an empty table is empty.

        Without this, "created in this file" would become a blanket excuse and
        the check would stop detecting the incident it exists for.
        """
        sql = """
        CREATE TEMP TABLE _d AS SELECT id FROM app.tb_widget;

        DO $$
        DECLARE v int;
        BEGIN
          SELECT count(*) INTO v FROM _d;
          IF v = 0 THEN RAISE EXCEPTION 'empty'; END IF;
        END $$;
        """
        found = find_data_assertions(sql, HERE)

        assert [f.variable for f in found] == ["v"]

    def test_a_mixed_source_is_flagged(self) -> None:
        """One user relation among the sources is enough to empty the result."""
        sql = """
        CREATE TEMP TABLE _e AS
          SELECT c.relname FROM pg_class c JOIN app.tb_widget w ON w.id = c.oid;

        DO $$
        DECLARE v int;
        BEGIN
          SELECT count(*) INTO v FROM _e;
          IF v = 0 THEN RAISE EXCEPTION 'empty'; END IF;
        END $$;
        """
        assert len(find_data_assertions(sql, HERE)) == 1

    def test_an_unqualified_catalogue_read_is_not_flagged(self) -> None:
        """`FROM pg_class` — no qualifier — is a catalogue read.

        PostgreSQL puts `pg_catalog` on the implicit `search_path`, and the
        `pg_` prefix is reserved for exactly that. Only the *qualified* form
        was excluded before, so this shape was a false positive too.
        """
        sql = """
        DO $$
        DECLARE v int;
        BEGIN
          SELECT count(*) INTO v FROM pg_class WHERE relkind = 'r';
          IF v = 0 THEN RAISE EXCEPTION 'no tables'; END IF;
        END $$;
        """
        assert find_data_assertions(sql, HERE) == []

    def test_a_user_table_named_like_a_catalogue_one_is_still_a_user_table(self) -> None:
        """The `pg_` shortcut applies only unqualified: `app.pg_thing` is yours."""
        sql = """
        DO $$
        DECLARE v int;
        BEGIN
          SELECT count(*) INTO v FROM app.pg_thing;
          IF v = 0 THEN RAISE EXCEPTION 'empty'; END IF;
        END $$;
        """
        assert len(find_data_assertions(sql, HERE)) == 1

    def test_the_incident_still_reports(self) -> None:
        """The regression guard for all of the above."""
        assert len(find_data_assertions(INCIDENT, HERE)) == 1


class TestACountAssignedWithColonEquals:
    """`v := (SELECT count(*) …)` is the same count as `SELECT count(*) INTO v` (#363)."""

    ASSIGNED = """
DO $$
DECLARE v_ok int;
BEGIN
  v_ok := (SELECT count(*) FROM catalog.tb_field WHERE identifier = 'a');
  IF v_ok <> 1 THEN
    RAISE EXCEPTION 'expected 1 field, got %', v_ok;
  END IF;
END $$;
"""

    def test_it_is_found_like_its_select_into_twin(self) -> None:
        (f,) = find_data_assertions(self.ASSIGNED, HERE)

        assert (f.variable, f.relation, f.line) == ("v_ok", "catalog.tb_field", 7)

    def test_a_catalogue_count_by_assignment_is_not_flagged(self) -> None:
        sql = self.ASSIGNED.replace("catalog.tb_field", "pg_catalog.pg_class")

        assert find_data_assertions(sql, HERE) == []

    def test_an_assignment_that_reads_no_relation_is_not_a_count(self) -> None:
        sql = self.ASSIGNED.replace(
            "(SELECT count(*) FROM catalog.tb_field WHERE identifier = 'a')", "f(1)"
        )

        assert find_data_assertions(sql, HERE) == []


def test_a_fragment_the_reader_cannot_read_makes_the_file_unanalysed(monkeypatch) -> None:
    """Its count may be the one a guard reads: say the file was not read, not that it is clean."""
    from confiture.core import plpgsql_fragments
    from confiture.core.data_assertions import scan_sql

    slots = dict(plpgsql_fragments.SLOTS)
    del slots[("PLpgSQL_stmt_assign", "expr")]
    monkeypatch.setattr(plpgsql_fragments, "SLOTS", slots)

    scan = scan_sql(TestACountAssignedWithColonEquals.ASSIGNED, HERE)

    assert scan.unparseable
    assert scan.assertions == []
