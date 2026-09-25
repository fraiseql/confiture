"""Schema differ for detecting database schema changes.

This module provides functionality to:
- Parse SQL DDL statements into structured schema models
- Compare two schemas and detect differences
- Generate migrations from schema diffs
"""

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import pglast

from confiture.core.ddl_objects import objects_in, pair_definitions
from confiture.core.linting.duplicates import WINS_TEXT, CreateFlags, wins
from confiture.core.linting.inventory import (
    Inventory,
    SchemaObject,
    build_inventory,
    group_definitions,
    schema_model,
)
from confiture.core.schema_change import (
    CheckConstraintAdded,
    CheckConstraintDropped,
    ColumnAdded,
    ColumnDefaultChanged,
    ColumnDropped,
    ColumnNullabilityChanged,
    ColumnRenamed,
    ColumnTypeChanged,
    EnumTypeAdded,
    EnumTypeDropped,
    EnumValuesChanged,
    ExclusionConstraintAdded,
    ExclusionConstraintDropped,
    ForeignKeyAdded,
    ForeignKeyDropped,
    IndexAdded,
    IndexDropped,
    ObjectAdded,
    ObjectDropped,
    ObjectReplaced,
    SchemaChange,
    SchemaDiff,
    SequenceAdded,
    SequenceDropped,
    TableAdded,
    TableDropped,
    TableRenamed,
    UniqueConstraintAdded,
    UniqueConstraintDropped,
)
from confiture.core.schema_identity import DEFAULT_SCHEMA
from confiture.core.schema_model import (
    Column,
    EnumType,
    Sequence,
    Table,
    qualified_name,
)
from confiture.core.sql_lexer import blank_copy_blocks
from confiture.core.type_lattice import same_type
from confiture.models.warnings import BuildWarning

logger = logging.getLogger(__name__)


@dataclass
class ParsedSchema:
    """One side of a comparison: the schema model's objects, and what the parse had to say.

    ``tables``, ``enum_types`` and ``sequences`` are the model's, in the order the
    tree declared them. ``objects`` are the ones compared by definition rather than
    by structure (#288) — views, routines, triggers and the rest — keyed by
    ``ObjectRef``; the value carries the definition, so a redefinition in place is
    visible. ``warnings`` is what the parse has to say that is not a change: two
    definitions of one object, resolved the way ``confiture build`` resolves it
    (#313) — always present, empty when there is nothing to report.
    """

    tables: list[Table] = field(default_factory=list)
    enum_types: list[EnumType] = field(default_factory=list)
    sequences: list[Sequence] = field(default_factory=list)
    objects: dict[Any, Any] = field(default_factory=dict)
    warnings: list[BuildWarning] = field(default_factory=list)


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


