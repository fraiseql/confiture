"""``sec_003``: a credential written as a literal in the tree (#427).

``sec_001`` reads column *names*: a column named for a secret should not hold one
in plain text. This reads the *values*: a password committed in a seed file is in
git history, in every developer's database and in every environment that applies
the seed — and it is there before any build that would ship it has run, so the
check reads the source tree, not a bundle.

The rows come from the one seed reader
(:func:`~confiture.core.seed.validation.prep_seed.seed_rows.read_seed_statements`:
``INSERT … VALUES`` from the parse tree, ``COPY`` rows decoded), a role's password
from ``CREATE``/``ALTER ROLE`` parsed by PostgreSQL's own parser. A comment is not
a statement, so a documented example is never read. A value is reported when it
sits in a column named for a secret (``sec_001``'s own table), or in a column
named for a key and it looks like one (long, high-entropy, not a UUID) — and it is
neither a hash (the point is plaintext) nor an obvious placeholder.

A finding never repeats the secret: it says what kind of value and how long, and
names the row by another of its columns, so a baseline can hold it without the
value ever reaching a CI log.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pglast
import pglast.parser
from pglast import ast

from confiture.core.parser_info import ascii_shadow
from confiture.core.sql_lexer import blank_copy_blocks, skip_leading_comments

if TYPE_CHECKING:
    from confiture.core.seed.validation.prep_seed.seed_rows import SeedWrite

#: Column names that say "secret", and what each says — ``sec_001`` flags the
#: column, ``sec_003`` a literal written into it. One table for both rules.
SECRET_COLUMN_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"password", "password"),
    (r"token", "token"),
    (r"secret", "secret"),
    (r"api_key", "API key"),
    (r"credit_card", "credit card"),
    (r"ssn", "social security number"),
)

#: A column named for a key — ``signing_key``, but also ``sort_key`` — holds a
#: secret only when its value looks like one.
_KEY_COLUMN = re.compile(r"key", re.IGNORECASE)
_KEY_MIN_LENGTH = 16
_KEY_MIN_ENTROPY = 3.5  # bits per character

#: Password-hash formats, by the prefix each writes: what a column is meant to hold
#: instead of plaintext. Compared case-insensitively.
_HASH_PREFIXES = (
    "$2a$",
    "$2b$",
    "$2x$",
    "$2y$",  # bcrypt
    "$argon2id$",
    "$argon2i$",
    "$argon2d$",
    "scram-sha-256$",  # PostgreSQL's own
    "$1$",
    "$5$",
    "$6$",
    "$9$",
    "$y$",  # crypt(3): md5, sha256, sha512, scrypt, yescrypt
    "$pbkdf2",
    "pbkdf2_sha1$",
    "pbkdf2_sha256$",
    "pbkdf2_sha512$",  # passlib, Django
    "{ssha}",
    "{sha}",
    "{ssha256}",
    "{ssha512}",
    "{sha256}",
    "{sha512}",  # LDAP
)
_MD5_HASH_LENGTH = len("md5") + 32
#: How a template marks a value it stands in for: ``<…>``, ``{{ … }}``, ``${…}``, ``%(…)s``.
_TEMPLATE_BRACKETS = (("<", ">"), ("{{", "}}"), ("${", "}"), ("%(", ")s"))
_PLACEHOLDER_WORDS = frozenset(
    {"changeme", "change_me", "change-me", "placeholder", "redacted", "example", "dummy", "todo"}
)
_UUID = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$", re.IGNORECASE)


@dataclass(frozen=True)
class SecretFinding:
    """A credential literal: where it is, which value, what kind — never the value."""

    line: int
    subject: str
    kind: str
    length: int


def secret_kind(column: str) -> str | None:
    """What *column*'s name says it holds, when it names a secret; ``None`` otherwise."""
    for pattern, kind in SECRET_COLUMN_PATTERNS:
        if re.search(pattern, column, re.IGNORECASE):
            return kind
    return None


def is_placeholder(value: str) -> bool:
    """An empty value, one repeated character, a template, or a word that says so."""
    text = value.strip()
    if not text or len(set(text)) == 1:
        return True
    templated = any(text.startswith(o) and text.endswith(c) for o, c in _TEMPLATE_BRACKETS)
    return templated or text.lower() in _PLACEHOLDER_WORDS


