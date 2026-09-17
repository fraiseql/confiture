"""``--check-signatures`` scans the schemas the source declares, not ``public``.

The two halves of the same gate disagreed about scope. `--check-live-drift` reads
the schemas out of the DDL (`parse_expected_schema(...).schemas`), while
`--check-signatures` took `--schemas`, **default `public`** — so a project whose
routines live in `core` had every one of them reported in `missing_from_db`,
always, unless it passed a flag whose help text does not connect it to that
consequence (#303).

The DDL-derived answer is the right one, and it is the one `--check-live-drift`
already gives. An explicit `--schemas` still wins, because naming a schema is a
narrowing a caller may legitimately want.
"""

from __future__ import annotations

from confiture.core.function_signature_drift import schemas_to_scan
from confiture.core.function_signature_parser import FunctionSignature


def sig(schema: str, name: str = "f") -> FunctionSignature:
    return FunctionSignature(schema=schema, name=name, param_types=())


def test_no_request_means_the_schemas_the_source_declares() -> None:
    assert schemas_to_scan(None, [sig("core"), sig("app"), sig("core", "g")]) == ["app", "core"]


def test_an_explicit_request_wins() -> None:
    assert schemas_to_scan("public", [sig("core")]) == ["public"]
    assert schemas_to_scan("public,auth", [sig("core")]) == ["public", "auth"]


def test_whitespace_and_empty_entries_are_ignored() -> None:
    assert schemas_to_scan(" public , , auth ", []) == ["public", "auth"]


def test_a_source_declaring_nothing_falls_back_to_public() -> None:
    """A source with no routine at all has no schema to name, and ``public`` is
    the historical answer — there is nothing to compare either way."""
    assert schemas_to_scan(None, []) == ["public"]


def test_an_empty_string_is_not_a_request() -> None:
    """``--schemas ''`` names no schema; treating it as one would scan nothing."""
    assert schemas_to_scan("", [sig("core")]) == ["core"]
