"""What a seed tree populates, and by which key its rows are matched across two databases (#743).

``confiture seed drift`` compares the rows a seed-built database holds with the
rows a migrate-only one holds. This module decides, from the tree alone, *what*
is compared: every table a seed file writes (``seed_rows.SeedStatements.targets``),
a staging table replaced by the table its resolver moves the rows into
(``resolvers.read_resolution``), and for each table a **stable** key and the
columns the seed writes.

A key is stable when every statement that adds the table's rows writes it, and
no seed row computes it. A surrogate PostgreSQL generates (an identity
``pk_*``, a ``gen_random_uuid()`` default the seed leaves out) differs between
the two databases, so it can never match a row across them. A foreign key to
such a generated key is compared through the parent's stable key (a
:class:`Dereference`), never by its number. A table with no stable key, a seed
file PostgreSQL rejects, an ambiguous staging table: each is a
:class:`NotCompared` with its reason, never left out in silence.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from confiture.config.environment import SeedDriftSettings
from confiture.core import sql_lexer
from confiture.core.schema_identity import identifier_identity
from confiture.core.schema_model import Column, RelationName, Table, primary_key
from confiture.core.schema_read import SchemaRead
from confiture.core.seed.validation.prep_seed.final_tables import resolver_inserts
from confiture.core.seed.validation.prep_seed.resolvers import read_resolution
from confiture.core.seed.validation.prep_seed.seed_rows import (
    Computed,
    SeedParseError,
    SeedRow,
    SeedStatements,
    read_seed_statements,
)

#: Why a key is the one it is.
KeyBasis = Literal["declared", "primary_key", "unique"]


@dataclass(frozen=True)
class Dereference:
    """A foreign key compared as the parent row it points at, not as the number it holds.

    ``parent_column`` is the key the foreign key references (generated, so it
    differs per database); ``parent_key`` the parent's stable key, which is what
    is compared.
    """

    parent: RelationName
    parent_column: str
    parent_key: tuple[str, ...]


@dataclass(frozen=True)
class Field:
    """One compared value of a row: a column, or a foreign key read through its parent."""

    column: str
    via: Dereference | None = None


@dataclass(frozen=True)
class ScopedTable:
    """One table the seed populates, and how its rows are matched and compared."""

    relation: RelationName
    key: tuple[Field, ...]
    key_basis: KeyBasis
    columns: tuple[Field, ...]
    uncompared: tuple[tuple[str, str], ...] = ()
    mode: Literal["full", "subset"] = "full"
    written_at: tuple[str, ...] = ()
    staging: RelationName | None = None


@dataclass(frozen=True)
class NotCompared:
    """A table in scope that cannot be compared, and why: the run is incomplete."""

    table: str
    reason: str
    where: str | None = None


@dataclass(frozen=True)
class SeedScope:
    """Everything a seed-drift run compares, cannot compare, or was told to leave out."""

    tables: tuple[ScopedTable, ...] = ()
    not_compared: tuple[NotCompared, ...] = ()
    skipped: tuple[tuple[str, str], ...] = ()
    unused: tuple[str, ...] = ()


#: Statements the seed reader cannot read that may still write rows, into tables no
#: static reader can name: a run that holds one cannot claim its scope is whole.
_HIDDEN_WRITERS: dict[str, str] = {
    "DoStmt": "a DO block",
    "CallStmt": "a CALL",
    "CopyStmt": "a COPY that reads a file or a program",
    "ExecuteStmt": "an EXECUTE of a prepared statement",
}


@dataclass
class _Insert:
    """A statement that adds rows to a table: what it writes, and the rows a seed file spells.

    ``columns`` is ``None`` when the statement names none: an ``INSERT`` then
    supplies every column in table order, a ``COPY`` every column but the
    generated ones. ``trusted`` is false for a statement whose values cannot be
    read (an ``INSERT … SELECT`` in a seed file), so a key it writes may be
    computed at run time; a resolver copying the staging rows is trusted, since
    the seed wrote those values.
    """

    columns: tuple[str, ...] | None
    rows: tuple[SeedRow, ...] = ()
    form: Literal["insert", "copy"] = "insert"
    trusted: bool = True


@dataclass
class _Target:
    relation: RelationName
    inserts: list[_Insert] = field(default_factory=list)
    written_at: list[str] = field(default_factory=list)
    staging: RelationName | None = None


def _where(label: str | None, line: int) -> str:
    return f"{label}:{line}" if label else f"line {line}"


def config_identity(written: str) -> tuple[str, str] | None:
    """``(schema, name)`` of a ``seed_drift`` table key, read as the scanner reads a name."""
    parts = sql_lexer.name_parts(written)
    if parts is None or len(parts) != 2:  # noqa: PLR2004 - schema and name
        return None
    schema, name = parts
    return identifier_identity(schema), identifier_identity(name)


def _statements(
    seed_files: Sequence[tuple[str | None, str]],
) -> tuple[list[tuple[str | None, SeedStatements]], list[NotCompared]]:
    read: list[tuple[str | None, SeedStatements]] = []
    refused: list[NotCompared] = []
    for label, text in seed_files:
        try:
            read.append((label, read_seed_statements(text)))
        except SeedParseError as exc:
            refused.append(
                NotCompared(
                    label or "seed",
                    f"PostgreSQL's parser rejects this seed file, so the tables it writes "
                    f"are not known: {exc}",
                    _where(label, exc.line),
                )
            )
    return read, refused


def _targets(
    statements: Iterable[tuple[str | None, SeedStatements]],
) -> dict[tuple[str, str], _Target]:
    """Every table the seed files add rows to, in the order first written."""
    targets: dict[tuple[str, str], _Target] = {}
    for label, read in statements:
        for write in read.writes:
            target = targets.setdefault(write.relation.identity, _Target(write.relation))
            target.inserts.append(_Insert(write.columns, write.rows, write.form))
            target.written_at.append(_where(label, write.line))
        for unread in read.unread:
            if unread.relation is None:
                continue
            target = targets.setdefault(unread.relation.identity, _Target(unread.relation))
            if unread.inserts:
                form: Literal["insert", "copy"] = (
                    "copy" if unread.statement == "CopyStmt" else "insert"
                )
                target.inserts.append(_Insert(unread.columns, (), form, trusted=False))
            target.written_at.append(_where(label, unread.line))
    return targets


def _hidden(statements: Iterable[tuple[str | None, SeedStatements]]) -> list[NotCompared]:
    """A statement that may write rows into tables the reader cannot name, one entry each."""
    return [
        NotCompared(
            "seed",
            f"{_HIDDEN_WRITERS[unread.statement]} may write rows into tables the seed reader "
            "cannot see, so the scope may be incomplete",
            _where(label, unread.line),
        )
        for label, read in statements
        for unread in read.unread
        if unread.relation is None and unread.statement in _HIDDEN_WRITERS
    ]


def _resolved(
    targets: dict[tuple[str, str], _Target], read: SchemaRead, settings: SeedDriftSettings
) -> tuple[dict[tuple[str, str], _Target], list[NotCompared]]:
    """Each staging target replaced by its final table, with the resolver's ``INSERT``s."""
    prep = identifier_identity(settings.prep_seed_schema)
    if not any(identity[0] == prep for identity in targets):
        return targets, []
    resolution = read_resolution(
        read, catalog_schema=settings.catalog_schema, prep_seed_schema=settings.prep_seed_schema
    )
    out: dict[tuple[str, str], _Target] = {}
    refused: list[NotCompared] = []
    for identity, target in targets.items():
        if identity[0] != prep:
            out.setdefault(identity, _Target(target.relation)).inserts.extend(target.inserts)
            out[identity].written_at.extend(target.written_at)
            continue
        final = resolution.finals.of(identity[1])
        if final is None:
            candidates = ", ".join(resolution.finals.ambiguous.get(identity[1], ()))
            refused.append(
                NotCompared(
                    target.relation.qualified,
                    f"a staging table whose rows could land in any of {candidates}",
                    target.written_at[0] if target.written_at else None,
                )
            )
            continue
        relation = RelationName(final.schema, final.name)
        moved = out.setdefault(relation.identity, _Target(relation))
        moved.staging = target.relation
        moved.written_at.extend(target.written_at)
        for resolver in resolution.resolvers:
            if resolver.table != identity[1]:
                continue
            moved.inserts.extend(
                _Insert(tuple(t.name for t in node.cols) if node.cols else None)
                for node in resolver_inserts(resolver, identity[1], prep)
                if RelationName(node.relation.schemaname, node.relation.relname).identity
                == relation.identity
            )
    return out, refused


