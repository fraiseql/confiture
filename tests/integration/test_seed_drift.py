"""``confiture seed drift`` against real databases (#743).

Two databases on the test server: one holds the schema and its seeds (the
seed-built environment), the other the schema and only what a migration inserted
(the migrate-only one). The rows differ the way the issue's table does: a row the
seed adds that no migration shipped, a row only the live side holds, and one key
whose identifier was renamed on one side. Everything else is equal, even though
the live side's generated keys were handed out in another order and its server
renders timestamps in another time zone.
"""

import json
import os
from collections.abc import Callable, Iterator
from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.seed.drift import read_only
from confiture.core.temp_database import TempDatabase

runner = CliRunner()

pytestmark = pytest.mark.integration

DDL = """
CREATE SCHEMA catalog;
CREATE TABLE catalog.tb_unit (
    pk_unit bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id uuid NOT NULL UNIQUE,
    identifier text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE catalog.tb_conversion (
    id uuid PRIMARY KEY,
    fk_unit bigint NOT NULL REFERENCES catalog.tb_unit (pk_unit),
    factor numeric(12, 4) NOT NULL,
    valid_from timestamptz NOT NULL
);
"""

KILOGRAM, GRAM, METRE = (
    "a1000000-0000-4000-8000-000000000001",
    "b2000000-0000-4000-8000-000000000002",
    "c3000000-0000-4000-8000-000000000003",
)
CONVERSION = "d4000000-0000-4000-8000-000000000004"

SEED = f"""
INSERT INTO catalog.tb_unit (id, identifier) VALUES
    ('{KILOGRAM}', 'kilogram'),
    ('{METRE}', 'metre');
INSERT INTO catalog.tb_conversion (id, fk_unit, factor, valid_from)
    VALUES ('{CONVERSION}', 2, 1000, '2026-01-01 00:00:00+00');
"""

#: What migrations put in the migrate-only database: `meter`, not `metre`; `gram`,
#: which the seed lacks; no `kilogram`. Its generated keys come in another order.
MIGRATED = f"""
INSERT INTO catalog.tb_unit (id, identifier) VALUES ('{METRE}', 'meter'), ('{GRAM}', 'gram');
INSERT INTO catalog.tb_conversion (id, fk_unit, factor, valid_from)
    VALUES ('{CONVERSION}', 1, 1000.0000, '2026-01-01 09:00:00+09');
"""


def _apply(url: str, *sql: str) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        for text in sql:
            conn.execute(text)


@pytest.fixture
def in_tmp(tmp_path: Path) -> Iterator[Path]:
    old = Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(old)


@pytest.fixture
def databases(fresh_database_factory: Callable[[str], str]) -> tuple[str, str]:
    """``(seed-built, migrate-only)``: the second renders timestamps in Tokyo time."""
    seeded = fresh_database_factory("confiture_seeddrift_seed")
    live = fresh_database_factory("confiture_seeddrift_live")
    _apply(seeded, DDL, SEED)
    _apply(live, DDL, MIGRATED)
    with psycopg.connect(live, autocommit=True) as conn:
        name = conn.info.dbname
        conn.execute(f"ALTER DATABASE \"{name}\" SET TimeZone TO 'Asia/Tokyo'")
    return seeded, live


def _project(root: Path, database_url: str, *, scratch_url: str = "", extra: str = "") -> None:
    (root / "db" / "schema").mkdir(parents=True)
    (root / "db" / "seeds").mkdir(parents=True)
    (root / "db" / "environments").mkdir(parents=True)
    (root / "db" / "schema" / "010_catalog.sql").write_text(DDL)
    (root / "db" / "seeds" / "010_units.sql").write_text(SEED)
    scratch = f"scratch_url: {scratch_url}\n" if scratch_url else ""
    (root / "db" / "environments" / "local.yaml").write_text(
        f"database_url: {database_url}\n{scratch}"
        "include_dirs:\n  - path: db/schema\n  - path: db/seeds\n" + extra
    )


