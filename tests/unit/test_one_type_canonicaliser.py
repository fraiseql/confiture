"""One type canonicaliser: ``core/type_lattice.py`` holds the only alias table.

Two spellings of one PostgreSQL type are one type, and deciding which spellings
those are is a table. Confiture had **six** of them, resolving in three
different directions:

===============================================  ==================================
``core/type_lattice.py``                         ``int4`` -> ``integer``
``core/linting/libraries/functions.py``          ``int4`` -> ``integer``
``core/linting/libraries/security_definer.py``   ``int4`` -> ``integer``
``core/differ.py``                               ``INT4`` -> ``INTEGER``
``core/function_signature_parser.py``            ``varchar`` -> ``character varying``
``core/drift.py``                                ``integer`` -> ``int4``
===============================================  ==================================

The two under ``core/linting/`` were `_PG_CATALOG_ALIASES`, pasted from one to
the other under a comment reading "Shared with func_001" — it was not shared, it
was copied, and neither covered a bare internal name, so ``int8`` and ``bigint``
were two signatures and `build_001` reported no duplicate for a pair PostgreSQL
rejects (#275). They are gone; `canonical_type` answers for both.

The remaining three are listed below with the reason, and a listed module that
no longer matches anything fails, as in the one-lexer and one-path-matcher
guards. Each of them is a *different* direction from the lattice's and feeds a
published output, so folding one in is a behaviour change to a surface neither
#274 nor #275 is about — worth doing, not worth doing here.

The ten spellings that split, each a `CREATE` written one way and a `COMMENT`
the other, are pinned in `tests/unit/linting/test_type_spellings_are_one_type.py`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import confiture

PACKAGE = Path(confiture.__file__).resolve().parent
REPO = Path(__file__).resolve().parents[2]
CANONICALISER = PACKAGE / "core" / "type_lattice.py"

#: Spellings PostgreSQL accepts for its built-in types, both the SQL-standard
#: keyword forms and the internal names. A dict whose keys *and* values are all
#: drawn from this is a type-alias table and nothing else plausibly is.
SPELLINGS = frozenset(
    {
        "bigint",
        "bigserial",
        "bit",
        "bit varying",
        "bool",
        "boolean",
        "bpchar",
        "char",
        "character",
        "character varying",
        "date",
        "decimal",
        "double",
        "double precision",
        "float4",
        "float8",
        "int",
        "int2",
        "int4",
        "int8",
        "integer",
        "json",
        "jsonb",
        "money",
        "numeric",
        "real",
        "serial",
        "smallint",
        "smallserial",
        "text",
        "time",
        "time with time zone",
        "time without time zone",
        "timestamp",
        "timestamp with time zone",
        "timestamp without time zone",
        "timestamptz",
        "timetz",
        "uuid",
        "varbit",
        "varchar",
        "xml",
    }
)

#: Fewer than this and a dict of two type names is more likely a fixture or a
#: parametrised case than a table of aliases.
MIN_ENTRIES = 3

#: Modules that keep a type-alias table of their own, with the reason. Each one
#: canonicalises in a *different direction* from `type_lattice`, so folding it in
#: is a behaviour change to a surface neither #274 nor #275 is about.
ALLOWED: dict[str, str] = {
    "core/differ.py": (
        "`_PGLAST_TYPE_ALIASES` maps pglast's internal names back into the upper-case "
        "spellings of `_COLUMN_TYPE_MAP`, which is the column type `migrate diff` prints "
        "and writes into a generated migration; `canonical_type` answers lower-case"
    ),
    "core/function_signature_parser.py": (
        "`_TYPE_ALIASES` resolves toward the SQL-standard keyword form "
        "(`varchar` -> `character varying`), the opposite of `canonical_type`, because its "
        "output is the signature text `--check-signatures` prints and diffs; adopting the "
        "lattice would move that text for every project with a `varchar` parameter"
    ),
    "core/drift.py": (
        "`_types_compatible` resolves toward the internal name (`integer` -> `int4`) to "
        "compare a live column type against a DDL one; it is a predicate over two live "
        "spellings, not a rendering, and `confiture drift`'s output moves if the direction "
        "changes"
    ),
}


def _alias_tables(path: Path) -> list[int]:
    """Line numbers of every type-alias table literal in one module."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover - the package parses
        return []
    found: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict) or len(node.keys) < MIN_ENTRIES:
            continue
        keys = [
            k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)
        ]
        values = [
            v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)
        ]
        if len(keys) != len(node.keys) or len(values) != len(node.values):
            continue
        if all(k.lower() in SPELLINGS for k in keys) and all(
            v.lower() in SPELLINGS for v in values
        ):
            found.append(node.lineno)
    return found


def _tables_outside_the_canonicaliser() -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if path == CANONICALISER:
            continue
        lines = _alias_tables(path)
        if lines:
            found[path.relative_to(PACKAGE).as_posix()] = lines
    return found


def test_the_canonicaliser_still_holds_a_table() -> None:
    """The guard is worth nothing if its predicate stopped matching the real one."""
    assert _alias_tables(CANONICALISER), (
        "core/type_lattice.py no longer looks like a type-alias table; "
        "SPELLINGS or MIN_ENTRIES has drifted from what it holds"
    )


def test_no_second_type_alias_table() -> None:
    offenders = [
        f"{module}:{line}"
        for module, lines in _tables_outside_the_canonicaliser().items()
        if module not in ALLOWED
        for line in lines
    ]
    assert offenders == [], "type-alias tables outside core/type_lattice.py:\n  " + "\n  ".join(
        offenders
    )


def test_allow_list_is_current() -> None:
    present = set(_tables_outside_the_canonicaliser())
    stale = sorted(module for module in ALLOWED if module not in present)
    assert stale == [], f"allow-list entries with nothing left to allow: {stale}"
