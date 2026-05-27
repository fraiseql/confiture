"""The reference doc enumerates every schema file in this directory.

Catches drift if a schema is added but not cross-linked from
``docs/reference/json-schemas.md``.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
REFERENCE_DOC = REPO_ROOT / "docs" / "reference" / "json-schemas.md"
SCHEMAS_DIR = REPO_ROOT / "docs" / "reference" / "json-schemas"


def _public_schemas() -> list[Path]:
    """All schema files except the underscore-prefixed shared sub-schemas."""
    return sorted(
        p for p in SCHEMAS_DIR.glob("*.schema.json") if not p.name.startswith("_")
    )


def test_reference_doc_exists():
    assert REFERENCE_DOC.exists(), f"missing {REFERENCE_DOC}"


def test_reference_doc_mentions_every_schema_file():
    """Each public schema filename appears at least once in the reference doc."""
    text = REFERENCE_DOC.read_text()
    missing = [p.name for p in _public_schemas() if p.name not in text]
    assert not missing, f"reference doc does not mention: {missing}"


def test_reference_doc_calls_out_field_name_traps():
    """The four field-name surprises from issue #123 are documented."""
    text = REFERENCE_DOC.read_text()
    # Each trap surfaces in the doc body so agents can grep for the wrong name.
    assert "source_line" in text
    assert "line_number" in text  # called out as the WRONG field name
    assert "success" in text
    assert "passed" in text  # called out as the WRONG field name
