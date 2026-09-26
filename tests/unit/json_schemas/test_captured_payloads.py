"""Payloads captured from real ``--format json`` runs validate against their schemas.

A schema written by reading a dataclass agrees with that dataclass and nothing
else; these files were written by the commands themselves. They were captured
against PostgreSQL 18 with a one-migration project (``CREATE TABLE t``), by running
each command with ``--format json`` and saving stdout unedited. Recapture the same
way when a payload changes on purpose.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

REPO = Path(__file__).resolve().parents[3]
PAYLOADS = REPO / "tests" / "fixtures" / "payloads"
SCHEMAS = REPO / "python" / "confiture" / "schemas"

#: Captured payload → the schema its command publishes.
CAPTURED = {
    "migrate-up.json": "migrate-up.schema.json",
    "migrate-down.json": "migrate-down.schema.json",
    "migrate-reinit.json": "migrate-reinit.schema.json",
    "migrate-rebuild.json": "migrate-rebuild.schema.json",
    "migrate-rebuild-dry-run.json": "migrate-rebuild.schema.json",
}


def _validator(name: str) -> Draft202012Validator:
    registry = Registry().with_resources(
        (path.name, Resource.from_contents(json.loads(path.read_text()), DRAFT202012))
        for path in SCHEMAS.glob("*.schema.json")
    )
    return Draft202012Validator(json.loads((SCHEMAS / name).read_text()), registry=registry)


@pytest.mark.parametrize(("payload", "schema"), sorted(CAPTURED.items()))
def test_a_captured_payload_validates(payload: str, schema: str) -> None:
    errors = [
        e.message
        for e in _validator(schema).iter_errors(json.loads((PAYLOADS / payload).read_text()))
    ]

    assert errors == []


def test_every_captured_payload_is_checked() -> None:
    assert sorted(p.name for p in PAYLOADS.glob("*.json")) == sorted(CAPTURED)
