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
from pglast.enums.parsenodes import ConstrType
from pglast.stream import RawStream

from confiture.core._pglast_enums import member as _pg_member
from confiture.core.ddl_objects import OBJECT_KEYWORD, objects_in, pair_definitions
from confiture.core.ddl_walk import ColumnEdit, ObjectEdit, column_edit, object_edits
from confiture.core.linting.inventory import DEFAULT_SCHEMA
from confiture.core.sql_lexer import blank_copy_blocks
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
)

# ---------------------------------------------------------------------------
# Module-level constants: compiled once for performance
# ---------------------------------------------------------------------------

_COLUMN_TYPE_MAP: dict[str, ColumnType] = {
    "SMALLINT": ColumnType.SMALLINT,
    "INT2": ColumnType.SMALLINT,
    "INT": ColumnType.INTEGER,
    "INTEGER": ColumnType.INTEGER,
    "INT4": ColumnType.INTEGER,
    "BIGINT": ColumnType.BIGINT,
    "INT8": ColumnType.BIGINT,
    "SERIAL": ColumnType.SERIAL,
    "BIGSERIAL": ColumnType.BIGSERIAL,
    "NUMERIC": ColumnType.NUMERIC,
    "DECIMAL": ColumnType.DECIMAL,
    "REAL": ColumnType.REAL,
    "FLOAT4": ColumnType.REAL,
    "DOUBLE": ColumnType.DOUBLE_PRECISION,
    "FLOAT8": ColumnType.DOUBLE_PRECISION,
    "DOUBLE PRECISION": ColumnType.DOUBLE_PRECISION,
    "VARCHAR": ColumnType.VARCHAR,
    "CHARACTER VARYING": ColumnType.VARCHAR,
    "CHAR": ColumnType.CHAR,
    "CHARACTER": ColumnType.CHAR,
    "TEXT": ColumnType.TEXT,
    "BOOLEAN": ColumnType.BOOLEAN,
    "BOOL": ColumnType.BOOLEAN,
    "DATE": ColumnType.DATE,
    "TIME": ColumnType.TIME,
    "TIMETZ": ColumnType.TIME,
    "TIMESTAMP": ColumnType.TIMESTAMP,
    "TIMESTAMP WITHOUT TIME ZONE": ColumnType.TIMESTAMP,
    "TIMESTAMPTZ": ColumnType.TIMESTAMPTZ,
    "TIMESTAMP WITH TIME ZONE": ColumnType.TIMESTAMPTZ,
    "UUID": ColumnType.UUID,
    "JSON": ColumnType.JSON,
    "JSONB": ColumnType.JSONB,
    "BYTEA": ColumnType.BYTEA,
    # Network types
    "CIDR": ColumnType.CIDR,
    "INET": ColumnType.INET,
    "MACADDR": ColumnType.MACADDR,
    "MACADDR8": ColumnType.MACADDR8,
    # Money
    "MONEY": ColumnType.MONEY,
    # Bit strings
    "BIT": ColumnType.BIT,
    "VARBIT": ColumnType.VARBIT,
    "BIT VARYING": ColumnType.VARBIT,
    # Text search
    "TSVECTOR": ColumnType.TSVECTOR,
    "TSQUERY": ColumnType.TSQUERY,
    # XML
    "XML": ColumnType.XML,
    # Range types
    "INT4RANGE": ColumnType.INT4RANGE,
    "INT8RANGE": ColumnType.INT8RANGE,
    "NUMRANGE": ColumnType.NUMRANGE,
    "TSRANGE": ColumnType.TSRANGE,
    "TSTZRANGE": ColumnType.TSTZRANGE,
    "DATERANGE": ColumnType.DATERANGE,
}


# DDL statement prefixes — used to filter out non-DDL (INSERT, COPY, GRANT, etc.)
# before passing individual statements to sqlparse (avoids MAX_GROUPING_TOKENS crash).
_DDL_PREFIXES = ("CREATE", "ALTER", "DROP", "TRUNCATE", "COMMENT")

