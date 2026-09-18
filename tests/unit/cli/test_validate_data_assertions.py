"""`migrate validate --check-data-assertions` (#311).

A `RAISE EXCEPTION` guarded on a row count inside `up()` is exactly what a
schema-only `migrate preflight` cannot survive. Confiture recommends that
topology — twice, in `preflight`'s own help — so it owns telling the author
about the obligation that follows.

It is a heuristic, so it warns and never fails the gate. It also has to
*compose*: before #187 `migrate validate` was a chain of `if <flag>: … return`
blocks, so any two flags meant the second was silently skipped and the gate
still exited 0.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

INCIDENT = """ALTER TABLE catalog.tb_field ADD COLUMN bio text;

DO $$
DECLARE v_ok int;
BEGIN
  SELECT count(*) INTO v_ok FROM catalog.tb_field
   WHERE identifier IN ('meter_a4_color', 'volume_a4_color');
  IF v_ok <> 2 THEN
    RAISE EXCEPTION 'expected 2 fields, got %', v_ok;
  END IF;
END $$;
"""


@pytest.fixture
def migrations_dir(tmp_path: Path) -> Path:
    d = tmp_path / "migrations"
    d.mkdir()
    (d / "20260101000000_add_field.up.sql").write_text(INCIDENT)
    return d


@pytest.fixture
def clean_dir(tmp_path: Path) -> Path:
    d = tmp_path / "clean"
    d.mkdir()
    (d / "20260101000000_add_field.up.sql").write_text(
        "ALTER TABLE catalog.tb_field ADD COLUMN bio text;\n"
    )
    return d


@pytest.fixture
def cfg(tmp_path: Path) -> Path:
    p = tmp_path / "env.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "name": "test",
                "database_url": "postgresql://localhost/nonexistent_for_test",
                "include_dirs": ["db/schema"],
            }
        )
    )
    return p


def _validate(cfg: Path, migrations_dir: Path, *extra: str):
    return runner.invoke(
        app,
        [
            "migrate",
            "validate",
            "--check-data-assertions",
            "-c",
            str(cfg),
            "--migrations-dir",
            str(migrations_dir),
            *extra,
        ],
    )


class TestItWarns:
    def test_the_incident_is_reported(self, cfg: Path, migrations_dir: Path) -> None:
        result = _validate(cfg, migrations_dir, "--format", "json")

        payload = json.loads(result.stdout)
        assert len(payload["warnings"]) == 1
        assert payload["warnings"][0]["relation"] == "catalog.tb_field"

    def test_it_points_at_the_raise(self, cfg: Path, migrations_dir: Path) -> None:
        result = _validate(cfg, migrations_dir, "--format", "json")

        line = json.loads(result.stdout)["warnings"][0]["line"]
        assert INCIDENT.splitlines()[line - 1].strip().startswith("RAISE EXCEPTION")

    def test_the_remedy_names_the_sidecar(self, cfg: Path, migrations_dir: Path) -> None:
        """A warning that does not say what to do instead is noise."""
        result = _validate(cfg, migrations_dir, "--format", "json")

        assert ".verify.sql" in json.loads(result.stdout)["warnings"][0]["remedy"]

    def test_severity_is_warning(self, cfg: Path, migrations_dir: Path) -> None:
        result = _validate(cfg, migrations_dir, "--format", "json")

        assert json.loads(result.stdout)["severity"] == "warning"


class TestItDoesNotFailTheGate:
    def test_a_finding_still_exits_0(self, cfg: Path, migrations_dir: Path) -> None:
        """Heuristic. The topology is recommended, not enforced — so is this."""
        result = _validate(cfg, migrations_dir)

        assert result.exit_code == 0, result.output

    def test_a_clean_directory_exits_0_and_says_so(self, cfg: Path, clean_dir: Path) -> None:
        result = _validate(cfg, clean_dir)

        assert result.exit_code == 0, result.output
        assert "No data assertions" in result.output

    def test_it_never_connects(self, cfg: Path, migrations_dir: Path) -> None:
        """Static means static: the descriptor must not declare `needs_db`.

        Asserted on the registry rather than on output text, because that is
        the property — a check that declares it is handed the shared live
        connection, and every test here points at a database that does not
        exist. `exit_code != 3` below is the behavioural half of the same
        claim (3 is `db_unreachable`).
        """
        from confiture.cli.commands.validate_checks import ValidateOptions, build_registry

        opts = ValidateOptions(
            format_output="text",
            json_mode=False,
            migrations_dir=migrations_dir,
            config=cfg,
            git_env="local",
            schema_file=None,
            scratch_url=None,
            schemas=None,
            ssh_via=None,
            check_data_assertions=True,
        )
        (check,) = [c for c in build_registry(opts) if c.name == "data_assertions"]

        assert check.needs_db is False
        assert check.needs_git is False
        assert _validate(cfg, migrations_dir).exit_code == 0


class TestItComposes:
    def test_it_runs_alongside_another_static_check(self, cfg: Path, migrations_dir: Path) -> None:
        """Both payloads must appear — the #187 regression this guards."""
        result = _validate(cfg, migrations_dir, "--check-imports", "--format", "json")

        payload = json.loads(result.stdout)
        assert set(payload["checks"]) == {"data_assertions", "imports"}

    def test_a_warning_does_not_mask_a_real_failure(self, cfg: Path, migrations_dir: Path) -> None:
        """Composed with a check that fails, the exit code is the failure's."""
        (migrations_dir / "20260102000000_bad.py").write_text("import os\nthis is not python\n")

        result = _validate(cfg, migrations_dir, "--check-imports")

        assert result.exit_code == 1, result.output
