"""Shared fixtures for JSON-schema validation tests.

The schemas live under ``docs/reference/json-schemas/``. Each test loads
the relevant ``.schema.json`` and validates real CLI output against it
using Draft 2020-12.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "docs" / "reference" / "json-schemas"


def _load_schema(filename: str) -> dict:
    return json.loads((SCHEMAS_DIR / filename).read_text())


@pytest.fixture(scope="session")
def schemas_dir() -> Path:
    """Absolute path to ``docs/reference/json-schemas/``."""
    return SCHEMAS_DIR


@pytest.fixture(scope="session")
def common_schema() -> dict:
    """``_common.schema.json`` — shared $defs (Violation, HintsArray, DriftItem)."""
    return _load_schema("_common.schema.json")


@pytest.fixture(scope="session")
def schema_registry(common_schema):
    """A referencing registry that resolves ``_common.schema.json#/$defs/...`` $refs.

    jsonschema 4.18+ uses ``referencing`` for $ref resolution. Schemas use
    a relative ``_common.schema.json`` $ref, so the registry maps that
    relative URI to the loaded common-schema resource.
    """
    resource = Resource.from_contents(common_schema, default_specification=DRAFT202012)
    return Registry().with_resource(uri="_common.schema.json", resource=resource)


def make_validator(schema: dict, registry) -> Draft202012Validator:
    """Build a Draft 2020-12 validator with the shared registry."""
    return Draft202012Validator(schema, registry=registry)


@pytest.fixture()
def validate_against():
    """Validate a payload against a named schema file.

    Returns a callable: ``validate_against(payload, "schema-file.schema.json")``.
    Raises ``jsonschema.ValidationError`` on mismatch.
    """

    def _validate(payload: dict, schema_filename: str, registry) -> None:
        schema = _load_schema(schema_filename)
        validator = make_validator(schema, registry)
        validator.validate(payload)

    return _validate