def _drift(*args: str) -> tuple[int, dict]:
    result = runner.invoke(app, ["seed", "drift", "--format", "json", *args])
    try:
        return result.exit_code, json.loads(result.stdout)
    except json.JSONDecodeError:
        pytest.fail(result.output)


def _table(payload: dict, name: str) -> dict:
    return next(t for t in payload["tables"] if t["table"] == name)


class TestTheIssueTable:
    def test_seed_only_live_only_and_a_renamed_identifier(
        self, in_tmp: Path, databases: tuple[str, str]
    ) -> None:
        seeded, live = databases
        _project(in_tmp, seeded)

        code, payload = _drift("--against", live)

        assert code == 1
        units = _table(payload, "catalog.tb_unit")
        assert units["seed_only"] == [[KILOGRAM]]
        assert units["live_only"] == [[GRAM]]
        assert units["changed"] == [
            {
                "key": [METRE],
                "columns": [{"column": "identifier", "seed": "metre", "live": "meter"}],
            }
        ]

    def test_a_dereferenced_key_and_the_rendering_settings_hide_no_difference(
        self, in_tmp: Path, databases: tuple[str, str]
    ) -> None:
        """``fk_unit`` is 2 on one side and 1 on the other, the same metre; the times are one instant."""
        seeded, live = databases
        _project(in_tmp, seeded)

        _code, payload = _drift("--against", live)

        conversions = _table(payload, "catalog.tb_conversion")
        assert (conversions["seed_only"], conversions["live_only"], conversions["changed"]) == (
            [],
            [],
            [],
        )

    def test_built_seed_side_reports_the_same(
        self, in_tmp: Path, databases: tuple[str, str], test_db_url: str
    ) -> None:
        _seeded, live = databases
        _project(
            in_tmp, "postgresql://127.0.0.1:1/confiture_no_such_server", scratch_url=test_db_url
        )

        code, payload = _drift("--against", live, "--build")

        assert code == 1
        assert payload["seed_side"] == {"source": "built"}
        assert _table(payload, "catalog.tb_unit")["seed_only"] == [[KILOGRAM]]


