"""Every schema a command's payload is published under declares the envelope.

``helpers.emit`` adds ``ok``, ``command`` and ``parser`` to every payload it
writes. Twenty of these schemas close their root with
``additionalProperties: false``, so a key the emitter adds and the schema does
not declare makes the schema reject the payload it describes — the published
contract and the output would disagree on every run. A schema with a ``oneOf``
declares the envelope in every branch, since any branch may be the one a
payload matches; a schema that is a ``$ref`` to another declares what that one
declares.
"""

from __future__ import annotations

import pytest

from confiture.core.schema_exporter import load_schema, schema_files

ENVELOPE = ("ok", "command", "parser")

#: Schemas that describe no command's payload, and what they are instead.
NOT_A_PAYLOAD = {
    "_common.schema.json": "shared $defs",
    "_preflight_defs.schema.json": "shared $defs",
    "issue-object.schema.json": "the object embedded in a payload's issues, not a payload",
}


def _missing(schema: dict) -> set[str]:
    """The envelope keys *schema* does not declare, through ``$ref`` and ``oneOf``."""
    ref = schema.get("$ref")
    if isinstance(ref, str) and not ref.startswith("#"):
        return _missing(load_schema(ref))
    declared = set(schema.get("properties", {}))
    missing = {key for key in ENVELOPE if key not in declared}
    branches = schema.get("oneOf") or schema.get("anyOf")
    if branches:
        return set().union(*(_missing(branch) & missing for branch in branches))
    return missing


def _payload_schemas() -> list[str]:
    return [name for name in schema_files() if name not in NOT_A_PAYLOAD]


@pytest.mark.parametrize("name", _payload_schemas())
def test_payload_schema_declares_the_envelope(name: str) -> None:
    assert _missing(load_schema(name)) == set()


@pytest.mark.parametrize("name", sorted(NOT_A_PAYLOAD))
def test_every_exclusion_names_a_schema(name: str) -> None:
    assert name in schema_files(), f"{name} is gone: delete its exclusion"
