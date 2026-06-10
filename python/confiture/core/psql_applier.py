"""Shared COPY-aware SQL applier backed by ``psql``.

psycopg's ``Connection.execute()`` runs the libpq simple/extended query protocol,
which cannot consume the inline data rows of a ``COPY <t> FROM stdin; … \\.``
block embedded in a SQL string — the first data row is parsed as SQL and raises a
syntax error. ``psql`` *can*, because its own lexer understands inline ``COPY``.

This module wraps ``psql`` so the ephemeral apply paths (the ``test-db
provision-template`` DDL path, ``build --dump`` schema apply, and ephemeral seed
loading) can provision COPY-bearing schemas and seeds natively. It is **not** used
by the long-lived interactive ``SeedApplier`` / ``confiture seed apply`` path.

Subprocess conventions mirror the sibling ``pg_dump`` / ``pg_restore`` wrappers:
an argv list (never ``shell=True``), the DSN passed via ``-d <url>``, SQL fed via
stdin (``-f -``) or ``-f <path>``, hardened with ``-X`` (ignore ``~/.psqlrc``),
``-q``, and ``-v ON_ERROR_STOP=1``. There is deliberately **no**
``--single-transaction``: this preserves the existing per-statement autocommit
semantics and avoids breaking any ``CREATE … CONCURRENTLY`` in schema files.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from confiture.core.url_redaction import libpq_env, redact_url, split_password
from confiture.exceptions import SchemaError

# Matches an inline ``COPY … FROM stdin`` on a logical line (after comments are
# stripped). Server-side ``COPY … FROM '/path'`` has no ``stdin`` token and is
# intentionally not matched.
_COPY_FROM_STDIN_RE = re.compile(r"^\s*COPY\b.*\bFROM\s+stdin\b", re.IGNORECASE | re.MULTILINE)
_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
# Dollar-quoted bodies ($tag$ … $tag$) and single-quoted literals ('' = escaped
# quote). Stripped before matching so COPY text inside a function body or a
# multi-line string literal does not trip the predicate.
_DOLLAR_QUOTED_RE = re.compile(r"\$(\w*)\$.*?\$\1\$", re.DOTALL)
_SINGLE_QUOTED_RE = re.compile(r"'(?:[^']|'')*'", re.DOTALL)

_MISSING_PSQL_BASE = (
    "psql is required to apply COPY-bearing schemas and seeds. "
    "Install postgresql-client (e.g. apt install postgresql-client)."
)
_MISSING_PSQL_COPY = (
    " This SQL contains an inline COPY … FROM stdin block; if psql cannot be "
    "installed, provision from a pg_dump artifact instead — build it with "
    "'confiture build --dump' and restore via "
    "'confiture test-db provision-template --from-artifact' (pg_restore, no psql)."
)


def contains_inline_copy(sql: str) -> bool:
    """Return True if *sql* contains an inline ``COPY … FROM stdin`` block.

    Comments (``--`` line and ``/* … */`` block), dollar-quoted bodies, and
    single-quoted string literals are stripped first so the word ``copy`` — or a
    whole ``COPY … FROM stdin`` line — inside a comment, a function body, or a
    string does not trigger a false positive. Server-side ``COPY … FROM '/path'``
    is not matched (it has no ``stdin`` token). This is a best-effort heuristic
    (it drives a hint), not a full SQL lexer.

    Args:
        sql: SQL text to inspect.

    Returns:
        True if an inline COPY-from-stdin statement is present.
    """
    stripped = _BLOCK_COMMENT_RE.sub(" ", sql)
    stripped = _LINE_COMMENT_RE.sub("", stripped)
    stripped = _DOLLAR_QUOTED_RE.sub(" ", stripped)
    stripped = _SINGLE_QUOTED_RE.sub(" ", stripped)
    return bool(_COPY_FROM_STDIN_RE.search(stripped))


def apply_sql_via_psql(
    connection_url: str,
    sql: str | None = None,
    *,
    sql_file: Path | None = None,
) -> None:
    """Apply *sql* (or the contents of *sql_file*) to a database via ``psql``.

    Exactly one of *sql* or *sql_file* must be given. Inline SQL is streamed on
    ``psql``'s stdin (``-f -``); a file is passed as ``-f <path>`` for better
    line numbers in error output. ``COPY … FROM stdin`` blocks apply correctly
    because ``psql`` (not psycopg) reads the data rows.

    Args:
        connection_url: Target database connection URL.
        sql: Inline SQL to apply (mutually exclusive with *sql_file*).
        sql_file: Path to a SQL file to apply (mutually exclusive with *sql*).

    Raises:
        ValueError: If not exactly one of *sql* / *sql_file* is provided.
        SchemaError: If ``psql`` is not on PATH, or it exits non-zero. The URL is
            redacted and the last few stderr lines are included.
    """
    if (sql is None) == (sql_file is None):
        raise ValueError("apply_sql_via_psql requires exactly one of sql or sql_file.")

    # Keep the password off argv (it would show in ``ps aux``); it rides in
    # ``PGPASSWORD`` via the env instead.
    safe_url, password = split_password(connection_url)
    source_arg = "-" if sql is not None else str(sql_file)
    argv = [
        "psql",
        "-X",
        "-q",
        "-v",
        "ON_ERROR_STOP=1",
        "-d",
        safe_url,
        "-f",
        source_arg,
    ]
    _run_psql(argv, connection_url, stdin=sql, source_for_hint=sql or sql_file, password=password)


def _run_psql(
    argv: list[str],
    connection_url: str,
    *,
    stdin: str | None,
    source_for_hint: str | Path | None,
    password: str | None,
) -> None:
    """Run *argv*, translating ``psql`` failures into :class:`SchemaError`.

    These are throwaway ephemeral databases, so ``synchronous_commit=off`` is set
    (durability we never observe) to speed large ``COPY`` loads, and the password
    is passed via ``PGPASSWORD`` rather than on argv.
    """
    env = libpq_env(password, extra_options="-c synchronous_commit=off")
    try:
        subprocess.run(argv, input=stdin, capture_output=True, text=True, check=True, env=env)
    except FileNotFoundError as exc:
        raise SchemaError(
            "psql not found on PATH.",
            resolution_hint=_missing_psql_hint(source_for_hint),
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        tail = "\n".join(stderr.splitlines()[-5:]) or "(no stderr output)"
        raise SchemaError(
            f"psql failed applying SQL to {redact_url(connection_url)}:\n{tail}",
            resolution_hint="Fix the failing statement reported by psql above.",
        ) from exc


def _missing_psql_hint(source_for_hint: str | Path | None) -> str:
    """Build the missing-``psql`` hint, naming ``--from-artifact`` if COPY is present."""
    sql_text: str | None
    if isinstance(source_for_hint, Path):
        try:
            sql_text = source_for_hint.read_text(encoding="utf-8")
        except OSError:
            sql_text = None
    else:
        sql_text = source_for_hint
    if sql_text and contains_inline_copy(sql_text):
        return _MISSING_PSQL_BASE + _MISSING_PSQL_COPY
    return _MISSING_PSQL_BASE