def _writable(column: Column) -> bool:
    """Whether a statement can supply this column's value at all."""
    return column.generated is None and column.identity != "always"


def _written_columns(table: Table, insert: _Insert) -> tuple[str, ...]:
    """The columns *insert* supplies, in the order its values are written.

    With no column list an ``INSERT`` supplies every column in table order, as
    many as each row has values (a ``DEFAULT`` among them supplies nothing, and
    is read as computed); a ``COPY`` supplies every column but the generated ones.
    """
    if insert.columns is not None:
        return insert.columns
    if insert.form == "copy":
        return tuple(c.folded for c in table.columns if c.generated is None)
    names = tuple(c.folded for c in table.columns)
    widths = {len(row.values) for row in insert.rows}
    return names[: max(widths)] if widths else names


def _computed(table: Table, inserts: Sequence[_Insert]) -> dict[str, str]:
    """Each column a seed row writes as a computed value (a call, ``DEFAULT``), and the node."""
    found: dict[str, str] = {}
    for insert in inserts:
        names = _written_columns(table, insert)
        for row in insert.rows:
            for name, value in zip(names, row.values, strict=False):
                if isinstance(value, Computed):
                    found.setdefault(name, value.node)
    return found


def _every_insert_writes(table: Table, columns: Sequence[str], inserts: Sequence[_Insert]) -> bool:
    return bool(inserts) and all(
        set(columns) <= set(_written_columns(table, insert)) for insert in inserts
    )


