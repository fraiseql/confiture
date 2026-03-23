"""Tests for pre-flight migration checks (issue #88)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from confiture.core.migration_analyzer import MigrationAnalyzer
from confiture.core.preflight import run_preflight
from confiture.models.results import MigrationPreflightInfo, PreflightResult

# ── Phase 1: Models ──────────────────────────────────────────────────────


class TestMigrationPreflightInfo:
    def test_construction_and_reversible(self):
        info = MigrationPreflightInfo(version="001", name="create_users", has_down=True)
        assert info.reversible is True
        assert info.fully_transactional is True

    def test_irreversible(self):
        info = MigrationPreflightInfo(version="001", name="create_users", has_down=False)
        assert info.reversible is False

    def test_non_transactional(self):
        info = MigrationPreflightInfo(
            version="001",
            name="add_index",
            has_down=True,
            non_transactional_statements=["CREATE INDEX CONCURRENTLY: idx_users_email"],
        )
        assert info.fully_transactional is False

    def test_to_dict(self):
        info = MigrationPreflightInfo(
            version="001",
            name="create_users",
            has_down=True,
            checksum="abc123",
        )
        d = info.to_dict()
        assert d["version"] == "001"
        assert d["name"] == "create_users"
        assert d["has_down"] is True
        assert d["reversible"] is True
        assert d["fully_transactional"] is True
        assert d["non_transactional_statements"] == []
        assert d["checksum"] == "abc123"


class TestPreflightResult:
    def test_all_reversible(self):
        result = PreflightResult(
            migrations=[
                MigrationPreflightInfo(version="001", name="a", has_down=True),
                MigrationPreflightInfo(version="002", name="b", has_down=True),
            ]
        )
        assert result.all_reversible is True
        assert result.irreversible == []

    def test_some_irreversible(self):
        result = PreflightResult(
            migrations=[
                MigrationPreflightInfo(version="001", name="a", has_down=True),
                MigrationPreflightInfo(version="002", name="b", has_down=False),
            ]
        )
        assert result.all_reversible is False
        assert len(result.irreversible) == 1
        assert result.irreversible[0].version == "002"

    def test_all_transactional(self):
        result = PreflightResult(
            migrations=[
                MigrationPreflightInfo(version="001", name="a", has_down=True),
            ]
        )
        assert result.all_transactional is True
        assert result.non_transactional == []

    def test_some_non_transactional(self):
        result = PreflightResult(
            migrations=[
                MigrationPreflightInfo(
                    version="001",
                    name="a",
                    has_down=True,
                    non_transactional_statements=["VACUUM"],
                ),
            ]
        )
        assert result.all_transactional is False
        assert len(result.non_transactional) == 1

    def test_has_duplicates(self):
        result = PreflightResult(
            migrations=[],
            duplicate_versions={"001": ["001_foo.up.sql", "001_bar.up.sql"]},
        )
        assert result.has_duplicates is True

    def test_no_duplicates(self):
        result = PreflightResult(migrations=[])
        assert result.has_duplicates is False

    def test_has_checksum_mismatches(self):
        result = PreflightResult(
            migrations=[],
            checksum_mismatches=["001_foo: expected abc..., got def..."],
        )
        assert result.has_checksum_mismatches is True

    def test_safe_to_deploy_all_good(self):
        result = PreflightResult(
            migrations=[
                MigrationPreflightInfo(version="001", name="a", has_down=True),
            ]
        )
        assert result.safe_to_deploy is True

    def test_safe_to_deploy_false_when_irreversible(self):
        result = PreflightResult(
            migrations=[
                MigrationPreflightInfo(version="001", name="a", has_down=False),
            ]
        )
        assert result.safe_to_deploy is False

    def test_safe_to_deploy_false_when_duplicates(self):
        result = PreflightResult(
            migrations=[
                MigrationPreflightInfo(version="001", name="a", has_down=True),
            ],
            duplicate_versions={"001": ["001_a.up.sql", "001_b.up.sql"]},
        )
        assert result.safe_to_deploy is False

    def test_empty_migrations_safe(self):
        result = PreflightResult(migrations=[])
        assert result.all_reversible is True
        assert result.all_transactional is True
        assert result.safe_to_deploy is True

    def test_to_dict(self):
        result = PreflightResult(
            migrations=[
                MigrationPreflightInfo(version="001", name="a", has_down=True),
            ],
            checksum_verified=True,
        )
        d = result.to_dict()
        assert d["safe_to_deploy"] is True
        assert d["all_reversible"] is True
        assert d["all_transactional"] is True
        assert d["has_duplicates"] is False
        assert d["has_checksum_mismatches"] is False
        assert d["checksum_verified"] is True
        assert len(d["migrations"]) == 1
        assert d["duplicate_versions"] == {}
        assert d["checksum_mismatches"] == []


# ── Phase 1: Reversibility check ─────────────────────────────────────────


class TestReversibilityCheck:
    def test_all_have_down_sql(self, tmp_path: Path):
        mdir = tmp_path / "migrations"
        mdir.mkdir()
        for i in range(1, 4):
            (mdir / f"00{i}_m{i}.up.sql").write_text(f"CREATE TABLE t{i}();")
            (mdir / f"00{i}_m{i}.down.sql").write_text(f"DROP TABLE t{i};")

        result = run_preflight(mdir)
        assert len(result.migrations) == 3
        assert result.all_reversible is True
        assert result.irreversible == []

    def test_some_missing_down_sql(self, tmp_path: Path):
        mdir = tmp_path / "migrations"
        mdir.mkdir()
        (mdir / "001_first.up.sql").write_text("CREATE TABLE t1();")
        (mdir / "001_first.down.sql").write_text("DROP TABLE t1;")
        (mdir / "002_second.up.sql").write_text("CREATE TABLE t2();")
        (mdir / "002_second.down.sql").write_text("DROP TABLE t2;")
        (mdir / "003_third.up.sql").write_text("CREATE TABLE t3();")
        # No .down.sql for 003

        result = run_preflight(mdir)
        assert result.all_reversible is False
        assert len(result.irreversible) == 1
        assert result.irreversible[0].version == "003"
        assert result.irreversible[0].name == "third"

    def test_python_migrations_assumed_reversible(self, tmp_path: Path):
        mdir = tmp_path / "migrations"
        mdir.mkdir()
        (mdir / "001_create_users.py").write_text("class Migration: pass")

        result = run_preflight(mdir)
        assert len(result.migrations) == 1
        assert result.migrations[0].has_down is True
        assert result.migrations[0].reversible is True

    def test_empty_directory(self, tmp_path: Path):
        mdir = tmp_path / "migrations"
        mdir.mkdir()

        result = run_preflight(mdir)
        assert len(result.migrations) == 0
        assert result.all_reversible is True
        assert result.safe_to_deploy is True

    def test_nonexistent_directory(self, tmp_path: Path):
        result = run_preflight(tmp_path / "nonexistent")
        assert len(result.migrations) == 0
        assert result.safe_to_deploy is True


# ── Phase 1: Duplicate version detection ──────────────────────────────────


class TestDuplicateDetection:
    def test_duplicate_versions_detected(self, tmp_path: Path):
        mdir = tmp_path / "migrations"
        mdir.mkdir()
        (mdir / "001_foo.up.sql").write_text("CREATE TABLE foo();")
        (mdir / "001_bar.up.sql").write_text("CREATE TABLE bar();")

        result = run_preflight(mdir)
        assert result.has_duplicates is True
        assert "001" in result.duplicate_versions
        assert len(result.duplicate_versions["001"]) == 2
        assert result.safe_to_deploy is False

    def test_no_duplicates(self, tmp_path: Path):
        mdir = tmp_path / "migrations"
        mdir.mkdir()
        (mdir / "001_foo.up.sql").write_text("CREATE TABLE foo();")
        (mdir / "001_foo.down.sql").write_text("DROP TABLE foo;")
        (mdir / "002_bar.up.sql").write_text("CREATE TABLE bar();")
        (mdir / "002_bar.down.sql").write_text("DROP TABLE bar;")

        result = run_preflight(mdir)
        assert result.has_duplicates is False
        assert result.duplicate_versions == {}

    def test_versions_filter(self, tmp_path: Path):
        mdir = tmp_path / "migrations"
        mdir.mkdir()
        (mdir / "001_first.up.sql").write_text("CREATE TABLE t1();")
        (mdir / "001_first.down.sql").write_text("DROP TABLE t1;")
        (mdir / "002_second.up.sql").write_text("CREATE TABLE t2();")
        (mdir / "002_second.down.sql").write_text("DROP TABLE t2;")
        (mdir / "003_third.up.sql").write_text("CREATE TABLE t3();")
        (mdir / "003_third.down.sql").write_text("DROP TABLE t3;")

        result = run_preflight(mdir, versions=["001", "003"])
        assert len(result.migrations) == 2
        versions = [m.version for m in result.migrations]
        assert "001" in versions
        assert "003" in versions
        assert "002" not in versions


# ── Phase 2: MigrationAnalyzer (pglast path) ─────────────────────────────


class TestMigrationAnalyzerPglast:
    @pytest.fixture(autouse=True)
    def _require_pglast(self):
        pytest.importorskip("pglast")

    def test_create_index_concurrently(self):
        sql = "CREATE INDEX CONCURRENTLY idx_users_email ON users(email);"
        result = MigrationAnalyzer().analyze(sql)
        assert result == ["CREATE INDEX CONCURRENTLY: idx_users_email"]

    def test_regular_create_index_not_detected(self):
        sql = "CREATE INDEX idx_users_email ON users(email);"
        result = MigrationAnalyzer().analyze(sql)
        assert result == []

    def test_alter_type_add_value(self):
        sql = "ALTER TYPE status ADD VALUE 'archived';"
        result = MigrationAnalyzer().analyze(sql)
        assert len(result) == 1
        assert "ALTER TYPE" in result[0]
        assert "ADD VALUE" in result[0]

    def test_mixed_transactional_and_non(self):
        sql = """
        ALTER TABLE users ADD COLUMN bio TEXT;
        CREATE INDEX CONCURRENTLY idx_users_bio ON users(bio);
        """
        result = MigrationAnalyzer().analyze(sql)
        assert len(result) == 1
        assert "CREATE INDEX CONCURRENTLY" in result[0]

    def test_multiple_non_transactional(self):
        sql = """
        CREATE INDEX CONCURRENTLY idx_a ON t(a);
        CREATE INDEX CONCURRENTLY idx_b ON t(b);
        ALTER TYPE status ADD VALUE 'archived';
        """
        result = MigrationAnalyzer().analyze(sql)
        assert len(result) == 3

    def test_vacuum_detected(self):
        sql = "VACUUM ANALYZE users;"
        result = MigrationAnalyzer().analyze(sql)
        assert result == ["VACUUM"]

    def test_cluster_detected(self):
        sql = "CLUSTER users USING idx_users_email;"
        result = MigrationAnalyzer().analyze(sql)
        assert result == ["CLUSTER"]

    def test_purely_transactional_returns_empty(self):
        sql = """
        CREATE TABLE users (id SERIAL PRIMARY KEY, name TEXT);
        ALTER TABLE users ADD COLUMN email TEXT;
        CREATE INDEX idx_users_name ON users(name);
        """
        result = MigrationAnalyzer().analyze(sql)
        assert result == []

    def test_dollar_quoted_body_not_detected(self):
        """pglast correctly ignores statements inside function bodies."""
        sql = """
        CREATE FUNCTION rebuild_indexes() RETURNS void AS $$
        BEGIN
            EXECUTE 'CREATE INDEX CONCURRENTLY idx_temp ON t(c)';
        END;
        $$ LANGUAGE plpgsql;
        """
        result = MigrationAnalyzer().analyze(sql)
        assert result == []


# ── Phase 2: MigrationAnalyzer (regex fallback) ──────────────────────────


class TestMigrationAnalyzerRegex:
    @pytest.fixture(autouse=True)
    def _block_pglast(self):
        with patch.dict(sys.modules, {"pglast": None}):
            yield

    def test_create_index_concurrently(self):
        sql = "CREATE INDEX CONCURRENTLY idx_users_email ON users(email);"
        result = MigrationAnalyzer().analyze(sql)
        assert result == ["CREATE INDEX CONCURRENTLY: idx_users_email"]

    def test_alter_type_add_value(self):
        sql = "ALTER TYPE status ADD VALUE 'archived';"
        result = MigrationAnalyzer().analyze(sql)
        assert len(result) == 1
        assert "ALTER TYPE status ADD VALUE" in result[0]

    def test_drop_index_concurrently(self):
        sql = "DROP INDEX CONCURRENTLY idx_users_email;"
        result = MigrationAnalyzer().analyze(sql)
        assert result == ["DROP INDEX CONCURRENTLY"]

    def test_no_false_positives_on_regular_ddl(self):
        sql = """
        CREATE TABLE users (id SERIAL PRIMARY KEY, name TEXT);
        ALTER TABLE users ADD COLUMN email TEXT;
        CREATE INDEX idx_users_name ON users(name);
        """
        result = MigrationAnalyzer().analyze(sql)
        assert result == []

    def test_create_unique_index_concurrently(self):
        sql = "CREATE UNIQUE INDEX CONCURRENTLY idx_users_email ON users(email);"
        result = MigrationAnalyzer().analyze(sql)
        assert result == ["CREATE INDEX CONCURRENTLY: idx_users_email"]

    def test_vacuum(self):
        sql = "VACUUM ANALYZE users;"
        result = MigrationAnalyzer().analyze(sql)
        assert result == ["VACUUM"]

    def test_create_database(self):
        sql = "CREATE DATABASE mydb;"
        result = MigrationAnalyzer().analyze(sql)
        assert result == ["CREATE DATABASE"]


# ── Phase 2: Integration with reversibility ───────────────────────────────


class TestPreflightNonTransactional:
    def test_non_transactional_detected_in_preflight(self, tmp_path: Path):
        mdir = tmp_path / "migrations"
        mdir.mkdir()
        (mdir / "001_add_table.up.sql").write_text("CREATE TABLE t1();")
        (mdir / "001_add_table.down.sql").write_text("DROP TABLE t1;")
        (mdir / "002_add_index.up.sql").write_text("CREATE INDEX CONCURRENTLY idx ON t1(id);")
        (mdir / "002_add_index.down.sql").write_text("DROP INDEX idx;")

        result = run_preflight(mdir)
        assert result.all_reversible is True
        assert result.all_transactional is False
        assert result.safe_to_deploy is False
        assert len(result.non_transactional) == 1
        assert result.non_transactional[0].version == "002"


# ── Phase 3: MigratorSession.preflight() ─────────────────────────────────


class TestMigratorSessionPreflight:
    def _make_env(self):
        from confiture.config.environment import Environment

        return Environment.model_validate(
            {
                "name": "test",
                "database_url": "postgresql://localhost/test",
                "include_dirs": ["db/schema"],
                "migration": {"tracking_table": "tb_confiture"},
            }
        )

    def _make_session(self, env, migrations_dir):
        from unittest.mock import MagicMock

        from confiture.core.migrator import MigratorSession

        mock_conn = MagicMock()
        with patch("confiture.core.migrator.create_connection", return_value=mock_conn):
            session = MigratorSession(env, migrations_dir)
            session.__enter__()
        return session, mock_conn

    def test_preflight_no_context_all_files(self, tmp_path: Path):
        """Mode 1: no context manager — checks all files on disk."""
        from confiture.core.migrator import MigratorSession

        mdir = tmp_path / "migrations"
        mdir.mkdir()
        (mdir / "001_create.up.sql").write_text("CREATE TABLE t1();")
        (mdir / "001_create.down.sql").write_text("DROP TABLE t1;")
        (mdir / "002_alter.up.sql").write_text("ALTER TABLE t1 ADD COLUMN c TEXT;")
        (mdir / "002_alter.down.sql").write_text("ALTER TABLE t1 DROP COLUMN c;")

        env = self._make_env()
        session = MigratorSession(env, mdir)
        # NOT entering context — session._migrator is None

        result = session.preflight()
        assert len(result.migrations) == 2
        assert result.all_reversible is True
        assert result.checksum_verified is False

    def test_preflight_with_context_pending_only(self, tmp_path: Path):
        """Mode 2: inside context — checks only pending migrations."""
        from unittest.mock import MagicMock

        from confiture.models.results import MigrationInfo, StatusResult

        mdir = tmp_path / "migrations"
        mdir.mkdir()
        (mdir / "001_applied.up.sql").write_text("CREATE TABLE t1();")
        (mdir / "001_applied.down.sql").write_text("DROP TABLE t1;")
        (mdir / "002_pending.up.sql").write_text("CREATE TABLE t2();")
        (mdir / "002_pending.down.sql").write_text("DROP TABLE t2;")

        env = self._make_env()
        session, mock_conn = self._make_session(env, mdir)

        # Mock status() to return 001 as applied, 002 as pending
        mock_status = StatusResult(
            migrations=[
                MigrationInfo(version="001", name="applied", status="applied"),
                MigrationInfo(version="002", name="pending", status="pending"),
            ],
            tracking_table_exists=True,
            tracking_table="tb_confiture",
            summary={"applied": 1, "pending": 1, "total": 2},
        )
        session.status = MagicMock(return_value=mock_status)

        # Mock checksum verifier to return no mismatches
        with patch("confiture.core.checksum.MigrationChecksumVerifier") as mock_verifier_cls:
            mock_verifier = MagicMock()
            mock_verifier.verify_all.return_value = []
            mock_verifier_cls.return_value = mock_verifier

            result = session.preflight()

        assert len(result.migrations) == 1
        assert result.migrations[0].version == "002"
        assert result.checksum_verified is True

    def test_preflight_explicit_versions(self, tmp_path: Path):
        """Mode 3: explicit versions filter."""
        from confiture.core.migrator import MigratorSession

        mdir = tmp_path / "migrations"
        mdir.mkdir()
        (mdir / "001_a.up.sql").write_text("CREATE TABLE a();")
        (mdir / "001_a.down.sql").write_text("DROP TABLE a;")
        (mdir / "002_b.up.sql").write_text("CREATE TABLE b();")
        (mdir / "002_b.down.sql").write_text("DROP TABLE b;")
        (mdir / "003_c.up.sql").write_text("CREATE TABLE c();")
        (mdir / "003_c.down.sql").write_text("DROP TABLE c;")

        env = self._make_env()
        session = MigratorSession(env, mdir)

        result = session.preflight(versions=["001", "003"])
        assert len(result.migrations) == 2
        versions = [m.version for m in result.migrations]
        assert "002" not in versions

    def test_preflight_checksum_mismatches(self, tmp_path: Path):
        """Checksum verification detects tampered files."""
        from unittest.mock import MagicMock

        from confiture.core.checksum import ChecksumMismatch
        from confiture.models.results import MigrationInfo, StatusResult

        mdir = tmp_path / "migrations"
        mdir.mkdir()
        (mdir / "001_foo.up.sql").write_text("CREATE TABLE foo();")
        (mdir / "001_foo.down.sql").write_text("DROP TABLE foo;")

        env = self._make_env()
        session, _ = self._make_session(env, mdir)

        mock_status = StatusResult(
            migrations=[
                MigrationInfo(version="001", name="foo", status="pending"),
            ],
            tracking_table_exists=True,
            tracking_table="tb_confiture",
            summary={"applied": 0, "pending": 1, "total": 1},
        )
        session.status = MagicMock(return_value=mock_status)

        mismatch = ChecksumMismatch(
            version="001",
            name="foo",
            file_path=mdir / "001_foo.up.sql",
            expected="aaaaaaaaaaaa",
            actual="bbbbbbbbbbbb",
        )

        with patch("confiture.core.checksum.MigrationChecksumVerifier") as mock_cls:
            mock_verifier = MagicMock()
            mock_verifier.verify_all.return_value = [mismatch]
            mock_cls.return_value = mock_verifier

            result = session.preflight()

        assert result.has_checksum_mismatches is True
        assert len(result.checksum_mismatches) == 1
        assert result.safe_to_deploy is False

    def test_preflight_no_checksum_outside_context(self, tmp_path: Path):
        """No checksum verification when outside context manager."""
        from confiture.core.migrator import MigratorSession

        mdir = tmp_path / "migrations"
        mdir.mkdir()
        (mdir / "001_foo.up.sql").write_text("CREATE TABLE foo();")
        (mdir / "001_foo.down.sql").write_text("DROP TABLE foo;")

        env = self._make_env()
        session = MigratorSession(env, mdir)

        result = session.preflight()
        assert result.has_checksum_mismatches is False
        assert result.checksum_verified is False


# ── Phase 3: CLI command ──────────────────────────────────────────────────


class TestMigratePreflightCLI:
    def test_table_output_all_safe(self, tmp_path: Path):
        from typer.testing import CliRunner

        from confiture.cli.main import app

        mdir = tmp_path / "migrations"
        mdir.mkdir()
        (mdir / "001_create.up.sql").write_text("CREATE TABLE t1();")
        (mdir / "001_create.down.sql").write_text("DROP TABLE t1;")

        runner = CliRunner()
        result = runner.invoke(app, ["migrate", "preflight", "--migrations-dir", str(mdir)])
        assert result.exit_code == 0
        assert "Safe to deploy" in result.output

    def test_table_output_unsafe(self, tmp_path: Path):
        from typer.testing import CliRunner

        from confiture.cli.main import app

        mdir = tmp_path / "migrations"
        mdir.mkdir()
        (mdir / "001_create.up.sql").write_text("CREATE TABLE t1();")
        # No .down.sql → irreversible

        runner = CliRunner()
        result = runner.invoke(app, ["migrate", "preflight", "--migrations-dir", str(mdir)])
        assert result.exit_code == 1
        assert "irreversible" in result.output

    def test_json_output(self, tmp_path: Path):
        from typer.testing import CliRunner

        from confiture.cli.main import app

        mdir = tmp_path / "migrations"
        mdir.mkdir()
        (mdir / "001_create.up.sql").write_text("CREATE TABLE t1();")
        (mdir / "001_create.down.sql").write_text("DROP TABLE t1;")

        runner = CliRunner()
        result = runner.invoke(
            app, ["migrate", "preflight", "--migrations-dir", str(mdir), "--format", "json"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["safe_to_deploy"] is True
        assert "migrations" in data
        assert "checksum_verified" in data

    def test_json_output_unsafe(self, tmp_path: Path):
        from typer.testing import CliRunner

        from confiture.cli.main import app

        mdir = tmp_path / "migrations"
        mdir.mkdir()
        (mdir / "001_create.up.sql").write_text("CREATE TABLE t1();")
        # No .down.sql

        runner = CliRunner()
        result = runner.invoke(
            app, ["migrate", "preflight", "--migrations-dir", str(mdir), "--format", "json"]
        )
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["safe_to_deploy"] is False

    def test_duplicates_in_output(self, tmp_path: Path):
        from typer.testing import CliRunner

        from confiture.cli.main import app

        mdir = tmp_path / "migrations"
        mdir.mkdir()
        (mdir / "001_foo.up.sql").write_text("CREATE TABLE foo();")
        (mdir / "001_foo.down.sql").write_text("DROP TABLE foo;")
        (mdir / "001_bar.up.sql").write_text("CREATE TABLE bar();")
        (mdir / "001_bar.down.sql").write_text("DROP TABLE bar;")

        runner = CliRunner()
        result = runner.invoke(app, ["migrate", "preflight", "--migrations-dir", str(mdir)])
        assert result.exit_code == 1
        assert "duplicate" in result.output

    def test_non_transactional_in_output(self, tmp_path: Path):
        from typer.testing import CliRunner

        from confiture.cli.main import app

        mdir = tmp_path / "migrations"
        mdir.mkdir()
        (mdir / "001_idx.up.sql").write_text("CREATE INDEX CONCURRENTLY idx ON t(c);")
        (mdir / "001_idx.down.sql").write_text("DROP INDEX idx;")

        runner = CliRunner()
        result = runner.invoke(app, ["migrate", "preflight", "--migrations-dir", str(mdir)])
        assert result.exit_code == 1
        assert "non-transactional" in result.output


# ── Phase 3: Lazy exports ────────────────────────────────────────────────


class TestLazyExports:
    def test_preflight_result_importable(self):
        from confiture import PreflightResult

        assert PreflightResult is not None

    def test_migration_preflight_info_importable(self):
        from confiture import MigrationPreflightInfo

        assert MigrationPreflightInfo is not None

    def test_migration_analyzer_importable(self):
        from confiture import MigrationAnalyzer

        assert MigrationAnalyzer is not None
