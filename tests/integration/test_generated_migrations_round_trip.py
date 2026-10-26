"""A generated migration applies, its down undoes it, and it applies again (#335).

Parsing proves a statement is grammatical; it does not prove PostgreSQL accepts
it, nor that the down file really undoes the up. Each scenario here builds the
*old* schema into a scratch database, writes the migration ``migrate diff
--generate`` writes for old → new, and applies the up file, the down file, then
the up file again — statement by statement, as ``CREATE INDEX CONCURRENTLY``
requires, with the destructive gate open so every derived statement is written.

A file that runs in one transaction creates plainly and fails when applied over
what it creates; one that does not keeps ``IF NOT EXISTS``, so a failed
autocommit file retries from the top.

A generated Python migration runs in the mode its SQL pair would, through
``migrate up`` itself: the positional ``migrate diff OLD NEW --generate`` writes it,
and the CLI applies it, takes it back and applies it again (#698).
"""

from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core import sql_lexer
from confiture.core.differ import SchemaDiffer
from confiture.core.migration_generator import MigrationGenerator

pytestmark = pytest.mark.integration


def _apply(conn: psycopg.Connection, text: str) -> None:
    for statement in sql_lexer.split_statements(text):
        if sql_lexer.code_text(statement).text.strip():
            conn.execute(statement)


def _generated(tmp_path: Path, old: str, new: str) -> tuple[str, str]:
    up = MigrationGenerator(migrations_dir=tmp_path).generate_sql(
        SchemaDiffer().compare(old, new),
        name="step",
        version="20260101000000",
        destructive="allow",
    )
    return up.read_text(), up.with_name(up.name.replace(".up.sql", ".down.sql")).read_text()


def round_trip(url: str, tmp_path: Path, old: str, new: str) -> psycopg.Connection:
    """*old* built, then up, down and up applied; the connection, left after the last up."""
    up, down = _generated(tmp_path, old, new)
    conn = psycopg.connect(url, autocommit=True)
    if old.strip():
        _apply(conn, old)
    _apply(conn, up)
    _apply(conn, down)
    _apply(conn, up)
    return conn


def _constraints(conn: psycopg.Connection, table: str) -> set[str]:
    rows = conn.execute(
        "SELECT conname FROM pg_constraint WHERE conrelid = %s::regclass AND contype <> 'p'",
        (table,),
    ).fetchall()
    return {name for (name,) in rows}


PARENT = "CREATE TABLE parent (id INT PRIMARY KEY);\n"


class TestAddedConstraints:
    """The down of an added named constraint drops it; an unnamed one says it cannot."""

    OLD = PARENT + "CREATE TABLE t (id INT, pid INT);\n"
    NEW = PARENT + (
        "CREATE TABLE t (id INT, pid INT"
        ", CONSTRAINT fk_t_parent FOREIGN KEY (pid) REFERENCES parent(id)"
        ", CONSTRAINT ck_t_id CHECK (id > 0), CONSTRAINT uq_t_id UNIQUE (id));\n"
    )

    def test_named_ones_round_trip(self, fresh_database: str, tmp_path: Path) -> None:
        conn = round_trip(fresh_database, tmp_path, self.OLD, self.NEW)
        assert _constraints(conn, "t") == {"fk_t_parent", "ck_t_id", "uq_t_id"}

    def test_the_down_removes_them(self, fresh_database: str, tmp_path: Path) -> None:
        up, down = _generated(tmp_path, self.OLD, self.NEW)
        conn = psycopg.connect(fresh_database, autocommit=True)
        _apply(conn, self.OLD)
        _apply(conn, up)
        _apply(conn, down)
        assert _constraints(conn, "t") == set()


class TestEnumsAndSequences:
    """A dropped enum type or sequence comes back from what its change carries."""

    OLD = (
        "CREATE TYPE mood AS ENUM ('sad', 'ok', 'happy');\n"
        "CREATE SEQUENCE order_seq INCREMENT 5 START 100 MAXVALUE 100000;\n"
    )

    def test_the_down_of_a_drop_recreates_them(self, fresh_database: str, tmp_path: Path) -> None:
        up, down = _generated(tmp_path, self.OLD, "")
        conn = psycopg.connect(fresh_database, autocommit=True)
        _apply(conn, self.OLD)
        _apply(conn, up)
        _apply(conn, down)
        labels = conn.execute(
            "SELECT array_agg(enumlabel ORDER BY enumsortorder) FROM pg_enum"
            " WHERE enumtypid = 'mood'::regtype"
        ).fetchone()
        assert labels == (["sad", "ok", "happy"],)
        assert conn.execute(
            "SELECT increment_by, start_value, max_value FROM pg_sequences"
            " WHERE sequencename = 'order_seq'"
        ).fetchone() == (5, 100, 100000)
        _apply(conn, up)

    def test_an_added_sequence_keeps_its_options(self, fresh_database: str, tmp_path: Path) -> None:
        new = "CREATE SEQUENCE desc_seq INCREMENT -2 MAXVALUE 0;\n" + self.OLD
        conn = round_trip(fresh_database, tmp_path, self.OLD, new)
        assert conn.execute(
            "SELECT increment_by, start_value, min_value, max_value FROM pg_sequences"
            " WHERE sequencename = 'desc_seq'"
        ).fetchone() == (-2, 0, -(2**63), 0)


