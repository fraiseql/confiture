"""Unit tests for `confiture build --dump` CLI wiring (P1, Cycle 3).

The artifact orchestrator is mocked, so no real database or pg_dump is needed.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.schema_artifact import ArtifactResult

runner = CliRunner()


def _project(tmp_path: Path) -> Path:
    schema_dir = tmp_path / "db" / "schema"
    schema_dir.mkdir(parents=True)
    (schema_dir / "01_test.sql").write_text("CREATE TABLE t (id int);")
    env_dir = tmp_path / "db" / "environments"
    env_dir.mkdir(parents=True)
    (env_dir / "local.yaml").write_text(
        f"""
name: local
database_url: "postgresql://localhost/confiture_test"
include_dirs:
  - {schema_dir}
"""
    )
    return tmp_path


class TestBuildDump:
    @patch("confiture.cli.commands.schema.build_schema_artifact")
    def test_dump_invokes_orchestrator_and_reports_artifact(self, mock_build, tmp_path):
        _project(tmp_path)
        out = tmp_path / "art" / "test.pgdump"
        mock_build.return_value = ArtifactResult(
            artifact_path=out,
            artifact_hash="abcdef0123456789",
            dump_format="custom",
        )

        result = runner.invoke(
            app,
            [
                "build",
                "--env",
                "local",
                "--project-dir",
                str(tmp_path),
                "--dump",
                str(out),
                "--format",
                "json",
            ],
        )

        assert result.exit_code == 0
        mock_build.assert_called_once()
        # The artifact fields surface in the JSON envelope.
        assert "abcdef0123456789" in result.stdout
        assert "test.pgdump" in result.stdout

    @patch("confiture.cli.commands.schema.build_schema_artifact")
    def test_dump_format_directory_passed_through(self, mock_build, tmp_path):
        _project(tmp_path)
        out = tmp_path / "art" / "test.pgdir"
        mock_build.return_value = ArtifactResult(
            artifact_path=out, artifact_hash="h" * 16, dump_format="directory"
        )

        result = runner.invoke(
            app,
            [
                "build",
                "--env",
                "local",
                "--project-dir",
                str(tmp_path),
                "--dump",
                str(out),
                "--dump-format",
                "directory",
            ],
        )

        assert result.exit_code == 0
        _, kwargs = mock_build.call_args
        assert kwargs["dump_format"] == "directory"

    @patch("confiture.cli.commands.schema.build_schema_artifact")
    def test_invalid_dump_format_exits_5(self, mock_build, tmp_path):
        _project(tmp_path)
        result = runner.invoke(
            app,
            [
                "build",
                "--env",
                "local",
                "--project-dir",
                str(tmp_path),
                "--dump",
                str(tmp_path / "x.pgdump"),
                "--dump-format",
                "bogus",
            ],
        )
        assert result.exit_code == 5
        mock_build.assert_not_called()

    @patch("confiture.cli.commands.schema.build_schema_artifact")
    def test_no_dump_leaves_behaviour_unchanged(self, mock_build, tmp_path):
        _project(tmp_path)
        result = runner.invoke(
            app,
            ["build", "--env", "local", "--project-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        mock_build.assert_not_called()
