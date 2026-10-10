"""Session state a stored projection reads (#656): ``tview_003``–``005``, ``session_001``–``003``.

A pg_tviews TVIEW's rows are computed in the session that writes a base row,
not in the reader's. Whatever its definition reads of the session — a setting
(``current_setting('app.locale')``), the role, the time — is the writer's, and
is stored for every reader. So for each TVIEW the tree declares (both spellings,
as ``build_003`` resolves them), its query is read, then each **plain view** it
reads, transitively, and each function they call whose body confiture can read
(SQL, ``BEGIN ATOMIC``, PL/pgSQL, through :mod:`~confiture.core.linting.references`):

- ``tview_003`` (error): a session setting or the session's identity;
- ``tview_004`` (warning): a non-immutable function outside ``pg_catalog`` the
  TVIEW does not declare in ``function_reads``;
- ``tview_005`` (warning): the time, with no ``time_refresh`` declared.

A materialized view, a table and another TVIEW store their rows, so a chain stops
there: their reads are frozen at refresh, or reported on their own. pg_tviews
refuses ``tview_004``'s and ``tview_005``'s reads only under its ``error`` and
``full_refresh`` policies (pg_tviews#193), so a TVIEW declaring
``uncascaded_policy: warn`` is not reported for them.

``session_001``–``003`` ask the same of every view's own definition and the
functions it calls, for a view a cache or a replica serves; they are off unless
selected (``--select session_reads``). The two families report independently.

One finding per read, where the read is written — a helper reading a setting is
reported once, in the helper, naming every TVIEW that reaches it. A read is
waived by ``-- confiture:projection-reads-session <name>[, <name>]: <why>`` above
the TVIEW, a view in its chain, or the function holding the read; a waiver with
no reason waives nothing.
"""

from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from confiture.core import sql_lexer
from confiture.core._pglast_enums import member as _pg_member
from confiture.core.ddl_walk import constant_text, enum_int, walk_nodes
from confiture.core.linting.inventory import DEFAULT_SCHEMA, Inventory, SchemaObject, split_names
from confiture.core.linting.rule_registry import SESSION_CODES
from confiture.core.linting.tview_reads import (
    Holder,
    LineAt,
    Path,
    ReadGraph,
    Target,
    folded,
    spelled,
)
from confiture.core.schema_identity import identifier_identity
from confiture.core.schema_model import FunctionRead
from confiture.core.sql_lexer import ParsedFile

TVIEW_CODES = frozenset({"tview_003", "tview_004", "tview_005"})
VIEW_CODES = SESSION_CODES - TVIEW_CODES

#: The name a finding of each code carries.
RULE_NAMES = {
    "tview_003": "Projection Reads Session State",
    "tview_004": "Projection Calls Undeclared Function",
    "tview_005": "Projection Reads The Time",
    "session_001": "View Reads Session State",
    "session_002": "View Calls Non-Immutable Function",
    "session_003": "View Reads The Time",
}

#: The directive that waives a read.
WAIVER = "projection-reads-session"

#: Which code reports each kind of read, per family.
_CODE = {
    ("tview", "setting"): "tview_003",
    ("tview", "identity"): "tview_003",
    ("tview", "function"): "tview_004",
    ("tview", "time"): "tview_005",
    ("view", "setting"): "session_001",
    ("view", "identity"): "session_001",
    ("view", "function"): "session_002",
    ("view", "time"): "session_003",
}

