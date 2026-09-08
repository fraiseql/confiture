"""The ``doc`` family: every commentable object carries a ``COMMENT`` (#217).

``doc_001`` covers tables, ``doc_002`` functions and procedures (one finding per
overload — a comment on ``f(integer)`` says nothing about ``f(text)``),
``doc_003`` views and materialized views, ``doc_004`` composite and enum types
and domains. A partition child inherits its parent's purpose and is not asked
for a comment of its own; its parent still is. All four read the object
inventory, so a schema qualifier changes nothing.

They count comments, and a project that drives the count to zero is rewarded for
whatever satisfies them — a hundred one-line restatements of the signature read
as "documentation: 100 %" exactly as a hundred paragraphs do (#250).
:func:`documentation_summary` reports the distribution beside the count, so the
two are distinguishable without confiture having to judge prose.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from confiture.core.linting.inventory import KIND_KEYWORD, Inventory, SchemaObject, distinct
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
    """One ``doc_*`` finding per undocumented object, in source order.

    Per *object*, not per ``CREATE``: an object defined twice is one thing to
    document and ``build_001``'s finding besides (LINT-10).
    """
    return [_finding(obj) for obj in distinct(inventory.objects) if _needs_comment(obj)]


#: The percentiles the distribution reports: enough to tell "every comment is a
#: sentence" from "half of them are one word", which a median alone hides.
PERCENTILES = (10, 50, 90)


def _codes() -> list[str]:
    """The ``doc`` codes, in catalogue order, without the kinds that share one."""
    seen: list[str] = []
    for code, _name in _RULES.values():
        if code not in seen:
            seen.append(code)
    return seen


def _percentile(lengths: Sequence[int], percentile: int) -> int:
    """Nearest rank: the smallest observed length at or above ``percentile``%.

    No interpolation, so every number reported is a length some comment
    actually has — a median of 9 is a comment of 9 characters, not the average
    of its two neighbours — and one comment still has a distribution.
    """
    rank = math.ceil(percentile / 100 * len(lengths))
    return lengths[max(rank - 1, 0)]


def _lengths(objects: Sequence[SchemaObject]) -> dict[str, int] | None:
    """``{p10, p50, p90}`` over the comments, or ``None`` when there are none.

    A comment's length is its text with surrounding whitespace stripped: the
    padding a heredoc leaves is not documentation.
    """
    measured = sorted(len(obj.comment.strip()) for obj in objects if obj.comment)
    if not measured:
        return None
    return {f"p{p}": _percentile(measured, p) for p in PERCENTILES}


def _distribution(objects: Sequence[SchemaObject]) -> dict[str, Any]:
    documented = [obj for obj in objects if obj.documented]
    return {
        "documented": len(documented),
        "undocumented": len(objects) - len(documented),
        "comment_length": _lengths(documented),
    }


def documentation_summary(inventory: Inventory) -> dict[str, Any]:
    """How much of the schema is documented, and how much each comment says.

    The ``documentation`` block of ``lint --format json``: the counts a reader
    would otherwise infer from the absence of findings, plus the comment-length
    percentiles that tell one kind of "100 % documented" from the other (#250).
    Every ``doc`` code has a row whether or not the schema holds any of its
    objects, so a consumer reads a fixed shape; the top-level figures are the
    family's, which is what the summary line reports.
    """
    subject = [
        obj for obj in distinct(inventory.objects) if obj.kind in _RULES and not obj.is_partition
    ]
    by_code = {code: [obj for obj in subject if _RULES[obj.kind][0] == code] for code in _codes()}
    return {
        **_distribution(subject),
        "rules": [{"code": code, **_distribution(objects)} for code, objects in by_code.items()],
    }
