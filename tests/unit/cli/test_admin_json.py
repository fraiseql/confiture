"""``validate-profile`` and ``install-helpers`` answer in JSON.

The profile report says what a profile *is* and never what its seeds are: a
seed is the key to an anonymization's pseudonyms, and a JSON payload is the
kind of output that ends up in a CI log.
"""

from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()
EXAMPLE = Path(__file__).resolve().parents[3] / "examples" / "anonymization_profile_example.yaml"


def test_validate_profile_reports_the_profile_in_json() -> None:
    result = runner.invoke(app, ["validate-profile", str(EXAMPLE), "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert (payload["valid"], payload["ok"], payload["command"]) == (True, True, "validate-profile")
    assert payload["name"] == "production"
    assert payload["strategies"]["email_hash"] == {
        "type": "hash",
        "seed_env_var": "ANONYMIZATION_SEED",
    }
    assert payload["has_global_seed"] is True


def test_validate_profile_json_carries_no_seed_value() -> None:
    result = runner.invoke(app, ["validate-profile", str(EXAMPLE), "--format", "json"])

    assert "12345" not in result.stdout


def test_validate_profile_missing_file_is_the_error_envelope(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["validate-profile", str(tmp_path / "nope.yaml"), "--format", "json"]
    )

    assert result.exit_code == 5
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "CONFIG_004"


def test_install_helpers_dry_run_reports_the_sql_in_json(tmp_path: Path) -> None:
    config = tmp_path / "local.yaml"
    config.write_text("database_url: postgresql://localhost/unused\n")
    with patch(
        "confiture.cli.commands.admin.open_connection", return_value=nullcontext(MagicMock())
    ):
        result = runner.invoke(
            app, ["install-helpers", "-c", str(config), "--dry-run", "--format", "json"]
        )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert (payload["status"], payload["schema"]) == ("dry_run", "confiture")
    assert "save_and_drop_dependent_views" in payload["sql"]
    assert payload["command"] == "install-helpers"