_SVF_TIME = {
    "SVFOP_CURRENT_DATE": "CURRENT_DATE",
    "SVFOP_CURRENT_TIME": "CURRENT_TIME",
    "SVFOP_CURRENT_TIME_N": "CURRENT_TIME",
    "SVFOP_CURRENT_TIMESTAMP": "CURRENT_TIMESTAMP",
    "SVFOP_CURRENT_TIMESTAMP_N": "CURRENT_TIMESTAMP",
    "SVFOP_LOCALTIME": "LOCALTIME",
    "SVFOP_LOCALTIME_N": "LOCALTIME",
    "SVFOP_LOCALTIMESTAMP": "LOCALTIMESTAMP",
    "SVFOP_LOCALTIMESTAMP_N": "LOCALTIMESTAMP",
}
_SVF_IDENTITY = {
    "SVFOP_CURRENT_ROLE": "CURRENT_ROLE",
    "SVFOP_CURRENT_USER": "CURRENT_USER",
    "SVFOP_USER": "USER",
    "SVFOP_SESSION_USER": "SESSION_USER",
    "SVFOP_CURRENT_SCHEMA": "CURRENT_SCHEMA",
}
#: ``SQLValueFunction`` op → (kind of read, keyword).
_SVF: dict[int | None, tuple[str, str]] = {
    enum_int(_pg_member("SQLValueFunctionOp", op)): (kind, keyword)
    for kind, table in (("time", _SVF_TIME), ("identity", _SVF_IDENTITY))
    for op, keyword in table.items()
}
#: Built-in functions that read the clock (``age`` only with one argument).
_TIME_FUNCTIONS = frozenset(
    {"now", "transaction_timestamp", "statement_timestamp", "clock_timestamp", "timeofday", "age"}
)
#: Built-in functions that read the session's identity or its search path.
_IDENTITY_FUNCTIONS = frozenset({"current_schema", "current_schemas", "current_user"})
#: Literals PostgreSQL reads as the time when cast to a date or time type.
_TIME_LITERALS = frozenset({"now", "today", "tomorrow", "yesterday"})
_TIME_TYPES = frozenset({"date", "timestamp", "timestamptz", "time", "timetz"})
_BUILTIN_SCHEMAS = (None, "pg_catalog")


@dataclass(frozen=True)
class SessionFinding:
    """One read of session state, where it is written, and who reaches it."""

    code: str
    object_type: str
    object_name: str
    message: str
    fix: str
    file: str | None
    line: int


@dataclass(frozen=True)
class SessionReads:
    """The findings, and what a chain reached but could not read (a degraded rule)."""

    findings: list[SessionFinding]
    unread: list[str]
    #: Each selected code whose family's chains reached :attr:`unread` entries, with them.
    degraded: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class _Read:
    """One read: what kind, the name a waiver names, how a message writes it, its line."""

    kind: str
    name: str
    text: str
    line: int
    #: The routine a ``function`` read calls.
    routine: SchemaObject | None = None
    #: The name a waiver may write for a function read: its own, unqualified.
    bare: str | None = None


def session_reads(
    files: Sequence[ParsedFile], inventory: Inventory, codes: frozenset[str]
) -> SessionReads:
    """Every read of session state the selected *codes* report, in file order.

    A TVIEW query the parser rejects, or a routine body the reader refuses, that
    a selected chain reaches is named in :attr:`SessionReads.unread`: what was not
    read was not judged.
    """
    if not codes & SESSION_CODES:
        return SessionReads([], [])
    graph = ReadGraph.read(files, inventory)
    session = _Session(graph)
    findings: list[SessionFinding] = []
    unread: set[str] = set()
    degraded: dict[str, list[str]] = {}
    for family, family_codes in (("tview", TVIEW_CODES), ("view", VIEW_CODES)):
        if codes & family_codes:
            targets = [t for t in graph.targets if t.family == family]
            findings.extend(f for f in session.findings(targets) if f.code in codes)
            reached = graph.unread(targets)
            unread |= reached
            if reached:
                degraded.update(dict.fromkeys(sorted(codes & family_codes), sorted(reached)))
    return SessionReads(
        sorted(findings, key=lambda f: (f.file or "", f.line, f.code, f.object_name)),
        sorted(unread),
        degraded,
    )


def session_read_findings(
    files: Sequence[ParsedFile], inventory: Inventory, codes: frozenset[str]
) -> list[SessionFinding]:
    """:func:`session_reads`' findings alone."""
    return session_reads(files, inventory, codes).findings


