"""Schema differ for detecting database schema changes.

This module provides functionality to:
- Parse SQL DDL statements into structured schema models
- Compare two schemas and detect differences
- Generate migrations from schema diffs
"""

import logging
from collections.abc import Callable, Iterable
from typing import Any

import pglast
from pglast.stream import RawStream

from confiture.core.ddl_objects import OBJECT_KEYWORD, objects_in, pair_definitions
from confiture.core.ddl_walk import (
    ColumnEdit,
    ColumnFact,
    ObjectEdit,
    added_constraint,
    column_edit,
    object_edits,
    read_column_constraints,
    read_constraint,
    readable_type,
    render_default,
    written_type,
)
from confiture.core.differ_sql import column_body
from confiture.core.linting.duplicates import WINS_TEXT, CreateFlags, wins
from confiture.core.schema_identity import DEFAULT_SCHEMA
from confiture.core.schema_model import Constraint
from confiture.core.sql_lexer import blank_copy_blocks
from confiture.core.type_lattice import same_type
from confiture.models.schema import (
    CheckConstraint,
    Column,
    ColumnType,
    EnumType,
    ForeignKey,
    Index,
    ParsedSchema,
    SchemaChange,
    SchemaDiff,
    Sequence,
    Table,
    UniqueConstraint,
    qualified_name,
)
from confiture.models.warnings import BuildWarning

# ---------------------------------------------------------------------------
# Module-level constants: compiled once for performance
# ---------------------------------------------------------------------------


logger = logging.getLogger(__name__)


#: The differ's own model classes, in the kind vocabulary ``ObjectEdit`` speaks.
#: A ``Table`` answers for a table and a matview alike here, because this model
#: has only the one; a view and a routine live in ``ParsedSchema.objects``, and
#: ``ddl_objects`` folds their drops.
_MODEL_KINDS: dict[str, str] = {"Table": "table", "EnumType": "type", "Sequence": "sequence"}


def _identity(schema: str | None, name: str) -> tuple[str, str]:
    """What makes two statements the same relation, by the inventory's rule.

    :data:`~confiture.core.schema_identity.DEFAULT_SCHEMA` for a statement that
    names none, so ``CREATE TABLE t`` and ``CREATE TABLE public.t`` are one table
    and ``tenant.t`` another — the same fold ``inventory.object_key`` and
    ``ddl_objects.ObjectRef`` apply. The default is imported rather than spelled
    ``"public"`` here: one default, one module.

    The identity is not the spelling. ``Table.qualified`` prints what the author
    wrote and never invents a qualifier; this decides only whether two
    statements are about one relation.
    """
    return (schema or DEFAULT_SCHEMA).lower(), name


def _written_as(stmt: Any) -> CreateFlags:
    """How a ``CREATE`` node spelled itself, as :func:`wins` reads it.

    ``CREATE TABLE`` and ``CREATE SEQUENCE`` carry ``if_not_exists``;
    ``CREATE TYPE … AS ENUM`` carries neither flag, and none of the three kinds
    this module models has an ``OR REPLACE`` form — so ``wins`` never answers
    ``last`` for them. A view or a routine does, and is compared by definition
    through ``ddl_objects.pair_definitions`` instead.
    """
    return CreateFlags(
        replace=bool(getattr(stmt, "replace", False)),
        if_not_exists=bool(getattr(stmt, "if_not_exists", False)),
    )


_DUPLICATE_KINDS: dict[str, str] = {"Table": "Table", "EnumType": "Type", "Sequence": "Sequence"}


def _resolve_duplicates(result: ParsedSchema, written_as: dict[int, CreateFlags]) -> None:
    """Keep the definition the build keeps, and say that there was more than one.

    Two definitions of one ``(schema, name)`` in one tree is #313's defect with
    the schema taken out of it: an identity two objects share, resolved by "last
    one wins" rather than by asking which one ``confiture build`` ends up with.
    A later ``IF NOT EXISTS`` is a no-op, so the *first* is what the database
    has; a later plain ``CREATE`` fails the build at that statement, so the
    first is what exists when it does.

    The verdict is ``duplicates.wins`` — ``build_001``'s own rule, not a second
    one — and the collapse is reported either way. It is a warning, not a
    failure: a duplicate definition is real but it is ``confiture lint``'s
    problem and ``build --fail-on-duplicates``' problem, both of which already
    exist and are opt-in. Failing ``--require-migration`` for it would fail the
    gate for a reason the gate is not about.
    """
    for attribute in ("tables", "enum_types", "sequences"):
        models: list[Any] = getattr(result, attribute)
        groups: dict[tuple[str, str], list[Any]] = {}
        for model in models:
            groups.setdefault(_identity(model.schema, model.name), []).append(model)
        if all(len(group) == 1 for group in groups.values()):
            continue
        kept: list[Any] = []
        for group in groups.values():
            if len(group) == 1:
                kept.extend(group)
                continue
            verdict = wins([written_as.get(id(model), CreateFlags()) for model in group])
            used = "last" if verdict == "last" else "first"
            kept.append(group[-1] if verdict == "last" else group[0])
            result.warnings.append(
                BuildWarning.of(
                    "DIFFER_402",
                    kind=_DUPLICATE_KINDS[type(group[0]).__name__],
                    identity=group[0].qualified,
                    count=len(group),
                    outcome=WINS_TEXT[verdict],
                    used=used,
                )
            )
        # Filtered by object identity, not by ``==``: two duplicate definitions
        # of one table may well be structurally equal.
        keep = {id(model) for model in kept}
        setattr(result, attribute, [model for model in models if id(model) in keep])


def _merged_warnings(old_schema: ParsedSchema, new_schema: ParsedSchema) -> list[BuildWarning]:
    """Both sides' parse warnings, each said once.

    A duplicate present on both sides of a diff is one duplicate, not two: it is
    not a change, but it is a reason the comparison may be reading a tree the
    build does not produce, and saying so twice helps nobody.
    """
    merged: list[BuildWarning] = []
    for warning in (*old_schema.warnings, *new_schema.warnings):
        if warning not in merged:
            merged.append(warning)
    return merged


