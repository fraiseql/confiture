"""Guard: no AST path may compare against a hardcoded PostgreSQL enum ordinal (#192).

pglast 8 renumbered ``AlterTableType`` (PG18 inserted a member, shifting
everything at index >= 13 down by one). Confiture compared ``cmd.subtype``
against literals, so every comparison past that point missed and the ``elif``
chains fell through — dropping the operation **silently**. A dropped
``DropColumn`` turns a replica-unsafe migration into ``window_safe: true``.

These guards are the reason that cannot recur:

* the binding half asserts every declared member still resolves by name;
* the source half asserts nobody has reintroduced a literal.

The declared list lives in ``core/_pglast_enums.REQUIRED_MEMBERS``, so a new
constant joins this guard by being declared rather than by someone remembering
to extend a parallel table here.
"""

from __future__ import annotations

import re
import tokenize
from pathlib import Path

import pytest

from confiture.core import _pglast_enums
from confiture.core._pglast_enums import (
    MISSING_MEMBERS,
    REQUIRED_MEMBERS,
    enums_are_usable,
)
from confiture.core.idempotency.ast_detector import is_pglast_available

_CONFITURE_SRC = Path(__file__).resolve().parents[2] / "python" / "confiture"

pytestmark = pytest.mark.skipif(
    not is_pglast_available(),
    reason="the [ast] extra is not installed; the AST path is inert",
)


# ---------------------------------------------------------------------------
# The binding resolves
# ---------------------------------------------------------------------------


def test_no_declared_member_is_missing() -> None:
    """Every member confiture walks still exists in the installed pglast.

    A failure here means an upstream release removed or renamed something. The
    runtime degrades to the regex backend rather than misclassifying, but the
    AST path is disabled until this is reconciled — so fix it, don't skip it.
    """
    assert MISSING_MEMBERS == [], (
        f"pglast no longer exposes: {', '.join(MISSING_MEMBERS)}. "
        "The AST backend has silently degraded to regex for every caller. "
        "Update core/_pglast_enums.REQUIRED_MEMBERS to the new spelling."
    )
    assert enums_are_usable()


@pytest.mark.parametrize(
    ("enum_name", "member_name"),
    [(enum, m) for enum, members in REQUIRED_MEMBERS.items() for m in members],
)
def test_declared_member_resolves_by_name(enum_name: str, member_name: str) -> None:
    """Each declared member resolves to a real, non-sentinel ordinal."""
    from pglast import enums

    resolved = _pglast_enums.member(enum_name, member_name)
    assert resolved >= 0, f"{enum_name}.{member_name} fell back to a sentinel"
    assert resolved == int(getattr(getattr(enums, enum_name), member_name))


def test_alter_table_constants_track_the_installed_pglast() -> None:
    """The consumers' constants equal the name-resolved values, not 7.x literals.

    Pinned explicitly because ``AlterTableType`` is the enum that actually
    moved: under pglast 7 these are 14/25/17/23/27, under 8 they are
    13/24/16/22/26. Either is correct; a *literal* is not.
    """
    from pglast.enums import AlterTableType

    from confiture.core.idempotency import _captures, ast_detector
    from confiture.core.replica import classifier

    assert int(AlterTableType.AT_DropColumn) == classifier._AT_DROP_COLUMN
    assert int(AlterTableType.AT_AlterColumnType) == classifier._AT_ALTER_COLUMN_TYPE
    assert int(AlterTableType.AT_AddConstraint) == classifier._AT_ADD_CONSTRAINT
    assert int(AlterTableType.AT_DropConstraint) == ast_detector._AT_DROP_CONSTRAINT
    assert int(AlterTableType.AT_ChangeOwner) == ast_detector._AT_CHANGE_OWNER
    # The two inline comparisons that a constant-block sweep does not reach.
    assert int(AlterTableType.AT_AddConstraint) == _captures._AT_ADD_CONSTRAINT
    assert int(AlterTableType.AT_AddColumn) == _captures._AT_ADD_COLUMN


# ---------------------------------------------------------------------------
# Nobody reintroduced a literal
# ---------------------------------------------------------------------------

# Both shapes the codebase has actually used:
#   _AT_DROP_COLUMN = 14                     (module constant)
#   _CONSTR_KIND = {5: "check", ...}         (dict of ordinals)
#   if sub_int == 17:  # AT_ADD_CONSTRAINT   (inline — the one that got missed)
_CONSTANT_LITERAL = re.compile(r"_(?:AT|OBJECT|CONSTR|RENAME)_[A-Z_]+\s*[:=]\s*\{?\s*-?\d")
_INLINE_LITERAL = re.compile(
    r"(sub_int|subtype|contype|renameType|objtype|removeType)\s*[=!]=\s*-?\d"
)


def _python_sources() -> list[Path]:
    return [p for p in _CONFITURE_SRC.rglob("*.py") if "__pycache__" not in p.parts]


def _prose_lines(path: Path) -> set[int]:
    """Line numbers occupied by a string literal or comment.

    Tokenising rather than exempting files by name: ``_pglast_enums.py``'s
    docstring necessarily quotes ``_AT_DROP_COLUMN = 14`` (describing the bug
    is its job), and a path-based exemption would blind the guard to real
    literals in the very module that defines the binding.
    """
    prose: set[int] = set()
    with path.open("rb") as fh:
        for tok in tokenize.tokenize(fh.readline):
            if tok.type in (tokenize.STRING, tokenize.COMMENT):
                prose.update(range(tok.start[0], tok.end[0] + 1))
    return prose


def test_no_hardcoded_enum_ordinal_in_source() -> None:
    """No literal ordinal in executable code anywhere under python/confiture/."""
    offenders: list[str] = []
    for path in _python_sources():
        prose = _prose_lines(path)
        for i, raw in enumerate(path.read_text().splitlines(), start=1):
            if i in prose:
                continue
            line = raw.split("#")[0]
            if not line.strip():
                continue
            if _CONSTANT_LITERAL.search(line) or _INLINE_LITERAL.search(line):
                rel = path.relative_to(_CONFITURE_SRC.parent.parent)
                offenders.append(f"  {rel}:{i}  {line.strip()}")

    assert not offenders, (
        "hardcoded PostgreSQL enum ordinal(s) — resolve by name via "
        "core/_pglast_enums.member() instead (#192):\n" + "\n".join(offenders)
    )


def test_required_members_covers_every_resolved_constant() -> None:
    """Every `_pg_member(...)` call site names a member declared in the table.

    Without this, a new constant could be resolved by name (correct) but stay
    outside ``REQUIRED_MEMBERS`` — and so outside the missing-member guard that
    disables the AST path when upstream drops it.
    """
    call = re.compile(r"""_pg_member\(\s*["'](\w+)["']\s*,\s*["'](\w+)["']\s*\)""")
    undeclared: list[str] = []
    for path in _python_sources():
        for enum_name, member_name in call.findall(path.read_text()):
            if member_name not in REQUIRED_MEMBERS.get(enum_name, ()):
                rel = path.relative_to(_CONFITURE_SRC.parent.parent)
                undeclared.append(f"  {rel}: {enum_name}.{member_name}")

    assert not undeclared, (
        "resolved but not declared in REQUIRED_MEMBERS, so the missing-member "
        "guard does not cover them:\n" + "\n".join(undeclared)
    )