class _Session:
    """The session reads each holder of the graph makes, read once; then each target's findings."""

    def __init__(self, graph: ReadGraph) -> None:
        self.graph = graph
        self.waivers = graph.waivers(WAIVER)
        self._reads: dict[int, list[_Read]] = {}

    def reads(self, holder: Holder) -> list[_Read]:
        """What *holder*'s own text reads of the session, in the order it is written."""
        if id(holder) not in self._reads:
            found: list[_Read] = []
            for query in holder.queries:
                for node in walk_nodes(query.root):
                    if (read := _read_of(node, query.line_at)) is not None:
                        found.append(read)
                    elif type(node).__name__ == "FuncCall":
                        found.extend(self._calls(node, query.line_at))
            self._reads[id(holder)] = found
        return self._reads[id(holder)]

    def _calls(self, node: Any, line_at: LineAt) -> Iterator[_Read]:
        for routine in self.graph.routines_called(node):
            volatility = routine.routine.volatility if routine.routine else "volatile"
            if volatility != "immutable":
                yield _Read(
                    "function",
                    routine.qualified,
                    f"{routine.qualified}() ({volatility.upper()})",
                    line_at(node.location),
                    routine,
                    routine.folded_name,
                )

    def findings(self, targets: Iterable[Target]) -> list[SessionFinding]:
        sites: dict[tuple[str, int, str, str], list[tuple[Target, Path]]] = defaultdict(list)
        holders: dict[tuple[str, int, str, str], tuple[Holder, _Read]] = {}
        for target in targets:
            for holder, path in self.graph.chain(target):
                for read in self.reads(holder):
                    if self._reported(target, holder, path, read):
                        site = (
                            _CODE[(target.family, read.kind)],
                            id(holder),
                            read.text,
                            str(read.line),
                        )
                        sites[site].append((target, path))
                        holders[site] = (holder, read)
        return [
            self._finding(code, *holders[(code, at, text, line)], reached)
            for (code, at, text, line), reached in sites.items()
        ]

    def _reported(self, target: Target, holder: Holder, path: Path, read: _Read) -> bool:
        declared = target.declared
        if declared is not None and read.kind in ("function", "time"):
            if declared.uncascaded_policy == "warn":
                return False
            if read.kind == "time" and declared.time_refresh:
                return False
            if read.kind == "function" and _declared(read, declared.function_reads or ()):
                return False
        return not self._waived(target, holder, path, read)

    def _waived(self, target: Target, holder: Holder, path: Path, read: _Read) -> bool:
        """Whether a waiver with a reason, on the TVIEW or anything on the way, names *read*."""
        names = {folded(read.name)} | ({read.bare} if read.bare else set())
        on_chain = [target.obj, holder.obj, *(step.obj for step in path)]
        return any(
            names & set(self.waivers.get((obj.file, obj.statement_line)) or ()) for obj in on_chain
        )

    def _finding(
        self,
        code: str,
        holder: Holder,
        read: _Read,
        reached: list[tuple[Target, Path]],
    ) -> SessionFinding:
        names = list(dict.fromkeys(spelled(t.obj) for t, _ in reached))
        first_target, first_path = reached[0]
        verb = "call" if read.kind == "function" else "read"
        subject = (
            f"{names[0]} {verb}s"
            if len(names) == 1
            else f"{', '.join(names[:-1])} and {names[-1]} {verb}"
        )
        through = (
            f" through {' → '.join(spelled(step.obj) for step in first_path)}" if first_path else ""
        )
        outcome, fix = _WORDING[code]
        if code == "tview_005" and not first_target.spelled_as_call:
            fix = _CTAS_TIME_FIX
        on_chain = [holder.obj] + [t.obj for t, _ in reached]
        if any(self.waivers.get((o.file, o.statement_line), []) is None for o in on_chain):
            outcome += f" (a {WAIVER} waiver here gives no reason, so it waives nothing)"
        return SessionFinding(
            code=code,
            object_type=holder.obj.kind,
            object_name=f"{spelled(holder.obj)}:{_identity(read)}",
            message=f"{subject} {read.text}{through}: {outcome}",
            fix=fix,
            file=holder.obj.file,
            line=read.line,
        )


