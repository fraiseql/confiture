"""Is an `ALTER COLUMN … TYPE` widening or narrowing (issue #199)?

`bigint`→`integer` silently loses data or aborts mid-migration; `integer`→`bigint`
cannot. `ChangeColumnType` carried only the table and column, so preflight had to
treat both alike — and, having no honest answer, emitted no risk tier at all.

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
from dataclasses import dataclass
from enum import Enum

__all__ = [
    "SqlType",
    "canonical_type",
    "TypeChange",
    "changes_rewrite_table",
    "compare_types",
    "parse_type",
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
    """A parsed SQL type name with its typmod, normalised to a canonical spelling."""

    name: str
    precision: int | None = None
    scale: int | None = None


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
}

# Ordered families: a later member represents every value of an earlier one.
_INTEGER_WIDTHS = {"smallint": 16, "integer": 32, "bigint": 64}
_FLOAT_WIDTHS = {"real": 24, "double precision": 53}
_TEMPORAL_WIDTHS = {"date": 1, "timestamp": 2}

_EXACT_NUMERIC = frozenset({*_INTEGER_WIDTHS, "numeric"})
_STRING = frozenset({"varchar", "text", "char"})

_TYPE_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z_][\w ]*?)\s*(?:\(\s*(?P<p>\d+)\s*(?:,\s*(?P<s>\d+)\s*)?\))?\s*"
    r"(?:\[\s*\])?\s*$"
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
    name = re.sub(r"\s+", " ", match.group("name")).strip().lower()
    name = _ALIASES.get(name, name)
    precision = int(match.group("p")) if match.group("p") else None
    scale = int(match.group("s")) if match.group("s") else None
    return SqlType(name=name, precision=precision, scale=scale)


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
    """
    parsed = parse_type(raw)
    if parsed is None:
        return raw.strip().lower() or None if raw else None
    if parsed.precision is None:
        return parsed.name
    if parsed.scale is None:
        return f"{parsed.name}({parsed.precision})"
    return f"{parsed.name}({parsed.precision},{parsed.scale})"
