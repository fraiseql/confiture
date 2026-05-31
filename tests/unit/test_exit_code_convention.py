"""Convention test for the stabilized exit-code contract (issue #146).

This module asserts the live ``ERROR_CODE_REGISTRY`` against the HAND-AUTHORED
``CANONICAL_EXIT_CODES`` table. The two are deliberately independent sources:
``CANONICAL_EXIT_CODES`` is written from ``docs/reference/exit-codes.md``, the
registry is the runtime data ``ConfiturError.exit_code`` reads. The redundancy
is the enforcement mechanism — a drift between them fails here, not in
production. Deriving one from the other would make this test a tautology.
"""

from pathlib import Path

import pytest

from confiture.core.error_codes import (
    CANONICAL_EXIT_CODES,
    ERROR_CODE_REGISTRY,
    render_exit_codes_doc,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXIT_CODES_DOC = _REPO_ROOT / "docs" / "reference" / "exit-codes.md"


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
        "exit-codes.md generated block is stale; regenerate with "
        "`confiture --exit-codes`"
    )
