"""The Rust port's boundary names every module under ``core/``, once, and nothing gone.

``docs/architecture/rust-port-boundary.md`` sorts ``core/`` into three tables — the
crate, the Python I/O glue behind the same JSON contract, and what does not port —
from the rows in ``scripts/gen_port_boundary.py``. A row names a module or a
package; the most specific row covering a module decides, so a package can go to
one table and one of its modules to another. The one-X guards' rules apply: a
module no row covers fails, a row naming nothing fails, and a row that says what
the row above it already says is not a decision and fails too.
"""

from __future__ import annotations

import importlib
import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
DOC = REPO / "docs" / "architecture" / "rust-port-boundary.md"


def _generator():
    script = REPO / "scripts" / "gen_port_boundary.py"
    spec = importlib.util.spec_from_file_location("gen_port_boundary", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GEN = _generator()


def test_every_module_under_core_is_in_exactly_one_table() -> None:
    uncovered = [m for m in GEN.core_modules() if GEN.row_for(m) is None]
    assert uncovered == [], f"modules no row covers: {uncovered}"


def test_no_row_names_a_module_that_is_gone() -> None:
    present = GEN.core_modules()
    stale = [
        row for row in GEN.ROWS if not any(m == row or m.startswith(f"{row}/") for m in present)
    ]
    assert stale == [], f"rows naming nothing: {stale}"


def test_no_row_repeats_the_row_above_it() -> None:
    redundant = [
        row
        for row, decision in GEN.ROWS.items()
        if (parent := GEN.row_for(row, above=True)) is not None and GEN.ROWS[parent] == decision
    ]
    assert redundant == [], f"rows that decide nothing their package did not: {redundant}"


def test_the_tables_are_the_generated_ones() -> None:
    text = DOC.read_text(encoding="utf-8")
    assert GEN.BEGIN in text and GEN.END in text
    current = GEN.BEGIN + text.split(GEN.BEGIN, 1)[1].split(GEN.END, 1)[0] + GEN.END
    assert current == GEN.render(), "stale: run scripts/gen_port_boundary.py --write"


#: ``module.NAME`` for each exhaustiveness table the document names.
_TABLE = re.compile(r"`(core\.[\w.]+)\.([A-Z][A-Z_]+)`")


def _named_tables() -> list[tuple[str, str]]:
    return _TABLE.findall(DOC.read_text(encoding="utf-8"))


def test_the_document_names_the_six_exhaustiveness_guards() -> None:
    assert len({name for _, name in _named_tables()}) >= 12


@pytest.mark.parametrize(("module", "name"), _named_tables())
def test_every_named_table_exists(module: str, name: str) -> None:
    assert hasattr(importlib.import_module(f"confiture.{module}"), name)


def test_architecture_decision_8_links_the_boundary() -> None:
    assert "docs/architecture/rust-port-boundary.md" in (REPO / "ARCHITECTURE.md").read_text()
