"""One place documents every timing key a `to_dict()` emits (Phase 06).

The migrate family serializes ``total_duration_ms`` / ``duration_ms`` (since 1.0.0 the
dataclass attributes carry the same names); build and lint emit ``execution_time_ms`` as-is; the drift
reports emit ``detection_time_ms``. Rather than three vocabularies discovered by
reading source, ``docs/reference/json-schemas.md`` carries one table mapping
every ``*_ms`` key to the attribute that produces it, and this test derives the
same table from the code so the two cannot drift: a new timing key without a row
fails, and so does a row for a key that no longer exists.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import confiture

_PACKAGE_ROOT = Path(confiture.__file__).resolve().parent
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DOC = _REPO_ROOT / "docs" / "reference" / "json-schemas.md"
_HEADING = "## Timing vocabulary"

Row = tuple[str, str, str]  # (qualified class, attribute expression, JSON key)


def _emitted_timing_rows() -> set[Row]:
    rows: set[Row] = set()
    for path in sorted(_PACKAGE_ROOT.rglob("*.py")):
        module = "confiture." + ".".join(path.relative_to(_PACKAGE_ROOT).with_suffix("").parts)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            for fn in (
                n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "to_dict"
            ):
                for mapping in (n for n in ast.walk(fn) if isinstance(n, ast.Dict)):
                    for key, value in zip(mapping.keys, mapping.values, strict=True):
                        if (
                            isinstance(key, ast.Constant)
                            and isinstance(key.value, str)
                            and key.value.endswith("_ms")
                        ):
                            attribute = ast.unparse(value).removeprefix("self.")
                            rows.add((f"{module}.{cls.name}", attribute, key.value))
    return rows


def _documented_timing_rows() -> set[Row]:
    text = _DOC.read_text(encoding="utf-8")
    assert _HEADING in text, f"{_DOC.name} has no '{_HEADING}' section"
    section = text.split(_HEADING, 1)[1].split("\n## ", 1)[0]
    cell = r"`([^`]+)`"
    pattern = re.compile(rf"^\|\s*{cell}\s*\|\s*{cell}\s*\|\s*{cell}\s*\|", re.M)
    return {(m.group(1), m.group(2), m.group(3)) for m in pattern.finditer(section)}


def test_every_emitted_timing_key_is_documented_once() -> None:
    emitted = _emitted_timing_rows()
    documented = _documented_timing_rows()
    assert emitted, "the scan found no timing keys — the scanner is broken"
    assert emitted - documented == set(), (
        f"timing keys emitted but not in the table: {sorted(emitted - documented)}"
    )
    assert documented - emitted == set(), (
        f"table rows with no emitting to_dict(): {sorted(documented - emitted)}"
    )


def test_every_schema_timing_property_is_a_documented_key() -> None:
    """A wire key in a shipped schema is one the table explains."""
    documented_keys = {key for _, _, key in _documented_timing_rows()}
    schema_keys: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for name, value in node.items():
                if name == "properties" and isinstance(value, dict):
                    schema_keys.update(k for k in value if k.endswith("_ms"))
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for schema in sorted((_PACKAGE_ROOT / "schemas").glob("*.schema.json")):
        walk(json.loads(schema.read_text(encoding="utf-8")))
    assert schema_keys, "no *_ms property in any shipped schema — the scanner is broken"
    assert schema_keys - documented_keys == set(), (
        f"schema timing properties missing from the table: {sorted(schema_keys - documented_keys)}"
    )
