"""The live-drift corpus is DDL confiture can read, checked without a database.

`tests/fixtures/live_drift_corpus/` is the control corpus for #301, #302 and
#303: one file per gap, applied verbatim to a database so that "this database
was built from this DDL and therefore has zero drift" is a test a comparison can
fail against. A corpus file pglast rejects would make every measurement
a parse error wearing an empty expectation, so it is checked here first, where
no server is needed.
"""

from __future__ import annotations

from pathlib import Path

import pglast
import pytest

from confiture.core.drift import parse_expected_schema

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "live_drift_corpus"

#: Every corpus file, in the order the applier reads them.
FILES = sorted(CORPUS.glob("*.sql"))


def corpus_sql() -> str:
    """The whole corpus as one text, exactly as the identity test compares it."""
    return "\n".join(path.read_text(encoding="utf-8") for path in FILES)


def test_the_corpus_exists() -> None:
    """A floor: an empty glob would make every test below vacuously pass."""
    assert len(FILES) >= 5, [p.name for p in FILES]


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_every_corpus_file_parses(path: Path) -> None:
    assert pglast.parse_sql(path.read_text(encoding="utf-8")) is not None


def test_the_corpus_yields_an_expected_schema() -> None:
    expected = parse_expected_schema(corpus_sql())
    assert expected.model.tables, "no tables parsed out of the corpus"
    assert "core" in expected.schemas
