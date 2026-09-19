"""A `RAISE EXCEPTION` guarded on data inside a migration, which `migrate preflight` cannot survive.

``confiture migrate preflight --against <dsn>`` replays every pending ``up()``
against what its own help twice recommends be a schema-only database, seeded
from ``pg_dump --schema-only``. Every table there is empty. So a migration that
reads a row count and raises on it aborts the preflight every time, however
correct the migration's actual work — and a deploy gated on the preflight
aborts with it. One backend lost two nightly staging restores to exactly that,
three days apart, under two different migrations' names.

The assertion is not wrong; it is in the wrong file. ``.verify.sql`` sidecars
run under ``migrate verify``, separately, after the migration is applied,
against the database that has the rows. See
``docs/guides/migration-verification.md``.

This detector is a **heuristic**, so what it reports is a warning and never a
gate failure. Being narrow is what makes it worth having: three things must all
hold before anything is reported.

1. A ``RAISE`` at ERROR level. ``RAISE NOTICE`` logs and carries on.
2. Reached from an ``IF`` whose condition reads a variable.
3. That variable assigned by a ``SELECT ... INTO`` over a **user relation**.

Condition 3 is the one that keeps this honest. A ``RAISE EXCEPTION`` guarded on
a ``pg_catalog`` or ``information_schema`` lookup is *correct* under a
schema-only preflight: the schema is present, so the query answers truthfully
and the guard does its job. Reporting it would be advising the author to break
a working check.

**A schema-only copy is not an empty database**, and that is where the residual
blind spot is. ``pg_dump --schema-only | psql`` leaves every *user* table empty
but populates the catalogue, so anything derived from it has rows. Relations
this migration builds from the catalogue are resolved (see
:func:`_derivations`) — but only within the text being read. A view in
``db/schema/`` or a table a previous migration created carries no derivation
here, so a correct guard over it is reported. That is the main false-positive
source, it is documented in ``docs/guides/migrate-validate.md``, and it is why
findings are warnings rather than gate failures.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from functools import cache
from pathlib import Path
from typing import Any

import pglast.parser

from confiture.core.plpgsql_parse import parse_body
from confiture.core.sql_lexer import split_statements, statement_type, tokens

#: Relation schemas whose contents exist on a schema-only database.
_SCHEMA_ONLY_SAFE = frozenset({"pg_catalog", "information_schema"})

_PROBE = (
    "CREATE FUNCTION confiture_elog_probe() RETURNS void LANGUAGE plpgsql AS $$\n"
    "BEGIN\n  {raise_stmt}\nEND $$;"
)


@dataclass(frozen=True)
class AssertionScan:
    """What one file's scan found, and whether it could be read at all.

    ``unparseable`` is not folded into an empty ``assertions`` list: a file
    pglast rejects is a *finding* in this repo, never a clean result
    (``IDEM_UNPARSEABLE``, ``PFLIGHT_UNPARSEABLE``, lint's ``UNPARSEABLE``).
    A heuristic warning cannot fail a gate, so what it owes the reader instead
    is to say the file was not analysed rather than to imply it was clean.
    """

    file: Path
    assertions: list[DataAssertion]
    unparseable: bool = False


@dataclass(frozen=True)
class DataAssertion:
    """One `RAISE EXCEPTION` guarded on a row count.

    Attributes:
        file: The migration file it was found in.
        line: Line of the ``RAISE``, not of the ``SELECT`` or the ``DECLARE``
            — it is the statement the author has to move.
        variable: The PL/pgSQL variable the guard reads.
        relation: The relation the count was taken over, as written.
        condition: The ``IF`` condition, as the compiler rendered it.
        message: The exception's message text, when it has a literal one.
    """

    file: Path
    line: int
    variable: str
    relation: str
    condition: str
    message: str | None = None


def _elog_level_of(raise_stmt: str) -> int | None:
    """The ``elog_level`` PostgreSQL's own compiler assigns to one RAISE.

    Asking rather than tabulating. ``elog_level`` is a server constant from
    ``elog.h``, and the lesson of #192 is that a literal ordinal for a
    PostgreSQL enum fails silently at the next major: ``_AT_DROP_COLUMN = 14``
    stopped matching on pglast 8 and the ``elif`` chains fell through, turning
    replica-unsafe migrations into ``window_safe: true``. A probe cannot drift.
    """
    try:
        compiled = parse_body(_PROBE.format(raise_stmt=raise_stmt))
    # Reason: a probe that will not compile disables the check; it never crashes it
    except (pglast.parser.ParseError, json.JSONDecodeError):
        return None
    for node in _walk(compiled.tree):
        if "PLpgSQL_stmt_raise" in node:
            level = node["PLpgSQL_stmt_raise"].get("elog_level")
            return int(level) if isinstance(level, int) else None
    return None


@cache
def _error_elog_level() -> int | None:
    """``RAISE EXCEPTION``'s level, compiled once per process."""
    return _elog_level_of("RAISE EXCEPTION 'probe';")


def _walk(node: Any):
    """Every dict in a compiled PL/pgSQL tree, depth first."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _is_catalogue(schema: str | None, relname: str) -> bool:
    """Whether this relation has rows on a schema-only copy.

    ``pg_dump --schema-only | psql`` leaves every *user* table empty, but the
    catalogue is fully populated — it describes the schema that was just
    created. So a guard counting catalogue rows is correct at preflight time.

    The bare form matters as much as the qualified one: PostgreSQL puts
    ``pg_catalog`` on the implicit ``search_path``, so ``FROM pg_class`` — no
    qualifier — is a catalogue read, and the ``pg_`` prefix is reserved for
    exactly this.
    """
    if schema in _SCHEMA_ONLY_SAFE:
        return True
    return schema is None and relname.startswith("pg_")


def _relations_in(query: str) -> list[tuple[str | None, str]]:
    """Every relation a query reads, as ``(schema, relname)``."""
    # Reason: a PLpgSQL_expr query is a fragment the compiler produced; pglast may still reject it
    try:
        tree = pglast.parser.parse_sql(query)
    except pglast.parser.ParseError:
        return []
    return _range_vars(tree)


def _range_vars(tree: Any) -> list[tuple[str | None, str]]:
    """Every ``RangeVar`` reachable from ``tree``, as ``(schema, relname)``."""
    out: list[tuple[str | None, str]] = []
    for node in _iter_nodes(tree):
        if type(node).__name__ != "RangeVar":
            continue
        rel = getattr(node, "relname", None)
        if rel:
            out.append((getattr(node, "schemaname", None), rel))
    return out


def _user_relations(query: str, derivations: dict[str, set[str]] | None = None) -> list[str]:
    """Relations in a query that are **empty** on a schema-only database.

    Excluded: the catalogue (see :func:`_is_catalogue`), and any relation this
    migration builds from the catalogue (see :func:`_catalogue_derived`). A
    bare user name is included — unqualified ``tb_widget`` resolves through
    ``search_path`` to a user table.
    """
    names: list[str] = []
    for schema, rel in _relations_in(query):
        if _is_catalogue(schema, rel):
            continue
        qualified = f"{schema}.{rel}" if schema else rel
        if derivations and _catalogue_derived(qualified, rel, derivations):
            continue
        names.append(qualified)
    return names


def _catalogue_derived(
    qualified: str, bare: str, derivations: dict[str, set[str]], _seen: frozenset[str] = frozenset()
) -> bool:
    """Whether this migration fills ``qualified`` from the catalogue, transitively.

    The blind spot this closes was measured downstream, not reasoned about: the
    same detector, built independently, reported **76 findings across 295
    migrations** and the checked samples were false — a temp table or view
    populated from ``pg_class`` has rows at preflight time, and its *name* says
    nothing about that.

    A relation created here with **no** sources is not derived: an empty table
    is precisely the case worth flagging, so "created in this file" must not
    become a blanket excuse.
    """
    for key in (qualified, bare):
        if key in _seen:
            continue
        sources = derivations.get(key)
        if not sources:
            continue
        seen = _seen | {qualified, bare}
        if all(
            source in _CATALOGUE_SENTINEL
            or _catalogue_derived(source, source.rpartition(".")[2], derivations, seen)
            for source in sources
        ):
            return True
    return False


#: Marks a source already known to be a catalogue relation.
_CATALOGUE_SENTINEL = frozenset({"<catalogue>"})


def _derivations(sql: str) -> dict[str, set[str]]:
    """What each relation this migration creates or fills is populated *from*.

    Keyed under both the qualified and the bare name, because a migration
    writes ``CREATE TEMP TABLE _x`` and then ``FROM _x``, or
    ``CREATE VIEW app.v`` and then ``FROM app.v``, and either spelling has to
    find the entry.

    Sources are collected from ``CREATE TABLE … AS SELECT``,
    ``CREATE VIEW … AS``, ``CREATE MATERIALIZED VIEW … AS`` and
    ``INSERT INTO … SELECT`` — the last because the rows can arrive after the
    ``CREATE``.
    """
    # Reason: a file the parser rejects contributes no derivations; each statement still scans
    try:
        statements = pglast.parser.parse_sql(sql)
    except pglast.parser.ParseError:
        return {}

    found: dict[str, set[str]] = {}
    for raw in statements or []:
        stmt = raw.stmt
        target_attr = _TARGET_ATTR.get(type(stmt).__name__)
        if target_attr is None:
            continue
        target = getattr(stmt, target_attr, None)
        # CreateTableAsStmt's target is an IntoClause wrapping the RangeVar.
        target = getattr(target, "rel", target)
        relname = getattr(target, "relname", None)
        if not relname:
            continue
        schema = getattr(target, "schemaname", None)
        query = getattr(stmt, "query", None) or getattr(stmt, "selectStmt", None)
        sources = {
            "<catalogue>" if _is_catalogue(s, r) else (f"{s}.{r}" if s else r)
            for s, r in _range_vars(query)
        }
        for key in {relname, f"{schema}.{relname}" if schema else relname}:
            found.setdefault(key, set()).update(sources)
    return found


#: Statement kind -> the attribute naming the relation it populates.
_TARGET_ATTR = {
    "CreateTableAsStmt": "into",
    "ViewStmt": "view",
    "InsertStmt": "relation",
}


def _iter_nodes(node: Any):
    """Every pglast AST node reachable from ``node``."""
    if isinstance(node, tuple | list):
        for item in node:
            yield from _iter_nodes(item)
        return
    if not hasattr(node, "__slots__"):
        return
    yield node
    for slot in node.__slots__:
        yield from _iter_nodes(getattr(node, slot, None))


def _counted_variables(block: Any, derivations: dict[str, set[str]]) -> dict[str, str]:
    """Variables assigned by a ``SELECT ... INTO`` over a user relation.

    Maps the variable's name to the relation it counted, which is what a
    finding prints.
    """
    counted: dict[str, str] = {}
    for node in _walk(block):
        stmt = node.get("PLpgSQL_stmt_execsql")
        if not stmt or not stmt.get("into"):
            continue
        query = stmt.get("sqlstmt", {}).get("PLpgSQL_expr", {}).get("query", "")
        relations = _user_relations(query, derivations)
        if not relations:
            continue
        for target in _into_targets(stmt.get("target")):
            counted[target] = relations[0]
    return counted


def _into_targets(target: Any) -> list[str]:
    """The variable names an ``INTO`` clause writes.

    A single target compiles to a ``PLpgSQL_var``; two or more to a
    ``PLpgSQL_row`` of fields — and so does a single one, in the shape the
    compiler happens to emit, which is why both are read.
    """
    if not isinstance(target, dict):
        return []
    if "PLpgSQL_var" in target:
        name = target["PLpgSQL_var"].get("refname")
        return [name] if name else []
    row = target.get("PLpgSQL_row")
    if not row:
        return []
    return [f["name"] for f in row.get("fields", []) if f.get("name")]


def _raises_at_error(body: Any, error_level: int) -> dict | None:
    """The first ERROR-level ``RAISE`` in this branch, if any."""
    for node in _walk(body):
        raise_stmt = node.get("PLpgSQL_stmt_raise")
        if raise_stmt is not None and raise_stmt.get("elog_level") == error_level:
            return raise_stmt
    return None


def _assertions_in(
    tree: Any,
    file: Path,
    error_level: int,
    line_base: int,
    lines: list[str],
    derivations: dict[str, set[str]],
) -> list[DataAssertion]:
    counted = _counted_variables(tree, derivations)
    if not counted:
        return []

    found: list[DataAssertion] = []
    for node in _walk(tree):
        stmt_if = node.get("PLpgSQL_stmt_if")
        if not stmt_if:
            continue
        condition = stmt_if.get("cond", {}).get("PLpgSQL_expr", {}).get("query", "")
        guarded = [name for name in counted if _reads(condition, name)]
        if not guarded:
            continue
        raise_stmt = _raises_at_error(stmt_if.get("then_body"), error_level)
        if raise_stmt is None:
            continue
        variable = guarded[0]
        found.append(
            DataAssertion(
                file=file,
                line=_absolute_line(raise_stmt, stmt_if, line_base, lines),
                variable=variable,
                relation=counted[variable],
                condition=condition,
                message=raise_stmt.get("message"),
            )
        )
    return found


def _absolute_line(raise_stmt: dict, stmt_if: dict, line_base: int, lines: list[str]) -> int:
    """The ``RAISE``'s line in the **file**, not in its statement or its body.

    ``parse_plpgsql`` is handed one statement at a time and counts from the
    first line of the body string. Reported raw, two ``DO`` blocks in one file
    both claim line 7 — which is how this was caught: a scan of 3996 of this
    repo's SQL files reported the same line twice in the same file.
    ``confiture lint`` prints ``file:line`` on every finding, so an offset that
    is only locally correct is wrong.

    The computed line is then **checked by putting it back**: if the text there
    does not hold a ``RAISE``, the base was wrong and the ``IF``'s line is
    tried instead. A warning pointing at the wrong line is worse than a warning
    pointing at the block.
    """
    for internal in (raise_stmt.get("lineno"), stmt_if.get("lineno")):
        if not internal:
            continue
        candidate = line_base + int(internal) - 1
        if 1 <= candidate <= len(lines) and "raise" in lines[candidate - 1].lower():
            return candidate
    internal = raise_stmt.get("lineno") or stmt_if.get("lineno") or 1
    return line_base + int(internal) - 1


def _reads(condition: str, name: str) -> bool:
    """Whether ``condition`` references the variable ``name``.

    Word-boundary matching on the compiler's own rendering of the expression,
    which is the identifier as declared — so ``n`` does not match ``n_rows``.
    """
    return re.search(rf"\b{re.escape(name)}\b", condition) is not None


def _located_statements(sql: str) -> list[tuple[str, int]]:
    """Each top-level statement with the file line it starts on.

    Split with the **scanner**, not the parser. A migration is applied through
    ``psql`` (``core/psql_applier.py``), so it may legitimately carry a psql
    meta-command that ``pglast.parse_sql`` rejects outright — this repo's own
    ``examples/04-production-sync-anonymization/verify_anonymization.sql`` is
    one, and parsing the whole file lost all eight of its statements for a
    backslash on line 21. ``split_statements`` splits it and each statement is
    then judged on its own, which is exactly what its docstring promises.

    The line is tracked with a forward cursor rather than recounted from the
    top, so two identical blocks in one file get two different lines.
    """
    located: list[tuple[str, int]] = []
    cursor = 0
    for text in split_statements(sql):
        at = sql.find(text, cursor)
        if at < 0:
            # The scanner strips each statement, so a literal find can miss if
            # the text was normalised. Degrade to the cursor rather than
            # guessing an offset that would misreport every later finding.
            at = cursor
        located.append((text, sql.count("\n", 0, at + _body_offset(text)) + 1))
        cursor = at + len(text)
    return located


def _body_offset(statement: str) -> int:
    """Offset within ``statement`` of the dollar-quoted body's first line.

    PL/pgSQL's ``lineno`` counts from the first line of the **body string**,
    not from the statement. Those coincide only when nothing precedes the
    opening ``$$`` — and in this repo's own
    ``examples/04-production-sync-anonymization/verify_anonymization.sql``
    every block carries a banner comment, so a statement-relative base pointed
    findings at comment lines.

    The body is taken to be the longest dollar-quoted literal in the
    statement: a routine's body dwarfs any ``DEFAULT $$…$$`` or ``SET … = $x$…$x$``
    beside it. The choice is not trusted — :func:`_absolute_line` checks the
    line it produces really holds the ``RAISE`` and falls back if it does not.
    """
    best = 0
    longest = 0
    # Reason: a statement the scanner cannot tokenise contributes no body offset
    try:
        toks = tokens(statement)
    except pglast.parser.ParseError:
        return 0
    for tok in toks:
        start, end = tok.start, tok.end
        if statement[start : start + 1] != "$":
            continue
        if end - start > longest:
            longest, best = end - start, start
    return best


def scan_sql(sql: str, file: Path) -> AssertionScan:
    """Scan one migration's SQL text for data assertions.

    Each statement is compiled separately: ``pglast.parse_plpgsql`` answers for
    one PL/pgSQL-defining statement, and a real migration is DDL with a ``DO``
    block somewhere in the middle. A statement that is not PL/pgSQL contributes
    nothing and never raises — this is a findings pass, and it must not be the
    thing that fails the command.

    A statement that *is* PL/pgSQL-defining and that the compiler still rejects
    sets ``unparseable``: that one was meant to be read and was not, and saying
    so is the difference between "no assertions here" and "no idea".
    """
    error_level = _error_elog_level()
    if error_level is None:
        return AssertionScan(file=file, assertions=[])

    lines = sql.splitlines()
    derivations = _derivations(sql)
    found: list[DataAssertion] = []
    unparseable = False
    for text, line in _located_statements(sql):
        # Reason: most statements are not PL/pgSQL at all; the compiler rejecting one is expected
        try:
            compiled = parse_body(text)
        except (pglast.parser.ParseError, json.JSONDecodeError):
            unparseable = unparseable or _defines_plpgsql(text)
            continue
        found.extend(_assertions_in(compiled.tree, file, error_level, line, lines, derivations))
    return AssertionScan(file=file, assertions=found, unparseable=unparseable)


def _defines_plpgsql(statement: str) -> bool:
    """Whether this statement was supposed to carry a PL/pgSQL body.

    ``DO`` always does. A ``CREATE``/``ALTER`` does only when it names the
    language, which is read off the statement text because the statement did
    not parse — that is the whole reason this function is being asked.
    """
    kind = statement_type(statement)
    if kind == "DO":
        return True
    if kind not in ("CREATE", "ALTER"):
        return False
    return "plpgsql" in statement.lower()


def find_data_assertions(sql: str, file: Path) -> list[DataAssertion]:
    """The assertions in one migration's SQL, discarding the unparseable signal."""
    return scan_sql(sql, file).assertions


def scan_migration(path: Path, *, project_root: Path | None = None) -> AssertionScan:
    """Scan one migration file, ``.sql`` or ``.py``.

    A ``.py`` migration's SQL is resolved by the static evaluator
    (``core/idempotency/static_eval``, #213), which is the one place in this
    repo that answers "what text does this ``self.execute(...)`` hand over".
    Nothing here pattern-matches the call's argument, and nothing imports,
    executes or ``eval``s the migration.

    Findings from a ``.py`` migration are reported at the **call's** line. The
    SQL lives inside a string literal (or another file), so a line inside it is
    not a line in this file; pointing at the ``self.execute(...)`` is the
    honest answer, and it is what the reader greps for.

    A call the evaluator refuses is ``unparseable``: it was meant to be read
    and was not. Refusing to guess and then reporting "clean" would be the
    worse of the two.
    """
    # Reason: an unreadable migration file yields no findings, never an exception
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return AssertionScan(file=path, assertions=[])

    if path.suffix != ".py":
        return scan_sql(text, path)

    # Reason: the static evaluator pulls in the whole idempotency package, and this check is off by default
    from confiture.core.idempotency.python_migration_extractor import (
        extract_sql_from_python_source,
    )

    result = extract_sql_from_python_source(text, path=path, project_root=project_root)
    assertions: list[DataAssertion] = []
    unparseable = bool(result.warnings)
    for snippet in result.snippets:
        scan = scan_sql(snippet.sql, path)
        unparseable = unparseable or scan.unparseable
        assertions.extend(replace(found, line=snippet.source_line) for found in scan.assertions)
    return AssertionScan(file=path, assertions=assertions, unparseable=unparseable)
