"""Unit tests for seed-profile CLI surfaces (P4, Cycle 3).

Covers `seed apply --profile`, `build --seed-profile`, and
`test-db provision-template --seed-profile`: profile resolution, the
unknown-profile exit-5 gate, and that the profile is threaded to the applier.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.config.environment import SeedProfile
from confiture.core.seed_applier import ApplyResult
from confiture.core.test_db import TemplateState, TemplateStatus

runner = CliRunner()

_URL = "postgresql://localhost/confiture_test"


def _project(tmp_path: Path, *, profiles: bool = True) -> None:
    schema_dir = tmp_path / "db" / "schema"
    schema_dir.mkdir(parents=True)
    (schema_dir / "01.sql").write_text("CREATE TABLE t (id int);")
    seeds_dir = tmp_path / "db" / "seeds"
    seeds_dir.mkdir(parents=True)
    (seeds_dir / "core_1.sql").write_text("SELECT 1;")
    (seeds_dir / "stats_1.sql").write_text("SELECT 1;")
    env_dir = tmp_path / "db" / "environments"
    env_dir.mkdir(parents=True)
    # NB: do NOT set execution_mode: sequential here — it would make `build`
    # apply seeds to a real database (this is a unit test; CI's role needs a
    # password). The profile filtering/naming under test is DB-free.
    seed_block = (
        "seed:\n  profiles:\n    slim:\n      exclude:\n        - 'stats_*.sql'\n"
        if profiles
        else ""
    )
    (env_dir / "local.yaml").write_text(
        f'name: local\ndatabase_url: "{_URL}"\ninclude_dirs:\n  - {schema_dir}\n{seed_block}'
    )


class TestSeedApplyProfile:
    @patch("confiture.cli.seed.SeedApplier")
    @patch("confiture.core.connection.create_connection")
    def test_profile_threaded_to_applier(self, _mock_conn, mock_applier_cls, tmp_path, monkeypatch):
        _project(tmp_path)
        monkeypatch.chdir(tmp_path)
        mock_applier_cls.return_value.apply_sequential.return_value = ApplyResult(total=0)

        result = runner.invoke(
            app,
            [
                "seed",
                "apply",
                "--sequential",
                "--env",
                "local",
                "--seeds-dir",
                str(tmp_path / "db" / "seeds"),
                "--database-url",
                _URL,
                "--profile",
                "slim",
                "--format",
                "json",
            ],
        )

        assert result.exit_code == 0, result.output
        _, kwargs = mock_applier_cls.return_value.apply_sequential.call_args
        assert isinstance(kwargs["profile"], SeedProfile)
        assert kwargs["profile"].exclude == ["stats_*.sql"]

    def test_unknown_profile_exits_5(self, tmp_path, monkeypatch):
        _project(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app,
            [
                "seed",
                "apply",
                "--sequential",
                "--env",
                "local",
                "--seeds-dir",
                str(tmp_path / "db" / "seeds"),
                "--database-url",
                _URL,
                "--profile",
                "nope",
            ],
        )
        assert result.exit_code == 5
        assert "Unknown seed profile" in result.output


class TestBuildSeedProfile:
    def test_unknown_profile_exits_5(self, tmp_path):
        _project(tmp_path)
        result = runner.invoke(
            app,
            ["build", "--env", "local", "--project-dir", str(tmp_path), "--seed-profile", "nope"],
        )
        assert result.exit_code == 5
        assert "Unknown seed profile" in result.output

    @patch("confiture.cli.commands.schema.build_schema_artifact")
    def test_seed_profile_in_artifact_name(self, mock_build, tmp_path):
        from confiture.core.schema_artifact import ArtifactResult

        _project(tmp_path)
        art_dir = tmp_path / "art"
        art_dir.mkdir()
        captured = {}

        def _capture(**kwargs):
            captured.update(kwargs)
            return ArtifactResult(kwargs["output_path"], "hash", "custom")

        mock_build.side_effect = _capture
        result = runner.invoke(
            app,
            [
                "build",
                "--env",
                "local",
                "--project-dir",
                str(tmp_path),
                "--dump",
                str(art_dir),
                "--seed-profile",
                "slim",
            ],
        )
        assert result.exit_code == 0, result.output
        # The content-addressed name carries the profile segment.
        assert ".slim." in Path(captured["output_path"]).name


class TestProvisionTemplateSeedProfile:
    @patch("confiture.cli.test_db.TestDbProvisioner")
    def test_unknown_profile_exits_5(self, _mock_cls, tmp_path):
        _project(tmp_path)
        result = runner.invoke(
            app,
            [
                "test-db",
                "provision-template",
                "--template",
                "t",
                "--project-dir",
                str(tmp_path),
                "--seed-profile",
                "nope",
            ],
        )
        assert result.exit_code == 5

    @patch("confiture.cli.test_db.TestDbProvisioner")
    def test_profile_filters_seed_files(self, mock_cls, tmp_path):
        _project(tmp_path)
        mock_cls.return_value.provision_template.return_value = TemplateStatus(
            "t", TemplateState.CURRENT, "h", "h"
        )
        result = runner.invoke(
            app,
            [
                "test-db",
                "provision-template",
                "--template",
                "t",
                "--project-dir",
                str(tmp_path),
                "--seed-profile",
                "slim",
            ],
        )
        assert result.exit_code == 0, result.output
        _, kwargs = mock_cls.return_value.provision_template.call_args
        names = [Path(p).name for p in (kwargs.get("seed_files") or [])]
        assert "stats_1.sql" not in names  # excluded by slim
