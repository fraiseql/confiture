"""Schema differ for detecting database schema changes.

This module provides functionality to:
- Parse SQL DDL statements into structured schema models
- Compare two schemas and detect differences
- Generate migrations from schema diffs
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Literal

import pglast

from confiture.core.ddl_objects import DDLObject, pair_definitions
from confiture.core.ddl_walk import canonical_default
from confiture.core.linting.inventory import signatures_match
from confiture.core.linting.quoted_names import QuotedName
from confiture.core.schema_change import (
    CheckConstraintAdded,
    CheckConstraintDropped,
    ColumnAdded,
    ColumnDefaultChanged,
    ColumnDropped,
    ColumnNullabilityChanged,
    ColumnOrderChanged,
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
    PrimaryKeyAdded,
    PrimaryKeyDropped,
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
from confiture.core.schema_identity import DEFAULT_SCHEMA, identifier_words
from confiture.core.schema_model import (
    ALL_PARITY_RULES,
    TVIEW_OPTIONS,
    Column,
    Constraint,
    EnumType,
    Index,
    ObjectRef,
    Provenance,
    RelationName,
    Routine,
    SchemaModel,
    Sequence,
    Table,
    TView,
    parity_column,
    parity_constraint,
    parity_indexes,
    parity_routine,
    parity_tview,
    parity_view,
)
from confiture.core.schema_read import SchemaRead, read_text
from confiture.core.sql_utils import comment_text
from confiture.core.type_lattice import same_type
from confiture.exceptions import DifferError
from confiture.models.warnings import BuildWarning

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ComparisonPolicy:
    """How two schemas are compared, which follows from who wrote each side.

    Two trees are an author's twice: a table that vanished while a similar one
    appeared was renamed, an unnamed constraint is what it says, an expression is
    compared as written. A tree and a database are not: PostgreSQL rewrites what
    it stores (:data:`~confiture.core.schema_model.PARITY_NORMALISATIONS`), so
    every one of those rewrites is a rule of the comparison, and a database
    renames nothing by similarity. Two databases are both PostgreSQL's spelling,
    compared exactly.

    Attributes:
        name: Which of the three it is.
        renames: Whether a vanished and an appeared table or column are paired
            by similarity as one renamed.
        rules: The parity normalisations applied to both sides before an object
            is compared, each a key of ``PARITY_NORMALISATIONS``.
        author: The side an author wrote when the other is a database's. Its
            unnamed constraints and indexes are paired by what they say, whatever
            name PostgreSQL gave each — a name of PostgreSQL's own shape is not the
            only one it leaves: a renamed table keeps ``old_name_pkey``.
    """

    name: Literal["author", "catalogued", "exact"]
    renames: bool
    rules: frozenset[str]
    author: Literal["old", "new"] | None = None


#: Two trees: today's differ, renames detected, everything as written.
AUTHOR = ComparisonPolicy("author", renames=True, rules=frozenset())
#: A tree and a database, either way round: every parity rule, no fuzzy renames.
CATALOGUED = ComparisonPolicy("catalogued", renames=False, rules=ALL_PARITY_RULES)
#: Two databases: both in PostgreSQL's spelling, nothing to normalise.
EXACT = ComparisonPolicy("exact", renames=False, rules=frozenset())


def policy_between(old: Provenance, new: Provenance) -> ComparisonPolicy:
    """The policy two sides are compared under, from who wrote each."""
    if old == new:
        return AUTHOR if old == "author" else EXACT
    return CATALOGUED


@dataclass(frozen=True)
class Side:
    """One side of a comparison: its model, its objects compared by definition, and its notes.

    ``model`` is what is compared structurally — tables, enum types, sequences —
    and says who wrote it (``model.source``), which decides the policy.
    ``objects`` are the ones compared by definition (#288) — views, routines,
    triggers and the rest — keyed by ``ObjectRef``, each with the definition and
    the ``CREATE`` a migration writes. ``warnings`` is what the read has to say
    that is not a change: two definitions of one object, resolved the way
    ``confiture build`` resolves them (#313). ``quoted`` lists every name that
    needs quotes, which :meth:`SchemaDiffer.compare_sides` refuses.
    """

    model: SchemaModel = field(default_factory=SchemaModel)
    objects: Mapping[ObjectRef, list[DDLObject]] = field(default_factory=dict)
    warnings: list[BuildWarning] = field(default_factory=list)
    quoted: list[QuotedName] = field(default_factory=list)

    @classmethod
    def of(cls, read: SchemaRead, *, held: bool = False) -> Side:
        """The side a tree is: what it writes, its objects, and what its read had to say.

        *held* reads the tree as PostgreSQL holds it once applied
        (``SchemaRead.catalogued``: a partition with its parent's columns), the
        side a database is compared with.
        """
        model = read.catalogued if held else read.model
        return cls(model, read.declared.objects, read.warnings, read.quoted)

    @property
    def tables(self) -> list[Table]:
        """The model's tables, in the order the tree declared them."""
        return list(self.model.tables.values())

    @property
    def enum_types(self) -> list[EnumType]:
        """The model's enum types, in the order the tree declared them."""
        return list(self.model.enum_types.values())

    @property
    def sequences(self) -> list[Sequence]:
        """The model's sequences, in the order the tree declared them."""
        return list(self.model.sequences.values())


def refuse_quoted_names(side: str, quoted: list[QuotedName]) -> None:
    """Refuse a side that gives a name that needs quotes (``DIFFER_403``, #487).

    confiture supports a name only as PostgreSQL writes it bare (#484), and the
    lint that reports one (``naming_003``, ``naming_004``) is not what
    generation runs. Refused here, such a name never reaches a generated
    statement, where a crafted one (``"v; DROP TABLE t; --"``) would be SQL.

    Raises:
        DifferError: ``DIFFER_403``, naming the first such name and how many there are.
    """
    if not quoted:
        return
    first = quoted[0]
    more = len(quoted) - 1
    others = f" (and {more} more)" if more else ""
    raise DifferError(
        f"The {side} schema names {first.kind} {comment_text(first.spelled)}{others}, "
        "which needs quotes: confiture supports a name only as PostgreSQL writes it bare",
        error_code="DIFFER_403",
        resolution_hint=(
            f"Rename it so it needs no quotes, e.g. {comment_text(first.suggested)}; "
            "`confiture lint` lists every such name (naming_003, naming_004)"
        ),
    )


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


def _merged_warnings(old_schema: Side, new_schema: Side) -> list[BuildWarning]:
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
    return _content_identity(obj, fields)


def _content_identity(obj: Any, fields: tuple[str, ...]) -> tuple[Any, ...]:
    """What *obj* says, as :func:`_object_identity` identifies an unnamed one."""
    return (
        "",
        *(
            tuple(value) if isinstance(value, list) else value
            for value in (getattr(obj, field) for field in fields)
        ),
    )


def _pair_by_content(
    unnamed: dict[tuple[Any, ...], list[tuple[Any, Any]]],
    named: dict[tuple[Any, ...], list[tuple[Any, Any]]],
    fields: tuple[str, ...],
) -> None:
    """Re-key each of *named*'s objects under what it says, where *unnamed* has one more saying it.

    *unnamed* is an author's side, whose unnamed objects PostgreSQL names at apply
    time; a name only *named* holds is that name, so the two are one object.
    """
    for key in [key for key in named if key[0] and key not in unnamed]:
        for entry in list(named[key]):
            content = _content_identity(entry[1], fields)
            if len(unnamed.get(content, [])) > len(named.get(content, [])):
                named[key].remove(entry)
                named[content].append(entry)
        if not named[key]:
            del named[key]


def _types_differ(old: Column, new: Column) -> bool:
    """Whether two columns declare different types, typmod included.

    By identity (``type_key``), through ``type_lattice.same_type`` — the one
    canonicaliser, whose own docstring states this case: *a column type must keep
    [typmods] or ``varchar(50)`` and ``varchar(100)`` compare equal*. Never by the
    spellings: ``int4`` and ``integer`` are one type whichever side wrote which.
    """
    return not same_type(old.type_key, new.type_key)


def _fields_differ(fields: tuple[str, ...]) -> Callable[[Any, Any], bool]:
    """Whether two objects paired by identity differ in any of *fields*."""
    return lambda old, new: any(getattr(old, f) != getattr(new, f) for f in fields)


def _built_otherwise(old: Index, new: Index) -> bool:
    """Whether one index under one name is built with another access method.

    A side that does not say how an index is built says nothing about it.
    """
    return None not in (old.method, new.method) and old.method != new.method


def _names(indexes: Iterable[Index]) -> frozenset[str]:
    """The names *indexes* were declared with."""
    return frozenset(index.name for index in indexes if index.name)


def _says_otherwise(old: Constraint, new: Constraint) -> bool:
    """Whether one key-like constraint, paired by name, says something else (#501).

    Its columns; for a foreign key, the table it references, its referential
    actions, and the referenced columns when both sides list them — ``REFERENCES
    p`` with no list means the referenced key, which a database always spells
    out and a tree need not; and when it is checked. A dropped or re-pointed key
    lets rows exist that could not before.
    """
    return (
        old.columns != new.columns
        or _referenced(old.ref_table) != _referenced(new.ref_table)
        or bool(old.ref_columns and new.ref_columns and old.ref_columns != new.ref_columns)
        or (old.on_delete, old.on_update) != (new.on_delete, new.on_update)
        or old.deferrable != new.deferrable
    )


def _referenced(relation: RelationName | None) -> tuple[str, str] | None:
    return None if relation is None else relation.identity


def _default(column: Column, seen: Column, policy: ComparisonPolicy) -> str | None:
    """*column*'s default as *policy* compares it.

    PostgreSQL stores a default analysed (``'x'`` as ``'x'::text``), so under the
    ``analysed_expressions`` rule the default is compared as a parse tree
    (``ddl_walk.canonical_default``) — the value, not its spelling. A default the
    rules already set aside (a ``serial``'s own ``nextval``) stays set aside, and
    one the parser rejects is compared as written.
    """
    if "analysed_expressions" not in policy.rules or seen.default is None:
        return seen.default
    try:
        return canonical_default(column.default, column.type_text or column.type_key)
    except pglast.parser.ParseError:
        return column.default


def _object_sort_key(ref: Any) -> tuple[str, str, str, str]:
    """A stable order for object changes: kind, then schema, then name."""
    return (ref.kind, ref.schema, ref.name, str(ref.signature))


#: The section of the model each object kind is held in; every other kind is an
#: ``OtherObject``.
_SECTIONS: dict[str, str] = {
    "function": "routines",
    "procedure": "routines",
    "aggregate": "routines",
    "view": "views",
    "matview": "views",
    "trigger": "triggers",
    "tview": "tviews",
}


def _section(kind: str) -> str:
    return _SECTIONS.get(kind, "other_objects")


def _held(model: SchemaModel) -> set[ObjectRef]:
    """Every object *model* holds that is compared by definition, by its bucket."""
    return {*model.routines, *model.views, *model.triggers, *model.tviews, *model.other_objects}


def _routine(model: SchemaModel, ref: ObjectRef, obj: DDLObject) -> Routine | None:
    return next(
        (
            r
            for r in model.routines.get(ref, ())
            if signatures_match(obj.signature, r.signature_key)
        ),
        None,
    )


def _redefined(
    ref: ObjectRef,
    before: DDLObject,
    after: DDLObject,
    old: SchemaModel,
    new: SchemaModel,
    policy: ComparisonPolicy,
) -> bool:
    """Whether one object, paired on both sides, is defined differently.

    Two sides in one spelling compare the statements that create it. A tree and
    a database do not: PostgreSQL writes a routine's types, a view's query and a
    TVIEW's options its own way, so each side's model of the object is compared
    through the policy's rules — a routine by its body, language, volatility and
    security, never its spelling; a view by what the rules leave of it; a TVIEW by
    the options it pins. A kind the model holds by existence alone is the same
    object whenever both sides hold it.
    """
    if not policy.rules:
        return before.definition != after.definition
    rules = policy.rules
    section = _section(ref.kind)
    if section == "routines":
        old_routine, new_routine = _routine(old, ref, before), _routine(new, ref, after)
        if old_routine is None or new_routine is None:
            return False
        return parity_routine(old_routine, rules) != parity_routine(new_routine, rules)
    if section == "views":
        return parity_view(old.views[ref], rules) != parity_view(new.views[ref], rules)
    if section == "tviews":
        return _tview_redefined(old.tviews[ref], new.tviews[ref], policy)
    if section == "other_objects" and old.coverage.shared(new.coverage, section) == "definition":
        return before.definition != after.definition
    return False


def _tview_redefined(old: TView, new: TView, policy: ComparisonPolicy) -> bool:
    """Whether one TVIEW, on both sides, is defined differently.

    Against an author's side, an option that side does not pin is pg_tviews' to
    choose, whatever the database holds (``tview_defaults``), and one it pins is
    compared as pinned. With no author side, the rule's own reading decides.
    """
    if policy.author is None:
        return parity_tview(old, policy.rules) != parity_tview(new, policy.rules)
    pins = old if policy.author == "old" else new
    unpinned = {key: None for key in TVIEW_OPTIONS if getattr(pins, key) is None}
    rules = policy.rules - {"tview_defaults"}
    return parity_tview(replace(old, **unpinned), rules) != parity_tview(
        replace(new, **unpinned), rules
    )


class SchemaDiffer:
    """Compares two schemas and says what changed.

    Example:
        >>> differ = SchemaDiffer()
        >>> diff = differ.compare("CREATE TABLE users (id INT);", "CREATE TABLE users (id INT, n TEXT);")
        >>> print(len(diff.changes))
        1
    """

    def parse_sql(self, sql: str) -> list[Table]:
        """The tables *sql* declares, in declaration order.

        Example:
            >>> differ = SchemaDiffer()
            >>> tables = differ.parse_sql("CREATE TABLE users (id INT PRIMARY KEY, name TEXT)")
            >>> print(len(tables))
            1
        """
        return self.parse_schema(sql).tables

    def parse_schema(self, sql: str) -> Side:
        """The side *sql* is: one read (``schema_read.read_text``), nothing parsed here.

        Non-DDL statements (INSERT, COPY, GRANT, …) declare nothing and are ignored.

        Raises:
            SchemaError: ``DIFFER_400`` when PostgreSQL rejects a statement: what it
                rejects is not a schema to diff.
        """
        if not sql or not sql.strip():
            return Side()
        return Side.of(read_text(sql))

    def compare(self, old_sql: str, new_sql: str) -> SchemaDiff:
        """Compare two trees given as text.

        Example:
            >>> differ = SchemaDiffer()
            >>> diff = differ.compare("CREATE TABLE users (id INT);", "CREATE TABLE users (id INT, name TEXT);")
            >>> print(len(diff.changes))
            1
        """
        return self.compare_reads(read_text(old_sql), read_text(new_sql))

    def compare_reads(self, old: SchemaRead, new: SchemaRead) -> SchemaDiff:
        """:meth:`compare`, over two trees already read — each read once, by file."""
        return self.compare_sides(Side.of(old), Side.of(new))

    def compare_sides(
        self, old: Side, new: Side, policy: ComparisonPolicy | None = None
    ) -> SchemaDiff:
        """What changed from *old* to *new*: the one comparison of two schemas.

        Args:
            old: The schema before.
            new: The schema after.
            policy: How to compare them; by default the one their models'
                sources call for (:func:`policy_between`).

        Raises:
            DifferError: ``DIFFER_403`` when either side names an object that needs quotes.
        """
        refuse_quoted_names("old", old.quoted)
        refuse_quoted_names("new", new.quoted)
        if policy is None:
            policy = policy_between(old.model.source, new.model.source)
        if policy.rules and old.model.source != new.model.source:
            policy = replace(policy, author="old" if old.model.source == "author" else "new")

        changes = self._compare_tables(old.tables, new.tables, policy)
        changes.extend(self._compare_enum_types(old.enum_types, new.enum_types))
        changes.extend(self._compare_sequences(old.sequences, new.sequences))
        # Objects compared by definition: views, routines and the rest (#288).
        objects, unwritable = self._compare_objects(old, new, policy)
        changes.extend(objects)
        return SchemaDiff(changes=changes, warnings=[*_merged_warnings(old, new), *unwritable])

    # ------------------------------------------------------------------
    # Table comparison
    # ------------------------------------------------------------------

    def _compare_tables(
        self, old_tables: list[Table], new_tables: list[Table], policy: ComparisonPolicy
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
        old_map = {_identity(t.schema, t.name): t for t in old_tables}
        new_map = {_identity(t.schema, t.name): t for t in new_tables}

        old_only = set(old_map) - set(new_map)
        new_only = set(new_map) - set(old_map)

        # A renamed table is still compared: the rename is one change, and what
        # else the new table declares — columns, indexes, constraints — is more.
        renames = self._renamed_tables(old_only, new_only) if policy.renames else {}
        for old_key, new_key in renames.items():
            old_table, new_table = old_map[old_key], new_map[new_key]
            changes.append(TableRenamed(old_table, new_table))
            # Compared under its new name: every change after the rename runs
            # against a table that no longer answers to the old one.
            renamed = replace(old_table, name=new_table.name, schema=new_table.schema)
            changes.extend(self._compare_table(renamed, new_table, policy))
            old_only.discard(old_key)
            new_only.discard(new_key)

        changes.extend(TableDropped(old_map[key]) for key in sorted(old_only))
        changes.extend(TableAdded(new_map[key]) for key in sorted(new_only))

        for key in sorted(set(old_map) & set(new_map)):
            changes.extend(self._compare_table(old_map[key], new_map[key], policy))

        return changes

    def _compare_table(
        self, old_table: Table, new_table: Table, policy: ComparisonPolicy
    ) -> list[SchemaChange]:
        """What changed inside one table: columns, indexes and every constraint kind."""
        return [
            *self._compare_table_columns(old_table, new_table, policy),
            *self._compare_indexes(old_table, new_table, policy),
            *self._compare_foreign_keys(old_table, new_table, policy),
            *self._compare_check_constraints(old_table, new_table, policy),
            *self._compare_unique_constraints(old_table, new_table, policy),
            *self._compare_primary_keys(old_table, new_table, policy),
            *self._compare_exclusion_constraints(old_table, new_table, policy),
        ]

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

    def _compare_objects(
        self, old: Side, new: Side, policy: ComparisonPolicy
    ) -> tuple[list[SchemaChange], list[BuildWarning]]:
        """Added, dropped and redefined objects, in a stable order — and what cannot be written.

        An object present on both sides whose definition differs is a ``REPLACE``:
        for a view or a routine that is the entire change a migration has to
        carry, and it is invisible to a structural comparison because nothing
        about the object's shape moved. Whether it differs is *policy*'s
        question (:func:`_redefined`).

        The keys are buckets, not identities, so each one's definitions are
        paired by ``pair_definitions`` rather than assumed to be one apiece. A
        kind either side did not read (``Coverage``) is not compared: its
        silence is not absence. An object a side's model holds with no statement
        (a database reads some kinds by existence alone) is the same object as
        the other side's, and when the other side has none, a ``DIFFER_404``
        warning rather than a change no statement can carry.
        """
        changes: list[SchemaChange] = []
        unwritable: list[BuildWarning] = []
        old_held, new_held = _held(old.model), _held(new.model)
        refs = old.objects.keys() | new.objects.keys() | old_held | new_held
        for ref in sorted(refs, key=_object_sort_key):
            if not old.model.coverage.shared(new.model.coverage, _section(ref.kind)):
                continue
            before, after = old.objects.get(ref, []), new.objects.get(ref, [])
            unstated = [
                side
                for side, held, objs in (("old", old_held, before), ("new", new_held, after))
                if ref in held and not objs
            ]
            if unstated:
                if not (ref in old_held and ref in new_held):
                    unwritable.append(
                        BuildWarning.of(
                            "DIFFER_404",
                            kind=ref.kind.replace("_", " ").capitalize(),
                            identity=ref.display,
                            side=unstated[0],
                        )
                    )
                continue
            pairs, dropped, added = pair_definitions(before, after)
            changes.extend(ObjectAdded(ref, obj) for obj in added)
            changes.extend(ObjectDropped(ref, obj) for obj in dropped)
            changes.extend(
                ObjectReplaced(ref, b, a)
                for b, a in pairs
                if _redefined(ref, b, a, old.model, new.model, policy)
            )
        return changes, unwritable

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

    def _compare_table_columns(
        self, old_table: Table, new_table: Table, policy: ComparisonPolicy
    ) -> list[SchemaChange]:
        """Compare columns between two versions of the same table."""
        changes: list[SchemaChange] = []

        table = old_table.relation
        # By the parser's spelling of each name, which is also what generated DDL
        # writes: an unquoted `UserId` is the column `userid`.
        old_col_map = {c.folded: c for c in old_table.columns}
        new_col_map = {c.folded: c for c in new_table.columns}

        old_col_names = set(old_col_map.keys())
        new_col_names = set(new_col_map.keys())

        renamed_columns = (
            self._detect_column_renames(
                sorted(old_col_names - new_col_names), sorted(new_col_names - old_col_names)
            )
            if policy.renames
            else {}
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
            # In declaration order: ADD COLUMN appends, so a table whose new columns
            # come last ends up in the order the tree declares.
            ColumnAdded(table, column)
            for column in new_table.columns
            if column.folded in new_col_names - old_col_names
        )

        for col_name in sorted(old_col_names & new_col_names):
            old_col = old_col_map[col_name]
            new_col = new_col_map[col_name]
            changes.extend(self._compare_column_properties(table, old_col, new_col, policy))

        # Observed only where a database is a side: two trees that list a table's
        # columns in another order have not changed it, and no statement reorders one.
        old_order, new_order = tuple(old_col_map), tuple(new_col_map)
        if policy.rules and set(old_order) == set(new_order) and old_order != new_order:
            changes.append(ColumnOrderChanged(table, old_order, new_order))

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
        self, table: RelationName, old_col: Column, new_col: Column, policy: ComparisonPolicy
    ) -> list[SchemaChange]:
        """Compare properties of a column, each as *policy*'s rules see it.

        *table* is the table's **spelling**, what a finding prints and what
        generated DDL alters — never an identity. The two are separate fields on
        the model for the same reason ``SchemaObject.signature`` and
        ``signature_key`` are (#275). A change carries what each side wrote; the
        rules decide only whether there is one.
        """
        changes: list[SchemaChange] = []
        old_seen = parity_column(old_col, policy.rules)
        new_seen = parity_column(new_col, policy.rules)

        # Type change, typmod included: a `varchar(50)` widened to `varchar(100)`
        # is a change.
        if _types_differ(old_seen, new_seen):
            changes.append(ColumnTypeChanged(table, old_col, new_col))

        if old_seen.not_null != new_seen.not_null:
            changes.append(
                ColumnNullabilityChanged(table, old_col.folded, nullable=not new_col.not_null)
            )

        if _default(old_col, old_seen, policy) != _default(new_col, new_seen, policy):
            changes.append(
                ColumnDefaultChanged(table, old_col.folded, old_col.default, new_col.default)
            )

        return changes

    # ------------------------------------------------------------------
    # Index, FK, constraint, enum, sequence comparison helpers
    # ------------------------------------------------------------------

    def _compare_indexes(
        self, old_table: Table, new_table: Table, policy: ComparisonPolicy
    ) -> list[SchemaChange]:
        """Detect added / dropped indexes.

        The variant carries the ``Index`` itself, not its name under a key two
        modules have to spell alike: a generator that misses the key takes its
        fallback and creates ``idx_{table}`` instead of the index the author
        declared.
        """
        return self._compare_named_objects(
            author=policy.author,
            old=parity_indexes(old_table.indexes, policy.rules, _names(new_table.indexes)),
            new=parity_indexes(new_table.indexes, policy.rules, _names(old_table.indexes)),
            added=IndexAdded,
            dropped=IndexDropped,
            table=old_table.relation,
            # The access method is part of what an index *is*: a btree and a hash
            # index on one column are two indexes.
            identity=("columns", "unique", "method"),
            differs=_built_otherwise,
        )

    @staticmethod
    def _constraints(table: Table, kind: str, policy: ComparisonPolicy) -> list[tuple[Any, Any]]:
        """*table*'s constraints of *kind*, each paired with how *policy*'s rules see it."""
        return [
            (constraint, parity_constraint(table.name, constraint, policy.rules))
            for constraint in table.constraints_of(kind)
        ]

    def _compare_foreign_keys(
        self, old_table: Table, new_table: Table, policy: ComparisonPolicy
    ) -> list[SchemaChange]:
        """Detect added / dropped foreign keys."""
        return self._compare_named_objects(
            author=policy.author,
            old=self._constraints(old_table, "foreign_key", policy),
            new=self._constraints(new_table, "foreign_key", policy),
            added=ForeignKeyAdded,
            dropped=ForeignKeyDropped,
            table=old_table.relation,
            # Not the referenced columns: `REFERENCES p` means p's key, which a
            # database always spells out and a tree need not (`_says_otherwise`).
            identity=("columns", "ref_table"),
            differs=_says_otherwise,
        )

    def _compare_check_constraints(
        self, old_table: Table, new_table: Table, policy: ComparisonPolicy
    ) -> list[SchemaChange]:
        """Detect added / dropped check constraints."""
        return self._compare_named_objects(
            author=policy.author,
            old=self._constraints(old_table, "check", policy),
            new=self._constraints(new_table, "check", policy),
            added=CheckConstraintAdded,
            dropped=CheckConstraintDropped,
            table=old_table.relation,
            identity=("expression",),
            # The one kind whose body is compared, and the only one that can be:
            # the expression is `RawStream`'s rendering of the parsed predicate, so
            # two spellings of one predicate are one string. A foreign key's
            # referenced column list written on one side and left implicit on the
            # other is the same constraint spelled twice, and telling that apart
            # means resolving the parent's primary key — so reporting it would
            # generate a DROP CONSTRAINT for a constraint that did not change.
            differs=_fields_differ(("expression",)),
        )

    def _compare_unique_constraints(
        self, old_table: Table, new_table: Table, policy: ComparisonPolicy
    ) -> list[SchemaChange]:
        """Detect added / dropped unique constraints."""
        return self._compare_named_objects(
            author=policy.author,
            old=self._constraints(old_table, "unique", policy),
            new=self._constraints(new_table, "unique", policy),
            added=UniqueConstraintAdded,
            dropped=UniqueConstraintDropped,
            table=old_table.relation,
            identity=("columns",),
            differs=_says_otherwise,
        )

    def _compare_primary_keys(
        self, old_table: Table, new_table: Table, policy: ComparisonPolicy
    ) -> list[SchemaChange]:
        """Detect an added, dropped or re-keyed primary key."""
        return self._compare_named_objects(
            author=policy.author,
            old=self._constraints(old_table, "primary_key", policy),
            new=self._constraints(new_table, "primary_key", policy),
            added=PrimaryKeyAdded,
            dropped=PrimaryKeyDropped,
            table=old_table.relation,
            identity=("columns",),
            differs=_says_otherwise,
        )

    def _compare_exclusion_constraints(
        self, old_table: Table, new_table: Table, policy: ComparisonPolicy
    ) -> list[SchemaChange]:
        """Detect added, dropped and changed EXCLUDE constraints.

        Compared whole, as a CHECK is: every part is the parser's rendering, so two
        spellings of one constraint are one, and PostgreSQL has no way to alter one
        in place — a change is its drop and its add.
        """
        parts = ("columns", "operators", "method", "where", "key_options")
        return self._compare_named_objects(
            author=policy.author,
            old=self._constraints(old_table, "exclusion", policy),
            new=self._constraints(new_table, "exclusion", policy),
            added=ExclusionConstraintAdded,
            dropped=ExclusionConstraintDropped,
            table=old_table.relation,
            identity=parts,
            differs=_fields_differ(parts),
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
        old: list[tuple[Any, Any]],
        new: list[tuple[Any, Any]],
        added: Callable[[RelationName, Any], SchemaChange],
        dropped: Callable[[RelationName, Any], SchemaChange],
        table: RelationName,
        identity: tuple[str, ...],
        differs: Callable[[Any, Any], bool] | None = None,
        author: Literal["old", "new"] | None = None,
    ) -> list[SchemaChange]:
        """Add/drop (and, where asked, replace) comparison for a table's own objects.

        *old* and *new* pair each object with how the policy's rules see it: the
        rules decide identity and change, the change carries what the side wrote.
        *identity* names the fields that tell two **unnamed** objects apart —
        see :func:`_object_identity`. *differs* says whether two objects paired
        under one identity are a change rather than a constant; a kind that
        passes none is compared by add and drop only.

        Two unnamed objects can say the same thing — under the catalogued policy
        every CHECK says ``<expression>`` — so each identity holds a list, paired
        in order: one more on a side is one added or dropped, never one collapsed
        into another. An *author* side's unnamed object is paired by what it
        says with the other side's under any name that side alone holds.

        Emitted in a stable order, and a changed object's drop immediately
        precedes its add: PostgreSQL has no ``ALTER CONSTRAINT``, so replacing one
        *is* the pair, and the pair is only valid in that order.
        """
        changes: list[SchemaChange] = []
        old_map: dict[tuple[Any, ...], list[tuple[Any, Any]]] = defaultdict(list)
        new_map: dict[tuple[Any, ...], list[tuple[Any, Any]]] = defaultdict(list)
        for found, pairs in ((old, old_map), (new, new_map)):
            for obj, seen in found:
                pairs[_object_identity(seen, identity)].append((obj, seen))
        if author is not None:
            _pair_by_content(
                *((old_map, new_map) if author == "old" else (new_map, old_map)), identity
            )
        keys = sorted(old_map.keys() | new_map.keys(), key=str)

        changes.extend(
            added(table, obj)
            for key in keys
            for obj, _ in new_map.get(key, [])[len(old_map.get(key, [])) :]
        )
        changes.extend(
            dropped(table, obj)
            for key in keys
            for obj, _ in old_map.get(key, [])[len(new_map.get(key, [])) :]
        )

        for key in keys:
            for (before, before_seen), (after, after_seen) in zip(
                old_map.get(key, []), new_map.get(key, []), strict=False
            ):
                if differs is not None and differs(before_seen, after_seen):
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

        name1_parts = list(identifier_words(name1))
        name2_parts = list(identifier_words(name2))

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