logger = logging.getLogger(__name__)

# pglast reports internal type aliases rather than the SQL keyword the user wrote.
# Map them back to the canonical names in _COLUMN_TYPE_MAP.
_PGLAST_TYPE_ALIASES: dict[str, str] = {
    "INT4": "INTEGER",
    "INT8": "BIGINT",
    "INT2": "SMALLINT",
    "FLOAT4": "REAL",
    "FLOAT8": "DOUBLE PRECISION",
    "BOOL": "BOOLEAN",
}

# pglast FK on-delete action code → human-readable string
_PG_FK_DEL_ACTION: dict[str, str | None] = {
    "a": None,  # NO ACTION — PostgreSQL's default, reported as no clause
    "r": "RESTRICT",
    "c": "CASCADE",
    "n": "SET NULL",
    "d": "SET DEFAULT",
    "": None,
    "\x00": None,
}
#: The differ's own model classes, in the kind vocabulary ``ObjectEdit`` speaks.
#: A ``Table`` answers for a table and a matview alike here, because this model
#: has only the one; a view and a routine live in ``ParsedSchema.objects``, and
#: ``ddl_objects`` folds their drops.
_MODEL_KINDS: dict[str, str] = {"Table": "table", "EnumType": "type", "Sequence": "sequence"}

_CONSTR_FOREIGN = _pg_member("ConstrType", "CONSTR_FOREIGN")
_CONSTR_CHECK = _pg_member("ConstrType", "CONSTR_CHECK")
_CONSTR_UNIQUE = _pg_member("ConstrType", "CONSTR_UNIQUE")


def _identity(schema: str | None, name: str) -> tuple[str, str]:
    """What makes two statements the same relation, by the inventory's rule.

    :data:`~confiture.core.linting.inventory.DEFAULT_SCHEMA` for a statement that
    names none, so ``CREATE TABLE t`` and ``CREATE TABLE public.t`` are one table
    and ``tenant.t`` another — the same fold ``inventory.object_key`` and
    ``ddl_objects.ObjectRef`` apply. The default is imported rather than spelled
    ``"public"`` here: one default, one module.

    The identity is not the spelling. ``Table.qualified`` prints what the author
    wrote and never invents a qualifier; this decides only whether two
    statements are about one relation.
    """
    return (schema or DEFAULT_SCHEMA).lower(), name


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


def _column_definition(column: Column) -> str:
    """The column's definition without its name — what ``ADD COLUMN`` takes after the name."""
    parts = [column.raw_sql_type or column.type.value]
    if not column.nullable:
        parts.append("NOT NULL")
    if column.default is not None:
        parts.append(f"DEFAULT {column.default}")
    return " ".join(parts)


