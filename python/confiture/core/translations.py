"""Which entity rows have no translation in a required locale, counted live (#657).

A project that translates reference data declares its translation tables in
``db/project.yaml`` (``translations:``) and the locales a release promises. A
missing translation is no error: a projection falls back to another locale, or
to an identifier, and nobody learns which rows are missing until a reader does.
This counts them — per translation table and required locale, the entity rows
with no translation in that locale, and the first few of their keys:

    tl_category: fr-FR 0 missing, en-US 14 missing (e.g. 7, 9, 12)

The tables are read from the tree, as ``i18n_001`` judges them: a table it
refuses is not counted, and is named. A soft-deleting table counts live rows
only — a deleted entity needs no label, a deleted label is none. Locales come
from ``required``, or from ``required_query``, the project's own SQL, run as
written; a required locale the locale table lacks is named, and every entity
misses it.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from string.templatelib import Template
from typing import Any

from psycopg import sql as pgsql

from confiture.config.project import ProjectConfig, TranslationsConfig
from confiture.core import sql_lexer
from confiture.core.connection import Connection
from confiture.core.linting.inventory import build_inventory
from confiture.core.linting.soft_delete import soft_deleting
from confiture.core.linting.translations import TranslationTable, translation_shapes
from confiture.core.schema_identity import identifier_identity
from confiture.core.schema_model import RelationName
from confiture.core.sql_lexer import ParsedFile


@dataclass(frozen=True)
class LocaleGap:
    """One required locale of one translation table: how many entities miss it, and which."""

    locale: str
    missing: int
    sample: tuple[str, ...]


@dataclass(frozen=True)
class TableCoverage:
    """One translation table and each required locale's gap, in the order they are required."""

    table: str
    gaps: tuple[LocaleGap, ...]

    def line(self) -> str:
        """``tl_category: fr-FR 0 missing, en-US 14 missing (e.g. 7, 9, 12)``."""
        parts = [
            f"{gap.locale} {gap.missing} missing"
            + (f" (e.g. {', '.join(gap.sample)})" if gap.sample else "")
            for gap in self.gaps
        ]
        return f"{self.table}: {', '.join(parts)}"


@dataclass(frozen=True)
class Coverage:
    """What a coverage count found, and what it could not count.

    Attributes:
        locales: The required locales, in order.
        tables: Each translation table counted.
        unknown_locales: Required locales the locale table does not hold.
        not_counted: ``i18n_001``'s findings: the tables, or the declaration, it refused.
    """

    locales: tuple[str, ...]
    tables: tuple[TableCoverage, ...]
    unknown_locales: tuple[str, ...]
    not_counted: tuple[str, ...]

    @property
    def missing(self) -> int:
        """Every entity row missing a translation, over every table and locale."""
        return sum(gap.missing for table in self.tables for gap in table.gaps)

    def to_dict(self) -> dict[str, Any]:
        """The JSON shape of a coverage count."""
        return {
            "locales": list(self.locales),
            "missing": self.missing,
            "tables": [
                {
                    "table": table.table,
                    "locales": [
                        {"locale": g.locale, "missing": g.missing, "sample": list(g.sample)}
                        for g in table.gaps
                    ],
                }
                for table in self.tables
            ],
            "unknown_locales": list(self.unknown_locales),
            "not_counted": list(self.not_counted),
        }


def translation_coverage(
    conn: Connection, files: Sequence[ParsedFile], project: ProjectConfig, sample: int = 3
) -> Coverage:
    """Count, on *conn*, the translations the tree's translation tables miss.

    *files* are the schema tree, parsed (``sql_lexer.parse_file``); *project* its
    ``db/project.yaml``, which must declare ``translations:``. The caller owns the
    connection and its transaction: this only reads.
    """
    config = project.translations
    if config is None:
        raise ValueError("db/project.yaml declares no translations: block")
    inventory = build_inventory(files)
    deleting = (
        None
        if project.soft_delete is None
        else soft_deleting(inventory, files, project.soft_delete)
    )
    shapes = translation_shapes(inventory, files, config, deleting)
    locale = _locale_table(config)
    column = identifier_identity(config.locale_column)
    locales = tuple(config.required) or _required_by_query(conn, config)
    # Built, then executed: the relation is a nested fragment, schema-qualified or not.
    held = t"SELECT {column:i} FROM {_relation(locale):q} WHERE {column:i} = ANY({list(locales)})"
    known = {row[0] for row in conn.execute(held).fetchall()}
    counted = tuple(
        TableCoverage(
            _spelled(shape.table),
            tuple(_gap(conn, shape, locale, config, code, max(sample, 0)) for code in locales),
        )
        for shape in shapes.tables
    )
    return Coverage(
        locales=locales,
        tables=counted,
        unknown_locales=tuple(code for code in locales if code not in known),
        not_counted=tuple(finding.message for finding in shapes.refused),
    )


def _required_by_query(conn: Connection, config: TranslationsConfig) -> tuple[str, ...]:
    """The locales ``required_query`` returns: the project's SQL, run as written."""
    if config.required_query is None:
        return ()
    return tuple(str(row[0]) for row in conn.execute(Template(config.required_query)).fetchall())


def _gap(
    conn: Connection,
    shape: TranslationTable,
    locale: RelationName,
    config: TranslationsConfig,
    code: str,
    sample: int,
) -> LocaleGap:
    """How many live entities *shape* has no live translation of in *code*, and the first keys."""
    joined = pgsql.SQL(" AND ").join(
        t"t.{mine:i} = e.{theirs:i}"
        for mine, theirs in zip(shape.entity_columns, shape.entity_key, strict=True)
    )
    keys = pgsql.SQL(", ").join(t"e.{k:i}::text" for k in shape.entity_key)
    order = pgsql.SQL(", ").join(t"e.{k:i}" for k in shape.entity_key)
    live_entity = t"e.{shape.entity_tombstone:i} IS NULL" if shape.entity_tombstone else t"true"
    live_label = t"t.{shape.tombstone:i} IS NULL" if shape.tombstone else t"true"
    locale_fk = identifier_identity(config.locale_fk)
    column = identifier_identity(config.locale_column)
    (referenced,) = shape.locale_columns
    # Built, then executed: relations and key lists are nested fragments.
    missing_rows = t"""SELECT count(*) OVER (), concat_ws(', ', {keys:q})
FROM {_relation(shape.entity):q} e
WHERE {live_entity:q} AND NOT EXISTS (
    SELECT 1 FROM {_relation(shape.table):q} t
    JOIN {_relation(locale):q} l ON l.{referenced:i} = t.{locale_fk:i}
    WHERE {joined:q} AND l.{column:i} = {code} AND {live_label:q}
)
ORDER BY {order:q}
LIMIT {max(sample, 1)}"""
    rows = conn.execute(missing_rows).fetchall()
    missing = rows[0][0] if rows else 0
    return LocaleGap(code, missing, tuple(row[1] for row in rows[:sample]))


def _locale_table(config: TranslationsConfig) -> RelationName:
    parts = sql_lexer.name_parts(config.locale_table) or (config.locale_table,)
    return RelationName(None, parts[0]) if len(parts) == 1 else RelationName(parts[0], parts[-1])


def _relation(name: RelationName) -> Template:
    return t"{name.schema:i}.{name.name:i}" if name.schema else t"{name.name:i}"


def _spelled(name: RelationName) -> str:
    return f"{name.schema}.{name.name}" if name.schema else name.name
