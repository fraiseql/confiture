"""Unit tests for the external migration generator feature (Issue #49).

Tests cover:
- MigrationGeneratorConfig validation
- _strip_transaction_wrappers helper
- MigrationGenerator.run_external_generator() (mocked subprocess, tmp_path for I/O)
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from confiture.config.environment import MigrationGeneratorConfig
from confiture.core.migration_generator import MigrationGenerator, _strip_transaction_wrappers
from confiture.exceptions import ExternalGeneratorError

# ---------------------------------------------------------------------------
# MigrationGeneratorConfig validation
# ---------------------------------------------------------------------------


class TestMigrationGeneratorConfig:
    def test_valid_config_parses_ok(self):
        cfg = MigrationGeneratorConfig(
            command="pgdiff --from {from} --to {to} --output {output}",
            description="Diff tool",
        )
        assert "{from}" in cfg.command
        assert cfg.description == "Diff tool"

    def test_empty_command_raises(self):
        with pytest.raises(ValidationError, match="must not be empty"):
            MigrationGeneratorConfig(command="")

    def test_missing_from_placeholder_raises(self):
        with pytest.raises(ValidationError, match=r"\{from\}"):
            MigrationGeneratorConfig(command="tool --to {to} --output {output}")

    def test_missing_to_placeholder_raises(self):
        with pytest.raises(ValidationError, match=r"\{to\}"):
            MigrationGeneratorConfig(command="tool --from {from} --output {output}")

    def test_missing_output_placeholder_raises(self):
        with pytest.raises(ValidationError, match=r"\{output\}"):
            MigrationGeneratorConfig(command="tool --from {from} --to {to}")

    def test_empty_migration_generators_dict_ok(self):
        from confiture.config.environment import MigrationConfig

        cfg = MigrationConfig()
        assert cfg.migration_generators == {}

    def test_description_defaults_to_empty_string(self):
        cfg = MigrationGeneratorConfig(command="tool {from} {to} {output}")
        assert cfg.description == ""


# ---------------------------------------------------------------------------
# _strip_transaction_wrappers
# ---------------------------------------------------------------------------


class TestStripTransactionWrappers:
    def test_strips_begin_semicolon(self):
        sql = "BEGIN;\nALTER TABLE foo ADD COLUMN bar TEXT;\nCOMMIT;"
        result = _strip_transaction_wrappers(sql)
        assert "BEGIN" not in result
        assert "COMMIT" not in result
        assert "ALTER TABLE foo ADD COLUMN bar TEXT;" in result

    def test_strips_begin_without_semicolon(self):
        sql = "BEGIN\nSELECT 1;\nCOMMIT"
        result = _strip_transaction_wrappers(sql)
        assert result.strip() == "SELECT 1;"

    def test_strips_commit_without_semicolon(self):
        sql = "BEGIN;\nSELECT 1;\nCOMMIT"
        result = _strip_transaction_wrappers(sql)
        assert "COMMIT" not in result

    def test_case_insensitive_begin(self):
        sql = "begin;\nSELECT 1;\ncommit;"
        result = _strip_transaction_wrappers(sql)
        assert "begin" not in result.lower().split("\n")[0] if result.strip() else True
        assert "SELECT 1;" in result

    def test_case_insensitive_commit(self):
        sql = "Begin;\nSELECT 1;\nCommit;"
        result = _strip_transaction_wrappers(sql)
        assert "Select" not in result or "SELECT 1;" in result
        assert "Begin" not in result
        assert "Commit" not in result

    def test_does_not_strip_begin_deferred(self):
        sql = "BEGIN DEFERRED;\nSELECT 1;\nCOMMIT;"
        result = _strip_transaction_wrappers(sql)
        assert "BEGIN DEFERRED;" in result

    def test_does_not_strip_partial_match_mid_line(self):
        sql = "-- BEGIN migration\nSELECT 1;\n-- COMMIT done"
        result = _strip_transaction_wrappers(sql)
        assert "-- BEGIN migration" in result
        assert "-- COMMIT done" in result

    def test_preserves_sql_body_untouched(self):
        body = "ALTER TABLE orders ADD COLUMN total NUMERIC(10,2) DEFAULT 0;"
        sql = f"BEGIN;\n{body}\nCOMMIT;"
        result = _strip_transaction_wrappers(sql)
        assert result.strip() == body

    def test_leading_trailing_blank_lines_collapsed(self):
        sql = "\n\nBEGIN;\n\nSELECT 1;\n\nCOMMIT;\n\n"
        result = _strip_transaction_wrappers(sql)
        assert not result.startswith("\n")
        assert result.strip() == "SELECT 1;"

    def test_empty_input_returns_empty(self):
        assert _strip_transaction_wrappers("") == ""

    def test_only_begin_commit_returns_empty(self):
        sql = "BEGIN;\nCOMMIT;"
        result = _strip_transaction_wrappers(sql)
        assert result.strip() == ""


# ---------------------------------------------------------------------------
# MigrationGenerator.run_external_generator
# ---------------------------------------------------------------------------


class TestRunExternalGenerator:
    def _make_gen_config(
        self, command: str = "tool {from} {to} {output}"
    ) -> MigrationGeneratorConfig:
        return MigrationGeneratorConfig(command=command)

    def test_dry_run_returns_command_and_path_without_subprocess(self, tmp_path):
        from_file = tmp_path / "v1.sql"
        to_file = tmp_path / "v2.sql"
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        gen = MigrationGenerator(migrations_dir=migrations_dir)
        cfg = self._make_gen_config()

        with patch("subprocess.run") as mock_run:
            resolved_cmd, out_path = gen.run_external_generator(
                generator_config=cfg,
                from_path=from_file,
                to_path=to_file,
                migration_name="add_column",
                dry_run=True,
            )
            mock_run.assert_not_called()

        assert "add_column" in out_path.name
        assert out_path.name.endswith(".up.sql")
        assert "tool" in resolved_cmd

    def test_success_path_writes_up_and_down_sql(self, tmp_path):
        from_file = tmp_path / "v1.sql"
        from_file.write_text("SELECT 1;")
        to_file = tmp_path / "v2.sql"
        to_file.write_text("SELECT 2;")
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        gen = MigrationGenerator(migrations_dir=migrations_dir)
        cfg = self._make_gen_config()

        def fake_run(cmd, **kwargs):
            # Simulate generator writing SQL to output path
            import shlex as _shlex

            # Extract the output path from the command (last quoted arg)
            parts = _shlex.split(cmd)
            out = parts[-1]
            Path(out).write_text("BEGIN;\nALTER TABLE foo ADD COLUMN bar TEXT;\nCOMMIT;")
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            return result

        with patch("subprocess.run", side_effect=fake_run):
            resolved_cmd, up_path = gen.run_external_generator(
                generator_config=cfg,
                from_path=from_file,
                to_path=to_file,
                migration_name="add_bar_column",
            )

        assert up_path.exists()
        sql = up_path.read_text()
        assert "BEGIN" not in sql
        assert "COMMIT" not in sql
        assert "ALTER TABLE foo ADD COLUMN bar TEXT;" in sql

        down_path = up_path.parent / up_path.name.replace(".up.sql", ".down.sql")
        assert down_path.exists()
        assert "TODO" in down_path.read_text()

    def test_nonzero_exit_raises_external_generator_error(self, tmp_path):
        from_file = tmp_path / "v1.sql"
        from_file.write_text("SELECT 1;")
        to_file = tmp_path / "v2.sql"
        to_file.write_text("SELECT 2;")
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        gen = MigrationGenerator(migrations_dir=migrations_dir)
        cfg = self._make_gen_config()

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "pgdiff: connection refused"

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(ExternalGeneratorError) as exc_info:
                gen.run_external_generator(
                    generator_config=cfg,
                    from_path=from_file,
                    to_path=to_file,
                    migration_name="fail_migration",
                )

        assert exc_info.value.returncode == 1
        assert "connection refused" in str(exc_info.value)

    def test_from_path_missing_raises_file_not_found(self, tmp_path):
        from_file = tmp_path / "nonexistent_v1.sql"
        to_file = tmp_path / "v2.sql"
        to_file.write_text("SELECT 2;")
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        gen = MigrationGenerator(migrations_dir=migrations_dir)
        cfg = self._make_gen_config()

        with patch("subprocess.run") as mock_run:
            with pytest.raises(FileNotFoundError, match="from_path"):
                gen.run_external_generator(
                    generator_config=cfg,
                    from_path=from_file,
                    to_path=to_file,
                    migration_name="add_column",
                )
            mock_run.assert_not_called()

    def test_to_path_missing_raises_file_not_found(self, tmp_path):
        from_file = tmp_path / "v1.sql"
        from_file.write_text("SELECT 1;")
        to_file = tmp_path / "nonexistent_v2.sql"
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        gen = MigrationGenerator(migrations_dir=migrations_dir)
        cfg = self._make_gen_config()

        with patch("subprocess.run") as mock_run:
            with pytest.raises(FileNotFoundError, match="to_path"):
                gen.run_external_generator(
                    generator_config=cfg,
                    from_path=from_file,
                    to_path=to_file,
                    migration_name="add_column",
                )
            mock_run.assert_not_called()

    def test_down_stub_not_overwritten_if_exists(self, tmp_path):
        from_file = tmp_path / "v1.sql"
        from_file.write_text("SELECT 1;")
        to_file = tmp_path / "v2.sql"
        to_file.write_text("SELECT 2;")
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        gen = MigrationGenerator(migrations_dir=migrations_dir)
        cfg = self._make_gen_config()

        existing_down_content = "DROP TABLE foo;\n"

        def fake_run(cmd, **kwargs):
            import shlex as _shlex

            parts = _shlex.split(cmd)
            out = parts[-1]
            out_path = Path(out)
            out_path.write_text("ALTER TABLE foo ADD COLUMN bar TEXT;")
            # Pre-create the down stub to verify it's not overwritten
            down = out_path.parent / out_path.name.replace(".up.sql", ".down.sql")
            down.write_text(existing_down_content)
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            return result

        with patch("subprocess.run", side_effect=fake_run):
            _, up_path = gen.run_external_generator(
                generator_config=cfg,
                from_path=from_file,
                to_path=to_file,
                migration_name="add_bar_column",
            )

        down_path = up_path.parent / up_path.name.replace(".up.sql", ".down.sql")
        assert down_path.read_text() == existing_down_content

    def test_path_with_spaces_is_shell_quoted(self, tmp_path):
        spaced_dir = tmp_path / "my schema files"
        spaced_dir.mkdir()
        from_file = spaced_dir / "v1.sql"
        from_file.write_text("SELECT 1;")
        to_file = spaced_dir / "v2.sql"
        to_file.write_text("SELECT 2;")
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        gen = MigrationGenerator(migrations_dir=migrations_dir)
        cfg = self._make_gen_config("tool {from} {to} {output}")

        resolved_cmd, _ = gen.run_external_generator(
            generator_config=cfg,
            from_path=from_file,
            to_path=to_file,
            migration_name="spaced_test",
            dry_run=True,
        )

        # The path contains a space, so it must appear inside quotes in the resolved command
        assert "my schema files" in resolved_cmd
        # The space-containing directory must be wrapped in single quotes by shlex.quote
        assert (
            f"'/{from_file.parent.name}/" in resolved_cmd or f"'{from_file.parent}/" in resolved_cmd
        )

    def test_empty_sql_file_raises_external_generator_error(self, tmp_path):
        from_file = tmp_path / "v1.sql"
        from_file.write_text("SELECT 1;")
        to_file = tmp_path / "v2.sql"
        to_file.write_text("SELECT 2;")
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        gen = MigrationGenerator(migrations_dir=migrations_dir)
        cfg = self._make_gen_config()

        def fake_run(cmd, **kwargs):
            import shlex as _shlex

            parts = _shlex.split(cmd)
            out = parts[-1]
            Path(out).write_text("")
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            return result

        with patch("subprocess.run", side_effect=fake_run):
            with pytest.raises(ExternalGeneratorError, match="empty"):
                gen.run_external_generator(
                    generator_config=cfg,
                    from_path=from_file,
                    to_path=to_file,
                    migration_name="empty_gen",
                )
