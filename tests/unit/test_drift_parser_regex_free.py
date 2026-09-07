"""The drift expected-schema parser is the pglast walk, not a regex (#227, ANA-05).

pglast is the one parser (D13); ``core/drift.py`` was the last analyzer
still matching ``CREATE TABLE (\\w+)`` by hand — which is how ``tenant.tb_user``
became a table called ``tenant``. This pins the replacement: no DDL regex in
the module, and the expected side built from the shared inventory.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import confiture.core.drift as drift_module

_SOURCE = Path(drift_module.__file__).read_text(encoding="utf-8")
_DDL_KEYWORDS = ("CREATE", "TABLE", "INDEX", "COLUMN")


def test_no_ddl_regex_survives_in_the_drift_module() -> None:
    offenders = []
    for node in ast.walk(ast.parse(_SOURCE)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if isinstance(node.func.value, ast.Name) and node.func.value.id == "re":
            text = ast.unparse(node)
            if any(keyword in text.upper() for keyword in _DDL_KEYWORDS):
                offenders.append(f"line {node.lineno}: {text[:80]}")
    assert offenders == [], "DDL is parsed with a regex again:\n" + "\n".join(offenders)


def test_the_regex_helpers_are_gone() -> None:
    for name in ("_extract_columns_from_create", "_split_column_definitions", "_DOLLAR_BODY_RE"):
        assert name not in _SOURCE, f"{name} is back in core/drift.py"
    assert not re.search(r"CREATE\\s\+TABLE", _SOURCE), (
        "a CREATE TABLE regex is back in core/drift.py"
    )


def test_the_expected_side_is_built_from_the_inventory() -> None:
    tree = ast.parse(_SOURCE)
    parser = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "parse_expected_schema"
    )
    calls = {ast.unparse(n.func) for n in ast.walk(parser) if isinstance(n, ast.Call)}
    assert "build_inventory" in calls