#: ``code → (outcome, fix)``: what a finding says happens, and what to do.
_WORDING = {
    "tview_003": (
        "the stored row takes the writer's value, not the reader's",
        "Read it at read time, as a request input, not in the projection.",
    ),
    "tview_004": (
        "declare it or remove it",
        'Declare it in the TVIEW\'s "function_reads" option, or remove the call.',
    ),
    "tview_005": (
        "declare time_refresh",
        'Declare "time_refresh": "external" and schedule pg_tviews_refresh_time_dependent().',
    ),
    "session_001": (
        "a cached or replicated row takes the computing session's value, not the reader's",
        "Read it at read time, as a request input, not in the view.",
    ),
    "session_002": (
        "its value may be the computing session's",
        "Make the function IMMUTABLE if it is, or call it at read time.",
    ),
    "session_003": (
        "a cached or replicated row is as old as its last refresh",
        "Read the time at read time, or accept a value as old as the last refresh.",
    ),
}
_CTAS_TIME_FIX = (
    "A CREATE TABLE … AS cannot pass options: write it as pg_tviews_create_or_replace() "
    'with "time_refresh": "external", or waive it.'
)


def _read_of(node: Any, line_at: LineAt) -> _Read | None:
    """The session read *node* is, if it is one (a call of a tree routine is not decided here)."""
    kind = type(node).__name__
    if kind == "SQLValueFunction":
        found = _SVF.get(enum_int(node.op))
        if found is None:
            return None
        what, keyword = found
        return _Read(what, keyword.lower(), keyword, line_at(node.location))
    if kind == "FuncCall":
        return _builtin_read(node, line_at)
    if kind == "TypeCast":
        literal = constant_text(node.arg)
        _schema, type_name = split_names(node.typeName.names)
        if literal is not None and literal.lower() in _TIME_LITERALS and type_name in _TIME_TYPES:
            return _Read(
                "time", literal.lower(), f"'{literal}'::{type_name}", line_at(node.location)
            )
    return None


def _builtin_read(node: Any, line_at: LineAt) -> _Read | None:
    schema, name = split_names(node.funcname)
    if schema not in _BUILTIN_SCHEMAS:
        return None
    args = node.args or ()
    line = line_at(node.location)
    if name == "current_setting":
        setting = constant_text(args[0]) if args else None
        spelled = setting if setting is not None else "?"
        return _Read("setting", spelled.lower(), f"current_setting('{spelled}')", line)
    if name in _TIME_FUNCTIONS and (name != "age" or len(args) == 1):
        return _Read("time", name, f"{name}()", line)
    if name in _IDENTITY_FUNCTIONS:
        return _Read("identity", name, f"{name}()", line)
    return None


def _declared(read: _Read, declared: tuple[FunctionRead, ...]) -> bool:
    """Whether a ``function_reads`` key names the routine *read* calls (by schema and name)."""
    routine = read.routine
    if routine is None:
        return False
    for key in (entry.function for entry in declared):
        parts = sql_lexer.name_parts(key.partition("(")[0].strip())
        if not parts:
            continue
        schema, name = (None, parts[0]) if len(parts) == 1 else (parts[0], parts[-1])
        same_schema = schema is None or identifier_identity(schema) == (
            routine.folded_schema or DEFAULT_SCHEMA
        )
        if same_schema and identifier_identity(name) == routine.folded_name:
            return True
    return False


def _identity(read: _Read) -> str:
    """How a baseline names the read: ``current_setting(app.locale)``, ``CURRENT_DATE``."""
    if read.kind == "setting":
        return f"current_setting({read.name})"
    return read.text.split(" (")[0]
