"""The ``tenant`` rules read SQL through the parser, never through a pattern.

Tenancy is a column the model holds, and what a view or a routine reads is what
pglast's tree says. The family once inferred tenant relationships from views whose
text matched five regexes; a pattern here would be a second reader of SQL beside
the one parser, so any use of :mod:`re` under ``core/linting/tenant/`` fails.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TENANT = REPO / "python" / "confiture" / "core" / "linting" / "tenant"


def _uses_re(path: Path) -> list[str]:
    """``file:line`` of each import of :mod:`re` or attribute read off it in *path*."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        imports_re = (isinstance(node, ast.Import) and any(a.name == "re" for a in node.names)) or (
            isinstance(node, ast.ImportFrom) and node.module == "re"
        )
        reads_re = (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "re"
        )
        if imports_re or reads_re:
            found.append(f"{path.relative_to(REPO)}:{node.lineno}")
    return found


def test_the_package_is_where_the_scan_looks() -> None:
    assert sorted(TENANT.glob("*.py")), f"no modules under {TENANT}"


def test_no_tenant_rule_matches_sql_with_a_pattern() -> None:
    uses = [use for path in sorted(TENANT.glob("*.py")) for use in _uses_re(path)]
    assert uses == [], f"read SQL through pglast, not a regex: {uses}"
