"""The ``doc`` family: every commentable object carries a ``COMMENT`` (#217).

``doc_001`` covers tables, ``doc_002`` functions and procedures (one finding per
overload — a comment on ``f(integer)`` says nothing about ``f(text)``),
``doc_003`` views and materialized views, ``doc_004`` composite and enum types
and domains. A partition child inherits its parent's purpose and is not asked
for a comment of its own; its parent still is. All four read the object
inventory, so a schema qualifier changes nothing.
"""

from __future__ import annotations

from confiture.core.linting.inventory import KIND_KEYWORD, Inventory, SchemaObject
from confiture.core.linting.schema_linter import LintViolation, RuleSeverity

#: ``(rule code, rule name)`` per inventory kind. The noun each finding uses is
#: ``KIND_KEYWORD``'s entry, capitalised — one table for both.
_RULES: dict[str, tuple[str, str]] = {
    "table": ("doc_001", "Missing Documentation"),
    "function": ("doc_002", "Undocumented Routine"),
    "procedure": ("doc_002", "Undocumented Routine"),
    "view": ("doc_003", "Undocumented View"),
    "matview": ("doc_003", "Undocumented View"),
    "type": ("doc_004", "Undocumented Type"),
    "domain": ("doc_004", "Undocumented Type"),
}


def _needs_comment(obj: SchemaObject) -> bool:
    return obj.kind in _RULES and not obj.documented and not obj.is_partition


def _finding(obj: SchemaObject) -> LintViolation:
    code, name = _RULES[obj.kind]
    keyword = KIND_KEYWORD[obj.kind]
    return LintViolation(
        rule_id=code,
        rule_name=name,
        severity=RuleSeverity.INFO,
        object_type=obj.kind,
        object_name=obj.identity,
        message=(
            f"{keyword.capitalize()} '{obj.identity}' should have a COMMENT describing its purpose"
        ),
        file_path=obj.file,
        line_number=obj.line,
        suggested_fix=f"COMMENT ON {keyword} {obj.identity} IS '...';",
    )


def documentation_findings(inventory: Inventory) -> list[LintViolation]:
    """One ``doc_*`` finding per undocumented object, in source order."""
    return [_finding(obj) for obj in inventory.objects if _needs_comment(obj)]
