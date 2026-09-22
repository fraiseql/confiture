"""Is an `ALTER COLUMN … TYPE` widening or narrowing (issue #199)?

`bigint`→`integer` silently loses data or aborts mid-migration; `integer`→`bigint`
cannot. Knowing only the table and column, preflight would have to treat both
alike — and, having no honest answer, emit no risk tier at all.

Two questions are answered separately because their answers differ:

* :func:`compare_types` — the **semantic** direction. Drives the risk tier:
  narrowing destroys data with no down path.
* :func:`changes_rewrite_table` — whether PostgreSQL **rewrites the heap**.
  Drives the lock cost. `varchar(50)`→`text` is widening *and* rewrite-free;
  `integer`→`bigint` is widening but still rewrites every page.

Only the rewrite exemptions PostgreSQL documents are claimed: a rewrite is
skipped when the old type is binary-coercible to the new one, which for the types
here means the unconstrained-length string cases. Everything else — including
`numeric(10,2)`→`numeric(12,2)`, which merely *looks* free — is reported as a
rewrite. Guessing in the cheap direction is the failure this module exists to
prevent.

An unrecognised or user-defined type is :attr:`TypeChange.UNKNOWN`, never
optimistic. The old type is absent from `ALTER TABLE … ALTER COLUMN … TYPE`
altogether — SQL states only the target — so it has to come from the differ or a
live database, and when it does not, the answer stays UNKNOWN.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from confiture.core.schema_model import Signature

__all__ = [
    "SqlType",
    "TypeChange",
    "canonical_type",
    "catalog_spelling",
    "changes_rewrite_table",
    "compare_types",
    "parse_type",
    "same_type",
    "signature_from_type_names",
    "signature_type",
    "signatures_match",
    "types_match",
]


class TypeChange(Enum):
    """The direction of a column type change."""

    IDENTICAL = "identical"
    """The same type. Nothing to reason about."""

    WIDENING = "widening"
    """Every value of the old type is representable in the new one."""

    NARROWING = "narrowing"
    """Values can be lost, truncated, or rejected outright."""

    LATERAL = "lateral"
    """Same family or cross-family with a meaning change, not a pure width move."""

    UNKNOWN = "unknown"
    """A type confiture does not model, or a missing side. Never treated as safe."""


@dataclass(frozen=True)
class SqlType:
    """A parsed SQL type name with its typmod and array depth, canonically spelled.

    ``dimensions`` is how many ``[]`` the type carries. It is part of the type's
    identity, not decoration: ``text`` and ``text[]`` share a name and nothing
    else, and a lattice that dropped the suffix answered ``IDENTICAL`` for a
    change that rewrites every page.
    """

    name: str
    precision: int | None = None
    scale: int | None = None
    dimensions: int = 0


# Aliases → the canonical name used throughout the lattice.
_ALIASES = {
    "int": "integer",
    "int4": "integer",
    "int2": "smallint",
    "int8": "bigint",
    "serial": "integer",
    "bigserial": "bigint",
    "smallserial": "smallint",
    "bool": "boolean",
    "character varying": "varchar",
    "character": "char",
    "bpchar": "char",
    "decimal": "numeric",
    "float4": "real",
    "float8": "double precision",
    "double": "double precision",
    "timestamp without time zone": "timestamp",
    "timestamp with time zone": "timestamptz",
    "time without time zone": "time",
    "time with time zone": "timetz",
    "varbit": "bit varying",
}

#: Spellings PostgreSQL gives an implicit length of 1: ``char`` *is* ``char(1)``,
#: and ``format_type`` renders the column back as ``character(1)``. ``bpchar``
#: without a length is deliberately absent — measured on PostgreSQL 18.4, a bare
#: ``bpchar`` comes back as ``bpchar``, which is the unlimited internal variant
#: and a different type.
_IMPLICIT_LENGTH_ONE = frozenset({"char", "character"})

# Ordered families: a later member represents every value of an earlier one.
_INTEGER_WIDTHS = {"smallint": 16, "integer": 32, "bigint": 64}
_FLOAT_WIDTHS = {"real": 24, "double precision": 53}
_TEMPORAL_WIDTHS = {"date": 1, "timestamp": 2}

_EXACT_NUMERIC = frozenset({*_INTEGER_WIDTHS, "numeric"})
_STRING = frozenset({"varchar", "text", "char"})

#: ``NAME [(typmod)] [TAIL] [arrays]``. The ``TAIL`` is what ``format_type``
#: writes *after* the typmod — ``timestamp(3) without time zone``. A regex that
#: expects the typmod last cannot read that live spelling: the whole value falls
#: through unparsed and lower-cased.
#:
#: The tail needs the whitespace in front of it. Without it the non-greedy
#: ``name`` splits a single word — ``serial`` into ``s`` + ``erial`` — and every
#: one-word type stops resolving.
_TYPE_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z_][\w ]*?)\s*(?:\(\s*(?P<p>\d+)\s*(?:,\s*(?P<s>\d+)\s*)?\))?\s*"
    r"(?:\s+(?P<tail>[A-Za-z][A-Za-z ]*?))?\s*"
    r"(?P<arr>(?:\[\s*\d*\s*\])*)\s*$"
)


def parse_type(raw: str | None) -> SqlType | None:
    """Parse ``varchar(50)`` / ``numeric(10,2)`` / ``bigint`` into a :class:`SqlType`.

    Returns ``None`` when ``raw`` is empty or not a plain type reference.
    """
    if not raw:
        return None
    match = _TYPE_RE.match(raw)
    if not match:
        return None
    written = " ".join(part for part in (match.group("name"), match.group("tail")) if part)
    written = re.sub(r"\s+", " ", written).strip().lower()
    name = _ALIASES.get(written, written)
    precision = int(match.group("p")) if match.group("p") else None
    if precision is None and written in _IMPLICIT_LENGTH_ONE:
        # PostgreSQL's own default, and what `format_type` reports back.
        precision = 1
    scale = int(match.group("s")) if match.group("s") else None
    if written == "float":
        # SQL's `float(p)` is a precision in *bits*: up to 24 is `real`, and a bare
        # `float` or anything wider is `double precision` — PostgreSQL's rule. The
        # parser folds it for DDL; text a person writes (a precondition) does not.
        narrow = precision is not None and precision <= _FLOAT_WIDTHS["real"]
        name, precision = ("real" if narrow else "double precision"), None
    return SqlType(
        name=name,
        precision=precision,
        scale=scale,
        dimensions=(match.group("arr") or "").count("["),
    )


def compare_types(old: str | None, new: str | None) -> TypeChange:
    """The semantic direction of ``old`` → ``new``.

    Either side missing yields :attr:`TypeChange.UNKNOWN`: the old type is not in
    the SQL, and a missing side must never read as safe.
    """
    old_type, new_type = parse_type(old), parse_type(new)
    if old_type is None or new_type is None:
        return TypeChange.UNKNOWN
    if old_type == new_type:
        return TypeChange.IDENTICAL
    if old_type.dimensions or new_type.dimensions:
        # Equal arrays are IDENTICAL above. Anything else involving one —
        # element to array, array to element, one dimension to two, or two
        # different element types — is a conversion this module does not model,
        # and an unmodelled change never reads as safe.
        return TypeChange.UNKNOWN
    if not _is_modelled(old_type) or not _is_modelled(new_type):
        return TypeChange.UNKNOWN
    if old_type.name == new_type.name:
        return _same_name(old_type, new_type)
    return _cross_name(old_type, new_type)


def _is_modelled(sql_type: SqlType) -> bool:
    return (
        sql_type.name in _EXACT_NUMERIC
        or sql_type.name in _FLOAT_WIDTHS
        or sql_type.name in _STRING
        or sql_type.name in _TEMPORAL_WIDTHS
        or sql_type.name == "timestamptz"
    )


def _same_name(old: SqlType, new: SqlType) -> TypeChange:
    """Same type name, different typmod."""
    if old.name in {"varchar", "char"}:
        return _compare_lengths(old.precision, new.precision)
    if old.name == "numeric":
        return _compare_numeric(old, new)
    return TypeChange.IDENTICAL


def _compare_lengths(old_len: int | None, new_len: int | None) -> TypeChange:
    """``None`` length is unconstrained — the widest a string type can be."""
    if old_len == new_len:
        return TypeChange.IDENTICAL
    if old_len is None:
        return TypeChange.NARROWING  # unconstrained → constrained
    if new_len is None:
        return TypeChange.WIDENING  # constrained → unconstrained
    return TypeChange.WIDENING if new_len > old_len else TypeChange.NARROWING


def _compare_numeric(old: SqlType, new: SqlType) -> TypeChange:
    """`numeric(p,s)` widens when both the scale and the integral digits grow."""
    if old.precision is None:
        # Unconstrained numeric holds more than any constrained one.
        return TypeChange.IDENTICAL if new.precision is None else TypeChange.NARROWING
    if new.precision is None:
        return TypeChange.WIDENING
    old_scale, new_scale = old.scale or 0, new.scale or 0
    old_integral = old.precision - old_scale
    new_integral = new.precision - new_scale
    if new_scale >= old_scale and new_integral >= old_integral:
        return TypeChange.WIDENING
    return TypeChange.NARROWING


def _cross_name(old: SqlType, new: SqlType) -> TypeChange:
    """Different type names."""
    # Integers and numeric form one exact-numeric ladder.
    if old.name in _EXACT_NUMERIC and new.name in _EXACT_NUMERIC:
        if old.name in _INTEGER_WIDTHS and new.name in _INTEGER_WIDTHS:
            return (
                TypeChange.WIDENING
                if _INTEGER_WIDTHS[new.name] > _INTEGER_WIDTHS[old.name]
                else TypeChange.NARROWING
            )
        # numeric holds any integer; the reverse loses the fractional part.
        return TypeChange.NARROWING if new.name in _INTEGER_WIDTHS else TypeChange.WIDENING
    if old.name in _FLOAT_WIDTHS and new.name in _FLOAT_WIDTHS:
        return (
            TypeChange.WIDENING
            if _FLOAT_WIDTHS[new.name] > _FLOAT_WIDTHS[old.name]
            else TypeChange.NARROWING
        )
    if old.name in _STRING and new.name in _STRING:
        return _compare_lengths(_string_length(old), _string_length(new))
    if old.name in _TEMPORAL_WIDTHS and new.name in _TEMPORAL_WIDTHS:
        return (
            TypeChange.WIDENING
            if _TEMPORAL_WIDTHS[new.name] > _TEMPORAL_WIDTHS[old.name]
            else TypeChange.NARROWING
        )
    # `timestamp` ↔ `timestamptz` reinterprets every stored value against the
    # session time zone. Not a width move in either direction.
    if {old.name, new.name} <= {"timestamp", "timestamptz", "date"}:
        return TypeChange.LATERAL
    return TypeChange.LATERAL


def _string_length(sql_type: SqlType) -> int | None:
    """`text` is unconstrained; `varchar`/`char` carry their declared length."""
    return None if sql_type.name == "text" else sql_type.precision


# The binary-coercible cases PostgreSQL documents as skipping the heap rewrite.
# Deliberately short: an unlisted pair rewrites.
def changes_rewrite_table(old: str | None, new: str | None) -> bool:
    """Whether PostgreSQL rewrites the heap for ``old`` → ``new``.

    ``True`` whenever confiture cannot prove otherwise, including for an unknown
    or missing type.
    """
    old_type, new_type = parse_type(old), parse_type(new)
    if old_type is None or new_type is None:
        return True
    if old_type == new_type:
        return False
    if old_type.dimensions or new_type.dimensions:
        # The binary-coercible cases below are between scalars. `varchar[]` to
        # `text[]` is not one of them, whatever `varchar` to `text` costs.
        return True
    # varchar(n) → varchar(m>n) and varchar/char → text are binary coercible.
    if old_type.name in {"varchar", "char"} and new_type.name == "text":
        return False
    return not (
        old_type.name == new_type.name == "varchar"
        and _compare_lengths(old_type.precision, new_type.precision) is TypeChange.WIDENING
    )


def canonical_type(raw: str | None) -> str | None:
    """The canonical spelling of ``raw`` — aliases resolved, typmod normalised.

    pglast reports PostgreSQL's internal names (``int8``) while the regex backend
    reports what the migration author wrote (``bigint``). Both classifiers run
    the captured type through this so the two backends stay byte-identical, which
    ``test_pglast_and_regex_agree`` requires. An unparseable type is returned
    lowercased rather than dropped.

    That lower-casing folds a quoted user type into an unquoted one: a type
    created as ``"MyType"`` canonicalises to ``mytype`` and keys the same as a
    distinct ``mytype``. pglast's ``sval`` does not record whether the
    identifier was quoted, so the two cannot be told apart here. Accepted, and
    pinned by ``TestAQuotedTypeNameFoldsWithAnUnquotedOne`` so it stays a
    choice rather than becoming a surprise.
    """
    parsed = parse_type(raw)
    if parsed is None:
        return raw.strip().lower() or None if raw else None
    suffix = "[]" * parsed.dimensions
    if parsed.precision is None:
        return parsed.name + suffix
    if parsed.scale is None:
        return f"{parsed.name}({parsed.precision}){suffix}"
    return f"{parsed.name}({parsed.precision},{parsed.scale}){suffix}"


def same_type(written: str | None, other: str | None) -> bool:
    """Whether two spellings name one type — the drift comparison's predicate.

    Both sides are canonicalised, so ``bigserial`` meets ``bigint`` and
    ``varchar(50)`` meets ``character varying(50)``. On top of that, **a schema
    written on one side and left off the other matches**: ``format_type`` omits a
    schema that is visible through ``search_path``, so a DDL that spelled
    ``public.citext`` meets a live ``citext``. Two schemas that both say
    something and disagree are two types — ``app.custom_t`` and
    ``other.custom_t`` (D9).

    That wildcard is the rule
    :func:`confiture.core.linting.inventory.types_match` applies to a routine's
    argument types, and the two are deliberately not one function: a signature
    drops typmods, because PostgreSQL ignores them there, and a **column** type
    must keep them or ``varchar(50)`` and ``varchar(100)`` compare equal. One
    rule, two questions.

    A missing side is never a match: nothing is known, so nothing is claimed.
    """
    if not written or not other:
        return False
    left, right = _schema_and_type(written), _schema_and_type(other)
    if left[1] != right[1]:
        return False
    return left[0] is None or right[0] is None or left[0] == right[0]


def _schema_and_type(written: str) -> tuple[str | None, str | None]:
    """``(schema, canonical type)``; the ``pg_catalog`` qualifier is the parser's."""
    schema, _, name = written.strip().rpartition(".")
    schema = schema.strip().lower() or None
    return (None if schema == _CATALOG_SCHEMA else schema), canonical_type(name)


