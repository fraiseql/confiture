"""The relations another tool owns, left out of a comparison: ``diff.exclude`` and ``--exclude`` (#767).

A runtime that creates its own bookkeeping tables (FraiseQL's ``_fraiseql_*``) has a
database the tree never declares in full. An :class:`Exclusion` names those
relations by pattern and is applied once, to both sides a comparison is handed
(``SchemaDiffer.compare_sides``), so every comparator that reads the engine —
``migrate diff``, ``confiture drift``, ``migrate validate --check-live-drift`` —
leaves out the same relations.

A pattern with no dot matches a relation's name in any schema; one with a dot
matches ``schema.name``. Each part is a glob over an *object name*
(``fnmatch.fnmatchcase``: case-sensitive, ``*``, ``?`` and ``[…]``), never a path.

What an excluded relation takes with it: the table, view, materialized view,
TVIEW, sequence or foreign table itself, and what belongs to it — its columns,
constraints and indexes (held on it), the triggers, policies and rules on it,
and an index a tree writes on it. A user object that still depends on it — a
foreign key that references it, or a trigger, policy, rule or index a tree
writes on it — is said (``DIFFER_411``) rather than skipped in silence. A view's
or a routine's reads are text the model does not resolve, so they are not.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from fnmatch import fnmatchcase
from typing import Any

from pydantic import ValidationError

from confiture.config.environment import DiffConfig
from confiture.core.schema_model import ObjectRef, SchemaModel
from confiture.core.sql_lexer import name_parts
from confiture.exceptions import ConfigurationError
from confiture.models.warnings import BuildWarning

#: The kinds of object that are a relation, as the model keys them.
RELATION_KINDS = frozenset({"table", "view", "matview", "tview", "sequence", "foreign_table"})

#: The kinds of object that belong to the relation their name starts with (``table.name``).
_ON_A_RELATION = frozenset({"policy", "rule"})

#: The glob characters a pattern may hold, which the SQL scanner reads as operators.
_GLOB = frozenset("*?[]!-")


@dataclass(frozen=True)
class RelationPattern:
    """One pattern: a glob over a relation's name, and over its schema when it names one."""

    written: str
    name: str
    schema: str | None = None

    @classmethod
    def of(cls, written: str) -> RelationPattern:
        """*written* read as ``name`` or ``schema.name``, each part a glob.

        Raises:
            ConfigurationError: ``CONFIG_001`` when *written* is not one or two dotted parts.
        """
        parts = _parts(written)
        if parts is None or len(parts) > len(("schema", "name")):
            raise ConfigurationError(
                f"diff.exclude: {written!r} is not a relation pattern",
                error_code="CONFIG_001",
                resolution_hint=(
                    "Write `name` (any schema) or `schema.name`, each part a glob: "
                    "`_fraiseql_*`, `public._fraiseql_*`"
                ),
            )
        return cls(written, parts[-1], parts[0] if len(parts) > 1 else None)

    def matches(self, schema: str, name: str) -> bool:
        """Whether the relation *schema*.*name* is one this pattern names."""
        if self.schema is not None and not fnmatchcase(schema, self.schema):
            return False
        return fnmatchcase(name, self.name)


def _parts(written: str) -> list[str] | None:
    """*written*'s dotted parts, read by the scanner with each glob character standing in.

    The scanner reads ``*`` as an operator, so it reads a copy in which each glob
    character is a letter — the same length, so each part is found again at its
    place in *written*.
    """
    shadow = "".join("x" if char in _GLOB else char for char in written)
    parts = name_parts(shadow)
    if parts is None:
        return None
    found: list[str] = []
    at = 0
    for part in parts:
        at = shadow.index(part, at)
        found.append(written[at : at + len(part)])
        at += len(part)
    return found


@dataclass(frozen=True)
class Exclusion:
    """The relations a comparison leaves out, by pattern; empty leaves out nothing."""

    patterns: tuple[RelationPattern, ...] = ()

    @classmethod
    def of(cls, *written: Iterable[str] | None) -> Exclusion:
        """The patterns in each of *written*, in order: the config's, then the CLI's.

        Raises:
            ConfigurationError: ``CONFIG_001`` for a pattern that is not one.
        """
        seen: dict[str, RelationPattern] = {}
        for group in written:
            for pattern in group or ():
                seen.setdefault(pattern, RelationPattern.of(pattern))
        return cls(tuple(seen.values()))

    def __bool__(self) -> bool:
        return bool(self.patterns)

    def pattern_for(self, schema: str, name: str) -> RelationPattern | None:
        """The first pattern that leaves the relation *schema*.*name* out, or ``None``."""
        return next((p for p in self.patterns if p.matches(schema, name)), None)

    def excludes(self, schema: str, name: str) -> bool:
        """Whether the relation *schema*.*name* is left out."""
        return self.pattern_for(schema, name) is not None

    def excludes_ref(self, ref: ObjectRef) -> bool:
        """Whether *ref* is an excluded relation, or a policy or rule on one."""
        if ref.kind in RELATION_KINDS:
            return self.excludes(ref.schema, ref.name)
        if ref.kind in _ON_A_RELATION:
            parts = name_parts(ref.name)
            return parts is not None and len(parts) > 1 and self.excludes(ref.schema, parts[0])
        return False