class TestWhatIsNotAPass:
    def test_a_table_missing_on_the_live_side_is_not_compared(
        self, in_tmp: Path, databases: tuple[str, str]
    ) -> None:
        seeded, live = databases
        _apply(live, "DROP TABLE catalog.tb_conversion")
        _apply(
            live, "DELETE FROM catalog.tb_unit WHERE id <> '00000000-0000-0000-0000-000000000000'"
        )
        _apply(
            live,
            f"INSERT INTO catalog.tb_unit (id, identifier) VALUES ('{KILOGRAM}', 'kilogram'), ('{METRE}', 'metre')",
        )
        _project(in_tmp, seeded)

        code, payload = _drift("--against", live)

        assert code == 2
        [entry] = payload["not_compared"]
        assert entry["table"] == "catalog.tb_conversion"
        assert "does not exist on the live side" in entry["reason"]

    def test_a_seed_file_that_fails_to_build_is_named_and_the_scratch_dropped(
        self,
        in_tmp: Path,
        databases: tuple[str, str],
        test_db_url: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _seeded, live = databases
        _project(
            in_tmp, "postgresql://127.0.0.1:1/confiture_no_such_server", scratch_url=test_db_url
        )
        (in_tmp / "db" / "seeds" / "020_broken.sql").write_text(
            "INSERT INTO catalog.tb_unit (id, identifier) VALUES ('not-a-uuid', 'x');\n"
        )
        built: list[str] = []
        enter = TempDatabase.__enter__

        def recording(self: TempDatabase) -> str:
            url = enter(self)
            built.append(url.rsplit("/", 1)[-1])
            return url

        monkeypatch.setattr(TempDatabase, "__enter__", recording)

        code, payload = _drift("--against", live, "--build")

        assert code == 2
        [entry] = [e for e in payload["not_compared"] if e["table"] == "seed side"]
        assert "020_broken.sql" in entry["reason"]
        [name] = built
        with psycopg.connect(test_db_url) as conn:
            left = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
        assert left is None

    def test_an_unreachable_against_exits_3_with_its_password_masked(
        self, in_tmp: Path, databases: tuple[str, str]
    ) -> None:
        seeded, _live = databases
        _project(in_tmp, seeded)

        result = runner.invoke(
            app,
            [
                "seed",
                "drift",
                "--against",
                "postgresql://u:hunter2@127.0.0.1:1/confiture_no_such_server",
                "--format",
                "json",
            ],
        )

        assert result.exit_code == 3, result.output
        assert "hunter2" not in result.output


class TestOptOuts:
    def test_subset_reports_no_live_only_row(
        self, in_tmp: Path, databases: tuple[str, str]
    ) -> None:
        seeded, live = databases
        _project(
            in_tmp,
            seeded,
            extra="seed_drift:\n  tables:\n    catalog.tb_unit:\n"
            "      mode: subset\n      reason: grows in production\n",
        )

        _code, payload = _drift("--against", live)

        units = _table(payload, "catalog.tb_unit")
        assert units["live_only"] == []
        assert units["seed_only"] == [[KILOGRAM]]

    def test_an_accepted_difference_is_kept_visible_and_an_unused_one_is_a_finding(
        self, in_tmp: Path, databases: tuple[str, str]
    ) -> None:
        seeded, live = databases
        _project(
            in_tmp,
            seeded,
            extra=(
                "seed_drift:\n  accepted:\n    production:\n"
                f"      - {{table: catalog.tb_unit, key: ['{METRE}'], reason: renamed on purpose}}\n"
                f"      - {{table: catalog.tb_unit, key: ['{CONVERSION}'], reason: long gone}}\n"
            ),
        )
        (in_tmp / "db" / "environments" / "production.yaml").write_text(
            f"database_url: {live}\ninclude_dirs:\n  - path: db/schema\n"
        )

        code, payload = _drift("--against", "production")

        units = _table(payload, "catalog.tb_unit")
        assert units["accepted"] == [[METRE]]
        assert units["changed"] == []
        assert payload["unused"] == [
            f"seed_drift.accepted.production: catalog.tb_unit ['{CONVERSION}'] matches no difference"
        ]
        assert code == 1

    def test_a_table_over_max_rows_is_not_read_whole(
        self, in_tmp: Path, databases: tuple[str, str]
    ) -> None:
        seeded, live = databases
        _apply(live, "ANALYZE catalog.tb_unit")
        _project(in_tmp, seeded, extra="seed_drift:\n  max_rows: 1\n")

        code, payload = _drift("--against", live)

        assert code in (1, 2)
        assert any(
            e["table"] == "catalog.tb_unit" and "mode: subset" in e["reason"]
            for e in payload["not_compared"]
        )


def test_the_live_side_is_read_only(databases: tuple[str, str]) -> None:
    _seeded, live = databases
    with psycopg.connect(live) as conn, read_only(conn, "5s"):
        assert conn.execute("SHOW transaction_read_only").fetchone() == ("on",)
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction), conn.transaction():
            conn.execute("DELETE FROM catalog.tb_unit")


def test_list_scope_reads_no_database(in_tmp: Path) -> None:
    _project(in_tmp, "postgresql://127.0.0.1:1/confiture_no_such_server")

    code, payload = _drift("--list-scope")

    assert code == 0
    assert payload["compared"] is False
    assert [t["table"] for t in payload["scope"]] == ["catalog.tb_unit", "catalog.tb_conversion"]
    conversion = payload["scope"][1]
    assert conversion["columns"] == ["fk_unit -> catalog.tb_unit.id", "factor", "valid_from"]


