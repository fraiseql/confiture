"""``sec_003``: a credential written as a literal in the tree (#427).

``sec_001`` reads column *names*: a column named for a secret should not hold one
in plain text. This reads the *values*: a password committed in a seed file is in
git history, in every developer's database and in every environment that applies
the seed — and it is there before any build that would ship it has run, so the
check reads the source tree, not a bundle.

The rows come from the one seed reader
(:func:`~confiture.core.seed.validation.prep_seed.seed_rows.read_seed_statements`:
``INSERT … VALUES`` from the parse tree, ``COPY`` rows decoded); an assignment from
``UPDATE … SET`` or ``INSERT … ON CONFLICT DO UPDATE SET``, and a role's password
from ``CREATE``/``ALTER ROLE``, are read from PostgreSQL's own parse tree (#658). A comment is not
a statement, so a documented example is never read. A value is reported when it
sits in a column named for a secret (``sec_001``'s own table), or in a column
named for a key and it looks like one (long, high-entropy, not a UUID) — and it is
neither a hash (the point is plaintext) nor an obvious placeholder.

A finding never repeats the secret: it says what kind of value and how long, and
names the row by another of its columns, so a baseline can hold it without the
value ever reaching a CI log.
"""

import math
import re
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pglast
import pglast.parser
from pglast import ast

from confiture.core._pglast_enums import member as _pg_member
from confiture.core.ddl_walk import enum_int
from confiture.core.parser_info import ascii_shadow
from confiture.core.schema_identity import contains_words
from confiture.core.sql_lexer import parse_file, skip_leading_comments

if TYPE_CHECKING:
    from confiture.core.seed.validation.prep_seed.seed_rows import SeedWrite, Value

#: The words of a column name that say it holds a credential, and what the
#: finding calls it — ``sec_001`` flags the column, ``sec_003`` a literal written
#: into it. One table for both rules, matched by whole words
#: (``schema_identity.contains_words``), so ``smtp_passwd`` holds a password and
#: ``tokenizer`` no token. The first entry that matches names the kind.
CREDENTIAL_NAMES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("password",), "password"),
    (("passwd",), "password"),
    (("pwd",), "password"),
    (("passphrase",), "password"),
    (("credential",), "credential"),
    (("credentials",), "credential"),
    (("api", "key"), "API key"),
    (("apikey",), "API key"),
    (("secret",), "secret"),
    (("token",), "token"),
)

#: The words of a column name that say it holds personal data: not a credential,
#: and a leak all the same when a seed commits a real one.
PERSONAL_NAMES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("credit", "card"), "credit card"),
    (("card", "number"), "card number"),
    (("ssn",), "social security number"),
    (("iban",), "IBAN"),
)

#: A column named for a key — ``signing_key``, but also ``sort_key`` — holds a
#: secret only when its value looks like one.
_KEY_WORD = ("key",)
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
#: The words that say a value stands in for one: ``'PLACEHOLDER-not-a-real-credential'``,
#: ``'test_password'``, ``'my-example-secret'``. Matched as whole words, so
#: ``'contest-winner'`` holds no ``test``.
_PLACEHOLDER_WORDS: tuple[tuple[str, ...], ...] = (
    ("placeholder",),
    ("changeme",),
    ("change", "me"),
    ("example",),
    ("dummy",),
    ("fake",),
    ("redacted",),
    ("sample",),
    ("todo",),
    ("test",),
    ("xxx",),
    ("not", "a", "secret"),
)
_AND_EXPR = _pg_member("BoolExprType", "AND_EXPR")
_AEXPR_OP = _pg_member("A_Expr_Kind", "AEXPR_OP")
_ONCONFLICT_UPDATE = _pg_member("OnConflictAction", "ONCONFLICT_UPDATE")
_UUID = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$", re.IGNORECASE)


@dataclass(frozen=True)
class SecretFinding:
    """A credential literal: where it is, which value, what kind — never the value."""

    line: int
    subject: str
    kind: str
    length: int
    #: Personal data rather than a credential (``PERSONAL_NAMES``).
    personal: bool = False


def secret_kinds(column: str) -> tuple[str, ...]:
    """Every kind of sensitive value *column*'s name says it holds, credentials first."""
    found: list[str] = []
    for words, kind in (*CREDENTIAL_NAMES, *PERSONAL_NAMES):
        if contains_words(column, words) and kind not in found:
            found.append(kind)
    return tuple(found)


def secret_kind(column: str) -> str | None:
    """What *column*'s name says it holds, when it names a sensitive value; ``None`` otherwise."""
    kinds = secret_kinds(column)
    return kinds[0] if kinds else None


def is_personal(kind: str) -> bool:
    """Whether *kind* is personal data rather than a credential."""
    return kind in {kind for _words, kind in PERSONAL_NAMES}


def is_placeholder(value: str) -> bool:
    """An empty value, one repeated character, a template, or a word that says so."""
    text = value.strip()
    if not text or len(set(text)) == 1:
        return True
    templated = any(text.startswith(o) and text.endswith(c) for o, c in _TEMPLATE_BRACKETS)
    return templated or any(contains_words(text, words) for words in _PLACEHOLDER_WORDS)


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


def _names_a_secret(column: str, value: str) -> bool:
    """Whether naming a row by *column* = *value* could repeat a secret (#463)."""
    return bool(secret_kind(column) or contains_words(column, _KEY_WORD) or looks_like_a_key(value))


def _value_finding(
    column: str, value: Value, line: int, table: str, label: str
) -> SecretFinding | None:
    """The finding for *value* written into *column*, when it is a credential literal."""
    kind = secret_kind(column)
    keyed = kind is None and contains_words(column, _KEY_WORD)
    if kind is None and not keyed:
        return None
    text = _plaintext(value)
    if text is None or (keyed and not looks_like_a_key(text)):
        return None
    return SecretFinding(
        line=line,
        subject=f"{table}.{column}[{label}]",
        kind=kind or "key",
        length=len(text),
        personal=kind is not None and is_personal(kind),
    )