def _column_details(table: Table) -> list[dict[str, Any]]:
    """The columns of ``table`` in the shape ``DifferSQLGenerator`` renders a ``CREATE TABLE`` from."""
    return [
        {
            "name": column.name,
            "type": column.raw_sql_type or column.type.value,
            "nullable": column.nullable,
            "default": column.default,
        }
        for column in table.columns
    ]


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
        for raw in raws:
            if type(raw.stmt).__name__ == "CreateStmt":
                table = self._parse_create_table_pglast(raw.stmt)
                if table:
                    result.tables.append(table)
                    declared_at[id(table)] = raw.stmt_location or 0
        for raw in raws:
            self._collect_statement(raw, result, declared_at)
        return result

    def _collect_statement(
        self, raw: Any, result: ParsedSchema, declared_at: dict[int, int]
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
        elif kind == "CreateSeqStmt":
            sequence = _sequence_from_stmt(stmt)
            result.sequences.append(sequence)
            declared_at[id(sequence)] = offset
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
        """Build a Table model from a pglast CreateStmt node."""
        try:
            table = Table(name=stmt.relation.relname, schema=stmt.relation.schemaname)

            for elt in stmt.tableElts or []:
                if type(elt).__name__ == "ColumnDef":
                    col = self._parse_column_pglast(elt, ConstrType)
                    if col:
                        table.columns.append(col)
                elif type(elt).__name__ == "Constraint":
                    self._parse_table_constraint_pglast(elt, table, ConstrType)

            return table
        except (AttributeError, KeyError, TypeError, ValueError):
            return None

    def _parse_column_pglast(self, col_def: Any, ConstrType: Any) -> Column | None:
        """Build a Column model from a pglast ColumnDef node."""
        try:
            # Extract type name: last entry in typeName.names (skip 'pg_catalog' prefix)
            names = [n.sval for n in col_def.typeName.names]
            raw_type_str = names[-1].upper()
            lookup_str = _PGLAST_TYPE_ALIASES.get(raw_type_str, raw_type_str)
            col_type = _COLUMN_TYPE_MAP.get(lookup_str, ColumnType.UNKNOWN)
            raw_sql_type = raw_type_str.lower() if col_type == ColumnType.UNKNOWN else None

            # Extract length from first typmod (VARCHAR(N), NUMERIC(P,S), etc.)
            length: int | None = None
            typmods = col_def.typeName.typmods
            if typmods:
                first = typmods[0]
                if type(first).__name__ == "A_Const" and hasattr(first, "val"):
                    val = first.val
                    if type(val).__name__ == "Integer":
                        length = val.ival

            # Array column (INT[], TEXT[], etc.) → UNKNOWN with raw type preserved
            if col_def.typeName.arrayBounds:
                col_type = ColumnType.UNKNOWN
                raw_sql_type = raw_type_str.lower() + "[]"

            nullable = True
            primary_key = False
            default: str | None = None

            for constraint in col_def.constraints or []:
                ctype = constraint.contype
                if ctype == ConstrType.CONSTR_NOTNULL:
                    nullable = False
                elif ctype == ConstrType.CONSTR_PRIMARY:
                    primary_key = True
                    nullable = False
                elif ctype == ConstrType.CONSTR_DEFAULT:
                    default = self._render_default_pglast(constraint.raw_expr)

            return Column(
                name=col_def.colname,
                type=col_type,
                nullable=nullable,
                default=default,
                primary_key=primary_key,
                unique=False,
                length=length,
                raw_sql_type=raw_sql_type,
            )
        except (AttributeError, KeyError, TypeError, ValueError):
            return None

    def _parse_table_constraint_pglast(
        self, constraint: Any, table: Table, ConstrType: Any
    ) -> None:
        """Attach a table-level inline constraint (FK / CHECK / UNIQUE) to the table."""
        try:
            ctype = constraint.contype
            name = constraint.conname or ""

            if ctype == ConstrType.CONSTR_FOREIGN:
                fk_cols = [s.sval for s in (constraint.fk_attrs or [])]
                pk_cols = [s.sval for s in (constraint.pk_attrs or [])]
                ref_table = constraint.pktable.relname if constraint.pktable else ""
                on_delete = _PG_FK_DEL_ACTION.get(str(constraint.fk_del_action or ""))
                table.foreign_keys.append(
                    ForeignKey(
                        name=name,
                        table=table.name,
                        columns=fk_cols,
                        ref_table=ref_table,
                        ref_columns=pk_cols,
                        on_delete=on_delete,
                    )
                )
            elif ctype == ConstrType.CONSTR_CHECK:
                # Store the AST node type as a placeholder — identity-level comparison
                # (detecting that a CHECK constraint was added/removed) is what matters.
                expr = type(constraint.raw_expr).__name__ if constraint.raw_expr else ""
                table.check_constraints.append(
                    CheckConstraint(name=name, table=table.name, expression=expr)
                )
            elif ctype == ConstrType.CONSTR_UNIQUE:
                cols = [s.sval for s in (constraint.keys or [])]
                table.unique_constraints.append(
                    UniqueConstraint(name=name, table=table.name, columns=cols)
                )
        except (AttributeError, KeyError, TypeError, ValueError):
            pass

    def _render_default_pglast(self, raw_expr: Any) -> str | None:
        """Render a pglast default expression as a comparable string."""
        if raw_expr is None:
            return None
        ntype = type(raw_expr).__name__
        if ntype == "A_Const":
            if getattr(raw_expr, "isnull", False):
                return "NULL"
            val = getattr(raw_expr, "val", None)
            if val is None:
                return None
            vtype = type(val).__name__
            if vtype == "Integer":
                return str(val.ival)
            if vtype == "Float":
                return str(val.fval)
            if vtype == "String":
                return f"'{val.sval}'"
            if vtype == "Boolean":
                return "true" if val.boolval else "false"
        # A call, a cast, a column reference: the expression as PostgreSQL would
        # print it, arguments included, so a down file can write the default back.
        return RawStream()(raw_expr)

    # ------------------------------------------------------------------
    # sqlparse-based CREATE TABLE parser (fallback when pglast not installed)
    # ------------------------------------------------------------------

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
            table=table.name,
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
            column = self._parse_column_pglast(edit.coldef, ConstrType)
            if column is not None:
                self._replace_column(table, column)
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
            existing.default = self._render_default_pglast(edit.default)
        elif edit.kind == "drop_default":
            existing.default = None

    def _retype_column(self, table: Table, edit: ColumnEdit) -> None:
        retyped = self._parse_column_pglast(edit.coldef, ConstrType)
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
        table = self._table_named(result, stmt.relation)
        if table is None:
            return
        for cmd in stmt.cmds or []:
            constraint = getattr(cmd, "def_", None)
            if constraint is None or type(constraint).__name__ != "Constraint":
                continue
            contype = _enum_value(constraint.contype)
            if contype == _CONSTR_FOREIGN:
                table.foreign_keys.append(
                    ForeignKey(
                        name=constraint.conname,
                        table=table.name,
                        columns=[k.sval for k in constraint.fk_attrs or []],
                        ref_table=constraint.pktable.relname,
                        ref_columns=[k.sval for k in constraint.pk_attrs or []],
                        on_delete=_PG_FK_DEL_ACTION.get(constraint.fk_del_action or ""),
                    )
                )
            elif contype == _CONSTR_CHECK and constraint.raw_expr is not None:
                table.check_constraints.append(
                    CheckConstraint(
                        name=constraint.conname,
                        table=table.name,
                        expression=RawStream()(constraint.raw_expr),
                    )
                )
            elif contype == _CONSTR_UNIQUE:
                table.unique_constraints.append(
                    UniqueConstraint(
                        name=constraint.conname,
                        table=table.name,
                        columns=[k.sval for k in constraint.keys or []],
                    )
                )

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

        changes: list[SchemaChange] = []

        # --- Table-level changes ---
        old_table_map = {t.name: t for t in old_schema.tables}
        new_table_map = {t.name: t for t in new_schema.tables}

        old_table_names = set(old_table_map.keys())
        new_table_names = set(new_table_map.keys())

        renamed_tables = self._detect_table_renames(
            sorted(old_table_names - new_table_names), sorted(new_table_names - old_table_names)
        )

        for old_name, new_name in renamed_tables.items():
            changes.append(
                SchemaChange(type="RENAME_TABLE", old_value=old_name, new_value=new_name)
            )
            old_table_names.discard(old_name)
            new_table_names.discard(new_name)

        changes.extend(
            SchemaChange(
                type="DROP_TABLE",
                table=table_name,
                details={"columns": _column_details(old_table_map[table_name])},
            )
            for table_name in sorted(old_table_names - new_table_names)
        )

        changes.extend(
            SchemaChange(
                type="ADD_TABLE",
                table=table_name,
                details={"columns": _column_details(new_table_map[table_name])},
            )
            for table_name in sorted(new_table_names - old_table_names)
        )

        for table_name in sorted(old_table_names & new_table_names):
            old_table = old_table_map[table_name]
            new_table = new_table_map[table_name]
            changes.extend(self._compare_table_columns(old_table, new_table))
            changes.extend(self._compare_indexes(old_table, new_table))
            changes.extend(self._compare_foreign_keys(old_table, new_table))
            changes.extend(self._compare_check_constraints(old_table, new_table))
            changes.extend(self._compare_unique_constraints(old_table, new_table))

        # --- Enum type changes ---
        changes.extend(self._compare_enum_types(old_schema.enum_types, new_schema.enum_types))

        # --- Sequence changes ---
        changes.extend(self._compare_sequences(old_schema.sequences, new_schema.sequences))

        # --- Objects compared by definition: views, and #288's later kinds ---
        changes.extend(self._compare_objects(old_schema.objects, new_schema.objects))

        return SchemaDiff(changes=changes)

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
                    table=old_table.name,
                    old_value=old_name,
                    new_value=new_name,
                )
            )
            old_col_names.discard(old_name)
            new_col_names.discard(new_name)

        changes.extend(
            SchemaChange(
                type="DROP_COLUMN",
                table=old_table.name,
                column=col_name,
                old_value=_column_definition(old_col_map[col_name]),
            )
            for col_name in sorted(old_col_names - new_col_names)
        )

        changes.extend(
            SchemaChange(
                type="ADD_COLUMN",
                table=old_table.name,
                column=col_name,
                new_value=_column_definition(new_col_map[col_name]),
            )
            for col_name in sorted(new_col_names - old_col_names)
        )

        for col_name in sorted(old_col_names & new_col_names):
            old_col = old_col_map[col_name]
            new_col = new_col_map[col_name]
            changes.extend(self._compare_column_properties(old_table.name, old_col, new_col))

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
        self, table_name: str, old_col: Column, new_col: Column
    ) -> list[SchemaChange]:
        """Compare properties of a column."""
        changes: list[SchemaChange] = []

        # Type change — handle UNKNOWN types using raw_sql_type
        if old_col.type == new_col.type == ColumnType.UNKNOWN:
            if old_col.raw_sql_type != new_col.raw_sql_type:
                changes.append(
                    SchemaChange(
                        type="CHANGE_COLUMN_TYPE",
                        table=table_name,
                        column=old_col.name,
                        old_value=old_col.raw_sql_type,
                        new_value=new_col.raw_sql_type,
                    )
                )
        elif old_col.type != new_col.type:
            changes.append(
                SchemaChange(
                    type="CHANGE_COLUMN_TYPE",
                    table=table_name,
                    column=old_col.name,
                    old_value=old_col.type.value,
                    new_value=new_col.type.value,
                )
            )

        if old_col.nullable != new_col.nullable:
            changes.append(
                SchemaChange(
                    type="CHANGE_COLUMN_NULLABLE",
                    table=table_name,
                    column=old_col.name,
                    old_value="true" if old_col.nullable else "false",
                    new_value="true" if new_col.nullable else "false",
                )
            )

        if old_col.default != new_col.default:
            changes.append(
                SchemaChange(
                    type="CHANGE_COLUMN_DEFAULT",
                    table=table_name,
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
        """Detect added / dropped indexes."""
        return self._compare_named_objects(
            old_map={idx.name: idx for idx in old_table.indexes},
            new_map={idx.name: idx for idx in new_table.indexes},
            add_type="ADD_INDEX",
            drop_type="DROP_INDEX",
            table=old_table.name,
            detail_fn=lambda obj: {"index_name": obj.name, "columns": obj.columns},
        )

    def _compare_foreign_keys(self, old_table: Table, new_table: Table) -> list[SchemaChange]:
        """Detect added / dropped foreign keys."""
        return self._compare_named_objects(
            old_map={fk.name: fk for fk in old_table.foreign_keys},
            new_map={fk.name: fk for fk in new_table.foreign_keys},
            add_type="ADD_FOREIGN_KEY",
            drop_type="DROP_FOREIGN_KEY",
            table=old_table.name,
            detail_fn=lambda obj: {
                "name": obj.name,
                "columns": obj.columns,
                "ref_table": obj.ref_table,
                "ref_columns": obj.ref_columns,
                "on_delete": obj.on_delete,
            },
        )

    def _compare_check_constraints(self, old_table: Table, new_table: Table) -> list[SchemaChange]:
        """Detect added / dropped check constraints."""
        return self._compare_named_objects(
            old_map={cc.name: cc for cc in old_table.check_constraints},
            new_map={cc.name: cc for cc in new_table.check_constraints},
            add_type="ADD_CHECK_CONSTRAINT",
            drop_type="DROP_CHECK_CONSTRAINT",
            table=old_table.name,
            detail_fn=lambda obj: {"name": obj.name, "expression": obj.expression},
        )

    def _compare_unique_constraints(self, old_table: Table, new_table: Table) -> list[SchemaChange]:
        """Detect added / dropped unique constraints."""
        return self._compare_named_objects(
            old_map={uc.name: uc for uc in old_table.unique_constraints},
            new_map={uc.name: uc for uc in new_table.unique_constraints},
            add_type="ADD_UNIQUE_CONSTRAINT",
            drop_type="DROP_UNIQUE_CONSTRAINT",
            table=old_table.name,
            detail_fn=lambda obj: {"name": obj.name, "columns": obj.columns},
        )

    def _compare_enum_types(
        self, old_enums: list[EnumType], new_enums: list[EnumType]
    ) -> list[SchemaChange]:
        """Detect added / dropped / changed enum types."""
        changes: list[SchemaChange] = []
        old_map = {e.name: e for e in old_enums}
        new_map = {e.name: e for e in new_enums}

        changes.extend(
            SchemaChange(type="ADD_ENUM_TYPE", table=name) for name in set(new_map) - set(old_map)
        )

        changes.extend(
            SchemaChange(type="DROP_ENUM_TYPE", table=name) for name in set(old_map) - set(new_map)
        )

        for name in set(old_map) & set(new_map):
            old_vals = set(old_map[name].values)
            new_vals = set(new_map[name].values)
            if old_vals != new_vals:
                changes.append(
                    SchemaChange(
                        type="CHANGE_ENUM_VALUES",
                        table=name,
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
        """Detect added / dropped sequences."""
        changes: list[SchemaChange] = []
        old_map = {s.name: s for s in old_seqs}
        new_map = {s.name: s for s in new_seqs}

        changes.extend(
            SchemaChange(type="ADD_SEQUENCE", table=name) for name in set(new_map) - set(old_map)
        )

        changes.extend(
            SchemaChange(type="DROP_SEQUENCE", table=name) for name in set(old_map) - set(new_map)
        )

        return changes

    def _compare_named_objects(
        self,
        old_map: dict,
        new_map: dict,
        add_type: str,
        drop_type: str,
        table: str,
        detail_fn: object,
    ) -> list[SchemaChange]:
        """Generic name-based add/drop comparison for indexes/constraints."""

        detail_fn_typed: Callable = detail_fn  # ty: ignore[invalid-assignment]
        changes: list[SchemaChange] = []
        old_names = set(old_map.keys())
        new_names = set(new_map.keys())

        for name in new_names - old_names:
            obj = new_map[name]
            changes.append(
                SchemaChange(
                    type=add_type,
                    table=table,
                    details=detail_fn_typed(obj),
                )
            )

        for name in old_names - new_names:
            obj = old_map[name]
            changes.append(
                SchemaChange(
                    type=drop_type,
                    table=table,
                    details=detail_fn_typed(obj),
                )
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

    # ------------------------------------------------------------------
    # SQL parsing helpers
    # ------------------------------------------------------------------


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