class TestWhatTheReleaseReviewFound:
    """Each a shape a reviewer built against the first cut, and what it got wrong."""

    def test_a_sensitive_column_is_compared_as_a_digest_and_never_printed(
        self, in_tmp: Path, fresh_database_factory: Callable[[str], str]
    ) -> None:
        ddl = "CREATE TABLE app_user (login text PRIMARY KEY, api_token text NOT NULL);\n"
        seeded = fresh_database_factory("confiture_seeddrift_seed")
        live = fresh_database_factory("confiture_seeddrift_live")
        _apply(seeded, ddl, "INSERT INTO app_user VALUES ('admin', 'dev-token');")
        _apply(live, ddl, "INSERT INTO app_user VALUES ('admin', 'prod-live-token');")
        (in_tmp / "db" / "schema").mkdir(parents=True)
        (in_tmp / "db" / "seeds").mkdir(parents=True)
        (in_tmp / "db" / "environments").mkdir(parents=True)
        (in_tmp / "db" / "schema" / "010.sql").write_text(ddl)
        (in_tmp / "db" / "seeds" / "010.sql").write_text(
            "INSERT INTO app_user VALUES ('admin', 'dev-token');\n"
        )
        (in_tmp / "db" / "environments" / "local.yaml").write_text(
            f"database_url: {seeded}\ninclude_dirs:\n  - path: db/schema\n  - path: db/seeds\n"
        )

        result = runner.invoke(app, ["seed", "drift", "--against", live])

        assert result.exit_code == 1, result.output
        assert "api_token" in result.output
        assert "prod-live-token" not in result.output
        assert "dev-token" not in result.output

    def test_an_unanalysed_table_over_max_rows_is_not_read_whole(
        self, in_tmp: Path, databases: tuple[str, str]
    ) -> None:
        """A planner estimate is -1 before the first ANALYZE: the bound is a count."""
        seeded, live = databases
        _project(in_tmp, seeded, extra="seed_drift:\n  max_rows: 1\n")

        code, payload = _drift("--against", live)

        assert code == 2
        [entry] = payload["not_compared"]
        assert entry["table"] == "catalog.tb_unit"  # 2 live rows; tb_conversion holds 1
        assert "mode: subset" in entry["reason"]

    def test_duplicate_live_keys_are_not_compared(
        self, in_tmp: Path, databases: tuple[str, str]
    ) -> None:
        seeded, live = databases
        _apply(
            live,
            "ALTER TABLE catalog.tb_conversion DROP CONSTRAINT tb_conversion_pkey",
            f"INSERT INTO catalog.tb_conversion SELECT * FROM catalog.tb_conversion "
            f"WHERE id = '{CONVERSION}'",
        )
        _project(in_tmp, seeded)

        code, payload = _drift("--against", live)

        assert code == 2
        [entry] = [e for e in payload["not_compared"] if e["table"] == "catalog.tb_conversion"]
        assert "share the key" in entry["reason"]

    def test_the_live_search_path_cannot_redirect_a_read(
        self, in_tmp: Path, databases: tuple[str, str]
    ) -> None:
        seeded, live = databases
        _apply(
            live,
            "CREATE SCHEMA shadow",
            "CREATE TABLE shadow.tb_unit (id uuid)",
            f'ALTER ROLE CURRENT_USER IN DATABASE "{live.rsplit("/", 1)[-1]}" '
            "SET search_path = shadow, catalog, public",
        )
        _project(in_tmp, seeded)

        _code, payload = _drift("--against", live)

        assert _table(payload, "catalog.tb_unit")["live_rows"] == 2

    def test_an_unreachable_scratch_server_exits_3(
        self, in_tmp: Path, databases: tuple[str, str]
    ) -> None:
        _seeded, live = databases
        _project(
            in_tmp,
            "postgresql://127.0.0.1:1/confiture_no_such_server",
            scratch_url="postgresql://127.0.0.1:1/confiture_no_such_server",
        )

        result = runner.invoke(app, ["seed", "drift", "--against", live, "--build"])

        assert result.exit_code == 3, result.output


