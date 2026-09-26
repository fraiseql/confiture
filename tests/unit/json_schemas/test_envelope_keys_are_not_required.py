"""A payload schema does not require the envelope keys ``emit`` adds.

``ok``, ``command`` and ``parser`` joined every payload in 1.16.0. A schema
published since declares them without requiring them, so a consumer validating a
capture from before the envelope is not refused for a key added later. The
exceptions are the ones the reference names: schemas that required them when
they were published, and payloads whose ``ok`` is their own verdict.
"""

from __future__ import annotations

import json
from pathlib import Path

from confiture.core import schema_exporter

SCHEMAS = Path(__file__).resolve().parents[3] / "python" / "confiture" / "schemas"
_ENVELOPE = {"ok", "command", "parser"}

#: Schema → the envelope keys it requires, and why.
REQUIRES_ENVELOPE_KEYS: dict[str, set[str]] = {
    # `ok` is the report's own verdict here, not the envelope's.
    "migrate-preflight.schema.json": {"ok"},
    "migrate-preflight-against.schema.json": {"ok"},
    "migrate-verify.schema.json": {"ok"},
    "verify-checksums.schema.json": {"ok"},
    # Required them when published; loosening a published contract is not done quietly.
    "schema-dump-model.schema.json": {"ok", "command", "parser"},
    "sync.schema.json": {"ok", "command"},
}


def _payload_schemas() -> list[str]:
    names = set(schema_exporter.MODEL_SCHEMAS.values()) | set(schema_exporter.CLI_BUILT_SCHEMAS)
    return sorted(names - {"error-envelope.schema.json", "issue-object.schema.json"})


def test_only_the_named_schemas_require_envelope_keys() -> None:
    requiring = {}
    for name in _payload_schemas():
        required = set(json.loads((SCHEMAS / name).read_text()).get("required", [])) & _ENVELOPE
        if required:
            requiring[name] = required

    assert requiring == REQUIRES_ENVELOPE_KEYS
