"""``confiture migrate generate``: stdout is the JSON and nothing else, whatever the flags.

``--verbose`` narrates the directory scan and ``--generator`` hands the diff to an
external tool; in JSON mode neither may write text where a consumer parses.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests._helpers import strip_ansi
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


def _generate(*args: str) -> tuple[int, str, str]:
    result = runner.invoke(app, ["migrate", "generate", *args])
    return result.exit_code, result.stdout, result.stderr


def _project(
    tmp_path: Path, command: str = "test -f {from} && cp {to} {output}"
) -> tuple[Path, Path, Path]:
    """An environment file with one external generator, and two schema files."""
    config = tmp_path / "db" / "environments" / "local.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "name: local\n"
        "migration:\n"
        "  migration_generators:\n"
        "    copier:\n"
        f"      command: {json.dumps(command)}\n"
    )
    old, new = tmp_path / "old.sql", tmp_path / "new.sql"
    old.write_text("CREATE TABLE t (id int);\n")
    new.write_text("CREATE TABLE t (id int, name text);\n")
    return config, old, new


class TestVerbose:
    def test_the_scan_stays_off_stdout_in_json_mode(self, tmp_path: Path) -> None:
        migrations = tmp_path / "migrations"
        migrations.mkdir()
        (migrations / "20260101120000_first.py").write_text("")

        code, stdout, stderr = _generate(
            "second", "--migrations-dir", str(migrations), "--format", "json",
            "--verbose", "--no-snapshot",
        )  # fmt: skip

        assert (code, json.loads(stdout)["status"]) == (0, "success")
        assert "20260101120000_first.py" in strip_ansi(stderr)

    def test_the_highest_version_is_the_highest_file_s_whole_version(self, tmp_path: Path) -> None:
        migrations = tmp_path / "migrations"
        migrations.mkdir()
        (migrations / "20260101120000_first.py").write_text("")
        (migrations / "20260102120007_second.up.sql").write_text("SELECT 1;")

        code, stdout, _ = _generate(
            "third", "--migrations-dir", str(migrations), "--verbose", "--dry-run",
            "--no-snapshot",
        )  # fmt: skip

        assert code == 0
        assert "Highest version: 20260102120007\n" in strip_ansi(stdout)


class TestGenerator:
    def test_success_is_a_json_payload(self, tmp_path: Path) -> None:
        config, old, new = _project(tmp_path)
        migrations = tmp_path / "migrations"

        code, stdout, _ = _generate(
            "add_name", "--generator", "copier", "--from", str(old), "--to", str(new),
            "--config", str(config), "--migrations-dir", str(migrations), "--format", "json",
        )  # fmt: skip

        payload = json.loads(stdout)
        written = Path(payload["filepath"])
        assert (code, payload["status"], payload["generator"], payload["name"]) == (
            0,
            "success",
            "copier",
            "add_name",
        )
        assert written.name == f"{payload['version']}_add_name.up.sql"
        assert written.read_text() == new.read_text()

    def test_dry_run_is_a_json_payload(self, tmp_path: Path) -> None:
        config, old, new = _project(tmp_path)

        code, stdout, _ = _generate(
            "add_name", "--generator", "copier", "--from", str(old), "--to", str(new),
            "--config", str(config), "--migrations-dir", str(tmp_path / "m"),
            "--format", "json", "--dry-run",
        )  # fmt: skip

        payload = json.loads(stdout)
        assert (code, payload["status"]) == (0, "dry_run")
        assert payload["resolved_command"].startswith("test -f ")

    def test_an_unknown_generator_is_the_error_envelope(self, tmp_path: Path) -> None:
        config, old, new = _project(tmp_path)

        code, stdout, _ = _generate(
            "add_name", "--generator", "nope", "--from", str(old), "--to", str(new),
            "--config", str(config), "--migrations-dir", str(tmp_path / "m"),
            "--format", "json",
        )  # fmt: skip

        payload = json.loads(stdout)
        assert (code, payload["ok"], payload["error"]["code"]) == (5, False, "CONFIG_001")

    def test_a_missing_from_is_the_error_envelope(self, tmp_path: Path) -> None:
        config, _, new = _project(tmp_path)

        code, stdout, _ = _generate(
            "add_name", "--generator", "copier", "--to", str(new), "--config", str(config),
            "--migrations-dir", str(tmp_path / "m"), "--format", "json",
        )  # fmt: skip

        assert (code, json.loads(stdout)["error"]["code"]) == (5, "CONFIG_001")

    def test_a_failing_generator_is_the_gen_001_envelope(self, tmp_path: Path) -> None:
        config, old, new = _project(tmp_path, command="false {from} {to} {output}")

        code, stdout, _ = _generate(
            "add_name", "--generator", "copier", "--from", str(old), "--to", str(new),
            "--config", str(config), "--migrations-dir", str(tmp_path / "m"),
            "--format", "json",
        )  # fmt: skip

        payload = json.loads(stdout)
        assert (code, payload["ok"], payload["error"]["code"]) == (3, False, "GEN_001")
