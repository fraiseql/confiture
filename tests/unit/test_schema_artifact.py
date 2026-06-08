"""Unit tests for the cacheable schema-artifact dumper (P1).

Subprocess and TempDatabase are mocked; no real database or pg_dump is needed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from confiture.core.schema_artifact import (
    ArtifactResult,
    SchemaArtifactDumper,
    build_schema_artifact,
    default_artifact_path,
)
from confiture.exceptions import SchemaError

# ---------------------------------------------------------------------------
# Cycle 1: dumper core — argv construction + error paths
# ---------------------------------------------------------------------------


class TestBuildArgv:
    def test_custom_format_argv(self) -> None:
        argv = SchemaArtifactDumper().build_argv(
            "postgresql://localhost/tmp", Path("/out/a.pgdump"), "custom"
        )
        assert argv == [
            "pg_dump",
            "-Fc",
            "-d",
            "postgresql://localhost/tmp",
            "-f",
            "/out/a.pgdump",
        ]

    def test_directory_format_argv_has_parallel_jobs(self) -> None:
        argv = SchemaArtifactDumper(jobs=8).build_argv(
            "postgresql://localhost/tmp", Path("/out/a.pgdir"), "directory"
        )
        assert argv[:4] == ["pg_dump", "-Fd", "-j", "8"]
        assert argv[-4:] == ["-d", "postgresql://localhost/tmp", "-f", "/out/a.pgdir"]

    def test_directory_format_single_job_omits_j(self) -> None:
        argv = SchemaArtifactDumper(jobs=1).build_argv(
            "postgresql://localhost/tmp", Path("/out/a.pgdir"), "directory"
        )
        assert "-j" not in argv

    def test_unsupported_format_raises(self) -> None:
        with pytest.raises(SchemaError, match="dump format"):
            SchemaArtifactDumper().build_argv("postgresql://x/y", Path("/o"), "plain")


class TestDump:
    @patch("confiture.core.schema_artifact.subprocess.run")
    def test_dump_invokes_pg_dump(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess([], 0, "", "")
        SchemaArtifactDumper().dump("postgresql://localhost/tmp", Path("/out/a.pgdump"), "custom")
        argv = mock_run.call_args.args[0]
        assert argv[0] == "pg_dump"
        assert "-Fc" in argv

    @patch("confiture.core.schema_artifact.subprocess.run")
    def test_dump_raises_on_nonzero_returncode(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            [], 1, "", "pg_dump: error: connection failed\n"
        )
        with pytest.raises(SchemaError, match="connection failed"):
            SchemaArtifactDumper().dump("postgresql://x/y", Path("/o"), "custom")

    @patch(
        "confiture.core.schema_artifact.subprocess.run",
        side_effect=FileNotFoundError("pg_dump"),
    )
    def test_dump_raises_when_pg_dump_missing(self, _mock_run: MagicMock) -> None:
        with pytest.raises(SchemaError, match="pg_dump not found"):
            SchemaArtifactDumper().dump("postgresql://x/y", Path("/o"), "custom")


# ---------------------------------------------------------------------------
# Cycle 2: content-addressing + idempotent skip
# ---------------------------------------------------------------------------


class TestDefaultArtifactPath:
    def test_name_embeds_short_hash(self) -> None:
        path = default_artifact_path(Path("/art"), "test", "abcdef0123456789", profile=None)
        assert path.name == "schema_test.full.abcdef012345.pgdump"

    def test_name_embeds_profile(self) -> None:
        path = default_artifact_path(Path("/art"), "test", "abcdef0123456789", profile="slim")
        assert path.name == "schema_test.slim.abcdef012345.pgdump"

    def test_directory_format_uses_pgdir_extension(self) -> None:
        path = default_artifact_path(
            Path("/art"), "test", "abcdef0123456789", dump_format="directory"
        )
        assert path.suffix == ".pgdir"

    def test_distinct_profiles_do_not_collide(self) -> None:
        full = default_artifact_path(Path("/a"), "test", "deadbeefcafe", profile="full")
        slim = default_artifact_path(Path("/a"), "test", "deadbeefcafe", profile="slim")
        assert full != slim


class TestBuildArtifactSkip:
    def test_skips_when_artifact_already_exists(self, tmp_path: Path) -> None:
        existing = tmp_path / "schema_test.full.abcdef012345.pgdump"
        existing.write_bytes(b"PGDMP-stub")
        dumper = MagicMock(spec=SchemaArtifactDumper)

        result = build_schema_artifact(
            server_url="postgresql://localhost/postgres",
            schema_sql="CREATE TABLE t (id int);",
            output_path=existing,
            schema_hash="abcdef0123456789",
            dumper=dumper,
        )

        assert isinstance(result, ArtifactResult)
        assert result.skipped is True
        assert result.artifact_hash == "abcdef0123456789"
        dumper.dump.assert_not_called()

    @patch("confiture.core.schema_artifact.TempDatabase")
    def test_builds_and_dumps_when_absent(self, mock_tempdb: MagicMock, tmp_path: Path) -> None:
        # TempDatabase context yields a temp URL; apply_schema is a no-op mock.
        instance = mock_tempdb.return_value
        instance.__enter__.return_value = "postgresql://localhost/confiture_tmp_x"
        instance.__exit__.return_value = False
        dumper = MagicMock(spec=SchemaArtifactDumper)
        out = tmp_path / "schema_test.full.abcdef012345.pgdump"

        result = build_schema_artifact(
            server_url="postgresql://localhost/postgres",
            schema_sql="CREATE TABLE t (id int);",
            output_path=out,
            schema_hash="abcdef0123456789",
            dumper=dumper,
        )

        assert result.skipped is False
        instance.apply_schema.assert_called_once()
        dumper.dump.assert_called_once()