#: No user schema can be called this — the ``pg_`` prefix is reserved — so the
#: qualifier is always the parser's rather than something the author wrote.
_CATALOG_SCHEMA = "pg_catalog"


# ---------------------------------------------------------------------------
# A routine's signature: the argument types a call is resolved by
# ---------------------------------------------------------------------------


def signature_type(written: str) -> str:
    """One argument type's canonical name, as a routine's signature holds it.

    :func:`canonical_type`'s name, with what a signature does not have taken off:
    a typmod — ``character`` is ``bpchar`` whatever its implicit length, and
    PostgreSQL ignores a typmod in a signature anyway — and every array
    dimension past the first, since PostgreSQL does not record how many a type
    was written with (``text[][]`` is ``text[]``).
    """
    parsed = parse_type(written)
    if parsed is None:
        return canonical_type(written) or written
    base = parsed.name
    if written.partition("[")[0].strip() == _ONE_BYTE_CHAR:
        base = f'"{_ONE_BYTE_CHAR}"'
    return base + ("[]" if parsed.dimensions else "")


#: A bare ``char`` in a signature is PostgreSQL's internal one-byte type, never the
#: keyword: the parser reads the keyword as ``bpchar`` and ``format_type`` writes it
#: ``character``, but writes this one quoted. It keeps its quotes, so a routine
#: taking it is never mistaken for one taking ``character``.
_ONE_BYTE_CHAR = "char"


