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

from confiture.core.ddl_objects import OBJECT_KEYWORD, objects_in, pair_definitions
from confiture.core.differ_sql import column_body
from confiture.core.linting.duplicates import WINS_TEXT, CreateFlags, wins
from confiture.core.linting.inventory import (
    Inventory,
    SchemaObject,
    build_inventory,
    group_definitions,
    schema_model,
)
from confiture.core.schema_identity import DEFAULT_SCHEMA
from confiture.core.schema_model import (
    Column,
    Constraint,
    EnumType,
    Sequence,
    Table,
    qualified_name,
)
from confiture.core.sql_lexer import blank_copy_blocks
from confiture.core.type_lattice import same_type
from confiture.models.schema import ParsedSchema, SchemaChange, SchemaDiff
from confiture.models.warnings import BuildWarning

logger = logging.getLogger(__name__)


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


#: The kinds this module compares structurally, as a duplicate warning names them.
_DUPLICATE_KINDS: dict[str, str] = {"table": "Table", "type": "Type", "sequence": "Sequence"}


def _structural(obj: SchemaObject) -> bool:
    """A table, an enum or a sequence — what the model holds and this module compares."""
    return obj.kind in ("table", "sequence") or (obj.kind == "type" and obj.enum_values is not None)


def _duplicate_warnings(inventory: Inventory) -> list[BuildWarning]:
    """Say so when one ``(schema, name)`` is defined more than once in one tree.

    Two definitions of one object is #313's defect with the schema taken out of
    it. The model keeps the definition a build keeps — a later ``IF NOT EXISTS``
    is a no-op, a later plain ``CREATE`` fails the build at that statement — and
    the collapse is reported either way. The verdict is ``duplicates.wins``,
    ``build_001``'s own rule. A warning, not a failure: a duplicate is
    ``confiture lint``'s and ``build --fail-on-duplicates``' problem, and failing
    ``--require-migration`` for it would fail the gate for a reason it is not about.
    """
    warnings: list[BuildWarning] = []
    for kind in ("table", "type", "sequence"):
        objects = [obj for obj in inventory.objects if obj.kind == kind and _structural(obj)]
        for group in group_definitions(objects):
            if len(group) == 1:
                continue
            verdict = wins(
                [CreateFlags(replace=obj.replace, if_not_exists=obj.if_not_exists) for obj in group]
            )
            first = group[0]
            warnings.append(
                BuildWarning.of(
                    "DIFFER_402",
                    kind=_DUPLICATE_KINDS[kind],
                    identity=qualified_name(first.folded_schema, first.folded_name),
                    count=len(group),
                    outcome=WINS_TEXT[verdict],
                    used="last" if verdict == "last" else "first",
                )
            )
    return warnings


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


# ---------------------------------------------------------------------------
# The model constraint, landed on this module's own ``Table``
# ---------------------------------------------------------------------------
#
# ``ddl_walk.read_constraint`` is the one reader of a ``Constraint`` node (#315,
# #316) and returns what the node declares. This module still compares its own
# ``models.schema`` types, so a returned value is applied to them here; nothing
# below decides what a node means.


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

    By identity (``type_key``), through ``type_lattice.same_type`` — the one
    canonicaliser, whose own docstring states this case: *a column type must keep
    [typmods] or ``varchar(50)`` and ``varchar(100)`` compare equal*. Never by the
    spellings: ``int4`` and ``integer`` are one type whichever side wrote which.
    """
    return not same_type(old.type_key, new.type_key)


#: What a column with no written type is called in a change — none from a parse.
_UNKNOWN_TYPE = "UNKNOWN"


def _written(column: Column) -> str:
    """The column's type as generated DDL writes it."""
    return column.raw_sql_type or column.type_key or _UNKNOWN_TYPE


def _column_detail(column: Column) -> dict[str, Any]:
    """One column in the shape ``DifferSQLGenerator`` renders it from.

    Identity and generation are present only on a column that has them, so an
    ordinary column's details read exactly as they always have.
    """
    detail: dict[str, Any] = {
        "name": column.folded,
        "type": _written(column),
        "nullable": not column.not_null,
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
            "columns": [column.folded for column in table.columns if column.primary_key],
        }
    ]
    details.extend(_foreign_key_detail(fk) for fk in table.constraints_of("foreign_key"))
    details.extend(_unique_detail(uc) for uc in table.constraints_of("unique"))
    details.extend(_check_detail(cc) for cc in table.constraints_of("check"))
    return [detail for detail in details if detail.get("columns") or detail.get("expression")]


def _foreign_key_detail(fk: Constraint) -> dict[str, Any]:
    return {
        "kind": "FOREIGN KEY",
        "name": fk.name,
        "columns": list(fk.columns),
        "ref_table": fk.ref_table or "",
        "ref_columns": list(fk.ref_columns),
        "on_delete": fk.on_delete,
        "on_update": fk.on_update,
    }


