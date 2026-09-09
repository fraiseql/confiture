"""What a build has to say reaches the envelope, not only the console (#268).

`build --format json` published a `warnings` array that no code path ever wrote
to, while the same run printed its diagnostics as prose. A consumer doing the
right thing — reading the JSON, not the console — could not learn that seed
files had failed under `--continue-on-error`, or that a file the duplicate scan
could not parse went unchecked.

The guard at the bottom is the point of the issue: a published array that
nothing can fill is a defect, so every array this envelope publishes has a
scenario here that fills it.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.core.seed.applier import ApplyResult

runner = CliRunner()

_URL = "postgresql://localhost/confiture_test"


_ONE_TABLE = {"01_tables.sql": "CREATE TABLE tb_widget (id int);\n"}
_ONE_TABLE_AND_A_BROKEN_FILE = {**_ONE_TABLE, "02_broken.sql": "CREATE TABEL broken (;\n"}


def _project(
    tmp_path: Path, *, seeds: dict[str, str] | None = None, schema: dict[str, str] | None = None
) -> Path:
    """A minimal project; ``schema`` and ``seeds`` name the files under each directory."""
    schema_dir = tmp_path / "db" / "schema"
    schema_dir.mkdir(parents=True)
    for name, body in (schema or _ONE_TABLE).items():
        (schema_dir / name).write_text(body)

    seed_block = ""
    if seeds is not None:
        seeds_dir = tmp_path / "db" / "seeds"
        seeds_dir.mkdir(parents=True)
        for name, body in seeds.items():
            (seeds_dir / name).write_text(body)
        seed_block = f"  - {seeds_dir}\n"

    env_dir = tmp_path / "db" / "environments"
    env_dir.mkdir(parents=True)
    (env_dir / "local.yaml").write_text(
        f'name: local\ndatabase_url: "{_URL}"\n'
        f"include_dirs:\n  - {schema_dir}\n{seed_block}"
        "build:\n  validate_comments:\n    enabled: false\n"
    )
    return tmp_path


def _build(project: Path, *extra: str):
    return runner.invoke(
        app,
        [
            "build",
            "--env",
            "local",
            "--project-dir",
            str(project),
            "--output",
            str(project / "schema.sql"),
            *extra,
        ],
    )


def _payload(project: Path, *extra: str) -> dict:
    result = _build(project, "--format", "json", *extra)
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


class TestSeedWarnings:
    """`--sequential` applies seed files; what it has to say about them is published."""

    def test_failed_seed_files_are_in_the_envelope(self, tmp_path: Path) -> None:
        """`success: true`, three files applied — and two that did not, said out loud."""
        project = _project(tmp_path, seeds={"01_widgets.sql": "SELECT 1;\n"})

        with patch("confiture.cli.commands.schema.apply_seed_files") as applier:
            applier.return_value = ApplyResult(total=5, succeeded=3, failed=2)
            payload = _payload(project, "--sequential", "--continue-on-error")

        assert payload["success"] is True
        assert payload["seed_files_applied"] == 3
        assert payload["warnings"] == [
            {
                "code": "SEED_002",
                "severity": "warning",
                "message": "2 seed file(s) failed",
                "file": None,
            }
        ]

    def test_an_empty_seed_set_is_in_the_envelope(self, tmp_path: Path) -> None:
        """`--sequential` over a project with no seed files says so where it counts."""
        project = _project(tmp_path)

        payload = _payload(project, "--sequential")

        assert [w["code"] for w in payload["warnings"]] == ["SEED_003"]
        assert payload["warnings"][0]["severity"] == "info"
        assert "local" in payload["warnings"][0]["message"]

    def test_a_clean_seed_run_says_nothing(self, tmp_path: Path) -> None:
        """The channel carries diagnostics, not chatter."""
        project = _project(tmp_path, seeds={"01_widgets.sql": "SELECT 1;\n"})

        with patch("confiture.cli.commands.schema.apply_seed_files") as applier:
            applier.return_value = ApplyResult(total=3, succeeded=3, failed=0)
            payload = _payload(project, "--sequential")

        assert payload["warnings"] == []

    def test_the_console_says_it_once(self, tmp_path: Path) -> None:
        """One renderer: a warning is not printed by its producer *and* by the result."""
        project = _project(tmp_path, seeds={"01_widgets.sql": "SELECT 1;\n"})

        with patch("confiture.cli.commands.schema.apply_seed_files") as applier:
            applier.return_value = ApplyResult(total=5, succeeded=3, failed=2)
            result = _build(project, "--sequential", "--continue-on-error")

        assert result.exit_code == 0
        assert result.stdout.count("2 seed file(s) failed") == 1
        assert "SEED_002" in result.stdout


class TestDuplicateScanWarnings:
    """The scan skips a file it cannot parse; the envelope says which one."""

    def test_a_file_the_scan_could_not_parse_is_in_the_envelope(self, tmp_path: Path) -> None:
        """An object defined twice in *that* file was not looked for; a consumer learns so."""
        project = _project(tmp_path, schema=_ONE_TABLE_AND_A_BROKEN_FILE)

        payload = _payload(project, "--warn-duplicates")

        assert [w["code"] for w in payload["warnings"]] == ["SCHEMA_206"]
        warning = payload["warnings"][0]
        assert warning["file"] == "db/schema/02_broken.sql"
        assert warning["file"] in warning["message"]
        assert warning["severity"] == "warning"

    def test_a_plain_build_does_not_scan_and_says_nothing(self, tmp_path: Path) -> None:
        """The scan is opt-in; so is what it has to say."""
        project = _project(tmp_path, schema=_ONE_TABLE_AND_A_BROKEN_FILE)

        assert _payload(project)["warnings"] == []

    def test_a_failed_build_still_shows_them_on_the_console(self, tmp_path: Path) -> None:
        """A build that stopped is exactly when its warnings are worth reading."""
        project = _project(
            tmp_path,
            schema={
                "01_tables.sql": "CREATE TABLE tb_widget (id int);\n",
                "02_again.sql": "CREATE TABLE tb_widget (id int);\n",
                "03_broken.sql": "CREATE TABEL broken (;\n",
            },
        )

        result = _build(project, "--fail-on-duplicates")

        assert result.exit_code == 1
        assert "SCHEMA_206" in result.stdout
        assert result.stdout.count("could not parse it") == 1

    def test_the_failing_gate_carries_them_too(self, tmp_path: Path) -> None:
        """`--fail-on-duplicates` builds nothing — and still publishes what it saw."""
        project = _project(
            tmp_path,
            schema={
                "01_tables.sql": "CREATE TABLE tb_widget (id int);\n",
                "02_again.sql": "CREATE TABLE tb_widget (id int);\n",
                "03_broken.sql": "CREATE TABEL broken (;\n",
            },
        )

        result = _build(project, "--warn-duplicates", "--fail-on-duplicates", "--format", "json")

        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["success"] is False
        assert [w["code"] for w in payload["warnings"]] == ["SCHEMA_206"]
        assert payload["duplicates"]


@pytest.mark.parametrize("array", ["warnings", "duplicates"])
def test_every_published_array_has_something_that_fills_it(array: str, tmp_path: Path) -> None:
    """No published field of this envelope is one nothing can ever write to.

    `warnings` shipped in 1.5.0 as an array that was serialised on every run and
    written to by nothing (#268). This test is the reason that cannot happen
    again quietly: a new array in `build.schema.json` either has a scenario here
    that fills it, or it fails.
    """
    fillers = {
        "warnings": lambda: _seed_failure_payload(tmp_path),
        "duplicates": lambda: _duplicate_payload(tmp_path),
    }
    published = set(json.loads(_read_build_schema())["properties"])
    assert array in published, f"{array} is no longer published; drop it from this guard"

    assert fillers[array]()[array], f"nothing in the build path ever writes {array}[]"


def _read_build_schema() -> str:
    from confiture.core.schema_exporter import load_schema

    return json.dumps(load_schema("build.schema.json"))


def _seed_failure_payload(tmp_path: Path) -> dict:
    project = _project(tmp_path / "seeds", seeds={"01_widgets.sql": "SELECT 1;\n"})
    with patch("confiture.cli.commands.schema.apply_seed_files") as applier:
        applier.return_value = ApplyResult(total=5, succeeded=3, failed=2)
        return _payload(project, "--sequential", "--continue-on-error")


def _duplicate_payload(tmp_path: Path) -> dict:
    project = _project(
        tmp_path / "duplicates",
        schema={
            "01_tables.sql": "CREATE TABLE tb_widget (id int);\n",
            "02_again.sql": "CREATE TABLE tb_widget (id int);\n",
        },
    )
    return _payload(project, "--warn-duplicates")
