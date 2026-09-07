"""The error-code registry is rendered from a data table, and the table equals the snapshot.

``confiture.error_code_table.ERROR_CODE_DEFINITIONS`` is plain data (one mapping per
code, no imports, no logic); ``error_codes.py`` turns it into ``ErrorCodeDefinition``
objects. The snapshot under ``tests/fixtures/error_codes/`` was captured from the
hand-written registry the table replaced, so the refactor is byte-for-byte checked;
a deliberate change to a code updates the snapshot in the same commit.
"""

from __future__ import annotations

import ast
import dataclasses
import json
from pathlib import Path

from confiture.error_codes import ERROR_CODE_REGISTRY

REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = REPO_ROOT / "tests" / "fixtures" / "error_codes" / "registry_snapshot.json"
ERROR_CODES_MODULE = REPO_ROOT / "python" / "confiture" / "error_codes.py"
ROW_KEYS = {"code", "message_template", "severity", "exit_code", "resolution_hint"}
MAX_FUNCTION_LINES = 60


def _registry_as_rows() -> dict[str, dict]:
    rows = {}
    for definition in ERROR_CODE_REGISTRY.all_codes():
        row = dataclasses.asdict(definition)
        row["severity"] = definition.severity.value
        rows[definition.code] = {k: v for k, v in row.items() if k != "code"}
    return rows


def test_registry_equals_the_snapshot() -> None:
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert _registry_as_rows() == snapshot, (
        "the registry differs from tests/fixtures/error_codes/registry_snapshot.json; "
        "a deliberate change to a code updates the snapshot in the same commit"
    )


def test_registry_is_rendered_from_the_data_table() -> None:
    from confiture.error_code_table import ERROR_CODE_DEFINITIONS

    assert isinstance(ERROR_CODE_DEFINITIONS, tuple)
    codes = [row["code"] for row in ERROR_CODE_DEFINITIONS]
    assert len(codes) == len(set(codes)), "duplicate code in the table"
    for row in ERROR_CODE_DEFINITIONS:
        assert set(row) == ROW_KEYS, f"{row.get('code')}: keys {sorted(row)}"
        assert isinstance(row["exit_code"], int)
    assert set(codes) == set(_registry_as_rows()), "the table and the registry disagree"


def test_data_table_module_is_data_only() -> None:
    table = REPO_ROOT / "python" / "confiture" / "error_code_table.py"
    tree = ast.parse(table.read_text(encoding="utf-8"))
    kinds = {type(node).__name__ for node in tree.body}
    allowed = {"Expr", "Assign", "AnnAssign", "ImportFrom"}
    assert kinds <= allowed, f"the table module contains logic: {sorted(kinds - allowed)}"
    imports = [n for n in tree.body if isinstance(n, ast.ImportFrom)]
    assert all(n.module == "__future__" for n in imports), "the table imports something"


def test_error_codes_module_has_no_hand_written_catalog_function() -> None:
    tree = ast.parse(ERROR_CODES_MODULE.read_text(encoding="utf-8"))
    long_functions = [
        f"{node.name} ({node.end_lineno - node.lineno + 1} lines)"
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.end_lineno is not None
        and node.end_lineno - node.lineno + 1 > MAX_FUNCTION_LINES
    ]
    assert long_functions == [], f"catalog still hand-written in a function: {long_functions}"
