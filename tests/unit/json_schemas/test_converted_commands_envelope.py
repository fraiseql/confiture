"""Conformance: Phase-02-converted commands emit the #145 error envelope.

Phase 02 routed every CLI failure path through the single ``fail()`` boundary,
so a command run with ``--format json`` must emit the published
``error-envelope.schema.json`` shape on stdout — and *only* that (no Rich error
text interleaved). This test pins that contract for a representative set of the
newly-converted commands: a regression in any of them (reverting to a hand-rolled
error dict, or printing Rich to stdout alongside the envelope) fails here.

Mirrors ``test_error_envelope_schema.py`` (which covers ``migrate up``); these
cases cover the build/seed/diff/drift/apply-as surface DOCS-M1 calls out.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from typer.testing import CliRunner

from confiture.cli.main import app

SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "docs" / "reference" / "json-schemas"

runner = CliRunner()


def _load(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text())


def _envelope_validator() -> Draft202012Validator:
    issue = _load("issue-object.schema.json")
    registry = Registry().with_resource(
        uri="issue-object.schema.json",
        resource=Resource.from_contents(issue, default_specification=DRAFT202012),
    )
    return Draft202012Validator(_load("error-envelope.schema.json"), registry=registry)


# (cli args, expected error.code) — each triggers an early, DB-independent
# failure so stdout is the envelope and nothing else.
_CASES = [
    pytest.param(
        ["diff", "--from", "/no/such-a.sql", "--to", "/no/such-b.sql", "--format", "json"],
        "SCHEMA_201",
        id="diff-missing-file",
    ),
    pytest.param(
        ["drift", "--config", "/no/such.yaml", "--schema", "/no/x.sql", "--format", "json"],
        "CONFIG_004",
        id="drift-missing-config",
    ),
    pytest.param(
        ["seed", "validate", "--seeds-dir", "/no/such-dir", "--format", "json"],
        "CONFIG_004",
        id="seed-validate-missing-dir",
    ),
    pytest.param(
        ["seed", "apply", "--sequential", "--seeds-dir", "/no/such-dir", "--format", "json"],
        "CONFIG_004",
        id="seed-apply-missing-dir",
    ),
    pytest.param(
        [
            "migrate",
            "apply-as",
            "postgres",
            "20260101000000",
            "--config",
            "/no/such.yaml",
            "--format",
            "json",
        ],
        "CONFIG_004",
        id="apply-as-missing-config",
    ),
]


@pytest.mark.parametrize(("args", "expected_code"), _CASES)
def test_converted_command_emits_valid_envelope(args: list[str], expected_code: str) -> None:
    result = runner.invoke(app, args)

    # Non-zero exit, and stdout is the envelope and nothing but the envelope
    # (proves no Rich error text leaked onto stdout alongside it).
    assert result.exit_code != 0, result.output
    payload = json.loads(result.stdout)

    _envelope_validator().validate(payload)
    assert payload["ok"] is False
    assert payload["error"]["code"] == expected_code
    # The envelope's actionable/severity fields are part of the #145 contract.
    assert payload["error"]["severity"] in {"error", "warning", "info"}
    assert "message" in payload["error"]


def test_envelope_exit_code_matches_registry() -> None:
    """The process exit code equals the registry exit code for the envelope's code."""
    from confiture.core.error_codes import CANONICAL_EXIT_CODES

    result = runner.invoke(
        app, ["seed", "validate", "--seeds-dir", "/no/such-dir", "--format", "json"]
    )
    payload = json.loads(result.stdout)
    code = payload["error"]["code"]
    assert result.exit_code == CANONICAL_EXIT_CODES[code]
