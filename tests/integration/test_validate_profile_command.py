"""``confiture validate-profile``, run by its command line.

The profile it validates is the one ``confiture sync`` anonymizes production
data with. A profile that passes here and then fails, or anonymizes the wrong
thing, during a sync leaks data. So a valid profile must pass and report what
it holds. Each way a profile can be wrong must be refused with the exit code
the error registry gives its code: ``ANON_1400`` for a profile that is invalid,
``CONFIG_004`` for one that is not there. The command reads a file and opens no
connection.

The ``xfail`` test records a defect found while writing this file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.error_codes import exit_code_of

pytestmark = pytest.mark.integration

runner = CliRunner()

_VALID = """\
name: production
version: "1.0"
global_seed: 12345
strategies:
  email_mask:
    type: email
  phone_mask:
    type: phone
    seed_env_var: PHONE_SEED
tables:
  users:
    rules:
      - column: email
        strategy: email_mask
      - column: phone
        strategy: phone_mask
        seed: 7
"""

#: Each way a profile is refused, and the words that say which way it was.
_INVALID = {
    "unknown strategy type": (
        _VALID.replace("type: email", "type: rot13"),
        "Strategy type 'rot13' not allowed",
    ),
    "rule names an undefined strategy": (
        _VALID.replace("strategy: email_mask", "strategy: emial_mask"),
        "Did you mean 'email_mask'?",
    ),
    "required field missing": (_VALID.replace('version: "1.0"\n', ""), "version"),
    "malformed yaml": ("name: [unclosed\n", "Invalid YAML"),
    "empty file": ("", "is empty"),
    "not a mapping": ("- name\n- version\n", "Invalid profile"),
}


def _profile(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "profile.yaml"
    path.write_text(text)
    return path


def test_a_valid_profile_passes_and_reports_what_it_holds(tmp_path: Path) -> None:
    path = _profile(tmp_path, _VALID)

    result = runner.invoke(app, ["validate-profile", str(path), "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert (payload["ok"], payload["valid"], payload["command"]) == (
        True,
        True,
        "validate-profile",
    )
    assert (payload["name"], payload["version"], payload["has_global_seed"]) == (
        "production",
        "1.0",
        True,
    )
    assert payload["strategies"] == {
        "email_mask": {"type": "email", "seed_env_var": None},
        "phone_mask": {"type": "phone", "seed_env_var": "PHONE_SEED"},
    }
    assert payload["tables"] == {
        "users": [
            {"column": "email", "strategy": "email_mask", "has_seed": False},
            {"column": "phone", "strategy": "phone_mask", "has_seed": True},
        ]
    }


def test_a_valid_profile_passes_in_text_mode(tmp_path: Path) -> None:
    result = runner.invoke(app, ["validate-profile", str(_profile(tmp_path, _VALID))])

    assert result.exit_code == 0, result.output
    assert "Profile validation passed" in result.stdout
    assert "users: 2 rules" in result.stdout


@pytest.mark.parametrize(("text", "says"), list(_INVALID.values()), ids=list(_INVALID))
def test_an_invalid_profile_is_refused(tmp_path: Path, text: str, says: str) -> None:
    path = _profile(tmp_path, text)

    result = runner.invoke(app, ["validate-profile", str(path), "--format", "json"])

    assert result.exit_code == exit_code_of("ANON_1400") == 5, result.output
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    assert envelope["error"]["code"] == "ANON_1400"
    assert says in envelope["error"]["message"]


def test_an_invalid_profile_is_refused_in_text_mode(tmp_path: Path) -> None:
    path = _profile(tmp_path, _VALID.replace("type: email", "type: rot13"))

    result = runner.invoke(app, ["validate-profile", str(path)])

    assert result.exit_code == exit_code_of("ANON_1400"), result.output
    assert "ANON_1400" in result.output
    assert "Valid profile" not in result.output


def test_a_missing_profile_is_a_configuration_error(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["validate-profile", str(tmp_path / "absent.yaml"), "--format", "json"]
    )

    assert result.exit_code == exit_code_of("CONFIG_004") == 5, result.output
    assert json.loads(result.stdout)["error"]["code"] == "CONFIG_004"


@pytest.mark.xfail(
    strict=True,
    reason="#360: text mode prints '[env: X]' and '[seed: N]' through Rich, which takes "
    "them for markup and drops them",
)
def test_text_mode_names_the_seeds_it_found(tmp_path: Path) -> None:
    result = runner.invoke(app, ["validate-profile", str(_profile(tmp_path, _VALID))])

    assert result.exit_code == 0, result.output
    assert "PHONE_SEED" in result.stdout
    assert "seed: 7" in result.stdout
