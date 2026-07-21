"""Convention test for the stabilized exit-code contract (issue #146).

This module asserts the live ``ERROR_CODE_REGISTRY`` against the HAND-AUTHORED
``CANONICAL_EXIT_CODES`` table. The two are deliberately independent sources:
``CANONICAL_EXIT_CODES`` is written from ``docs/reference/exit-codes.md``, the
registry is the runtime data ``ConfiturError.exit_code`` reads. The redundancy
is the enforcement mechanism — a drift between them fails here, not in
production. Deriving one from the other would make this test a tautology.
"""

import json
from pathlib import Path

import pytest

from confiture.core.error_codes import (
    CANONICAL_EXIT_CODES,
    ERROR_CODE_REGISTRY,
    EXIT_CODE_MEANINGS,
    EXIT_CODE_SEMANTIC_CLASS,
    NO_LEDGER_ERROR_CODE,
    render_exit_codes_doc,
    render_exit_codes_json,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXIT_CODES_DOC = _REPO_ROOT / "docs" / "reference" / "exit-codes.md"

# The frozen semantic-class vocabulary — an independent hand-authored source, so a
# drift from EXIT_CODE_SEMANTIC_CLASS fails here rather than in a consumer's CI.
# This is the taxonomy the fraisier adapters (Rust + Python) project onto.
_CANONICAL_CLASSES = frozenset(
    {
        "ok",
        "internal_error",
        "precondition_failed",
        "db_unreachable",
        "schema_error",
        "invalid_config",
        "lock_contention",
        "git_error",
        "irreversible_rollback",
    }
)


@pytest.mark.parametrize(
    "definition",
    ERROR_CODE_REGISTRY.all_codes(),
    ids=lambda d: d.code,
)
def test_registry_exit_code_matches_canonical(definition) -> None:
    """Every registered error code exits with its canonical number."""
    assert definition.code in CANONICAL_EXIT_CODES, (
        f"{definition.code} is registered but missing from CANONICAL_EXIT_CODES; "
        f"add it to the hand-authored contract (and docs/reference/exit-codes.md)"
    )
    assert definition.exit_code == CANONICAL_EXIT_CODES[definition.code], (
        f"{definition.code}: registry says {definition.exit_code}, "
        f"canonical says {CANONICAL_EXIT_CODES[definition.code]}"
    )


def test_canonical_table_covers_exactly_the_registry() -> None:
    """The contract and the registry describe the same set of codes.

    A newly added registry code must also be added to CANONICAL_EXIT_CODES
    (and the doc) — it cannot silently skip the convention. A stale canonical
    entry for a removed code is likewise caught here.
    """
    canonical = set(CANONICAL_EXIT_CODES)
    registered = {d.code for d in ERROR_CODE_REGISTRY.all_codes()}
    assert canonical == registered, (
        f"only in canonical: {sorted(canonical - registered)}; "
        f"only in registry: {sorted(registered - canonical)}"
    )


@pytest.mark.parametrize(
    ("code", "expected_exit"),
    [
        ("MIGR_101", 0),  # already applied — success-with-signal
        ("MIGR_105", 0),  # no pending migrations — success-with-signal
        ("LINT_1501", 0),  # lint warning — informational, non-blocking
        ("DIFFER_402", 1),  # ambiguous-change advisory (DIFFER family is 5)
        ("PRECON_1001", 2),  # tracking table absent (PRECON family is 5)
        ("CONFIG_006", 3),  # DB connection failed (CONFIG family is 5)
    ],
)
def test_intentional_carve_outs(code: str, expected_exit: int) -> None:
    """Codes that deliberately differ from their family default stay put.

    These are not strays to "align" during a call-site audit — each is a
    documented carve-out in docs/reference/exit-codes.md.
    """
    assert ERROR_CODE_REGISTRY.get(code).exit_code == expected_exit
    assert CANONICAL_EXIT_CODES[code] == expected_exit


def test_exit_codes_doc_covers_every_code() -> None:
    """The reference doc has a summary row for every in-use exit code."""
    doc = _EXIT_CODES_DOC.read_text()
    for code in sorted(set(CANONICAL_EXIT_CODES.values())):
        assert f"| {code} |" in doc, f"exit code {code} undocumented in exit-codes.md"


def test_exit_codes_doc_embeds_current_generated_section() -> None:
    """The doc's generated block matches render_exit_codes_doc() (no drift).

    If a code is added/renumbered, regenerate with ``confiture --exit-codes``
    and paste between the BEGIN/END GENERATED markers.
    """
    doc = _EXIT_CODES_DOC.read_text()
    begin = "<!-- BEGIN GENERATED: confiture --exit-codes -->"
    end = "<!-- END GENERATED -->"
    assert begin in doc and end in doc, "generated-section markers missing"
    embedded = doc.split(begin, 1)[1].split(end, 1)[0].strip()
    assert embedded == render_exit_codes_doc().strip(), (
        "exit-codes.md generated block is stale; regenerate with `confiture --exit-codes`"
    )


# ---------------------------------------------------------------------------
# Semantic classes — the machine-readable taxonomy the fraisier adapters consume
# (fraisier-core Rust + fraisier Python). Redundancy against the hand-authored
# _CANONICAL_CLASSES is the enforcement, exactly as above.
# ---------------------------------------------------------------------------


def test_semantic_class_covers_exactly_the_used_exit_codes() -> None:
    """Every in-use exit integer has a semantic class, and no stray ones exist."""
    used = set(CANONICAL_EXIT_CODES.values())
    assert set(EXIT_CODE_SEMANTIC_CLASS) == used, (
        f"only classed: {sorted(set(EXIT_CODE_SEMANTIC_CLASS) - used)}; "
        f"only used: {sorted(used - set(EXIT_CODE_SEMANTIC_CLASS))}"
    )


def test_semantic_classes_are_the_frozen_vocabulary() -> None:
    """The classes are exactly the 9 frozen names, one per exit code (a bijection)."""
    assert set(EXIT_CODE_SEMANTIC_CLASS.values()) == _CANONICAL_CLASSES
    assert len(set(EXIT_CODE_SEMANTIC_CLASS.values())) == len(EXIT_CODE_SEMANTIC_CLASS)


def test_no_ledger_error_code_is_precondition_at_exit_two() -> None:
    """The no-ledger code the adapters key on stays PRECON_1001 → exit 2 → precondition."""
    assert NO_LEDGER_ERROR_CODE == "PRECON_1001"
    assert CANONICAL_EXIT_CODES[NO_LEDGER_ERROR_CODE] == 2
    assert EXIT_CODE_SEMANTIC_CLASS[2] == "precondition_failed"


def test_render_exit_codes_json_matches_the_registry() -> None:
    """The machine-readable emit is generated from the same tables, without drift."""
    payload = json.loads(render_exit_codes_json())
    assert payload["no_ledger_error_code"] == NO_LEDGER_ERROR_CODE
    assert set(payload["classes"]) == _CANONICAL_CLASSES
    for code_str, entry in payload["exit_codes"].items():
        code = int(code_str)
        assert entry["class"] == EXIT_CODE_SEMANTIC_CLASS[code]
        assert entry["meaning"] == EXIT_CODE_MEANINGS[code]
        symbols = sorted(c for c, ec in CANONICAL_EXIT_CODES.items() if ec == code)
        assert entry["symbolic_codes"] == symbols
    assert {int(c) for c in payload["exit_codes"]} == set(CANONICAL_EXIT_CODES.values())
