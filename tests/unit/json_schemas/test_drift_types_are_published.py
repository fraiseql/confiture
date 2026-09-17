"""``DriftType`` and the published ``DriftItem`` enum say the same thing (#303).

Three members — ``default_mismatch``, ``missing_constraint`` and
``extra_constraint`` — were declared in ``DriftType`` and published in
``_common.schema.json`` while **nothing in the package constructed them**. An
agent reading the published enum would write a handler for
``missing_constraint`` that can never fire; a member added to the enum and not to
the code advertises a capability confiture has not got, and one added to the code
and not the enum breaks a consumer validating against the schema.

Both directions are cheap to check, and checking them would have caught that the
day it was introduced. Whether each member is *emitted* is
``test_drift_types_are_emitted.py``'s question; this one is only about the two
lists agreeing.
"""

from __future__ import annotations

import json
from pathlib import Path

import confiture
from confiture.core.drift import DriftType

SCHEMAS = Path(confiture.__file__).resolve().parent / "schemas"
PUBLISHED_COPY = Path(__file__).resolve().parents[3] / "docs" / "reference" / "json-schemas"


def published_enum(root: Path) -> set[str]:
    common = json.loads((root / "_common.schema.json").read_text(encoding="utf-8"))
    return set(common["$defs"]["DriftItem"]["properties"]["type"]["enum"])


def test_every_drift_type_is_published() -> None:
    assert {member.value for member in DriftType} - published_enum(SCHEMAS) == set()


def test_the_published_enum_declares_nothing_the_code_has_not_got() -> None:
    assert published_enum(SCHEMAS) - {member.value for member in DriftType} == set()


def test_the_docs_copy_is_the_same_file() -> None:
    """`docs/reference/json-schemas/` is a byte-identical copy, written by
    `scripts/gen_schemas.py --write`; a consumer may read either."""
    assert published_enum(PUBLISHED_COPY) == published_enum(SCHEMAS)