def signature_from_type_names(written: Iterable[str]) -> Signature:
    """A routine's signature from its argument types spelled as *text*.

    A ``DROP FUNCTION f(bigint)`` names its arguments as text, and so does a live
    catalogue (``format_type``); the DDL's parse nodes are read by
    ``inventory.type_key``, through :func:`signature_type` too, so there is one
    idea of what makes two routines the same routine (#275). A quoted identifier
    loses its quotes, which the DDL's parser has already dropped, and the
    ``pg_catalog`` qualifier is the parser's, never the author's.
    """
    return tuple(_argument_key(name) for name in written)


def _argument_key(written: str) -> tuple[str | None, str]:
    schema, _, name = written.rpartition(".")
    schema = schema.replace('"', "")
    return (
        None if not schema or schema == _CATALOG_SCHEMA else schema,
        signature_type(name.replace('"', "")),
    )


def types_match(a: tuple[str | None, str], b: tuple[str | None, str]) -> bool:
    """Whether two argument types, as each side spelled them, are one type.

    The names must agree exactly — they are canonical by then, and the array
    suffix is part of the name — but a schema written on one side and left off
    the other matches, because PostgreSQL resolves the bare spelling through
    ``search_path`` and lands on the same type. Two schemas that are both
    present and disagree never match: ``app.custom_t`` and ``other.custom_t``
    are two types (D9).
    """
    if a[1] != b[1]:
        return False
    return a[0] is None or b[0] is None or a[0] == b[0]