def duplicate_warnings(inventory: Inventory) -> list[BuildWarning]:
    """Say so when one ``(schema, name)`` is defined more than once in one tree.

    Two definitions of one ``(schema, name)`` collapse into one entry of the
    model (#313). The model keeps the definition a build keeps — a later
    ``IF NOT EXISTS`` is a no-op, a later plain ``CREATE`` fails the build at
    that statement — and the collapse is reported either way. The verdict is ``duplicates.wins``,
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
# When two of a table's own objects, or two column types, are one
# ---------------------------------------------------------------------------


def _object_identity(obj: Any, fields: tuple[str, ...]) -> tuple[Any, ...]:
    """What makes two of a table's own objects the same object.

    Its name, when the schema wrote one. PostgreSQL lets a constraint and an
    index go unnamed — ``pid INT REFERENCES b.parent(id)``, ``CREATE INDEX ON t
    (x)`` — and generates the name at apply time; two unnamed ones on a table are
    two objects, and a map keyed on ``""`` keeps one of them — #313's collapse,
    one field along. Unnamed is the common case: a column-level ``REFERENCES``
    is a foreign key (#315) and almost never carries a name.

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


def _object_sort_key(ref: Any) -> tuple[str, str, str, str]:
    """A stable order for object changes: kind, then schema, then name."""
    return (ref.kind, ref.schema, ref.name, str(ref.signature))


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

        One parse: ``pglast.parse_sql`` once, the statements handed
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
            warnings=duplicate_warnings(inventory),
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
        # Objects compared by definition: views, routines and the rest (#288).
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
        ``etl.t`` are two tables, and pairing one against the other would report
        a ``DROP COLUMN`` on a schema where nothing changed — a migration
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
            changes.append(TableRenamed(old_table, new_table))
            old_only.discard(old_key)
            new_only.discard(new_key)

        changes.extend(TableDropped(old_map[key]) for key in sorted(old_only))
        changes.extend(TableAdded(new_map[key]) for key in sorted(new_only))

        for key in sorted(set(old_map) & set(new_map)):
            old_table = old_map[key]
            new_table = new_map[key]
            changes.extend(self._compare_table_columns(old_table, new_table))
            changes.extend(self._compare_indexes(old_table, new_table))
            changes.extend(self._compare_foreign_keys(old_table, new_table))
            changes.extend(self._compare_check_constraints(old_table, new_table))
            changes.extend(self._compare_unique_constraints(old_table, new_table))
            changes.extend(self._compare_exclusion_constraints(old_table, new_table))

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
            changes.extend(ObjectAdded(ref, obj) for obj in added)
            changes.extend(ObjectDropped(ref, obj) for obj in dropped)
            changes.extend(
                ObjectReplaced(ref, before, after)
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
            changes.append(ColumnRenamed(table, old_name, new_name))
            old_col_names.discard(old_name)
            new_col_names.discard(new_name)

        changes.extend(
            ColumnDropped(table, old_col_map[col_name])
            for col_name in sorted(old_col_names - new_col_names)
        )
        changes.extend(
            ColumnAdded(table, new_col_map[col_name])
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
        # is a change.
        if _types_differ(old_col, new_col):
            changes.append(ColumnTypeChanged(table, old_col, new_col))

        if old_col.not_null != new_col.not_null:
            changes.append(
                ColumnNullabilityChanged(table, old_col.folded, nullable=not new_col.not_null)
            )

        if old_col.default != new_col.default:
            changes.append(
                ColumnDefaultChanged(table, old_col.folded, old_col.default, new_col.default)
            )

        return changes

    # ------------------------------------------------------------------
    # Index, FK, constraint, enum, sequence comparison helpers
    # ------------------------------------------------------------------

    def _compare_indexes(self, old_table: Table, new_table: Table) -> list[SchemaChange]:
        """Detect added / dropped indexes.

        The variant carries the ``Index`` itself, not its name under a key two
        modules have to spell alike: a generator that misses the key takes its
        fallback and creates ``idx_{table}`` instead of the index the author
        declared.
        """
        return self._compare_named_objects(
            old=list(old_table.indexes),
            new=list(new_table.indexes),
            added=IndexAdded,
            dropped=IndexDropped,
            table=old_table.qualified,
            # The access method is part of what an index *is*: a btree and a hash
            # index on one column are two indexes.
            identity=("columns", "unique", "method"),
            compared=("method",),
        )

    def _compare_foreign_keys(self, old_table: Table, new_table: Table) -> list[SchemaChange]:
        """Detect added / dropped foreign keys."""
        return self._compare_named_objects(
            old=list(old_table.constraints_of("foreign_key")),
            new=list(new_table.constraints_of("foreign_key")),
            added=ForeignKeyAdded,
            dropped=ForeignKeyDropped,
            table=old_table.qualified,
            identity=("columns", "ref_table", "ref_columns"),
        )

    def _compare_check_constraints(self, old_table: Table, new_table: Table) -> list[SchemaChange]:
        """Detect added / dropped check constraints."""
        return self._compare_named_objects(
            old=list(old_table.constraints_of("check")),
            new=list(new_table.constraints_of("check")),
            added=CheckConstraintAdded,
            dropped=CheckConstraintDropped,
            table=old_table.qualified,
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
            added=UniqueConstraintAdded,
            dropped=UniqueConstraintDropped,
            table=old_table.qualified,
            identity=("columns",),
        )

    def _compare_exclusion_constraints(
        self, old_table: Table, new_table: Table
    ) -> list[SchemaChange]:
        """Detect added, dropped and changed EXCLUDE constraints.

        Compared whole, as a CHECK is: every part is the parser's rendering, so two
        spellings of one constraint are one, and PostgreSQL has no way to alter one
        in place — a change is its drop and its add.
        """
        parts = ("columns", "operators", "method", "where", "key_options")
        return self._compare_named_objects(
            old=list(old_table.constraints_of("exclusion")),
            new=list(new_table.constraints_of("exclusion")),
            added=ExclusionConstraintAdded,
            dropped=ExclusionConstraintDropped,
            table=old_table.qualified,
            identity=parts,
            compared=parts,
        )

    def _compare_enum_types(
        self, old_enums: list[EnumType], new_enums: list[EnumType]
    ) -> list[SchemaChange]:
        """Detect added / dropped / changed enum types, paired by identity."""
        changes: list[SchemaChange] = []
        old_map = {_identity(e.schema, e.name): e for e in old_enums}
        new_map = {_identity(e.schema, e.name): e for e in new_enums}

        # By identity, as tables are: a `set` iterates in hash order, and a `str`
        # hash is randomised per process, so the same two trees listed their enum
        # types in a different order on every run.
        changes.extend(EnumTypeAdded(new_map[key]) for key in sorted(set(new_map) - set(old_map)))
        changes.extend(EnumTypeDropped(old_map[key]) for key in sorted(set(old_map) - set(new_map)))

        for key in sorted(set(old_map) & set(new_map)):
            old_vals = set(old_map[key].values)
            new_vals = set(new_map[key].values)
            if old_vals != new_vals:
                changes.append(
                    EnumValuesChanged(
                        old_map[key].qualified,
                        added=tuple(sorted(new_vals - old_vals)),
                        removed=tuple(sorted(old_vals - new_vals)),
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

        changes.extend(SequenceAdded(new_map[key]) for key in sorted(set(new_map) - set(old_map)))
        changes.extend(SequenceDropped(old_map[key]) for key in sorted(set(old_map) - set(new_map)))

        return changes

    def _compare_named_objects(
        self,
        *,
        old: list[Any],
        new: list[Any],
        added: Callable[[str, Any], SchemaChange],
        dropped: Callable[[str, Any], SchemaChange],
        table: str,
        identity: tuple[str, ...],
        compared: tuple[str, ...] = (),
    ) -> list[SchemaChange]:
        """Add/drop (and, where asked, replace) comparison for a table's own objects.

        *identity* names the fields that tell two **unnamed** objects apart —
        see :func:`_object_identity`. *compared* names the fields that, differing
        under one name, make the object a change rather than a constant; a kind
        that passes none is compared by add and drop only.

        Emitted in a stable order, and a changed object's drop immediately
        precedes its add: PostgreSQL has no ``ALTER CONSTRAINT``, so replacing one
        *is* the pair, and the pair is only valid in that order.
        """
        changes: list[SchemaChange] = []
        old_map = {_object_identity(obj, identity): obj for obj in old}
        new_map = {_object_identity(obj, identity): obj for obj in new}

        changes.extend(
            added(table, new_map[key]) for key in sorted(set(new_map) - set(old_map), key=str)
        )
        changes.extend(
            dropped(table, old_map[key]) for key in sorted(set(old_map) - set(new_map), key=str)
        )

        for key in sorted(set(old_map) & set(new_map), key=str):
            before, after = old_map[key], new_map[key]
            if any(getattr(before, field) != getattr(after, field) for field in compared):
                changes.append(dropped(table, before))
                changes.append(added(table, after))

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
