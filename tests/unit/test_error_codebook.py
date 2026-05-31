"""Codebook coverage tests for the structured error contract (issue #145).

Confirms the common failure modes the issue lists are each a registered code,
that every code carries an `actionable` resolution hint (the envelope field), and
that the published codebook doc stays generated from the registry.
"""

from __future__ import annotations

from pathlib import Path

from confiture.core.error_codes import ERROR_CODE_REGISTRY, render_error_codebook

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CODEBOOK_DOC = _REPO_ROOT / "docs" / "reference" / "error-codes.md"

# The common failure modes the issue enumerates, each mapped to its stable code.
REQUIRED_COMMON = {
    "MIGR_106",  # duplicate version
    "ROLLBACK_600",  # irreversible / missing down
    "LOCK_1300",  # lock contention
    "CONFIG_006",  # connection failed
    "MIGR_011",  # checksum mismatch
    "PRECON_1001",  # not initialized / no tracking table
}


def test_required_common_codes_registered() -> None:
    have = {d.code for d in ERROR_CODE_REGISTRY.all_codes()}
    assert have >= REQUIRED_COMMON


def test_every_code_has_actionable_hint() -> None:
    """Every registered code carries a resolution hint (envelope `actionable`)."""
    missing = [d.code for d in ERROR_CODE_REGISTRY.all_codes() if not d.resolution_hint]
    assert missing == [], f"codes without a resolution_hint: {missing}"


def test_codebook_doc_lists_required_common_codes() -> None:
    doc = _CODEBOOK_DOC.read_text()
    for code in REQUIRED_COMMON:
        assert f"`{code}`" in doc, f"{code} missing from error-codes.md"


def test_codebook_doc_embeds_current_generated_table() -> None:
    doc = _CODEBOOK_DOC.read_text()
    begin = "<!-- BEGIN GENERATED: codebook -->"
    end = "<!-- END GENERATED -->"
    assert begin in doc and end in doc, "codebook generated-section markers missing"
    embedded = doc.split(begin, 1)[1].split(end, 1)[0].strip()
    assert embedded == render_error_codebook().strip(), (
        "error-codes.md codebook is stale; regenerate from render_error_codebook()"
    )
