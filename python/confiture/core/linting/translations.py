"""``i18n_001``: a translation table has the shape a coverage check can count (#657).

A project that translates reference data keeps one translation table per
translated entity — ``tl_category (fk_category, fk_locale, label)`` beside
``tb_category`` and the locale table — and declares them in ``db/project.yaml``
(``translations:``). Each table it names must:

- carry the locale column (``locale_fk``) and reference the locale table with it;
- translate **one** entity: the foreign key whose columns, with the locale
  column, form a unique key (an audit key such as ``fk_created_by`` is no
  entity, so "exactly one other foreign key" would be the wrong test);
- hold one row per entity and locale — among live rows when it soft-deletes, so
  through a unique index whose ``WHERE`` excludes the tombstone;
- reference an entity table the tree creates.

A glob that matches no table, and a locale table the tree does not create, are
findings too: a typo is never an empty success.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase

from confiture.config.project import TranslationsConfig
from confiture.core import sql_lexer
from confiture.core.linting.inventory import (
    DEFAULT_SCHEMA,
    Inventory,
    SchemaObject,
    distinct,
)
from confiture.core.linting.soft_delete import SoftDeleting, excludes_tombstones, written_keys
from confiture.core.linting.tombstones import key_of
from confiture.core.schema_identity import identifier_identity
from confiture.core.schema_model import Constraint, RelationName
from confiture.core.sql_lexer import ParsedFile

RULE_ID = "i18n_001"


@dataclass(frozen=True)
class TranslationFinding:
    """One way a translation table, or the declaration, is not what a coverage check needs."""

    object_name: str
    message: str
    fix: str
    file: str | None
    line: int


@dataclass(frozen=True)
class TranslationTable:
    """A translation table ``i18n_001`` accepts: what a live coverage count reads.

    Attributes:
        table: The translation table.
        entity_columns: Its foreign key to the translated entity.
        entity: The entity table.
        entity_key: The entity's columns that key references, in the same order.
        locale_columns: The locale table's columns ``locale_fk`` references.
        tombstone: The translation table's tombstone column when it soft-deletes.
        entity_tombstone: The entity table's, when it soft-deletes.
    """

    table: RelationName
    entity_columns: tuple[str, ...]
    entity: RelationName
    entity_key: tuple[str, ...]
    locale_columns: tuple[str, ...]
    tombstone: str | None
    entity_tombstone: str | None


@dataclass(frozen=True)
class Shapes:
    """The translation tables a tree declares: those a count can read, and those it cannot."""

    tables: list[TranslationTable]
    #: ``i18n_001``'s findings: a table named here is not counted.
    refused: list[TranslationFinding]


@dataclass(frozen=True)
class _Name:
    """A configured table name, folded: its schema (``None`` for any) and its name."""

    schema: str | None
    name: str

    @classmethod
    def read(cls, written: str) -> _Name:
        parts = [identifier_identity(p) for p in sql_lexer.name_parts(written) or (written,)]
        return cls(None, parts[0]) if len(parts) == 1 else cls(parts[0], parts[-1])

    def names(self, schema: str | None, name: str) -> bool:
        own = (schema or DEFAULT_SCHEMA).lower()
        return name == self.name and (self.schema is None or self.schema == own)


def matches(glob: str, table: SchemaObject) -> bool:
    """Whether a ``translations.tables`` glob names *table*.

    A glob with a dot is matched against ``schema.name`` (the schema folded in
    when the table names none), one without against the name in any schema.
    Both sides are folded, so ``TL_*`` and ``tl_*`` are one glob.
    """
    pattern = glob.strip().lower()
    if "." in pattern:
        schema = (table.folded_schema or DEFAULT_SCHEMA).lower()
        return fnmatchcase(f"{schema}.{table.folded_name}", pattern)
    return fnmatchcase(table.folded_name, pattern)


def translation_findings(
    inventory: Inventory,
    files: Sequence[ParsedFile],
    config: TranslationsConfig,
    deleting: SoftDeleting | None,
) -> list[TranslationFinding]:
    """Every ``i18n_001`` finding: the declaration's, then each translation table's."""
    return translation_shapes(inventory, files, config, deleting).refused


def translation_shapes(
    inventory: Inventory,
    files: Sequence[ParsedFile],
    config: TranslationsConfig,
    deleting: SoftDeleting | None,
) -> Shapes:
    """Each declared translation table judged once: counted, or refused by ``i18n_001``."""
    tables = [obj for obj in distinct(inventory.objects) if obj.kind == "table"]
    locale = _Name.read(config.locale_table)
    findings = [
        TranslationFinding(
            f"translations.tables:{glob}",
            f"translations.tables {glob!r} matches no table",
            "Correct the glob, or drop it.",
            None,
            1,
        )
        for glob in config.tables
        if not any(matches(glob, table) for table in tables)
    ]
    if not any(locale.names(t.folded_schema, t.folded_name) for t in tables):
        findings.append(
            TranslationFinding(
                f"translations.locale_table:{config.locale_table}",
                f"translations.locale_table {config.locale_table} is not a table the tree creates",
                "Name the locale table as the tree creates it.",
                None,
                1,
            )
        )
    shapes: list[TranslationTable] = []
    for table in tables:
        if any(matches(glob, table) for glob in config.tables):
            judged = _Table(table, config, locale, inventory, files, deleting)
            refused = judged.findings()
            findings.extend(refused)
            shape = None if refused else judged.shape(deleting)
            if shape is not None:
                shapes.append(shape)
    return Shapes(shapes, findings)


class _Table:
    """One translation table, judged clause by clause."""

    def __init__(
        self,
        table: SchemaObject,
        config: TranslationsConfig,
        locale: _Name,
        inventory: Inventory,
        files: Sequence[ParsedFile],
        deleting: SoftDeleting | None,
    ) -> None:
        self.table = table
        self.config = config
        self.locale = locale
        self.inventory = inventory
        self.files = files
        self.live = deleting is not None and deleting.judges(table)
        self.tombstone = deleting.column if deleting is not None else None
        self.locale_fk = identifier_identity(config.locale_fk)

    def findings(self) -> list[TranslationFinding]:
        name, fk = self.table.qualified, self.config.locale_fk
        if not any(column.folded == self.locale_fk for column in self.table.columns):
            return [self._finding("locale_fk", f"{name} has no column {fk}", f"Add {fk}.")]
        found: list[TranslationFinding] = []
        if not any(self._references_locale(key) for key in self._foreign_keys()):
            found.append(
                self._finding(
                    "locale_reference",
                    f"{name}.{fk} does not reference {self.config.locale_table}",
                    f"Add FOREIGN KEY ({fk}) REFERENCES {self.config.locale_table}.",
                )
            )
        found.extend(self._entity())
        return found

    def _entity(self) -> list[TranslationFinding]:
        name, fk = self.table.qualified, self.config.locale_fk
        keys = self._unique_keys()
        entities = [
            key
            for key in self._foreign_keys()
            if not self._references_locale(key)
            and self.locale_fk not in _folded(key.columns)
            and frozenset(_folded(key.columns)) | {self.locale_fk} in keys
        ]
        if len(entities) > 1:
            listed = ", ".join(", ".join(key.columns) for key in entities)
            return [
                self._finding(
                    "entity",
                    f"{name} translates more than one entity: {listed} each form a unique "
                    f"key with {fk}",
                    "Keep one translated entity per translation table.",
                )
            ]
        if not entities:
            return [self._no_unique_key()]
        return self._entity_created(entities[0])

    def _no_unique_key(self) -> TranslationFinding:
        name, fk = self.table.qualified, self.config.locale_fk
        others = [k for k in self._foreign_keys() if not self._references_locale(k)]
        hint = ""
        if len(others) >= 1 and others[0].ref_table is not None:
            columns = ", ".join(others[0].columns)
            hint = f" (UNIQUE ({columns}, {fk}), the one referencing {others[0].ref_table.name}?)"
        live = " among live rows" if self.live else ""
        where = f" WHERE {self.tombstone} IS NULL" if self.live else ""
        return self._finding(
            "unique_key",
            f"{name} holds more than one row per entity and locale{live}: no foreign key "
            f"forms a unique key with {fk}{hint}",
            f"Add a unique key over the entity's foreign key and {fk}"
            + (f" (a unique index{where})" if self.live else "")
            + ".",
        )

    def _entity_created(self, key: Constraint) -> list[TranslationFinding]:
        target = key.ref_table
        if target is None or self._created(key) is not None:
            return []
        spelled = f"{target.schema}.{target.name}" if target.schema else target.name
        return [
            self._finding(
                "entity_table",
                f"{self.table.qualified}.{', '.join(key.columns)} references {spelled}, "
                "which the tree does not create",
                "Create the entity table in the tree, or correct the foreign key.",
            )
        ]

    def shape(self, deleting: SoftDeleting | None) -> TranslationTable | None:
        """What a coverage count reads of this table, which :meth:`findings` accepted."""
        locale_key = next(k for k in self._foreign_keys() if self._references_locale(k))
        (entity_fk,) = [
            key
            for key in self._foreign_keys()
            if not self._references_locale(key)
            and frozenset(_folded(key.columns)) | {self.locale_fk} in self._unique_keys()
        ]
        entity = self._created(entity_fk)
        locale = next(
            (
                obj
                for obj in self.inventory.objects
                if obj.kind == "table" and self.locale.names(obj.folded_schema, obj.folded_name)
            ),
            None,
        )
        if entity is None or locale is None:
            return None
        entity_key = entity_fk.ref_columns or _primary_key(entity)
        locale_columns = locale_key.ref_columns or _primary_key(locale)
        if len(entity_key) != len(entity_fk.columns) or len(locale_columns) != 1:
            return None
        return TranslationTable(
            table=RelationName(self.table.schema, self.table.name),
            entity_columns=entity_fk.columns,
            entity=RelationName(entity.schema, entity.name),
            entity_key=tuple(entity_key),
            locale_columns=tuple(locale_columns),
            tombstone=self.tombstone if self.live else None,
            entity_tombstone=(
                deleting.column if deleting is not None and deleting.judges(entity) else None
            ),
        )

    def _created(self, key: Constraint) -> SchemaObject | None:
        """The table the tree creates that *key* references, or ``None``."""
        target = key.ref_table
        if target is None:
            return None
        wanted = _Name(
            None if target.schema is None else identifier_identity(target.schema),
            identifier_identity(target.name),
        )
        return next(
            (
                obj
                for obj in self.inventory.objects
                if obj.kind == "table" and wanted.names(obj.folded_schema, obj.folded_name)
            ),
            None,
        )

    def _foreign_keys(self) -> Iterator[Constraint]:
        return (key for key in self.table.constraints if key.kind == "foreign_key")

    def _references_locale(self, key: Constraint) -> bool:
        target = key.ref_table
        return (
            target is not None
            and _folded(key.columns) == (self.locale_fk,)
            and self.locale.names(
                None if target.schema is None else identifier_identity(target.schema),
                identifier_identity(target.name),
            )
        )

    def _unique_keys(self) -> set[frozenset[str]]:
        """The column sets that hold one row each: among live rows when the table soft-deletes."""
        if self.live and self.tombstone is not None:
            mine = key_of(self.table)
            return {
                frozenset(_folded(key.columns))
                for key in written_keys(self.inventory, self.files)
                if key_of(key.table) == mine
                and not any(key.expressions)
                and excludes_tombstones(key, self.tombstone)
            }
        keys = {
            frozenset(_folded(key.columns))
            for key in self.table.constraints
            if key.kind in ("primary_key", "unique") and not key.where
        }
        keys |= {
            frozenset(_folded(index.columns))
            for index in self.table.indexes
            if index.unique and not index.where and not any(index.expressions or ())
        }
        return keys

    def _finding(self, clause: str, message: str, fix: str) -> TranslationFinding:
        return TranslationFinding(
            f"{self.table.qualified}:{clause}", message, fix, self.table.file, self.table.line
        )


def _primary_key(table: SchemaObject) -> tuple[str, ...]:
    return next((key.columns for key in table.constraints if key.kind == "primary_key"), ())


def _folded(columns: Sequence[str]) -> tuple[str, ...]:
    return tuple(identifier_identity(column) for column in columns)
