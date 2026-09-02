"""Schema conformance for `--idempotent` git scoping (#181).

Two shapes must stay valid against
``migrate-validate-idempotent.schema.json``:

- the scoped report, whose ``meta`` gained a ``scope`` object (safe: ``meta``
  requires only ``backend`` and does not set ``additionalProperties: false``);
- the zero-scope report, which must reuse ``oneOf`` branch 2 verbatim — both
  top-level branches DO set ``additionalProperties: false``, and branch 2
  forbids the scan counters while requiring ``message``.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()

SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "docs" / "reference" / "json-schemas"

IDEMPOTENT = "CREATE TABLE IF NOT EXISTS {name} (id int);\n"
NON_IDEMPOTENT = "CREATE TABLE {name} (id int);\n"


def _load(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text())


def _validator() -> Draft202012Validator:
    common = _load("_common.schema.json")
    registry = Registry().with_resource(
        uri="_common.schema.json",
        resource=Resource.from_contents(common, default_specification=DRAFT202012),
    )
    return Draft202012Validator(_load("migrate-validate-idempotent.schema.json"), registry=registry)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "db" / "migrations").mkdir(parents=True)
    _git(root, "init")
    _git(root, "config", "user.email", "t@t.com")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "db" / "migrations" / "20260101000000_alpha.up.sql").write_text(
        IDEMPOTENT.format(name="alpha")
    )
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "base")
    return root


def _run(repo: Path, *extra: str) -> tuple[int, dict]:
    prev = Path.cwd()
    os.chdir(repo)
    try:
        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--migrations-dir",
                str(repo / "db" / "migrations"),
                "--format",
                "json",
                *extra,
            ],
        )
    finally:
        os.chdir(prev)
    return result.exit_code, json.loads(result.stdout)


def test_scoped_report_validates(repo: Path) -> None:
    base = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    _git(repo, "checkout", "-b", "feature")
    (repo / "db" / "migrations" / "20260102000000_beta.up.sql").write_text(
        NON_IDEMPOTENT.format(name="beta")
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "beta")

    exit_code, payload = _run(repo, "--base-ref", base)

    _validator().validate(payload)
    assert exit_code == 1
    assert payload["meta"]["scope"]["mode"] == "base-ref"
    assert payload["meta"]["scope"]["files_selected"] == 1
    assert payload["files_scanned"] == 1


def test_zero_scope_report_validates(repo: Path) -> None:
    base = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    _git(repo, "checkout", "-b", "feature")
    (repo / "README.md").write_text("docs\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "docs")

    exit_code, payload = _run(repo, "--base-ref", base)

    _validator().validate(payload)
    assert exit_code == 0
    assert payload["status"] == "ok"
    # Branch 2 shape: message present, scan counters absent.
    assert "message" in payload
    assert "files_scanned" not in payload
    assert payload["violations"] == []


def test_staged_scope_report_validates(repo: Path) -> None:
    (repo / "db" / "migrations" / "20260102000000_beta.up.sql").write_text(
        NON_IDEMPOTENT.format(name="beta")
    )
    _git(repo, "add", "-A")

    exit_code, payload = _run(repo, "--staged")

    _validator().validate(payload)
    assert exit_code == 1
    assert payload["meta"]["scope"]["mode"] == "staged"
    assert payload["files_scanned"] == 1


def test_unscoped_report_still_validates_and_has_no_scope(repo: Path) -> None:
    exit_code, payload = _run(repo)

    _validator().validate(payload)
    assert exit_code == 0
    assert "scope" not in payload["meta"]


def test_zero_scope_report_is_vacuously_complete(repo: Path) -> None:
    """D4 (#213): an empty scope is a pass, and says it read everything (of nothing)."""
    base = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    _git(repo, "checkout", "-b", "feature")
    (repo / "README.md").write_text("docs\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "docs")

    exit_code, payload = _run(repo, "--base-ref", base)

    _validator().validate(payload)
    assert exit_code == 0
    assert payload["analysis_complete"] is True
    assert payload["unanalyzed_count"] == 0


_DYNAMIC_PY = """\
from confiture.models.migration import Migration


class Dyn(Migration):
    version = "20260102000000"
    name = "dyn"

    def up(self) -> None:
        for table in ("a", "b"):
            self.execute(f"CREATE TABLE IF NOT EXISTS {table} (id int)")

    def down(self) -> None:
        pass
"""


def test_scoped_flag_judges_only_the_selected_files(repo: Path) -> None:
    """One unanalyzable file on the branch + the flag → 1; the base's files are not judged."""
    base = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    _git(repo, "checkout", "-b", "feature")
    (repo / "db" / "migrations" / "20260102000000_dyn.py").write_text(_DYNAMIC_PY)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "dyn")

    exit_code, payload = _run(repo, "--base-ref", base, "--fail-on-unanalyzable")

    _validator().validate(payload)
    assert exit_code == 1
    assert payload["status"] == "unverified"
    assert payload["files_scanned"] == 1


def test_empty_scope_with_the_flag_stays_a_pass(repo: Path) -> None:
    """D4: the flag fails on files it could not read, not on having none to read."""
    base = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    _git(repo, "checkout", "-b", "feature")
    (repo / "README.md").write_text("docs\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "docs")

    exit_code, payload = _run(repo, "--base-ref", base, "--fail-on-unanalyzable")

    _validator().validate(payload)
    assert exit_code == 0
    assert payload["status"] == "ok"
