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

from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import pglast.parser

from confiture.core import sql_lexer
from confiture.core._pglast_enums import member as _pg_member
from confiture.core.ddl_walk import (
    TViewCall,
    TViewDeclarations,
    constant_text,
    enum_int,
    tview_calls,
    tview_query_tree,
    walk_nodes,
)
from confiture.core.linting.inventory import (
    DEFAULT_SCHEMA,
    Inventory,
    SchemaObject,
    group_definitions,
    kept,
    object_from_statement,
    split_names,
)
from confiture.core.linting.references import routine_bodies
from confiture.core.linting.rule_registry import SESSION_CODES
from confiture.core.schema_identity import identifier_identity
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
_ROUTINE_KINDS = ("function", "procedure")


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


@dataclass
class _Holder:
    """A view, a TVIEW or a routine: the reads its own text makes, and what it reads next."""

    obj: SchemaObject
    reads: list[_Read] = field(default_factory=list)
    views: list[str] = field(default_factory=list)
    routines: list[str] = field(default_factory=list)
    #: Why some of its text was not read, or ``None``.
    unread: str | None = None


#: The holders that lead from a target to a holder, in order.
_Path = tuple[_Holder, ...]


@dataclass(frozen=True)
class _Target:
    """A TVIEW or a view whose chain is judged, and what it declares."""

    obj: SchemaObject
    family: str
    declared: TViewDeclarations = field(default_factory=TViewDeclarations)
    policy: str | None = None
    spelled_as_call: bool = False


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
    graph = _Graph.read(files, inventory)
    findings: list[SessionFinding] = []
    unread: set[str] = set()
    for family, family_codes in (("tview", TVIEW_CODES), ("view", VIEW_CODES)):
        if codes & family_codes:
            targets = [t for t in graph.targets if t.family == family]
            findings.extend(f for f in graph.findings(targets) if f.code in codes)
            unread |= graph.unread(targets)
    return SessionReads(
        sorted(findings, key=lambda f: (f.file or "", f.line, f.code, f.object_name)),
        sorted(unread),
    )


def session_read_findings(
    files: Sequence[ParsedFile], inventory: Inventory, codes: frozenset[str]
) -> list[SessionFinding]:
    """:func:`session_reads`' findings alone."""
    return session_reads(files, inventory, codes).findings


def _key(obj: SchemaObject) -> str:
    """A holder's key: a relation by schema and name, a routine by its identity (overloads apart)."""
    if obj.kind in _ROUTINE_KINDS:
        return f"routine:{obj.identity}"
    return f"{(obj.folded_schema or DEFAULT_SCHEMA).lower()}.{obj.folded_name}"