def _row_label(columns: tuple[str, ...], values: tuple[Any, ...], secret: int, number: int) -> str:
    """The row, named by its first other literal column — a key, typically.

    Never by a column this rule reads for secrets, nor by a value shaped like a
    key: a label that could be another secret would repeat it (#463).
    """
    for index, (column, value) in enumerate(zip(columns, values, strict=False)):
        if index == secret or not isinstance(value, str) or not value:
            continue
        if _names_a_secret(column, value):
            continue
        return f"{column}={value}"
    return f"row {number}"


def _write_findings(
    write: SeedWrite, table_columns: Callable[[str | None, str], tuple[str, ...] | None]
) -> Iterator[SecretFinding]:
    columns = write.columns or table_columns(write.schema, write.table)
    if not columns:
        return
    for index, column in enumerate(columns):
        for row in write.rows:
            if index >= len(row.values):
                continue
            label = _row_label(columns, row.values, index, row.number)
            found = _value_finding(column, row.values[index], row.line, write.qualified, label)
            if found is not None:
                yield found


def _conjuncts(node: Any) -> Iterator[Any]:
    """The terms of a ``WHERE``'s top-level ``AND``, nested ``AND`` flattened."""
    if isinstance(node, ast.BoolExpr) and enum_int(node.boolop) == _AND_EXPR:
        for arg in node.args or ():
            yield from _conjuncts(arg)
    elif node is not None:
        yield node


def _where_key(where: Any, constant: Callable[[Any], Value]) -> str | None:
    """``column=value`` from the first ``column = constant`` conjunct that names no secret."""
    for term in _conjuncts(where):
        if (
            not isinstance(term, ast.A_Expr)
            or enum_int(term.kind) != _AEXPR_OP
            or [n.sval for n in term.name or ()] != ["="]
        ):
            continue
        for ref, other in ((term.lexpr, term.rexpr), (term.rexpr, term.lexpr)):
            if not isinstance(ref, ast.ColumnRef) or not isinstance(ref.fields[-1], ast.String):
                continue
            value = constant(other)
            column = ref.fields[-1].sval
            if isinstance(value, str) and value and not _names_a_secret(column, value):
                return f"{column}={value}"
    return None


def _assigned(target: Any) -> Any:
    """The expression a ``SET`` target receives, ``SET (a, b) = (…)`` read per column."""
    val = target.val
    if isinstance(val, ast.MultiAssignRef):
        source = val.source
        if isinstance(source, ast.RowExpr) and val.colno <= len(source.args or ()):
            return source.args[val.colno - 1]
        return source
    return val


def _assignments(stmt: Any) -> tuple[Any, tuple[Any, ...], Any] | None:
    """The table, ``SET`` targets and ``WHERE`` of an ``UPDATE`` or ``ON CONFLICT DO UPDATE``."""
    if isinstance(stmt, ast.UpdateStmt):
        return stmt.relation, tuple(stmt.targetList or ()), stmt.whereClause
    conflict = stmt.onConflictClause if isinstance(stmt, ast.InsertStmt) else None
    if conflict is not None and enum_int(conflict.action) == _ONCONFLICT_UPDATE:
        return stmt.relation, tuple(conflict.targetList or ()), conflict.whereClause
    return None


def _assignment_findings(
    stmt: Any, line: int, constant: Callable[[Any], Value]
) -> Iterator[SecretFinding]:
    """A credential literal a ``SET`` writes, the row named by its ``WHERE`` key or its line."""
    read = _assignments(stmt)
    if read is None:
        return
    relation, targets, where = read
    table = f"{relation.schemaname}.{relation.relname}" if relation.schemaname else relation.relname
    label = _where_key(where, constant) or f"line {line}"
    for target in targets:
        found = _value_finding(target.name, constant(_assigned(target)), line, table, label)
        if found is not None:
            yield found


def _role_finding(stmt: Any, line: int) -> SecretFinding | None:
    """``CREATE``/``ALTER ROLE … PASSWORD '<literal>'``."""
    if not isinstance(stmt, ast.CreateRoleStmt | ast.AlterRoleStmt):
        return None
    for option in stmt.options or ():
        if option.defname != "password" or option.arg is None:
            continue
        value = _plaintext(getattr(option.arg, "sval", None))
        if value is None:
            continue
        if isinstance(stmt, ast.CreateRoleStmt):
            role = stmt.role
        else:
            role = stmt.role.rolename if stmt.role is not None else "?"
        return SecretFinding(line=line, subject=f"role {role}", kind="password", length=len(value))
    return None


def _statement_findings(sql: str, constant: Callable[[Any], Value]) -> Iterator[SecretFinding]:
    """What a statement's parse tree writes: ``SET`` assignments and role passwords.

    The shadow keeps offsets honest.
    """
    shadow = ascii_shadow(sql)
    try:
        raws = parse_file(shadow).statements
    except pglast.parser.ParseError:
        return
    for raw in raws or ():
        line = shadow.count("\n", 0, skip_leading_comments(shadow, raw.stmt_location)) + 1
        yield from _assignment_findings(raw.stmt, line, constant)
        role = _role_finding(raw.stmt, line)
        if role is not None:
            yield role


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
        constant,
        read_seed_statements,
    )

    try:
        statements = read_seed_statements(sql)
    except SeedParseError:
        return []
    found = [f for write in statements.writes for f in _write_findings(write, table_columns)]
    found.extend(_statement_findings(sql, constant))
    return sorted(found, key=lambda f: (f.line, f.subject))