def is_hash(value: str) -> bool:
    """A password hash in one of the formats databases and frameworks store."""
    folded = value.strip().lower()
    if folded.startswith("md5") and len(folded) == _MD5_HASH_LENGTH:
        return all(c in "0123456789abcdef" for c in folded[3:])
    return folded.startswith(_HASH_PREFIXES)


def _entropy(value: str) -> float:
    counts = Counter(value)
    return -sum(n / len(value) * math.log2(n / len(value)) for n in counts.values())


def looks_like_a_key(value: str) -> bool:
    """Long and high-entropy, and not a UUID (an identifier, not a secret)."""
    return (
        len(value) >= _KEY_MIN_LENGTH
        and not _UUID.match(value)
        and _entropy(value) >= _KEY_MIN_ENTROPY
    )


def _plaintext(value: object) -> str | None:
    """*value* when it is a literal that could be a credential; ``None`` otherwise."""
    if not isinstance(value, str) or is_placeholder(value) or is_hash(value):
        return None
    return value


def _row_label(columns: tuple[str, ...], values: tuple[Any, ...], secret: int, number: int) -> str:
    """The row, named by its first other literal column — a key, typically."""
    for index, (column, value) in enumerate(zip(columns, values, strict=False)):
        if index != secret and isinstance(value, str) and value:
            return f"{column}={value}"
    return f"row {number}"


def _write_findings(
    write: SeedWrite, table_columns: Callable[[str | None, str], tuple[str, ...] | None]
) -> Iterator[SecretFinding]:
    columns = write.columns or table_columns(write.schema, write.table)
    if not columns:
        return
    for index, column in enumerate(columns):
        kind = secret_kind(column)
        keyed = kind is None and bool(_KEY_COLUMN.search(column))
        if kind is None and not keyed:
            continue
        for row in write.rows:
            if index >= len(row.values):
                continue
            value = _plaintext(row.values[index])
            if value is None or (keyed and not looks_like_a_key(value)):
                continue
            label = _row_label(columns, row.values, index, row.number)
            yield SecretFinding(
                line=row.line,
                subject=f"{write.qualified}.{column}[{label}]",
                kind=kind or "key",
                length=len(value),
            )


def _role_findings(sql: str) -> Iterator[SecretFinding]:
    """``CREATE``/``ALTER ROLE … PASSWORD '<literal>'`` — the shadow keeps offsets honest."""
    shadow = ascii_shadow(blank_copy_blocks(sql))
    try:
        raws = pglast.parser.parse_sql(shadow)
    except pglast.parser.ParseError:
        return
    for raw in raws or ():
        stmt = raw.stmt
        if not isinstance(stmt, ast.CreateRoleStmt | ast.AlterRoleStmt):
            continue
        for option in stmt.options or ():
            if option.defname != "password" or option.arg is None:
                continue
            literal = getattr(option.arg, "sval", None)
            value = _plaintext(literal)
            if value is None:
                continue
            if isinstance(stmt, ast.CreateRoleStmt):
                role = stmt.role
            else:
                role = stmt.role.rolename if stmt.role is not None else "?"
            start = skip_leading_comments(shadow, raw.stmt_location)
            yield SecretFinding(
                line=shadow.count("\n", 0, start) + 1,
                subject=f"role {role}",
                kind="password",
                length=len(value),
            )


def findings_in(
    sql: str, table_columns: Callable[[str | None, str], tuple[str, ...] | None]
) -> list[SecretFinding]:
    """Every credential literal *sql* writes, in file order.

    Args:
        sql: One file's text, as written — ``COPY`` rows included.
        table_columns: The column order of a table the tree declares, for an
            ``INSERT`` that names no columns; ``None`` when unknown.

    Returns:
        The findings; empty for a file PostgreSQL's parser rejects, which the
        lint reports on its own as ``UNPARSEABLE``.
    """
    # Reason: import cycle (the prep_seed package imports schema_sources → ddl_objects → linting.duplicates → the linter that imports this module)
    from confiture.core.seed.validation.prep_seed.seed_rows import (
        SeedParseError,
        read_seed_statements,
    )

    try:
        statements = read_seed_statements(sql)
    except SeedParseError:
        return []
    found = [f for write in statements.writes for f in _write_findings(write, table_columns)]
    found.extend(_role_findings(sql))
    return sorted(found, key=lambda f: (f.line, f.subject))