class TestWhatTheSecondPassFound:
    def test_a_key_is_never_masked_and_subset_still_matches_it(
        self, in_tmp: Path, fresh_database_factory: Callable[[str], str]
    ) -> None:
        """``token_kind`` reads as sensitive; it is the key, so it must stay comparable."""
        ddl = "CREATE TABLE token_kind (token_kind text PRIMARY KEY, label text NOT NULL);\n"
        seed = "INSERT INTO token_kind VALUES ('refresh', 'Refresh'), ('access', 'Access');\n"
        seeded = fresh_database_factory("confiture_seeddrift_seed")
        live = fresh_database_factory("confiture_seeddrift_live")
        _apply(seeded, ddl, seed)
        _apply(live, ddl, seed, "INSERT INTO token_kind VALUES ('device', 'Device')")
        (in_tmp / "db" / "schema").mkdir(parents=True)
        (in_tmp / "db" / "seeds").mkdir(parents=True)
        (in_tmp / "db" / "environments").mkdir(parents=True)
        (in_tmp / "db" / "schema" / "010.sql").write_text(ddl)
        (in_tmp / "db" / "seeds" / "010.sql").write_text(seed)
        (in_tmp / "db" / "environments" / "local.yaml").write_text(
            f"database_url: {seeded}\ninclude_dirs:\n  - path: db/schema\n  - path: db/seeds\n"
            "seed_drift:\n  tables:\n    public.token_kind:\n"
            "      mode: subset\n      reason: grows in production\n"
        )

        code, payload = _drift("--against", live)

        table = _table(payload, "token_kind")
        assert (code, table["seed_only"], table["live_rows"]) == (0, [], 2)

    def test_a_changed_sensitive_value_prints_neither_value_nor_a_digest(
        self, in_tmp: Path, fresh_database_factory: Callable[[str], str]
    ) -> None:
        ddl = "CREATE TABLE app_user (login text PRIMARY KEY, api_token text NOT NULL);\n"
        seeded = fresh_database_factory("confiture_seeddrift_seed")
        live = fresh_database_factory("confiture_seeddrift_live")
        _apply(seeded, ddl, "INSERT INTO app_user VALUES ('admin', 'dev-token')")
        _apply(live, ddl, "INSERT INTO app_user VALUES ('admin', 'prod-live-token')")
        (in_tmp / "db" / "schema").mkdir(parents=True)
        (in_tmp / "db" / "seeds").mkdir(parents=True)
        (in_tmp / "db" / "environments").mkdir(parents=True)
        (in_tmp / "db" / "schema" / "010.sql").write_text(ddl)
        (in_tmp / "db" / "seeds" / "010.sql").write_text(
            "INSERT INTO app_user VALUES ('admin', 'dev-token');\n"
        )
        (in_tmp / "db" / "environments" / "local.yaml").write_text(
            f"database_url: {seeded}\ninclude_dirs:\n  - path: db/schema\n  - path: db/seeds\n"
        )

        _code, payload = _drift("--against", live)

        [changed] = _table(payload, "app_user")["changed"]
        assert changed == {
            "key": ["admin"],
            "columns": [{"column": "api_token", "seed": "<redacted>", "live": "<redacted>"}],
        }

    def test_an_accepted_entry_for_a_table_outside_the_scope_is_unused(
        self, in_tmp: Path, databases: tuple[str, str]
    ) -> None:
        seeded, live = databases
        _project(
            in_tmp,
            seeded,
            extra=(
                "seed_drift:\n  accepted:\n    production:\n"
                "      - {table: catalog.tb_gone, key: ['x'], reason: renamed table}\n"
            ),
        )
        (in_tmp / "db" / "environments" / "production.yaml").write_text(
            f"database_url: {live}\ninclude_dirs:\n  - path: db/schema\n"
        )

        _code, payload = _drift("--against", "production")

        assert payload["unused"] == [
            "seed_drift.accepted.production: catalog.tb_gone ['x'] matches no difference"
        ]
