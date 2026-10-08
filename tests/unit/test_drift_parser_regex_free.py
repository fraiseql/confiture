"""The drift expected-schema parser is the pglast walk, not a regex (#227).

pglast is the one parser; ``core/drift.py`` was the last analyzer
still matching ``CREATE TABLE (\\w+)`` by hand — which is how ``tenant.tb_user``
became a table called ``tenant``. This pins the replacement: no DDL regex in
the module, and the expected side built from the one schema read (``schema_read``).
"""

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


def test_the_expected_side_is_built_from_the_one_schema_read() -> None:
    functions = {n.name: n for n in ast.walk(ast.parse(_SOURCE)) if isinstance(n, ast.FunctionDef)}
    calls = {
        ast.unparse(n.func)
        for n in ast.walk(functions["parse_expected_schema"])
        if isinstance(n, ast.Call)
    }
    assert "read_text" in calls
    attributes = {
        ast.unparse(n)
        for n in ast.walk(functions["expected_schema"])
        if isinstance(n, ast.Attribute)
    }
    assert "read.catalogued" in attributes