class TestTypeChanges:
    """``text`` → ``integer`` has no assignment cast; the generated ``USING`` supplies one."""

    def test_a_cast_type_change_round_trips_with_its_rows(
        self, fresh_database: str, tmp_path: Path
    ) -> None:
        old, new = "CREATE TABLE t (n TEXT);\n", "CREATE TABLE t (n INTEGER);\n"
        up, down = _generated(tmp_path, old, new)
        conn = psycopg.connect(fresh_database, autocommit=True)
        _apply(conn, old)
        conn.execute("INSERT INTO t VALUES ('7'), ('42')")
        _apply(conn, up)
        assert conn.execute("SELECT sum(n) FROM t").fetchone() == (49,)
        _apply(conn, down)
        _apply(conn, up)
        assert conn.execute("SELECT pg_typeof(n)::text FROM t LIMIT 1").fetchone() == ("integer",)

    def test_a_narrowing_refuses_a_value_rather_than_truncate_it(
        self, fresh_database: str, tmp_path: Path
    ) -> None:
        """No ``USING``: an explicit ``::varchar(3)`` would cut ``'abcdef'`` to ``'abc'``."""
        old, new = "CREATE TABLE t (s VARCHAR(10));\n", "CREATE TABLE t (s VARCHAR(3));\n"
        up, _ = _generated(tmp_path, old, new)
        conn = psycopg.connect(fresh_database, autocommit=True)
        _apply(conn, old)
        conn.execute("INSERT INTO t VALUES ('abcdef')")
        with pytest.raises(psycopg.errors.StringDataRightTruncation):
            _apply(conn, up)
        assert conn.execute("SELECT s FROM t").fetchone() == ("abcdef",)


@pytest.mark.usefixtures("quoted_names_allowed")
class TestDefinitionKinds:
    """A trigger, extension, schema, policy, domain and composite type re-apply and drop."""

    OLD = (
        "CREATE TABLE t (a INT);\n"
        "CREATE FUNCTION fn_t() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN RETURN NEW; END$$;\n"
    )
    NEW = OLD + (
        'CREATE TRIGGER "Touch" BEFORE UPDATE ON t FOR EACH ROW EXECUTE FUNCTION fn_t();\n'
        "CREATE EXTENSION pgcrypto;\n"
        "CREATE SCHEMA app;\n"
        "CREATE POLICY p_all ON t USING (a > 0);\n"
        "CREATE DOMAIN posint AS INT CHECK (VALUE > 0);\n"
        "CREATE TYPE pair AS (x INT, y INT);\n"
    )
    PRESENT = """
        SELECT (SELECT count(*) FROM pg_trigger WHERE tgname = 'Touch')
             + (SELECT count(*) FROM pg_extension WHERE extname = 'pgcrypto')
             + (SELECT count(*) FROM pg_namespace WHERE nspname = 'app')
             + (SELECT count(*) FROM pg_policy WHERE polname = 'p_all')
             + (SELECT count(*) FROM pg_type WHERE typname IN ('posint', 'pair'))
    """

    def test_they_round_trip(self, fresh_database: str, tmp_path: Path) -> None:
        conn = round_trip(fresh_database, tmp_path, self.OLD, self.NEW)
        assert conn.execute(self.PRESENT).fetchone() == (6,)

    def test_the_up_applies_twice(self, fresh_database: str, tmp_path: Path) -> None:
        up, _ = _generated(tmp_path, self.OLD, self.NEW)
        conn = psycopg.connect(fresh_database, autocommit=True)
        _apply(conn, self.OLD)
        _apply(conn, up)
        _apply(conn, up)
        assert conn.execute(self.PRESENT).fetchone() == (6,)

    def test_the_down_removes_them(self, fresh_database: str, tmp_path: Path) -> None:
        up, down = _generated(tmp_path, self.OLD, self.NEW)
        conn = psycopg.connect(fresh_database, autocommit=True)
        _apply(conn, self.OLD)
        _apply(conn, up)
        _apply(conn, down)
        assert conn.execute(self.PRESENT).fetchone() == (0,)