def _relation_spelling(relation: Any) -> str:
    """A ``RangeVar`` as the statement wrote it: ``tenant.t``, or ``t`` unqualified.

    What the constraint and index models carry, because it is what a finding
    prints and what generated DDL alters. Never an invented ``public.`` — see
    :func:`~confiture.models.schema.qualified_name`.
    """
    return qualified_name(getattr(relation, "schemaname", None), relation.relname)


def _schema_matches(model_schema: str | None, edit_schema: str | None) -> bool:
    """Whether a statement qualified *edit_schema* reaches an object in *model_schema*.

    Either side naming no schema matches any: PostgreSQL resolves a bare
    spelling through ``search_path``, and a statement that wrote no qualifier did
    not say which schema it meant. That is ``ddl_objects._matches``' wildcard,
    and the reason ``DROP TABLE t`` still drops ``tenant.t`` in a tree that
    declares only that one.

    :func:`_identity` folds a missing schema to a default instead, because a
    dict key cannot express a wildcard. Same rule, two constraints.
    """
    if model_schema is None or edit_schema is None:
        return True
    return model_schema.lower() == edit_schema.lower()


# ---------------------------------------------------------------------------
# The model constraint, landed on this module's own ``Table``
# ---------------------------------------------------------------------------
#
# ``ddl_walk.read_constraint`` is the one reader of a ``Constraint`` node (#315,
# #316) and returns what the node declares. This module still compares its own
# ``models.schema`` types, so a returned value is applied to them here; nothing
# below decides what a node means.


def _apply_constraint(constraint: Constraint, table: Table) -> None:
    """Attach one model constraint to *table*, in this module's vocabulary."""
    if constraint.kind == "foreign_key":
        table.foreign_keys.append(
            ForeignKey(
                name=constraint.name,
                table=table.qualified,
                columns=list(constraint.columns),
                ref_table=constraint.ref_table or "",
                ref_columns=list(constraint.ref_columns),
                on_delete=constraint.on_delete,
                on_update=constraint.on_update,
            )
        )
    elif constraint.kind == "check" and constraint.expression is not None:
        table.check_constraints.append(
            CheckConstraint(
                name=constraint.name, table=table.qualified, expression=constraint.expression
            )
        )
    elif constraint.kind == "unique":
        # ``Column.unique`` stays untouched: ``u INT UNIQUE`` and ``UNIQUE (u)`` are
        # one declaration and must compare equal.
        table.unique_constraints.append(
            UniqueConstraint(
                name=constraint.name, table=table.qualified, columns=list(constraint.columns)
            )
        )
    elif constraint.kind == "primary_key":
        # A primary key travels on its columns, whichever spelling declared it:
        # ``PRIMARY KEY (id)`` otherwise compared unequal to ``id INT PRIMARY KEY``
        # and generated ``DROP NOT NULL`` on a primary-key column.
        for name in constraint.columns:
            target = table.get_column(name)
            if target is not None:
                target.primary_key = True
                target.nullable = False


def _apply_column_fact(fact: ColumnFact, column: Column) -> None:
    """What a column's own clauses say about it, applied to this module's ``Column``."""
    if fact.not_null:
        column.nullable = False
    if fact.default is not None:
        column.default = fact.default
    column.identity = fact.identity
    column.generated = fact.generated
    column.generated_kind = fact.generated_kind


def _read_constraint(node: Any, table: Table) -> None:
    """A table-level or ``ALTER TABLE … ADD CONSTRAINT`` node, read and applied."""
    read = read_constraint(node)
    if isinstance(read, Constraint):
        _apply_constraint(read, table)


def _object_identity(obj: Any, fields: tuple[str, ...]) -> tuple[Any, ...]:
    """What makes two of a table's own objects the same object.

    Its name, when the schema wrote one. PostgreSQL lets a constraint and an
    index go unnamed — ``pid INT REFERENCES b.parent(id)``, ``CREATE INDEX ON t
    (x)`` — and generates the name at apply time; two unnamed ones on a table are
    two objects, and a map keyed on ``""`` keeps one of them. That is #313's
    defect one field along, and #315 makes the unnamed form the common case.

    An unnamed object is therefore identified by what it *says*. Nothing here
    invents a name: the identity is internal to the comparison, and the DDL
    generated from it still writes no ``CONSTRAINT`` clause — PostgreSQL names it
    the same way it would have.
    """
    if obj.name:
        return (obj.name,)
    return (
        "",
        *(
            tuple(value) if isinstance(value, list) else value
            for value in (getattr(obj, field) for field in fields)
        ),
    )


def _types_differ(old: Column, new: Column) -> bool:
    """Whether two columns declare different types, typmod included.

    ``type_lattice.same_type`` is the predicate, and says so itself: *a column
    type must keep [typmods] or ``varchar(50)`` and ``varchar(100)`` compare
    equal*. Deciding that ``int4`` and ``integer`` are one type is the lattice's
    job too, which is why this compares the written spellings rather than adding
    a second alias table beside ``_COLUMN_TYPE_MAP``.

    A column built by hand may carry no spelling; then the canonical
    :class:`ColumnType` is all there is to compare.
    """
    if old.raw_sql_type and new.raw_sql_type:
        return not same_type(old.raw_sql_type, new.raw_sql_type)
    return old.type != new.type or old.raw_sql_type != new.raw_sql_type


def _column_detail(column: Column) -> dict[str, Any]:
    """One column in the shape ``DifferSQLGenerator`` renders it from.

    Identity and generation are present only on a column that has them, so an
    ordinary column's details read exactly as they always have.
    """
    detail: dict[str, Any] = {
        "name": column.name,
        "type": column.raw_sql_type or column.type.value,
        "nullable": column.nullable,
        "default": column.default,
    }
    if column.identity is not None:
        detail["identity"] = column.identity
    if column.generated is not None:
        detail["generated"] = column.generated
        detail["generated_kind"] = column.generated_kind
    return detail


def _column_definition(column: Column) -> str:
    """The column's definition without its name — what ``ADD COLUMN`` takes after the name."""
    return column_body(_column_detail(column))


def _column_details(table: Table) -> list[dict[str, Any]]:
    """The columns of ``table`` in the shape ``DifferSQLGenerator`` renders a ``CREATE TABLE`` from."""
    return [_column_detail(column) for column in table.columns]