def _unique_detail(uc: Constraint) -> dict[str, Any]:
    return {"kind": "UNIQUE", "name": uc.name, "columns": list(uc.columns)}


def _check_detail(cc: Constraint) -> dict[str, Any]:
    return {"kind": "CHECK", "name": cc.name, "expression": cc.expression}


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
        """Parse SQL DDL into the schema model, plus the objects compared by definition.

        The one parse (ANA-04): ``pglast.parse_sql`` once, the statements handed
        to the lint inventory — which reads a table whole through
        ``ddl_walk``'s one constraint reader, folds every ``ALTER``, ``DROP``
        and rename order-aware (#301), and keys every object by ``(schema,
        name)`` (#313) — and to ``ddl_objects`` for the views, routines and
        the rest. This module parses nothing itself. Non-DDL statements
        (INSERT, COPY, GRANT, …) declare nothing and are ignored.

        Args:
            sql: SQL DDL string (may contain any SQL, including non-DDL)

        Returns:
            ParsedSchema with the model's tables, enum types and sequences

        Raises:
            pglast.parser.ParseError: what PostgreSQL rejects is not a schema
                to diff; ``migrate diff`` reports it as ``DIFFER_400``.
        """
        if not sql or not sql.strip():
            return ParsedSchema()

        # Blank inline-COPY data blocks before the parser sees the text: pglast
        # rejects them outright (#194). Blanked, not deleted: the block keeps its
        # length and its newlines, so the `DIFFER_400` a rejected statement
        # raises carries a position into the text the author wrote.
        sql = blank_copy_blocks(sql)
        raws = list(pglast.parse_sql(sql) or [])
        inventory = build_inventory(sql, raws)
        model = schema_model(inventory)
        return ParsedSchema(
            tables=list(model.tables.values()),
            enum_types=list(model.enum_types.values()),
            sequences=list(model.sequences.values()),
            objects=objects_in(sql, raws),
            warnings=_duplicate_warnings(inventory),
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
        # By the parser's spelling of each name, which is also what generated DDL
        # writes: an unquoted `UserId` is the column `userid`.
        old_col_map = {c.folded: c for c in old_table.columns}
        new_col_map = {c.folded: c for c in new_table.columns}

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
                    column=old_col.folded,
                    old_value=_written(old_col),
                    new_value=_written(new_col),
                )
            )

        if old_col.not_null != new_col.not_null:
            changes.append(
                SchemaChange(
                    type="CHANGE_COLUMN_NULLABLE",
                    table=table,
                    column=old_col.folded,
                    old_value="false" if old_col.not_null else "true",
                    new_value="false" if new_col.not_null else "true",
                )
            )

        if old_col.default != new_col.default:
            changes.append(
                SchemaChange(
                    type="CHANGE_COLUMN_DEFAULT",
                    table=table,
                    column=old_col.folded,
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
            old=list(old_table.indexes),
            new=list(new_table.indexes),
            add_type="ADD_INDEX",
            drop_type="DROP_INDEX",
            table=old_table.qualified,
            detail_fn=lambda obj: {
                "name": obj.name,
                "columns": list(obj.columns),
                "unique": obj.unique,
            },
            # The access method is part of what an index *is*: a btree and a hash
            # index on one column are two indexes, and were one to this module
            # while it never read `USING`.
            identity=("columns", "unique", "method"),
            compared=("method",),
        )

    def _compare_foreign_keys(self, old_table: Table, new_table: Table) -> list[SchemaChange]:
        """Detect added / dropped foreign keys."""
        return self._compare_named_objects(
            old=list(old_table.constraints_of("foreign_key")),
            new=list(new_table.constraints_of("foreign_key")),
            add_type="ADD_FOREIGN_KEY",
            drop_type="DROP_FOREIGN_KEY",
            table=old_table.qualified,
            detail_fn=lambda obj: {
                key: value for key, value in _foreign_key_detail(obj).items() if key != "kind"
            },
            identity=("columns", "ref_table", "ref_columns"),
        )

    def _compare_check_constraints(self, old_table: Table, new_table: Table) -> list[SchemaChange]:
        """Detect added / dropped check constraints."""
        return self._compare_named_objects(
            old=list(old_table.constraints_of("check")),
            new=list(new_table.constraints_of("check")),
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
            old=list(old_table.constraints_of("unique")),
            new=list(new_table.constraints_of("unique")),
            add_type="ADD_UNIQUE_CONSTRAINT",
            drop_type="DROP_UNIQUE_CONSTRAINT",
            table=old_table.qualified,
            detail_fn=lambda obj: {"name": obj.name, "columns": list(obj.columns)},
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