class TestIndexes:
    """An index lands as declared: access method, key options, expression, predicate."""

    OLD = "CREATE EXTENSION IF NOT EXISTS pg_trgm;\nCREATE TABLE t (a INT, b INT, s TEXT);\n"
    NEW = OLD + (
        "CREATE INDEX ix_trgm ON t USING gin (s gin_trgm_ops);\n"
        "CREATE INDEX ix_sum ON t ((a + b));\n"
        "CREATE INDEX ix_part ON t (a DESC NULLS LAST) WHERE b > 0;\n"
    )

    def test_they_round_trip_as_declared(self, fresh_database: str, tmp_path: Path) -> None:
        conn = round_trip(fresh_database, tmp_path, self.OLD, self.NEW)
        definitions = dict(
            conn.execute(
                "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 't'"
            ).fetchall()
        )
        assert definitions == {
            "ix_trgm": "CREATE INDEX ix_trgm ON public.t USING gin (s gin_trgm_ops)",
            "ix_sum": "CREATE INDEX ix_sum ON public.t USING btree (((a + b)))",
            "ix_part": (
                "CREATE INDEX ix_part ON public.t USING btree (a DESC NULLS LAST) WHERE (b > 0)"
            ),
        }


def _relations(conn: psycopg.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace"
        " AND relkind IN ('r', 'm')"
    ).fetchall()
    return {name for (name,) in rows}


class TestPlainCreates:
    """A transactional generated migration creates its new relations with no IF NOT EXISTS."""

    OLD = "CREATE TABLE t (id INT PRIMARY KEY);\n"
    NEW = OLD + (
        "CREATE TABLE u (id INT, tid INT REFERENCES t (id));\n"
        "CREATE MATERIALIZED VIEW mv_u AS SELECT id FROM u;\n"
    )

    def test_a_new_table_and_matview_round_trip(self, fresh_database: str, tmp_path: Path) -> None:
        up, _ = _generated(tmp_path, self.OLD, self.NEW)
        assert sorted(d.argument for d in sql_lexer.directives(up) if d.name == "creates") == [
            "mv_u",
            "u",
        ]
        conn = round_trip(fresh_database, tmp_path, self.OLD, self.NEW)
        assert _relations(conn) == {"t", "u", "mv_u"}

    def test_the_up_applied_twice_fails_with_duplicate_table(
        self, fresh_database: str, tmp_path: Path
    ) -> None:
        up, _ = _generated(tmp_path, self.OLD, self.NEW)
        conn = psycopg.connect(fresh_database, autocommit=True)
        _apply(conn, self.OLD)
        _apply(conn, up)
        with pytest.raises(psycopg.errors.DuplicateTable):
            _apply(conn, up)


class TestAutocommitCreates:
    """A file with a concurrent index runs in autocommit; a failed run retries from the top."""

    OLD = "CREATE TABLE t (a INT, b TEXT);\n"
    NEW = (
        "CREATE TABLE t (a INT, b INT);\nCREATE INDEX ix_t_a ON t (a);\nCREATE TABLE u (id INT);\n"
    )

    def _up(self, url: str, tmp_path: Path) -> tuple[int, str]:
        config = tmp_path / "local.yaml"
        config.write_text(f"name: test\ndatabase_url: {url}\n")
        result = CliRunner().invoke(
            app,
            ["migrate", "up", "--migrations-dir", str(tmp_path / "migrations"), "--config", str(config), "--format", "json"],
        )  # fmt: skip
        return result.exit_code, result.output

    def test_a_failed_file_retries_cleanly(self, fresh_database: str, tmp_path: Path) -> None:
        migrations = tmp_path / "migrations"
        migrations.mkdir()
        up, _ = _generated(migrations, self.OLD, self.NEW)
        assert "CREATE TABLE IF NOT EXISTS u" in up
        assert "CONCURRENTLY" in up
        assert not [d for d in sql_lexer.directives(up) if d.name == "creates"]
        # The author answers the backfill gate (#766) wrongly: a row that does not cast
        # is left, so the file fails at the type change, after the table it creates.
        [up_file] = migrations.glob("*.up.sql")
        up_file.write_text(
            "\n".join(
                "-- confiture:backfill none" if line.startswith("-- confiture:backfill ") else line
                for line in up.splitlines()
            )
            + "\n"
        )

        conn = psycopg.connect(fresh_database, autocommit=True)
        _apply(conn, self.OLD)
        conn.execute("INSERT INTO t VALUES (1, 'x')")

        code, output = self._up(fresh_database, tmp_path)
        assert code != 0, output
        assert "u" in _relations(conn)
        assert conn.execute("SELECT count(*) FROM tb_confiture").fetchone() == (0,)

        conn.execute("UPDATE t SET b = '0'")
        code, output = self._up(fresh_database, tmp_path)
        assert code == 0, output
        assert conn.execute("SELECT version FROM tb_confiture").fetchall() == [("20260101000000",)]
        assert conn.execute(
            "SELECT indisvalid FROM pg_index WHERE indexrelid = 'ix_t_a'::regclass"
        ).fetchone() == (True,)