def _constraint_details(table: Table) -> list[dict[str, Any]]:
    """The table's own constraints, in the shape the generator renders a clause from.

    :func:`_column_details`' sibling. ``_up_add_table`` rendered the columns and
    nothing else, so a new table's foreign keys, CHECKs, UNIQUEs and primary key
    were dropped from the generated ``CREATE TABLE`` — for every spelling, which
    is why this outlived #315's parse fix rather than being caused by it.

    The primary key is emitted at table level rather than on the column so that a
    composite one has somewhere to go.
    """
    details: list[dict[str, Any]] = [
        {
            "kind": "PRIMARY KEY",
            "name": "",
            "columns": [column.name for column in table.columns if column.primary_key],
        }
    ]
    details.extend(
        {
            "kind": "FOREIGN KEY",
            "name": fk.name,
            "columns": fk.columns,
            "ref_table": fk.ref_table,
            "ref_columns": fk.ref_columns,
            "on_delete": fk.on_delete,
            "on_update": fk.on_update,
        }
        for fk in table.foreign_keys
    )
    details.extend(
        {"kind": "UNIQUE", "name": uc.name, "columns": uc.columns}
        for uc in table.unique_constraints
    )
    details.extend(
        {"kind": "CHECK", "name": cc.name, "expression": cc.expression}
        for cc in table.check_constraints
    )
    return [detail for detail in details if detail.get("columns") or detail.get("expression")]


def _object_sort_key(ref: Any) -> tuple[str, str, str, str]:
    """A stable order for object changes: kind, then schema, then name."""
    return (ref.kind, ref.schema, ref.name, str(ref.signature))


def _object_details(ref: Any) -> dict[str, Any]:
    return {
        "kind": ref.kind,
        "name": ref.qualified,
        "keyword": OBJECT_KEYWORD.get(ref.kind, ref.kind.replace("_", " ").upper()),
    }


def _added_change(ref: Any, obj: Any) -> SchemaChange:
    return SchemaChange(
        type=f"ADD_{ref.kind.upper()}",
        table=ref.qualified,
        new_value=obj.create_sql,
        details=_object_details(ref),
    )


def _dropped_change(ref: Any, obj: Any) -> SchemaChange:
    return SchemaChange(
        type=f"DROP_{ref.kind.upper()}",
        table=ref.qualified,
        old_value=obj.create_sql,
        details=_object_details(ref),
    )


def _replaced_change(ref: Any, before: Any, after: Any) -> SchemaChange:
    return SchemaChange(
        type=f"REPLACE_{ref.kind.upper()}",
        table=ref.qualified,
        old_value=before.create_sql,
        new_value=after.create_sql,
        details=_object_details(ref),
    )