class _Graph:
    """Every holder's own reads and edges, read once; then each target's chain."""

    def __init__(self, inventory: Inventory) -> None:
        self.inventory = inventory
        self.holders: dict[str, _Holder] = {}
        self.targets: list[_Target] = []
        self.waivers: dict[tuple[str | None, int], list[str] | None] = {}

    @classmethod
    def read(cls, files: Sequence[ParsedFile], inventory: Inventory) -> _Graph:
        graph = cls(inventory)
        built = {(obj.file, obj.offset) for obj in map(kept, group_definitions(inventory.objects))}
        for parsed in files:
            graph._read_waivers(parsed)
            graph._read_file(parsed, built)
        return graph

    def _read_waivers(self, parsed: ParsedFile) -> None:
        for directive in sql_lexer.directives(parsed.text):
            if directive.name != WAIVER or directive.statement_line is None:
                continue
            names, _, reason = (directive.argument or "").partition(":")
            spelled = [_folded(n) for n in names.split(",") if n.strip()]
            self.waivers[(parsed.label, directive.statement_line)] = (
                spelled if reason.strip() else None
            )

    def _read_file(self, parsed: ParsedFile, built: set[tuple[str | None, int]]) -> None:
        text = parsed.text
        for raw in parsed.statements:
            obj = object_from_statement(text, raw)
            if obj is not None and obj.kind in ("view", "matview", "tview"):
                if (parsed.label, parsed.base + obj.offset) not in built:
                    continue
                self._add_query(parsed, obj, raw.stmt.query, lambda at: _line(text, at))
            elif obj is None:
                self._add_calls(parsed, raw)
        for body in routine_bodies(parsed):
            if (parsed.label, parsed.base + body.obj.offset) not in built:
                continue
            holder = self._holder(parsed, body.obj)
            if body.refused is not None or body.unread:
                holder.unread = body.refused or "; ".join(reason for _, reason in body.unread)
            for statement in body.statements:
                self._walk(holder, statement.root, statement.line_at)

    def _add_calls(self, parsed: ParsedFile, raw: Any) -> None:
        """Each TVIEW a ``SELECT pg_tviews_create…(…)`` creates, its query read where written."""
        for call in tview_calls(raw.stmt):
            if call.action == "drop" or call.name is None or call.written is None:
                continue
            obj = next(
                (
                    o
                    for o in self.inventory.find_all(("tview",), call.schema, call.name)
                    if o.file == parsed.label
                ),
                None,
            )
            if obj is not None:
                self._add_call(parsed, obj, call)

    def _add_call(self, parsed: ParsedFile, obj: SchemaObject, call: TViewCall) -> None:
        written = call.written or ""
        try:
            root = tview_query_tree(written)
        except pglast.parser.ParseError, IndexError:
            # Not read, so not judged: session_reads() names it as unread.
            self._holder(parsed, obj).unread = "its query does not parse"
            self.targets.append(_Target(obj, "tview", call.declared, spelled_as_call=True))
        else:
            first = _line(parsed.text, call.written_at)
            self._add_query(
                parsed,
                obj,
                root,
                lambda at: first + written.count("\n", 0, at or 0),
                call=call,
            )

    def _add_query(
        self,
        parsed: ParsedFile,
        obj: SchemaObject,
        root: Any,
        line_at: Callable[[int | None], int],
        call: TViewCall | None = None,
    ) -> None:
        holder = self._holder(parsed, obj)
        self._walk(holder, root, line_at)
        if obj.kind == "tview":
            tview = obj.tview
            self.targets.append(
                _Target(
                    holder.obj,
                    "tview",
                    call.declared if call is not None else TViewDeclarations(),
                    None if tview is None else tview.uncascaded_policy,
                    spelled_as_call=call is not None,
                )
            )
        else:
            self.targets.append(_Target(holder.obj, "view"))

    def _holder(self, parsed: ParsedFile, obj: SchemaObject) -> _Holder:
        obj.file = parsed.label
        return self.holders.setdefault(_key(obj), _Holder(obj))

    def _walk(self, holder: _Holder, root: Any, line_at: Callable[[int | None], int]) -> None:
        nodes = list(walk_nodes(root))
        local = {n.ctename for n in nodes if type(n).__name__ == "CommonTableExpr"}
        for node in nodes:
            kind = type(node).__name__
            if kind == "RangeVar":
                if node.schemaname is None and node.relname in local:
                    continue
                holder.views.extend(
                    _key(o)
                    for o in self.inventory.find_all(
                        ("view",), node.schemaname, identifier_identity(node.relname)
                    )
                )
            elif (read := _read_of(node, line_at)) is not None:
                holder.reads.append(read)
            elif kind == "FuncCall":
                self._call(holder, node, line_at)

    def _call(self, holder: _Holder, node: Any, line_at: Callable[[int | None], int]) -> None:
        schema, name = split_names(node.funcname)
        if schema == "pg_catalog":
            return
        for routine in self.inventory.find_all(_ROUTINE_KINDS, schema, identifier_identity(name)):
            holder.routines.append(_key(routine))
            volatility = routine.routine.volatility if routine.routine else "volatile"
            if volatility != "immutable":
                holder.reads.append(
                    _Read(
                        "function",
                        routine.qualified,
                        f"{routine.qualified}() ({volatility.upper()})",
                        line_at(node.location),
                        routine,
                        routine.folded_name,
                    )
                )

    # -- Chains and findings ---------------------------------------------------

    def _chain(self, target: _Target) -> Iterator[tuple[_Holder, _Path]]:
        """Each holder *target* reaches, once, with the holders that lead to it first.

        A TVIEW's chain follows the plain views and the routines it reads; a
        view's, only the routines its own definition calls.
        """
        seen: set[int] = set()
        pending: deque[tuple[_Holder, _Path]] = deque([(self.holders[_key(target.obj)], ())])
        while pending:
            holder, path = pending.popleft()
            if id(holder) in seen:
                continue
            seen.add(id(holder))
            yield holder, path
            follow = holder.routines if target.family == "view" else holder.views + holder.routines
            pending.extend(
                (found, (*path, found))
                for found in (self.holders.get(key) for key in follow)
                if found is not None
            )

    def unread(self, targets: Iterable[_Target]) -> set[str]:
        """What the chains of *targets* reach and could not read, each named with why."""
        return {
            f"{_spelled(holder.obj)} ({holder.unread})"
            for target in targets
            for holder, _ in self._chain(target)
            if holder.unread is not None
        }

    def findings(self, targets: Iterable[_Target]) -> list[SessionFinding]:
        sites: dict[tuple[str, int, str, str], list[tuple[_Target, _Path]]] = defaultdict(list)
        holders: dict[tuple[str, int, str, str], tuple[_Holder, _Read]] = {}
        for target in targets:
            for holder, path in self._chain(target):
                for read in holder.reads:
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

    def _reported(self, target: _Target, holder: _Holder, path: _Path, read: _Read) -> bool:
        if target.family == "tview" and read.kind in ("function", "time"):
            if target.policy == "warn":
                return False
            if read.kind == "time" and target.declared.time_refresh:
                return False
            if read.kind == "function" and _declared(read, target.declared):
                return False
        return not self._waived(target, holder, path, read)

    def _waived(self, target: _Target, holder: _Holder, path: _Path, read: _Read) -> bool:
        """Whether a waiver with a reason, on the TVIEW or anything on the way, names *read*."""
        names = {_folded(read.name)} | ({read.bare} if read.bare else set())
        on_chain = [target.obj, holder.obj, *(step.obj for step in path)]
        return any(
            names & set(self.waivers.get((obj.file, obj.statement_line)) or ()) for obj in on_chain
        )

    def _finding(
        self,
        code: str,
        holder: _Holder,
        read: _Read,
        reached: list[tuple[_Target, _Path]],
    ) -> SessionFinding:
        names = list(dict.fromkeys(_spelled(t.obj) for t, _ in reached))
        first_target, first_path = reached[0]
        verb = "call" if read.kind == "function" else "read"
        subject = (
            f"{names[0]} {verb}s"
            if len(names) == 1
            else f"{', '.join(names[:-1])} and {names[-1]} {verb}"
        )
        through = (
            f" through {' → '.join(_spelled(step.obj) for step in first_path)}"
            if first_path
            else ""
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
            object_name=f"{_spelled(holder.obj)}:{_identity(read)}",
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


def _read_of(node: Any, line_at: Callable[[int | None], int]) -> _Read | None:
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


def _builtin_read(node: Any, line_at: Callable[[int | None], int]) -> _Read | None:
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


def _declared(read: _Read, declared: TViewDeclarations) -> bool:
    """Whether a ``function_reads`` key names the routine *read* calls (by schema and name)."""
    routine = read.routine
    if routine is None:
        return False
    for key in declared.function_reads:
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


def _spelled(obj: SchemaObject) -> str:
    return f"{obj.qualified}()" if obj.kind in _ROUTINE_KINDS else obj.qualified


def _identity(read: _Read) -> str:
    """How a baseline names the read: ``current_setting(app.locale)``, ``CURRENT_DATE``."""
    if read.kind == "setting":
        return f"current_setting({read.name})"
    return read.text.split(" (")[0]


def _folded(name: str) -> str:
    return name.strip().lower()


def _line(text: str, location: int | None) -> int:
    if location is None or location < 0:
        return 1
    return text.count("\n", 0, min(location, len(text))) + 1