def exclusion_from(config_data: Any, cli: Iterable[str] | None = None) -> Exclusion:
    """The ``diff.exclude`` of a loaded config, then *cli*'s ``--exclude`` patterns.

    A missing block excludes nothing; a block that is not a mapping of a list of
    patterns is ``CONFIG_001``.

    Raises:
        ConfigurationError: ``CONFIG_001`` for a malformed block or pattern.
    """
    raw = config_data.get("diff") if isinstance(config_data, dict) else None
    try:
        configured = DiffConfig.model_validate(raw or {}).exclude
    except ValidationError as exc:
        raise ConfigurationError(
            f"Invalid 'diff' configuration: {exc.errors()[0].get('msg', exc)}",
            error_code="CONFIG_001",
            resolution_hint="Use `diff:\n  exclude:\n    - _fraiseql_*`.",
        ) from exc
    return Exclusion.of(configured, cli)


@dataclass(frozen=True)
class Kept:
    """What one side keeps once an exclusion is applied, and what it has to say about it."""

    model: SchemaModel
    objects: Mapping[ObjectRef, Any]
    dangling: Mapping[ObjectRef, Any]
    notes: list[BuildWarning]


def leave_out(
    exclusion: Exclusion,
    model: SchemaModel,
    objects: Mapping[ObjectRef, Any],
    dangling: Mapping[ObjectRef, Any],
) -> Kept:
    """*model*, *objects* and *dangling* without the relations *exclusion* names.

    A side the author wrote (``model.source``) says each object of its own that
    depends on an excluded relation: a trigger, policy, rule or index it writes on
    one. Either side says each foreign key that references one, on a table it keeps.
    """
    author = model.source == "author"
    gone = exclusion.excludes
    triggers = {ref: t for ref, t in model.triggers.items() if not gone(ref.schema, t.table)}
    others = {ref: o for ref, o in model.other_objects.items() if not exclusion.excludes_ref(ref)}
    kept = replace(
        model,
        tables={ref: t for ref, t in model.tables.items() if not gone(ref.schema, ref.name)},
        sequences={ref: s for ref, s in model.sequences.items() if not gone(ref.schema, ref.name)},
        views={ref: v for ref, v in model.views.items() if not gone(ref.schema, ref.name)},
        tviews={ref: v for ref, v in model.tviews.items() if not gone(ref.schema, ref.name)},
        triggers=triggers,
        other_objects=others,
    )
    dropped_triggers = {ref for ref in model.triggers if ref not in triggers}
    notes = _foreign_keys(exclusion, kept)
    if author:
        notes += [
            _note("trigger", model.triggers[ref].qualified, ref.schema, model.triggers[ref].table)
            for ref in sorted(dropped_triggers, key=_order)
        ]
        notes += [
            _note(ref.kind, ref.qualified, ref.schema, ref.name)
            for ref in sorted(model.other_objects.keys() - others.keys(), key=_order)
            if ref.kind in _ON_A_RELATION
        ]
        notes += [
            _note("index", index.name or ", ".join(index.columns), *index.table.identity)
            for ref in sorted(dangling, key=_order)
            if gone(ref.schema, ref.name)
            for index in dangling[ref]
        ]
    return Kept(
        kept,
        {
            ref: found
            for ref, found in objects.items()
            if not exclusion.excludes_ref(ref) and ref not in dropped_triggers
        },
        {ref: found for ref, found in dangling.items() if not gone(ref.schema, ref.name)},
        notes,
    )


def _foreign_keys(exclusion: Exclusion, model: SchemaModel) -> list[BuildWarning]:
    """``DIFFER_411`` for each foreign key a kept table has on an excluded relation."""
    return [
        _note(
            "foreign key",
            f"{table.qualified}.{constraint.name or ', '.join(constraint.columns)}",
            *constraint.ref_table.identity,
        )
        for table in model.tables.values()
        for constraint in table.constraints
        if constraint.ref_table is not None and exclusion.excludes(*constraint.ref_table.identity)
    ]


def _note(kind: str, identity: str, schema: str, relation: str) -> BuildWarning:
    return BuildWarning.of(
        "DIFFER_411", kind=kind, identity=identity, relation=f"{schema}.{relation}"
    )


def _order(ref: ObjectRef) -> tuple[str, str, str]:
    return ref.kind, ref.schema, ref.name
