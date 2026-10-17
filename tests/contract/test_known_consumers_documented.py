"""Every consumer the contract tables pin is one the release policy names.

``docs/operations/release-trains.md`` promises that the known consumers are told
before a release. A consumer pinned here but missing from that list would be
protected by CI and still left out of the announcement, which is how fraiseql
learnt of #341 only after 1.16.0 had shipped (#737).
"""

import re
from pathlib import Path

from tests.contract.test_consumer_cli_surface import INVOCATIONS
from tests.contract.test_consumer_symbols import (
    APP_SYMBOLS,
    CALL_SHAPES,
    FRAISIER_SYMBOLS,
    MEMBERS,
)

DOC = Path(__file__).resolve().parents[2] / "docs" / "operations" / "release-trains.md"

# How the policy names each consumer key; "app" is never named in public.
NAMED_AS = {"app": "a downstream application"}


def _known_consumers_paragraph() -> str:
    text = DOC.read_text(encoding="utf-8")
    match = re.search(
        r"\*\*The known consumers are told before the release\.\*\*(.*?)\n- ", text, re.S
    )
    assert match, "release-trains.md no longer says the known consumers are told"
    return " ".join(match.group(1).split())


def test_every_pinned_consumer_is_a_known_consumer() -> None:
    pinned = {
        row.consumer
        for table in (INVOCATIONS, FRAISIER_SYMBOLS, APP_SYMBOLS, CALL_SHAPES, MEMBERS)
        for row in table
    }
    paragraph = _known_consumers_paragraph()
    unnamed = sorted(key for key in pinned if NAMED_AS.get(key, key) not in paragraph)
    assert not unnamed, (
        f"tests/contract/ pins {unnamed}, but release-trains.md's known consumers "
        f"do not name them: {paragraph!r}"
    )