def _stable(
    table: Table, columns: Sequence[str], inserts: Sequence[_Insert], computed: dict[str, str]
) -> bool:
    """Whether every statement adding rows writes *columns* with a value it spells.

    A column PostgreSQL fills, one a seed row computes, and one an unreadable
    ``INSERT … SELECT`` writes can differ per database, so none is a key.
    """
    return (
        _every_insert_writes(table, columns, inserts)
        and all(insert.trusted for insert in inserts)
        and not any(column in computed for column in columns)
        and all(
            (column := table.column(name)) is not None and _writable(column) for name in columns
        )
    )


def _unique_candidates(table: Table) -> list[tuple[str, ...]]:
    """Single-column ``UNIQUE`` constraints and indexes on a ``NOT NULL`` column, in order."""
    found = [c.columns for c in table.constraints_of("unique")] + [
        i.columns for i in table.indexes if i.unique and i.where is None
    ]
    return [
        cols
        for cols in dict.fromkeys(found)
        if len(cols) == 1 and (column := table.column(cols[0])) is not None and column.not_null
    ]


def _base_key(
    table: Table, target: _Target, declared: list[str] | None, computed: dict[str, str]
) -> tuple[tuple[str, ...], KeyBasis] | str:
    """The key, before any foreign key in it is dereferenced, or why there is none."""
    if declared is not None:
        folded = tuple(identifier_identity(name) for name in declared)
        missing = [c for c in folded if table.column(c) is None]
        if missing:
            return f"the declared key names columns the table does not have: {', '.join(missing)}"
        return folded, "declared"
    pk = primary_key(table)
    if pk and _stable(table, pk, target.inserts, computed):
        return pk, "primary_key"
    for cols in _unique_candidates(table):
        if _stable(table, cols, target.inserts, computed):
            return cols, "unique"
    return (
        "no stable key: no primary or unique key that every statement adding its rows writes "
        "with a value it spells; declare one in the environment as\n"
        f"  seed_drift:\n    tables:\n      {table.relation.qualified}: {{key: [<column>]}}"
    )


def _generated_reference(table: Table, column: str, tables: dict[tuple[str, str], Table]) -> Any:
    """The single-column foreign key from *column* to a key PostgreSQL generates, if any."""
    for fk in table.constraints_of("foreign_key"):
        if fk.columns != (column,) or fk.ref_table is None or len(fk.ref_columns) != 1:
            continue
        parent = tables.get(fk.ref_table.identity)
        referenced = parent.column(fk.ref_columns[0]) if parent else None
        if referenced is not None and referenced.value_source.filled_by_postgresql:
            return fk
    return None


def _composite_reference(table: Table, column: str, tables: dict[tuple[str, str], Table]) -> str:
    """Why *column* cannot be compared through a composite foreign key, or ``""``.

    A multi-column key into columns that PostgreSQL generates, or that are
    themselves such references, holds per-database numbers; it is not
    dereferenced, so it is not compared rather than compared wrongly.
    """
    for fk in table.constraints_of("foreign_key"):
        if column not in fk.columns or len(fk.columns) == 1 or fk.ref_table is None:
            continue
        parent = tables.get(fk.ref_table.identity)
        if parent is None:
            continue
        for name in fk.ref_columns:
            referenced = parent.column(name)
            if (referenced is not None and referenced.value_source.filled_by_postgresql) or (
                _generated_reference(parent, name, tables) is not None
            ):
                return (
                    f"part of a composite foreign key to {fk.ref_table.qualified}, whose "
                    "columns hold keys PostgreSQL generates; it is not dereferenced"
                )
    return ""


def _field(
    table: Table,
    column: str,
    tables: dict[tuple[str, str], Table],
    keys: dict[tuple[str, str], tuple[str, ...]],
) -> Field | str:
    """*column* as compared, or why it cannot be: a generated parent key with no stable key."""
    composite = _composite_reference(table, column, tables)
    if composite:
        return composite
    fk = _generated_reference(table, column, tables)
    if fk is None:
        return Field(column)
    parent_key = keys.get(fk.ref_table.identity)
    if parent_key is None:
        return (
            f"references {fk.ref_table.qualified}.{fk.ref_columns[0]}, a key PostgreSQL "
            f"generates, and {fk.ref_table.qualified} has no key the seed writes"
        )
    return Field(column, Dereference(fk.ref_table, fk.ref_columns[0], parent_key))