class TestPythonMigrationUnderMigrateUp:
    """The issue's reproduction: an enum label and a concurrent index, in one ``.py``."""

    OLD = "CREATE TABLE t (id bigint PRIMARY KEY, c text);\nCREATE TYPE mood AS ENUM ('a');\n"
    NEW = (
        "CREATE TABLE t (id bigint PRIMARY KEY, c text);\n"
        "CREATE INDEX idx_t_c ON t (c);\n"
        "CREATE TYPE mood AS ENUM ('a', 'b');\n"
    )

    @staticmethod
    def _run(*argv: str) -> None:
        result = CliRunner().invoke(app, list(argv))
        assert result.exit_code == 0, result.output

    def _generated(self, tmp_path: Path, url: str, old: str, new: str) -> list[str]:
        """*old* built into *url*, the ``.py`` generated; the ``migrate`` arguments that reach it."""
        (tmp_path / "old.sql").write_text(old)
        (tmp_path / "new.sql").write_text(new)
        migrations = tmp_path / "migrations"
        self._run(
            "migrate", "diff", str(tmp_path / "old.sql"), str(tmp_path / "new.sql"),
            "--generate", "--name", "step", "--migrations-dir", str(migrations),
        )  # fmt: skip
        assert [p.suffix for p in migrations.glob("*_step*")] == [".py"]
        with psycopg.connect(url, autocommit=True) as conn:
            _apply(conn, old)
        return ["--migrations-dir", str(migrations), "-d", url, "--no-config"]

    @staticmethod
    def _state(url: str) -> tuple[bool | None, list[str], int]:
        with psycopg.connect(url) as conn:
            valid = conn.execute(
                "SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid"
                " WHERE c.relname = 'idx_t_c'"
            ).fetchone()
            labels = conn.execute(
                "SELECT enumlabel FROM pg_enum WHERE enumtypid = 'mood'::regtype ORDER BY 1"
            ).fetchall()
            applied = conn.execute("SELECT count(*) FROM tb_confiture").fetchone()
        assert applied is not None
        return (valid[0] if valid else None), [label for (label,) in labels], applied[0]

    @pytest.fixture(autouse=True)
    def _isolated(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

    def test_a_generated_concurrent_index_applies(
        self, fresh_database: str, tmp_path: Path
    ) -> None:
        common = self._generated(tmp_path, fresh_database, self.OLD, self.NEW)
        self._run("migrate", "up", *common)
        assert self._state(fresh_database) == (True, ["a", "b"], 1)

    def test_the_down_drops_the_index_concurrently_and_up_applies_again(
        self, fresh_database: str, tmp_path: Path
    ) -> None:
        common = self._generated(tmp_path, fresh_database, self.OLD, self.NEW)
        self._run("migrate", "up", *common)
        self._run("migrate", "down", "-n", "1", *common)
        assert self._state(fresh_database) == (None, ["a", "b"], 0)
        self._run("migrate", "up", *common)
        assert self._state(fresh_database) == (True, ["a", "b"], 1)

    def test_a_label_used_by_a_default_in_the_same_file_applies(
        self, fresh_database: str, tmp_path: Path
    ) -> None:
        """In one transaction PostgreSQL refuses the new label before commit (55P04)."""
        old = "CREATE TYPE mood AS ENUM ('a');\nCREATE TABLE p (m mood DEFAULT 'a');\n"
        new = "CREATE TYPE mood AS ENUM ('a', 'b');\nCREATE TABLE p (m mood DEFAULT 'b');\n"
        common = self._generated(tmp_path, fresh_database, old, new)
        self._run("migrate", "up", *common)
        with psycopg.connect(fresh_database) as conn:
            default = conn.execute(
                "SELECT column_default FROM information_schema.columns"
                " WHERE table_name = 'p' AND column_name = 'm'"
            ).fetchone()
        assert default == ("'b'::mood",)
