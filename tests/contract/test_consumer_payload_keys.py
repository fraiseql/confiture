"""The JSON keys consumers read off a ``--format json`` payload stay required.

``test_consumer_symbols.py`` pins what a consumer imports and the attributes it
reads off a result object. A consumer that runs the CLI reads the payload instead,
and a key it reads is only a promise once the published schema requires it. Each
row names the key by its path in the payload and the consumer's own ``file:line``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, NamedTuple

import pytest

SCHEMAS = Path(__file__).resolve().parents[2] / "python" / "confiture" / "schemas"


class PayloadKey(NamedTuple):
    consumer: str
    schema: str
    path: str
    """Dotted path from the payload root (``error.code``)."""
    source: str
    pinned_since: str


_FRAISIER_DBOPS = "fraisier:fraisier/dbops/confiture.py"
_FRAISIER_CONTRACT = "fraisier:fraisier/dbops/confiture_contract.py"

PAYLOAD_KEYS: tuple[PayloadKey, ...] = (
    # `_COUNT_KEYS`: how many migrations a run touched, one key per command.
    PayloadKey("fraisier", "migrate-up.schema.json", "applied", f"{_FRAISIER_DBOPS}:690", "1.24.0"),
    PayloadKey(
        "fraisier", "migrate-down.schema.json", "rolled_back", f"{_FRAISIER_DBOPS}:690", "1.24.0"
    ),
    PayloadKey(
        "fraisier", "migrate-down-to.schema.json", "rolled_back", f"{_FRAISIER_DBOPS}:690", "1.24.0"
    ),
    PayloadKey(
        "fraisier", "migrate-rebuild.schema.json", "marked", f"{_FRAISIER_DBOPS}:690", "1.24.0"
    ),
    # `envelope_error_code` / `envelope_error_message`: only these two envelope fields.
    PayloadKey(
        "fraisier",
        "error-envelope.schema.json",
        "error.code",
        f"{_FRAISIER_CONTRACT}:179",
        "1.24.0",
    ),
    PayloadKey(
        "fraisier",
        "error-envelope.schema.json",
        "error.message",
        f"{_FRAISIER_CONTRACT}:154",
        "1.24.0",
    ),
)


def _load(reference: str) -> dict[str, Any]:
    """A schema, or the node a ``file#/pointer`` reference names in a sibling file."""
    name, _, pointer = reference.partition("#")
    node: Any = json.loads((SCHEMAS / name).read_text())
    for part in [p for p in pointer.split("/") if p]:
        node = node[part]
    return node


def _resolved(node: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in node:
        node = _load(node["$ref"])
    return node


def _missing(schema: str, path: str) -> str | None:
    """Where ``path`` stops being required in ``schema``, or ``None``."""
    node = _resolved(_load(schema))
    for depth, key in enumerate(path.split(".")):
        if key not in node.get("required", []):
            return ".".join(path.split(".")[: depth + 1])
        node = _resolved(node["properties"][key])
    return None


@pytest.mark.parametrize("row", PAYLOAD_KEYS, ids=lambda r: f"{r.consumer}:{r.schema}:{r.path}")
def test_a_payload_key_a_consumer_reads_is_required(row: PayloadKey) -> None:
    assert _missing(row.schema, row.path) is None, (
        f"{row.schema} does not require {row.path} — {row.consumer} reads it at {row.source}"
    )


def test_the_check_notices_a_key_that_is_not_required() -> None:
    assert _missing("migrate-up.schema.json", "no_such_key") == "no_such_key"
    assert _missing("error-envelope.schema.json", "error.no_such_key") == "error.no_such_key"