class SchemaDiffer:
    """Parses SQL and detects schema differences.

    Example:
        >>> differ = SchemaDiffer()
        >>> tables = differ.parse_sql("CREATE TABLE users (id INT)")
        >>> print(tables[0].name)
        users
    """

    def parse_sql(self, sql: str) -> list[Table]:
        """Parse SQL DDL into structured Table objects (backwards-compatible shim).

        Args:
            sql: SQL DDL string containing CREATE TABLE statements

        Returns:
            List of parsed Table objects

        Example:
            >>> differ = SchemaDiffer()
            >>> sql = "CREATE TABLE users (id INT PRIMARY KEY, name TEXT)"
            >>> tables = differ.parse_sql(sql)
            >>> print(len(tables))
            1
        """
        return self.parse_schema(sql).tables

    def parse_schema(self, sql: str) -> ParsedSchema:
        """Parse SQL DDL into a ParsedSchema (tables, enums, sequences, objects).

        Uses pglast (PostgreSQL's own parser) when available for accurate,
        limit-free parsing.
        Non-DDL statements (INSERT, COPY, GRANT, etc.) are silently ignored.

        Args:
            sql: SQL DDL string (may contain any SQL, including non-DDL)

        Returns:
            ParsedSchema with tables, enum_types, sequences
        """
        if not sql or not sql.strip():
            return ParsedSchema()

        # Blank inline-COPY data blocks before ANY parser or regex pass sees
        # the text: pglast rejects them outright (#194), and the free-form data
        # lines could false-match the regex passes below.
        #
        # Blanked, not deleted: the block keeps its length and its newlines, so
        # the `DIFFER_400` a rejected statement raises below carries a position
        # into the text the author wrote, not one shifted by however many data
        # rows an earlier seed file happened to carry.
        sql = blank_copy_blocks(sql)

        result = ParsedSchema()

        # One parse, one walk (ANA-04): pglast.parser.ParseError propagates —
        # what PostgreSQL rejects is not a schema to diff, and `migrate diff`
        # reports it as DIFFER_400. A commented-out statement is not a node.
        raws = list(pglast.parse_sql(sql) or [])
        result.objects = objects_in(sql, raws)
        # Where each model was declared, so a `DROP` folded below reaches what the
        # tree had written *before* it and not what it writes after: the everyday
        # `DROP TABLE IF EXISTS x; CREATE TABLE x (…);` declares `x` (#301).
        declared_at: dict[int, int] = {}
        # How each `CREATE` was written, so `duplicates.wins` can say which of
        # several definitions of one object the build actually keeps.
        written_as: dict[int, CreateFlags] = {}
        for raw in raws:
            if type(raw.stmt).__name__ == "CreateStmt":
                table = self._parse_create_table_pglast(raw.stmt)
                if table:
                    result.tables.append(table)
                    declared_at[id(table)] = raw.stmt_location or 0
                    written_as[id(table)] = _written_as(raw.stmt)
        for raw in raws:
            self._collect_statement(raw, result, declared_at, written_as)
        _resolve_duplicates(result, written_as)
        return result

    def _collect_statement(
        self,
        raw: Any,
        result: ParsedSchema,
        declared_at: dict[int, int],
        written_as: dict[int, CreateFlags],
    ) -> None:
        stmt = raw.stmt
        kind = type(stmt).__name__
        offset = raw.stmt_location or 0
        if kind == "IndexStmt":
            self._collect_index(stmt, result, declared_at, offset)
        elif kind == "CreateEnumStmt":
            enum_type = _enum_type_from_stmt(stmt)
            result.enum_types.append(enum_type)
            declared_at[id(enum_type)] = offset
            written_as[id(enum_type)] = _written_as(stmt)
        elif kind == "CreateSeqStmt":
            sequence = _sequence_from_stmt(stmt)
            result.sequences.append(sequence)
            declared_at[id(sequence)] = offset
            written_as[id(sequence)] = _written_as(stmt)
        elif kind == "AlterTableStmt":
            self._collect_alter_table(stmt, result)
        else:
            self._fold_object_edits(stmt, result, declared_at, offset)

    def _fold_object_edits(
        self, stmt: Any, result: ParsedSchema, declared_at: dict[int, int], offset: int
    ) -> None:
        """Apply a ``DROP`` / ``RENAME`` / ``SET SCHEMA`` to what this tree declared.

        Every model here carries the schema its statement wrote (#313), so an
        edit reaches the object it names and no same-named object in another
        schema. ``SET SCHEMA`` folds for the same reason: a move between schemas
        became expressible in this model the moment a ``Table`` had one. The
        lint inventory folds all four; only the application differs.
        """
        for edit in object_edits(stmt):
            declared = [
                model
                for model in (*result.tables, *result.enum_types, *result.sequences)
                if declared_at.get(id(model), 0) < offset
            ]
            if edit.kind == "drop":
                self._drop_declared(edit, result, declared)
            elif edit.kind == "rename":
                self._rename_declared(edit, declared)
            elif edit.kind == "rename_column":
                self._rename_column(edit, declared)
            elif edit.kind == "set_schema":
                self._move_declared(edit, declared)

    @staticmethod
    def _named(edit: ObjectEdit, model: Any) -> bool:
        """Whether *edit* names *model*: the same kind, the same name, a matching schema."""
        return (
            getattr(model, "name", None) == edit.name
            and _MODEL_KINDS.get(type(model).__name__) == edit.object_kind
            and _schema_matches(getattr(model, "schema", None), edit.schema)
        )

    def _drop_declared(self, edit: ObjectEdit, result: ParsedSchema, declared: list[Any]) -> None:
        gone = {id(model) for model in declared if self._named(edit, model)}
        result.tables = [t for t in result.tables if id(t) not in gone]
        result.enum_types = [e for e in result.enum_types if id(e) not in gone]
        result.sequences = [s for s in result.sequences if id(s) not in gone]
        if edit.object_kind == "index":
            # An index name is unique per schema, not per table, and `DROP INDEX`
            # names no table — so the drop is scoped to the schema and then
            # applied to every table in it.
            for table in result.tables:
                if _schema_matches(table.schema, edit.schema):
                    table.indexes = [ix for ix in table.indexes if ix.name != edit.name]

    def _rename_declared(self, edit: ObjectEdit, declared: list[Any]) -> None:
        for model in declared:
            if self._named(edit, model) and edit.new_name:
                model.name = edit.new_name

    def _move_declared(self, edit: ObjectEdit, declared: list[Any]) -> None:
        """``ALTER … SET SCHEMA`` — the object keeps its name and changes schema."""
        for model in declared:
            if self._named(edit, model) and edit.new_schema:
                model.schema = edit.new_schema

    def _rename_column(self, edit: ObjectEdit, declared: list[Any]) -> None:
        for model in declared:
            if not isinstance(model, Table) or not self._named(edit, model):
                continue
            column = model.get_column(edit.column) if edit.column else None
            if column is not None and edit.new_name:
                column.name = edit.new_name

    # ------------------------------------------------------------------
    # pglast-based CREATE TABLE parser (primary path)
    # ------------------------------------------------------------------

    def _parse_create_table_pglast(self, stmt: Any) -> Table | None:
        """Build a Table model from a pglast CreateStmt node.

        A column is appended before its own constraints are read, because a
        constraint reads back the column it covers — ``PRIMARY KEY`` marks it
        ``NOT NULL`` whichever of the two spellings declared it.
        """
        try:
            table = Table(name=stmt.relation.relname, schema=stmt.relation.schemaname)

            for elt in stmt.tableElts or []:
                if type(elt).__name__ == "ColumnDef":
                    self._add_column_pglast(elt, table)
                elif type(elt).__name__ == "Constraint":
                    _read_constraint(elt, table)

            return table
        except (AttributeError, KeyError, TypeError, ValueError):
            return None

    def _add_column_pglast(self, col_def: Any, table: Table) -> Column | None:
        """Append the column *col_def* declares, then read what it declares about it."""
        column = self._parse_column_pglast(col_def)
        if column is None:
            return None
        self._replace_column(table, column)
        fact, constraints = read_column_constraints(col_def)
        _apply_column_fact(fact, column)
        for constraint in constraints:
            _apply_constraint(constraint, table)
        return column

    def _parse_column_pglast(self, col_def: Any) -> Column | None:
        """Build a Column model from a pglast ColumnDef node."""
        try:
            readable = readable_type(col_def.typeName)
            col_type = ColumnType(readable) if readable is not None else ColumnType.UNKNOWN

            # Extract length from first typmod (VARCHAR(N), NUMERIC(P,S), etc.)
            length: int | None = None
            typmods = col_def.typeName.typmods
            if typmods:
                first = typmods[0]
                if type(first).__name__ == "A_Const" and hasattr(first, "val"):
                    val = first.val
                    if type(val).__name__ == "Integer":
                        length = val.ival

            # The spelling is recorded for every column, not only for a type the
            # map missed: it is what carries the length and the precision. An
            # array has no readable keyword and keeps the parser's spelling.
            raw_sql_type = written_type(col_def.typeName)

            return Column(
                name=col_def.colname,
                type=col_type,
                nullable=True,
                default=None,
                primary_key=False,
                unique=False,
                length=length,
                raw_sql_type=raw_sql_type,
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # AST collectors for indexes and ALTER TABLE constraints (ANA-04)
    # ------------------------------------------------------------------

    def _table_named(self, result: ParsedSchema, relation: Any) -> Table | None:
        """The declared table a ``RangeVar`` names, by identity rather than by name.

        A relation that wrote no schema matches any — the wildcard
        ``ddl_objects._matches`` and ``inventory.find_all`` already apply, and
        the reason a tree writing ``ALTER TABLE t`` after ``CREATE TABLE
        public.t`` still folds. First match is still the answer: with the
        wildcard it is the only one an unambiguous tree has, and a genuine
        ambiguity is a duplicate definition, reported as such rather than
        resolved here.
        """
        relname = getattr(relation, "relname", None)
        schema = getattr(relation, "schemaname", None)
        wanted = _identity(schema, relname)
        return next(
            (
                t
                for t in result.tables
                if t.name == relname
                and (schema is None or t.schema is None or _identity(t.schema, t.name) == wanted)
            ),
            None,
        )

    def _collect_index(
        self,
        stmt: Any,
        result: ParsedSchema,
        declared_at: dict[int, int] | None = None,
        offset: int = 0,
    ) -> None:
        table = self._table_named(result, stmt.relation)
        if table is None:
            return
        columns = [
            elem.name if elem.name else RawStream()(elem.expr) for elem in stmt.indexParams or []
        ]
        index = Index(
            name=stmt.idxname,
            table=table.qualified,
            columns=columns,
            unique=bool(stmt.unique),
            where=RawStream()(stmt.whereClause) if stmt.whereClause is not None else None,
        )
        table.indexes.append(index)
        if declared_at is not None:
            declared_at[id(index)] = offset

    def _collect_alter_table(self, stmt: Any, result: ParsedSchema) -> None:
        """Fold an ``ALTER TABLE`` into the table the tree already created.

        A build-from-DDL tree may append ``ALTER TABLE`` rather than edit the
        ``CREATE TABLE``; what a database ends up with is the two together, so
        that is what the comparison has to see. Before #288 only ``Constraint``
        nodes were read out of ``stmt.cmds``, which meant a ``ColumnDef`` — an
        added or dropped *column* — was dropped on the floor.

        An ``ALTER`` naming a table this tree never creates has nothing to fold
        into and is ignored: it belongs to a schema built elsewhere.
        """
        table = self._table_named(result, stmt.relation)
        if table is None:
            return
        for cmd in stmt.cmds or []:
            self._apply_alter_column(cmd, table)
        self._collect_alter_table_constraints(stmt, result)

    def _apply_alter_column(self, cmd: Any, table: Table) -> None:
        """Add, drop or retype one column, as ``ddl_walk.column_edit`` reads ``cmd``.

        *What* the cmd does is decided there, once, for both readers of a DDL
        tree — this one and the lint inventory, whose object model shares none of
        these types (#301). *How* it lands is here, because only the differ knows
        what a ``Column`` is.

        Nothing in this module names an ``AlterTableType`` member: PostgreSQL 18
        renumbered the enum at index >= 13 and a literal ordinal then stops
        matching silently, which is the whole of #192.
        """
        edit = column_edit(cmd)
        if edit is None:
            return
        if edit.kind == "add":
            # Through the same reader a CREATE TABLE column goes through: an
            # added column carries the same clauses, NOT NULL and a column-level
            # REFERENCES included.
            self._add_column_pglast(edit.coldef, table)
        elif edit.kind == "drop":
            table.columns = [c for c in table.columns if c.name != edit.column]
        elif edit.kind == "retype":
            self._retype_column(table, edit)
        else:
            self._edit_column_property(table, edit)

    def _edit_column_property(self, table: Table, edit: ColumnEdit) -> None:
        """Nullability and defaults, which change a column rather than replace it."""
        existing = table.get_column(edit.column) if edit.column else None
        if existing is None:
            return
        if edit.kind == "set_not_null":
            existing.nullable = False
        elif edit.kind == "drop_not_null":
            existing.nullable = True
        elif edit.kind == "set_default":
            existing.default = render_default(edit.default)
        elif edit.kind == "drop_default":
            existing.default = None

    def _retype_column(self, table: Table, edit: ColumnEdit) -> None:
        retyped = self._parse_column_pglast(edit.coldef)
        existing = table.get_column(edit.column) if edit.column else None
        if retyped is not None and existing is not None:
            existing.type = retyped.type
            existing.raw_sql_type = retyped.raw_sql_type
            existing.length = retyped.length

    @staticmethod
    def _replace_column(table: Table, column: Column) -> None:
        """Append the column, or overwrite one of the same name written earlier."""
        for index, existing in enumerate(table.columns):
            if existing.name == column.name:
                table.columns[index] = column
                return
        table.columns.append(column)

    def _collect_alter_table_constraints(self, stmt: Any, result: ParsedSchema) -> None:
        """``ALTER TABLE … ADD CONSTRAINT``, through the reader the CREATE path uses.

        This was the third reader of a ``Constraint`` node, and the only one that
        rendered a CHECK expression rather than storing the AST class name — so
        the two ways of writing one constraint produced two different models
        (#316).
        """
        table = self._table_named(result, stmt.relation)
        if table is None:
            return
        for cmd in stmt.cmds or []:
            constraint = added_constraint(cmd)
            if constraint is not None:
                _read_constraint(constraint, table)

    def compare(self, old_sql: str, new_sql: str) -> SchemaDiff:
        """Compare two schemas and detect changes.

        Args:
            old_sql: SQL DDL for the old schema
            new_sql: SQL DDL for the new schema

        Returns:
            SchemaDiff object containing list of changes

        Example:
            >>> differ = SchemaDiffer()
            >>> old = "CREATE TABLE users (id INT);"
            >>> new = "CREATE TABLE users (id INT, name TEXT);"
            >>> diff = differ.compare(old, new)
            >>> print(len(diff.changes))
            1
        """
        old_schema = self.parse_schema(old_sql)
        new_schema = self.parse_schema(new_sql)

        changes = self._compare_tables(old_schema, new_schema)
        changes.extend(self._compare_enum_types(old_schema.enum_types, new_schema.enum_types))
        changes.extend(self._compare_sequences(old_schema.sequences, new_schema.sequences))
        # Objects compared by definition: views, and #288's later kinds.
        changes.extend(self._compare_objects(old_schema.objects, new_schema.objects))
        return SchemaDiff(changes=changes, warnings=_merged_warnings(old_schema, new_schema))

    # ------------------------------------------------------------------
    # Table comparison
    # ------------------------------------------------------------------

    def _compare_tables(
        self, old_schema: ParsedSchema, new_schema: ParsedSchema
    ) -> list[SchemaChange]:
        """Added, dropped, renamed and edited tables, paired by identity.

        The maps key on :func:`_identity`, never on a bare name: ``tenant.t`` and
        ``etl.t`` are two tables, and pairing one against the other reported a
        ``DROP COLUMN`` on a schema where nothing had changed — a migration
        generated from a file rename (#313).

        What a change *prints* is ``Table.qualified``, the spelling the author
        wrote. Identity folds a missing schema; spelling never invents one.
        """
        changes: list[SchemaChange] = []
        old_map = {_identity(t.schema, t.name): t for t in old_schema.tables}
        new_map = {_identity(t.schema, t.name): t for t in new_schema.tables}

        old_only = set(old_map) - set(new_map)
        new_only = set(new_map) - set(old_map)

        for old_key, new_key in self._renamed_tables(old_only, new_only).items():
            old_table, new_table = old_map[old_key], new_map[new_key]
            changes.append(
                SchemaChange(
                    type="RENAME_TABLE",
                    table=old_table.qualified,
                    old_value=old_table.qualified,
                    new_value=new_table.qualified,
                    # `ALTER TABLE a.t RENAME TO a.t2` is a syntax error — the
                    # target of a RENAME is a bare name. Both spellings travel so
                    # the up and the down each have the two they need without
                    # taking a qualifier apart.
                    details={"old_name": old_table.name, "new_name": new_table.name},
                )
            )
            old_only.discard(old_key)
            new_only.discard(new_key)

        changes.extend(
            SchemaChange(
                type="DROP_TABLE",
                table=old_map[key].qualified,
                # The constraints travel too: a ``DROP_TABLE`` down recreates the
                # table from exactly these details, so a table that came back
                # without its foreign keys was a table that came back wrong.
                details={
                    "columns": _column_details(old_map[key]),
                    "constraints": _constraint_details(old_map[key]),
                },
            )
            for key in sorted(old_only)
        )

        changes.extend(
            SchemaChange(
                type="ADD_TABLE",
                table=new_map[key].qualified,
                details={
                    "columns": _column_details(new_map[key]),
                    "constraints": _constraint_details(new_map[key]),
                },
            )
            for key in sorted(new_only)
        )

        for key in sorted(set(old_map) & set(new_map)):
            old_table = old_map[key]
            new_table = new_map[key]
            changes.extend(self._compare_table_columns(old_table, new_table))
            changes.extend(self._compare_indexes(old_table, new_table))
            changes.extend(self._compare_foreign_keys(old_table, new_table))
            changes.extend(self._compare_check_constraints(old_table, new_table))
            changes.extend(self._compare_unique_constraints(old_table, new_table))

        return changes

    def _renamed_tables(
        self, old_keys: set[tuple[str, str]], new_keys: set[tuple[str, str]]
    ) -> dict[tuple[str, str], tuple[str, str]]:
        """Pair a vanished table with an appeared one — **within one schema**.

        PostgreSQL's ``ALTER TABLE … RENAME TO`` takes a bare name and cannot
        move a table between schemas (``ALTER TABLE a.t RENAME TO a.t2`` is a
        syntax error; the operation that moves a table is ``SET SCHEMA``). A
        cross-schema pairing is therefore not a rename by construction.

        That is a grammatical separation, not a threshold: ``_similarity_score``
        scores ``tenant.tb_meter`` against ``etl.tb_meter`` at 0.6, which is
        exactly what it scores the real rename ``tenant.tb_a`` →
        ``tenant.tb_b``. No threshold tells those apart, so feeding qualified
        names to the fuzzy matcher invents a destructive ``RENAME_TABLE``.

        ``_detect_column_renames`` needs no equivalent: a column comparison is
        already scoped to one table.
        """
        renames: dict[tuple[str, str], tuple[str, str]] = {}
        old_schemas = {schema for schema, _ in old_keys}
        for schema in sorted(old_schemas & {schema for schema, _ in new_keys}):
            paired = self._detect_table_renames(
                sorted(name for s, name in old_keys if s == schema),
                sorted(name for s, name in new_keys if s == schema),
            )
            for old_name, new_name in paired.items():
                renames[schema, old_name] = (schema, new_name)
        return renames

    # ------------------------------------------------------------------
    # Objects compared by definition (#288)
    # ------------------------------------------------------------------

    @staticmethod
    def _compare_objects(
        old_objects: dict[Any, Any], new_objects: dict[Any, Any]
    ) -> list[SchemaChange]:
        """Added, dropped and redefined objects, in a stable order.

        An object present on both sides whose canonical definition differs is a
        ``REPLACE``: for a view or a routine that is the entire change a
        migration has to carry, and it is invisible to a structural comparison
        because nothing about the object's shape moved.

        The keys are buckets, not identities, so each one's definitions are
        paired by ``pair_definitions`` rather than assumed to be one apiece.
        """
        changes: list[SchemaChange] = []
        for ref in sorted(old_objects.keys() | new_objects.keys(), key=_object_sort_key):
            pairs, dropped, added = pair_definitions(
                old_objects.get(ref, []), new_objects.get(ref, [])
            )
            changes.extend(_added_change(ref, obj) for obj in added)
            changes.extend(_dropped_change(ref, obj) for obj in dropped)
            changes.extend(
                _replaced_change(ref, before, after)
                for before, after in pairs
                if before.definition != after.definition
            )
        return changes

    # ------------------------------------------------------------------
    # Table column comparison
    # ------------------------------------------------------------------

    def _detect_table_renames(
        self, old_names: Iterable[str], new_names: Iterable[str]
    ) -> dict[str, str]:
        """Detect renamed tables using fuzzy matching."""
        renames: dict[str, str] = {}
        for old_name in old_names:
            best_match = self._find_best_match(old_name, new_names)
            if best_match and self._similarity_score(old_name, best_match) > 0.5:
                renames[old_name] = best_match
        return renames

    def _compare_table_columns(self, old_table: Table, new_table: Table) -> list[SchemaChange]:
        """Compare columns between two versions of the same table."""
        changes: list[SchemaChange] = []

        table = old_table.qualified
        old_col_map = {c.name: c for c in old_table.columns}
        new_col_map = {c.name: c for c in new_table.columns}

        old_col_names = set(old_col_map.keys())
        new_col_names = set(new_col_map.keys())

        renamed_columns = self._detect_column_renames(
            sorted(old_col_names - new_col_names), sorted(new_col_names - old_col_names)
        )

        for old_name, new_name in renamed_columns.items():
            changes.append(
                SchemaChange(
                    type="RENAME_COLUMN",
                    table=table,
                    old_value=old_name,
                    new_value=new_name,
                )
            )
            old_col_names.discard(old_name)
            new_col_names.discard(new_name)

        changes.extend(
            SchemaChange(
                type="DROP_COLUMN",
                table=table,
                column=col_name,
                old_value=_column_definition(old_col_map[col_name]),
            )
            for col_name in sorted(old_col_names - new_col_names)
        )

        changes.extend(
            SchemaChange(
                type="ADD_COLUMN",
                table=table,
                column=col_name,
                new_value=_column_definition(new_col_map[col_name]),
            )
            for col_name in sorted(new_col_names - old_col_names)
        )

        for col_name in sorted(old_col_names & new_col_names):
            old_col = old_col_map[col_name]
            new_col = new_col_map[col_name]
            changes.extend(self._compare_column_properties(table, old_col, new_col))

        return changes

    def _detect_column_renames(
        self, old_names: Iterable[str], new_names: Iterable[str]
    ) -> dict[str, str]:
        """Detect renamed columns using fuzzy matching."""
        renames: dict[str, str] = {}
        for old_name in old_names:
            best_match = self._find_best_match(old_name, new_names)
            if best_match and self._similarity_score(old_name, best_match) > 0.5:
                renames[old_name] = best_match
        return renames

    def _compare_column_properties(
        self, table: str, old_col: Column, new_col: Column
    ) -> list[SchemaChange]:
        """Compare properties of a column.

        *table* is the table's **spelling**, what a finding prints and what
        generated DDL alters — never an identity. The two are separate fields on
        the model for the same reason ``SchemaObject.signature`` and
        ``signature_key`` are (#275).
        """
        changes: list[SchemaChange] = []

        # Type change, typmod included: a `varchar(50)` widened to `varchar(100)`
        # is a change, and was reported as nothing at all.
        if _types_differ(old_col, new_col):
            changes.append(
                SchemaChange(
                    type="CHANGE_COLUMN_TYPE",
                    table=table,
                    column=old_col.name,
                    old_value=old_col.raw_sql_type or old_col.type.value,
                    new_value=new_col.raw_sql_type or new_col.type.value,
                )
            )

        if old_col.nullable != new_col.nullable:
            changes.append(
                SchemaChange(
                    type="CHANGE_COLUMN_NULLABLE",
                    table=table,
                    column=old_col.name,
                    old_value="true" if old_col.nullable else "false",
                    new_value="true" if new_col.nullable else "false",
                )
            )

        if old_col.default != new_col.default:
            changes.append(
                SchemaChange(
                    type="CHANGE_COLUMN_DEFAULT",
                    table=table,
                    column=old_col.name,
                    old_value=str(old_col.default) if old_col.default else None,
                    new_value=str(new_col.default) if new_col.default else None,
                )
            )

        return changes

    # ------------------------------------------------------------------
    # Index, FK, constraint, enum, sequence comparison helpers
    # ------------------------------------------------------------------

    def _compare_indexes(self, old_table: Table, new_table: Table) -> list[SchemaChange]:
        """Detect added / dropped indexes.

        Every ``detail_fn`` below emits the object's own name under ``name``,
        which is the key ``differ_sql`` and ``_CHANGE_TEMPLATES`` read. Indexes
        were the one kind spelled ``index_name`` on this side of the seam, so
        every generator read took its fallback and created ``idx_{table}``
        instead of the index the author declared.
        """
        return self._compare_named_objects(
            old=old_table.indexes,
            new=new_table.indexes,
            add_type="ADD_INDEX",
            drop_type="DROP_INDEX",
            table=old_table.qualified,
            detail_fn=lambda obj: {
                "name": obj.name,
                "columns": obj.columns,
                "unique": obj.unique,
            },
            identity=("columns", "unique"),
        )

    def _compare_foreign_keys(self, old_table: Table, new_table: Table) -> list[SchemaChange]:
        """Detect added / dropped foreign keys."""
        return self._compare_named_objects(
            old=old_table.foreign_keys,
            new=new_table.foreign_keys,
            add_type="ADD_FOREIGN_KEY",
            drop_type="DROP_FOREIGN_KEY",
            table=old_table.qualified,
            detail_fn=lambda obj: {
                "name": obj.name,
                "columns": obj.columns,
                "ref_table": obj.ref_table,
                "ref_columns": obj.ref_columns,
                "on_delete": obj.on_delete,
                "on_update": obj.on_update,
            },
            identity=("columns", "ref_table", "ref_columns"),
        )

    def _compare_check_constraints(self, old_table: Table, new_table: Table) -> list[SchemaChange]:
        """Detect added / dropped check constraints."""
        return self._compare_named_objects(
            old=old_table.check_constraints,
            new=new_table.check_constraints,
            add_type="ADD_CHECK_CONSTRAINT",
            drop_type="DROP_CHECK_CONSTRAINT",
            table=old_table.qualified,
            detail_fn=lambda obj: {"name": obj.name, "expression": obj.expression},
            identity=("expression",),
            # The one kind whose body is compared, and the only one that can be:
            # the expression is `RawStream`'s rendering of the parsed predicate, so
            # two spellings of one predicate are one string. A foreign key's
            # referenced column list written on one side and left implicit on the
            # other is the same constraint spelled twice, and telling that apart
            # means resolving the parent's primary key — so reporting it would
            # generate a DROP CONSTRAINT for a constraint that did not change.
            compared=("expression",),
        )

    def _compare_unique_constraints(self, old_table: Table, new_table: Table) -> list[SchemaChange]:
        """Detect added / dropped unique constraints."""
        return self._compare_named_objects(
            old=old_table.unique_constraints,
            new=new_table.unique_constraints,
            add_type="ADD_UNIQUE_CONSTRAINT",
            drop_type="DROP_UNIQUE_CONSTRAINT",
            table=old_table.qualified,
            detail_fn=lambda obj: {"name": obj.name, "columns": obj.columns},
            identity=("columns",),
        )

    def _compare_enum_types(
        self, old_enums: list[EnumType], new_enums: list[EnumType]
    ) -> list[SchemaChange]:
        """Detect added / dropped / changed enum types, paired by identity."""
        changes: list[SchemaChange] = []
        old_map = {_identity(e.schema, e.name): e for e in old_enums}
        new_map = {_identity(e.schema, e.name): e for e in new_enums}

        changes.extend(
            SchemaChange(type="ADD_ENUM_TYPE", table=new_map[key].qualified)
            for key in set(new_map) - set(old_map)
        )

        changes.extend(
            SchemaChange(type="DROP_ENUM_TYPE", table=old_map[key].qualified)
            for key in set(old_map) - set(new_map)
        )

        for key in set(old_map) & set(new_map):
            old_vals = set(old_map[key].values)
            new_vals = set(new_map[key].values)
            if old_vals != new_vals:
                changes.append(
                    SchemaChange(
                        type="CHANGE_ENUM_VALUES",
                        table=old_map[key].qualified,
                        details={
                            "added_values": sorted(new_vals - old_vals),
                            "removed_values": sorted(old_vals - new_vals),
                        },
                    )
                )

        return changes

    def _compare_sequences(
        self, old_seqs: list[Sequence], new_seqs: list[Sequence]
    ) -> list[SchemaChange]:
        """Detect added / dropped sequences, paired by identity."""
        changes: list[SchemaChange] = []
        old_map = {_identity(s.schema, s.name): s for s in old_seqs}
        new_map = {_identity(s.schema, s.name): s for s in new_seqs}

        changes.extend(
            SchemaChange(type="ADD_SEQUENCE", table=new_map[key].qualified)
            for key in set(new_map) - set(old_map)
        )

        changes.extend(
            SchemaChange(type="DROP_SEQUENCE", table=old_map[key].qualified)
            for key in set(old_map) - set(new_map)
        )

        return changes

    def _compare_named_objects(
        self,
        *,
        old: list[Any],
        new: list[Any],
        add_type: str,
        drop_type: str,
        table: str,
        detail_fn: object,
        identity: tuple[str, ...],
        compared: tuple[str, ...] = (),
    ) -> list[SchemaChange]:
        """Add/drop (and, where asked, replace) comparison for a table's own objects.

        *identity* names the fields that tell two **unnamed** objects apart —
        see :func:`_object_identity`. *compared* names the fields that, differing
        under one name, make the object a change rather than a constant; a kind
        that passes none keeps the add/drop-only comparison it always had.

        Emitted in a stable order, and a changed object's drop immediately
        precedes its add: PostgreSQL has no ``ALTER CONSTRAINT``, so replacing one
        *is* the pair, and the pair is only valid in that order.
        """
        detail_fn_typed: Callable = detail_fn  # ty: ignore[invalid-assignment]
        changes: list[SchemaChange] = []
        old_map = {_object_identity(obj, identity): obj for obj in old}
        new_map = {_object_identity(obj, identity): obj for obj in new}

        changes.extend(
            SchemaChange(type=add_type, table=table, details=detail_fn_typed(new_map[key]))
            for key in sorted(set(new_map) - set(old_map), key=str)
        )
        changes.extend(
            SchemaChange(type=drop_type, table=table, details=detail_fn_typed(old_map[key]))
            for key in sorted(set(old_map) - set(new_map), key=str)
        )

        for key in sorted(set(old_map) & set(new_map), key=str):
            before, after = old_map[key], new_map[key]
            if any(getattr(before, field) != getattr(after, field) for field in compared):
                changes.append(
                    SchemaChange(type=drop_type, table=table, details=detail_fn_typed(before))
                )
                changes.append(
                    SchemaChange(type=add_type, table=table, details=detail_fn_typed(after))
                )

        return changes

    # ------------------------------------------------------------------
    # Fuzzy matching helpers
    # ------------------------------------------------------------------

    def _find_best_match(self, name: str, candidates: set[str]) -> str | None:
        """Find best matching name from candidates."""
        if not candidates:
            return None

        best_match = None
        best_score = 0.0

        for candidate in candidates:
            score = self._similarity_score(name, candidate)
            if score > best_score:
                best_score = score
                best_match = candidate

        return best_match

    def _similarity_score(self, name1: str, name2: str) -> float:
        """Calculate similarity score between two names (0.0 to 1.0).

        Uses multiple heuristics to detect renames:
        1. Common suffix/prefix patterns (e.g., "full_name" -> "display_name" = 0.5)
        2. Word-based similarity (e.g., "user_accounts" -> "user_profiles" = 0.5)
        3. Character-based Jaccard similarity
        """
        name1 = name1.lower()
        name2 = name2.lower()

        if name1 == name2:
            return 1.0

        name1_parts = name1.split("_")
        name2_parts = name2.split("_")

        if len(name1_parts) > 1 or len(name2_parts) > 1:
            if name1_parts[-1] == name2_parts[-1]:
                return 0.6
            if name1_parts[0] == name2_parts[0]:
                return 0.6

        name1_words = set(name1_parts)
        name2_words = set(name2_parts)
        common_words = name1_words & name2_words

        if common_words:
            return len(common_words) / len(name1_words | name2_words)

        name1_chars = set(name1)
        name2_chars = set(name2)
        common_chars = name1_chars & name2_chars

        if common_chars:
            return len(common_chars) / len(name1_chars | name2_chars)

        return 0.0


def _enum_value(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _qualified_parts(names: Any) -> tuple[str | None, str]:
    parts = [str(getattr(part, "sval", part)) for part in names or []]
    return (parts[-2] if len(parts) >= 2 else None), parts[-1]


def _enum_type_from_stmt(stmt: Any) -> EnumType:
    schema, name = _qualified_parts(stmt.typeName)
    return EnumType(name=name, schema=schema, values=[v.sval for v in stmt.vals or []])


def _sequence_from_stmt(stmt: Any) -> Sequence:
    options: dict[str, Any] = {}
    for opt in stmt.options or []:
        arg = getattr(opt, "arg", None)
        options[opt.defname] = getattr(arg, "ival", None) if arg is not None else None
    return Sequence(
        name=stmt.sequence.relname,
        schema=stmt.sequence.schemaname,
        start=options.get("start", 1) if options.get("start") is not None else 1,
        increment=options.get("increment", 1) if options.get("increment") is not None else 1,
        min_value=options.get("minvalue"),
        max_value=options.get("maxvalue"),
    )