def signatures_match(a: Signature | None, b: Signature | None) -> bool:
    """Whether two canonical signatures name one routine, argument by argument.

    ``None`` is not a signature but the absence of one — every kind that is not
    a routine — so it matches only itself and never an empty argument list.
    """
    if a is None or b is None:
        return a is None and b is None
    if len(a) != len(b):
        return False
    return all(types_match(x, y) for x, y in zip(a, b, strict=True))


#: The SQL-standard spellings ``format_type`` prints where the canonical name is
#: another word. Each is already an alias in the table above, pointing at its
#: canonical name; this says which alias is the catalogue's own word, and the
#: direction back is read from that table rather than written out a second time.
_CATALOG_WORDS = frozenset(
    {
        "character varying",
        "character",
        "timestamp without time zone",
        "timestamp with time zone",
        "time without time zone",
        "time with time zone",
    }
)
_SPELLED_BY_CATALOG = {
    canonical: spelling for spelling, canonical in _ALIASES.items() if spelling in _CATALOG_WORDS
}


def catalog_spelling(name: str) -> str:
    """How PostgreSQL's ``format_type`` spells a canonical argument type name.

    ``varchar`` is ``character varying``, ``timestamptz`` is ``timestamp with time
    zone``, ``char`` is ``character``; every other canonical name is already the
    catalogue's word. The spelling a report prints for a routine's argument, so
    one routine read from DDL and read live is printed once and not twice.
    """
    base, array = (name[:-2], "[]") if name.endswith("[]") else (name, "")
    return _SPELLED_BY_CATALOG.get(base, base) + array