def _compared(
    table: Table,
    target: _Target,
    key: tuple[str, ...],
    computed: dict[str, str],
    tables: dict[tuple[str, str], Table],
    keys: dict[tuple[str, str], tuple[str, ...]],
) -> tuple[tuple[Field, ...], tuple[tuple[str, str], ...]]:
    written = {c for insert in target.inserts for c in _written_columns(table, insert)}
    fields: list[Field] = []
    uncompared: list[tuple[str, str]] = []
    for column in table.columns:
        name = column.folded
        if name in key or name not in written or not _writable(column):
            continue
        if not _every_insert_writes(table, (name,), target.inserts):
            uncompared.append(
                (name, "not every statement adding rows writes it, so a row may hold its default")
            )
            continue
        if (column.type_key or "") == "money":
            uncompared.append((name, "money renders in each server's lc_monetary"))
            continue
        if name in computed:
            uncompared.append(
                (name, f"a seed row computes it ({computed[name]}), so it differs per database")
            )
            continue
        compared = _field(table, name, tables, keys)
        if isinstance(compared, str):
            uncompared.append((name, compared))
        else:
            fields.append(compared)
    return tuple(fields), tuple(uncompared)


def seed_scope(
    seed_files: Sequence[tuple[str | None, str]], read: SchemaRead, settings: SeedDriftSettings
) -> SeedScope:
    """What a seed-drift run compares: each table the seed populates, its key and its columns.

    *seed_files* are ``(label, text)`` in the order they are applied; *read* is the
    schema tree they are applied on, read once (``schema_sources.read_schema``).
    """
    statements, not_compared = _statements(seed_files)
    not_compared.extend(_hidden(statements))
    targets, refused = _resolved(_targets(statements), read, settings)
    not_compared.extend(refused)
    tables = {t.relation.identity: t for t in read.catalogued.tables.values()}
    config = {
        identity: (written, entry)
        for written, entry in settings.tables.items()
        if (identity := config_identity(written)) is not None
    }
    used: set[tuple[str, str]] = set()
    skipped: list[tuple[str, str]] = []
    bases: dict[tuple[str, str], tuple[tuple[str, ...], KeyBasis, dict[str, str]]] = {}
    modes: dict[tuple[str, str], Literal["full", "subset"]] = {}
    for identity, target in targets.items():
        entry = config.get(identity) or (
            config.get(target.staging.identity) if target.staging else None
        )
        if entry is not None:
            used.add(config_identity(entry[0]) or identity)
        if entry is not None and entry[1].skip:
            skipped.append((target.relation.qualified, entry[1].reason or ""))
            continue
        table = tables.get(identity)
        if table is None:
            not_compared.append(
                NotCompared(
                    target.relation.qualified,
                    "the schema tree declares no such table",
                    target.written_at[0] if target.written_at else None,
                )
            )
            continue
        computed = _computed(table, target.inserts)
        base = _base_key(table, target, entry[1].key if entry else None, computed)
        if isinstance(base, str):
            not_compared.append(NotCompared(target.relation.qualified, base, None))
            continue
        bases[identity] = (base[0], base[1], computed)
        modes[identity] = entry[1].mode if entry else "full"
    keys = {
        identity: key
        for identity, (key, _basis, _computed_cols) in bases.items()
        if not any(_generated_reference(tables[identity], c, tables) for c in key)
    }
    scoped: list[ScopedTable] = []
    for identity, (key, basis, computed) in bases.items():
        table, target = tables[identity], targets[identity]
        key_fields = [_field(table, column, tables, keys) for column in key]
        unreadable = [f for f in key_fields if isinstance(f, str)]
        if unreadable:
            not_compared.append(
                NotCompared(target.relation.qualified, f"no stable key: {unreadable[0]}", None)
            )
            continue
        columns, uncompared = _compared(table, target, key, computed, tables, keys)
        scoped.append(
            ScopedTable(
                relation=target.relation,
                key=tuple(f for f in key_fields if isinstance(f, Field)),
                key_basis=basis,
                columns=columns,
                uncompared=uncompared,
                mode=modes[identity],
                written_at=tuple(target.written_at),
                staging=target.staging,
            )
        )
    unused = tuple(
        f"seed_drift.tables.{written} matches no table the seed writes: remove it"
        for written in settings.tables
        if config_identity(written) not in used
    )
    if not scoped and not skipped and not not_compared:
        not_compared.append(
            NotCompared(
                "seed",
                "the seed tree writes no table, so nothing was compared: check --env, and "
                "--seeds-dir for seed files outside include_dirs",
            )
        )
    return SeedScope(tuple(scoped), tuple(not_compared), tuple(skipped), unused)
