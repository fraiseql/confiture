"""Executable guards: documented JSON/result shapes match the real models.

DOCS-H2 / DOCS-H3 anti-drift guards.

* ``migrate up`` JSON in ``structured-output.md`` must use the real
  ``MigrateUpResult.to_dict()`` keys (no fictional ``migrations_applied`` /
  ``total_execution_time_ms`` / ``count``).
* ``dry-run-api.md`` must describe the real ``DryRunExecutor`` / ``DryRunResult``
  surface (no ``locked_tables`` / ``confidence_percent`` / ``estimated_*``).
"""

from __future__ import annotations

import dataclasses
import json

from doc_snippets import assert_doc_imports_resolve, fenced_after_anchor, read_doc

from confiture.core.dry_run import DryRunResult
from confiture.models.results import MigrateUpResult

STRUCTURED_DOC = "docs/guides/structured-output.md"
DRY_RUN_DOC = "docs/reference/dry-run-api.md"


def _real_up_keys() -> set[str]:
    sample = MigrateUpResult(success=True, migrations_applied=[], total_execution_time_ms=0)
    return set(sample.to_dict().keys())


def test_migrate_up_json_keys_match_to_dict() -> None:
    """The documented `migrate up` JSON uses only real MigrateUpResult.to_dict keys."""
    snippet = fenced_after_anchor(read_doc(STRUCTURED_DOC), "migrate-up-json")
    doc_keys = set(json.loads(snippet).keys())
    real_keys = _real_up_keys()

    assert doc_keys <= real_keys, f"doc shows non-existent keys: {doc_keys - real_keys}"
    # The two historically-wrong keys must be the canonical ones.
    assert "applied" in doc_keys and "total_duration_ms" in doc_keys
    assert "migrations_applied" not in doc_keys
    assert "total_execution_time_ms" not in doc_keys


def test_dry_run_api_imports_resolve() -> None:
    """Every confiture import in dry-run-api.md resolves to a real symbol."""
    assert assert_doc_imports_resolve(DRY_RUN_DOC) > 0


def test_dry_run_api_documents_real_dry_run_result_fields() -> None:
    """dry-run-api.md lists the real DryRunResult fields and none of the fictional ones."""
    text = read_doc(DRY_RUN_DOC)
    real_fields = {f.name for f in dataclasses.fields(DryRunResult)}
    # {"migration_name", "success", "total_time_ms", "confidence_pct", "statements", "error"}
    for field_name in real_fields:
        assert field_name in text, f"dry-run-api.md omits real DryRunResult field {field_name!r}"

    fictional = [
        "migration_version",
        "locked_tables",
        "estimated_production_time_ms",
        "confidence_percent",  # real field is confidence_pct
        "stats: dict",
    ]
    leaked = [tok for tok in fictional if tok in text]
    assert not leaked, f"fictional DryRunResult fields still present: {leaked}"
