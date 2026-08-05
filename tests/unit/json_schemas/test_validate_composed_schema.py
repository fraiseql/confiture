"""Validate the composed ``migrate validate --format json`` envelope (#187).

Pins both halves of the contract: two-or-more checks emit the wrapper, and a
single check still emits its own payload — the wrapper must *not* appear then,
or every documented single-check schema breaks at once.
"""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

import pytest
from jsonschema import Draft202012Validator
from typer.testing import CliRunner

from confiture.cli.main import app

SCHEMA_FILE = "migrate-validate-composed.schema.json"

runner = CliRunner()


def _load(schemas_dir: Path, name: str) -> dict:
    return json.loads((schemas_dir / name).read_text())


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real project the static checks can run against, chdir-ed into."""
    migs = tmp_path / "db" / "migrations"
    migs.mkdir(parents=True)
    (tmp_path / "db" / "schema").mkdir(parents=True)
    (tmp_path / "db" / "environments").mkdir(parents=True)
    (tmp_path / "db" / "environments" / "local.yaml").write_text(
        "database_url: postgresql://localhost/test\ninclude_dirs:\n  - path: db/schema\n"
    )
    (migs / "20260527000000_init.up.sql").write_text(
        "CREATE TABLE IF NOT EXISTS public.orders (id INT PRIMARY KEY);\n"
        "GRANT SELECT ON public.orders TO app_reader;\n"
    )
    (tmp_path / "confiture.yaml").write_text(
        dedent(
            """\
            name: test
            database_url: postgresql://localhost/test
            include_dirs:
              - path: db/schema
            acls:
              - schema: public
                apply_to: ALL_TABLES
                grants:
                  - role: app_reader
                    privileges: [SELECT]
            """
        )
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_schema_is_valid_draft_2020_12(schemas_dir: Path) -> None:
    Draft202012Validator.check_schema(_load(schemas_dir, SCHEMA_FILE))


def test_two_checks_emit_the_composed_envelope(
    project: Path,  # noqa: ARG001
    schemas_dir: Path,
    schema_registry: object,
) -> None:
    result = runner.invoke(
        app,
        ["migrate", "validate", "--check-acls", "--check-imports", "--format", "json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    Draft202012Validator(_load(schemas_dir, SCHEMA_FILE), registry=schema_registry).validate(
        payload
    )
    assert set(payload["checks"]) == {"acl_coverage", "imports"}


def test_nested_payloads_still_match_their_own_schema(
    project: Path,  # noqa: ARG001
    schemas_dir: Path,
    schema_registry: object,
) -> None:
    """The wrapper nests each check's payload unchanged, not a reduced form."""
    result = runner.invoke(
        app,
        ["migrate", "validate", "--check-acls", "--check-imports", "--format", "json"],
    )
    nested = json.loads(result.stdout)["checks"]["acl_coverage"]
    Draft202012Validator(
        _load(schemas_dir, "migrate-validate-check-acl-coverage.schema.json"),
        registry=schema_registry,
    ).validate(nested)


def test_single_check_does_not_emit_the_wrapper(
    project: Path,  # noqa: ARG001
    schemas_dir: Path,
    schema_registry: object,
) -> None:
    result = runner.invoke(app, ["migrate", "validate", "--check-acls", "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)

    validator = Draft202012Validator(_load(schemas_dir, SCHEMA_FILE), registry=schema_registry)
    assert not validator.is_valid(payload), "single-check output must not be the composed wrapper"
    Draft202012Validator(
        _load(schemas_dir, "migrate-validate-check-acl-coverage.schema.json"),
        registry=schema_registry,
    ).validate(payload)
