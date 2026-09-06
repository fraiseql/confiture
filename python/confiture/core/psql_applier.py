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

**Meta-commands are refused.** ``psql`` executes backslash commands: ``\\!``
runs a shell command, ``\\copy … TO PROGRAM`` pipes data into one, ``\\i``
reads any file the operator can read. Schema and seed files are repository
content; the host running ``psql`` is not. :func:`reject_meta_commands` scans
the text the way ``psql``'s own lexer does — a backslash outside quotes,
comments, dollar-quoted bodies and ``COPY … FROM stdin`` data blocks is a
command wherever it sits on the line — and raises before ``psql`` is started.
The one tolerated backslash is a line consisting of ``\\.``, the COPY
terminator. The scan assumes ``standard_conforming_strings = on`` (the default
since PostgreSQL 9.1); with it off, ``psql`` would treat *more* text as string
literal than the scanner does, so the disagreement can only over-report.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from confiture.core.url_redaction import libpq_env, redact_url, split_password
from confiture.exceptions import SchemaError

# Matches an inline ``COPY … FROM stdin`` on a logical line (after comments are
# stripped). Server-side ``COPY … FROM '/path'`` has no ``stdin`` token and is
# intentionally not matched.
_COPY_FROM_STDIN_RE = re.compile(r"^\s*COPY\b.*\bFROM\s+stdin\b", re.IGNORECASE | re.MULTILINE)
# The statement-level form of the same test, applied to the code text of one
# statement (comments, literals and quoted identifiers already blanked) when the
# scanner reaches its terminating ``;`` — that is the moment ``psql`` switches to
# reading COPY data from the following lines.
_COPY_STDIN_STMT_RE = re.compile(r"^\s*COPY\b.*\bFROM\s+stdin\b", re.IGNORECASE | re.DOTALL)
# A dollar-quote opener: ``$$`` or ``$tag$`` where the tag is an identifier.
# ``$1`` (a positional parameter) has no closing ``$`` and does not match.
_DOLLAR_TAG_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$")
_COPY_TERMINATOR = "\\."

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

    Runs on the code text only — comments, string literals, quoted identifiers,
    dollar-quoted bodies and COPY data rows are blanked by :func:`code_text` —
    so the word ``copy``, or a whole ``COPY … FROM stdin`` line, inside a comment,
    a function body or a string does not trigger a false positive. Server-side
    ``COPY … FROM '/path'`` is not matched (it has no ``stdin`` token). This
    drives a hint, so it stays a per-line heuristic.

    Args:
        sql: SQL text to inspect.

    Returns:
        True if an inline COPY-from-stdin statement is present.
    """
    return bool(_COPY_FROM_STDIN_RE.search(code_text(sql)))


@dataclass(frozen=True)
class MetaCommand:
    """A ``psql`` backslash command found where ``psql`` would execute it.

    Attributes:
        line: 1-based line number in the scanned text.
        text: The offending line, stripped of surrounding whitespace.
    """

    line: int
    text: str


def find_meta_commands(sql: str) -> list[MetaCommand]:
    """Every backslash command ``psql`` would execute in *sql*, in order.

    A backslash in code text — outside quotes, comments, dollar-quoted bodies
    and ``COPY … FROM stdin`` data — starts a meta-command wherever it sits on
    the line (``SELECT 1 \\! id`` executes). A line consisting only of ``\\.``
    is tolerated: it is the COPY terminator shape and never a shell.

    Args:
        sql: SQL text to inspect.

    Returns:
        One :class:`MetaCommand` per offending line; empty when the text is clean.
    """
    found: list[MetaCommand] = []
    for number, (raw, code) in enumerate(
        zip(sql.split("\n"), code_text(sql).split("\n"), strict=True), start=1
    ):
        if "\\" not in code or code.strip() == _COPY_TERMINATOR:
            continue
        found.append(MetaCommand(line=number, text=raw.strip()))
    return found


def reject_meta_commands(sql: str, *, source: str | Path | None) -> None:
    """Raise :class:`SchemaError` if *sql* carries a ``psql`` meta-command.

    Args:
        sql: SQL text about to be handed to ``psql``.
        source: The file the text came from, for the error message; ``None``
            for inline SQL.

    Raises:
        SchemaError: ``SCHEMA_205``, naming the source and the first offending
            line, with up to five offending lines listed.
    """
    found = find_meta_commands(sql)
    if not found:
        return
    name = str(source) if source is not None else "<inline SQL>"
    first = found[0]
    listing = "\n".join(f"  line {m.line}: {m.text}" for m in found[:5])
    if len(found) > 5:
        listing += f"\n  … and {len(found) - 5} more"
    raise SchemaError(
        f"Refusing to apply {name}: psql meta-command at line {first.line} "
        f"({first.text}). psql executes backslash commands on this host — "
        "\\! runs a shell, \\copy … TO PROGRAM pipes into one, \\i reads any "
        f"file the operator can read.\n{listing}",
        error_code="SCHEMA_205",
        context={"file": name, "line": first.line, "command": first.text, "count": len(found)},
        resolution_hint=(
            "Remove the backslash commands; only SQL statements and inline "
            "COPY … FROM stdin data blocks are applied."
        ),
    )


# ---------------------------------------------------------------------------
# The scanner
# ---------------------------------------------------------------------------
#
# ``code_text`` is the one place that decides what is SQL and what is not. It
# is a line-oriented lexer with the same states as ``psql``'s: string literal
# (standard and ``E''``), quoted identifier, nested block comment, dollar-quoted
# body, and — after a ``COPY … FROM stdin;`` — a data block ending at a line
# that is exactly ``\.``. Line comments end with their line. The rest of a line
# after a COPY statement's ``;`` is still code (psql lexes it before it starts
# reading data), and the data block is skipped at the line level regardless of
# lexer state, exactly as psql consumes it from the input stream.

_NORMAL, _SQUOTE, _ESQUOTE, _DQUOTE, _BLOCK, _DOLLAR = range(6)


def _is_ident_char(c: str) -> bool:
    return c.isalnum() or c in "_$"


class _Lexer:
    """Lexer state that survives across lines."""

    def __init__(self) -> None:
        self.mode = _NORMAL
        self.depth = 0
        self.tag = ""
        self.stmt: list[str] = []

    def feed_line(self, line: str) -> tuple[str, int]:
        """Blank the non-code characters of *line*.

        Returns:
            The blanked line and how many ``COPY … FROM stdin`` statements were
            terminated on it (each one is followed by a data block).
        """
        out = [" "] * len(line)
        copies = 0
        i, n = 0, len(line)
        while i < n:
            c = line[i]
            if self.mode == _NORMAL:
                if line.startswith("--", i):
                    break
                if line.startswith("/*", i):
                    self.mode, self.depth = _BLOCK, 1
                    self.stmt.append(" ")
                    i += 2
                    continue
                if c == "'":
                    is_escape_string = (
                        i >= 1
                        and line[i - 1] in "eE"
                        and (i < 2 or not _is_ident_char(line[i - 2]))
                    )
                    self.mode = _ESQUOTE if is_escape_string else _SQUOTE
                    self.stmt.append(" ")
                    i += 1
                    continue
                if c == '"':
                    self.mode = _DQUOTE
                    self.stmt.append(" ")
                    i += 1
                    continue
                if c == "$" and (i == 0 or not _is_ident_char(line[i - 1])):
                    m = _DOLLAR_TAG_RE.match(line, i)
                    if m:
                        self.mode, self.tag = _DOLLAR, m.group(0)
                        self.stmt.append(" ")
                        i = m.end()
                        continue
                out[i] = c
                if c == ";":
                    if _COPY_STDIN_STMT_RE.match("".join(self.stmt)):
                        copies += 1
                    self.stmt = []
                else:
                    self.stmt.append(c)
                i += 1
            elif self.mode in (_SQUOTE, _ESQUOTE):
                if self.mode == _ESQUOTE and c == "\\":
                    i += 2
                    continue
                if c == "'":
                    if line.startswith("''", i):
                        i += 2
                        continue
                    self.mode = _NORMAL
                i += 1
            elif self.mode == _DQUOTE:
                if c == '"':
                    if line.startswith('""', i):
                        i += 2
                        continue
                    self.mode = _NORMAL
                i += 1
            elif self.mode == _BLOCK:
                if line.startswith("/*", i):
                    self.depth += 1
                    i += 2
                    continue
                if line.startswith("*/", i):
                    self.depth -= 1
                    if self.depth == 0:
                        self.mode = _NORMAL
                    i += 2
                    continue
                i += 1
            else:  # _DOLLAR
                if line.startswith(self.tag, i):
                    self.mode = _NORMAL
                    i += len(self.tag)
                    continue
                i += 1
        if self.mode == _NORMAL:
            self.stmt.append("\n")
        return "".join(out), copies


def code_text(sql: str) -> str:
    r"""*sql* with everything that is not SQL code blanked to spaces.

    Line structure is preserved exactly — the result has the same number of
    lines, each the same length — so a position in the output is a position in
    the input. Blanked: comments, string literals, quoted identifiers,
    dollar-quoted bodies and ``COPY … FROM stdin`` data rows (including the
    ``\.`` terminator). Kept: keywords, identifiers, operators, ``;`` and any
    backslash ``psql`` would execute.

    Args:
        sql: SQL text.

    Returns:
        The blanked text.
    """
    lexer = _Lexer()
    out: list[str] = []
    pending_copy_blocks = 0
    for raw in sql.split("\n"):
        if pending_copy_blocks:
            out.append(" " * len(raw))
            if raw.rstrip("\r") == _COPY_TERMINATOR:
                pending_copy_blocks -= 1
            continue
        code, copies = lexer.feed_line(raw)
        out.append(code)
        pending_copy_blocks += copies
    return "\n".join(out)


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
        SchemaError: ``SCHEMA_205`` if the SQL carries a ``psql`` meta-command
            (see :func:`reject_meta_commands`); otherwise if ``psql`` is not on
            PATH, or it exits non-zero. The URL is redacted and the last few
            stderr lines are included.
    """
    if (sql is None) == (sql_file is None):
        raise ValueError("apply_sql_via_psql requires exactly one of sql or sql_file.")

    reject_meta_commands(sql if sql is not None else _read_sql(sql_file), source=sql_file)

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


def _read_sql(sql_file: Path | None) -> str:
    """The text ``psql`` is about to read, for scanning; decode errors are replaced.

    A backslash is ASCII, so replacement characters cannot hide or invent one.
    """
    assert sql_file is not None  # guarded by the caller's exactly-one check
    try:
        return sql_file.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise SchemaError(
            f"Cannot read {sql_file}: {exc}",
            resolution_hint="Check that the file exists and is readable.",
        ) from exc


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
