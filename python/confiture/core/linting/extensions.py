"""The extensions a build creates: each one's name, the schema it lands in, and where it is written.

A ``CREATE EXTENSION ltree SCHEMA public`` creates ``public.text2ltree`` and a
hundred routines like it, and no file in the tree spells one of them out.
``build_003`` asks this module which schemas such routines may live in, so a call
into one is not reported as "no file in the build creates it" when a file does,
through the extension (#741).

*Which* extensions the tree keeps is :func:`~confiture.core.ddl_objects.declared_objects`'
answer: a later ``DROP EXTENSION`` and a repeated name fold there, as they do for
every other object. *What* each kept one says is read off the statement that
created it, because an extension's :class:`~confiture.core.ddl_objects.ObjectRef`
never carries its ``SCHEMA`` option and a ``DDLObject`` carries no location.

A parameterless ``CREATE LANGUAGE plpgsql`` is one of these: PostgreSQL's grammar
turns it into ``CREATE EXTENSION plpgsql``, and runs it as one.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from confiture.core.ddl_objects import DDLObject, declared_objects, defined_kind, object_of
from confiture.core.linting.inventory import line_of, statement_offset
from confiture.core.schema_identity import DEFAULT_SCHEMA, identifier_identity
from confiture.core.sql_lexer import ParsedFile


@dataclass(frozen=True)
class BuiltExtension:
    """One extension the build creates.

    ``schema`` is the ``SCHEMA`` option in the parser's spelling, or
    :data:`~confiture.core.schema_identity.DEFAULT_SCHEMA` when none is written;
    ``schema_written`` says which, because only a written schema is a fact the
    tree states (where an unwritten one lands is the applying role's
    ``search_path``). ``create_sql`` is the statement re-rendered with
    ``IF NOT EXISTS``, ``VERSION`` and ``CASCADE`` as written.
    """

    name: str
    schema: str
    schema_written: bool
    file: str | None
    line: int
    create_sql: str
    #: ``CASCADE``: the extensions it requires are installed too, into the same schema.
    cascade: bool = False

    @property
    def where(self) -> str:
        """``file:line``, or ``line N`` for DDL handed in as text."""
        return f"{self.file}:{self.line}" if self.file else f"line {self.line}"


def _option(stmt: Any, name: str) -> Any:
    """The value of the ``WITH`` option *name*, or ``None`` when it is not written."""
    for option in getattr(stmt, "options", None) or ():
        if option.defname == name:
            return option.arg
    return None


def _built(parsed: ParsedFile, raw: Any, obj: DDLObject) -> BuiltExtension:
    schema = _option(raw.stmt, "schema")
    cascade = _option(raw.stmt, "cascade")
    return BuiltExtension(
        name=raw.stmt.extname,
        schema=schema.sval if schema is not None else DEFAULT_SCHEMA,
        schema_written=schema is not None,
        file=parsed.label,
        line=line_of(parsed.text, statement_offset(parsed.text, raw)),
        create_sql=obj.create_sql,
        cascade=bool(cascade is not None and cascade.boolval),
    )


def built_extensions(
    files: Sequence[ParsedFile], uncreated: frozenset[tuple[int, str]] | None = None
) -> list[BuiltExtension]:
    """Every extension the tree still creates once it is applied, in build order.

    *uncreated* is the inventory's, when the caller holds one: without it
    :func:`~confiture.core.ddl_objects.declared_objects` builds the inventory
    again. A tree with no ``CREATE EXTENSION`` costs one look at each node.
    """
    creating = [
        (parsed, raw)
        for parsed in files
        for raw in parsed.statements
        if defined_kind(raw) == "extension"
    ]
    if not creating:
        return []
    kept = [
        obj
        for ref, bucket in declared_objects(files, uncreated).objects.items()
        if ref.kind == "extension"
        for obj in bucket
    ]
    found: list[BuiltExtension] = []
    for parsed, raw in creating:
        obj = object_of(parsed.text, raw)
        if obj is not None and obj in kept:
            kept.remove(obj)
            found.append(_built(parsed, raw, obj))
    return found


def extension_schemas(
    extensions: Sequence[BuiltExtension],
    files: Sequence[ParsedFile],
    uncreated: frozenset[tuple[int, str]] | None = None,
) -> frozenset[str]:
    """The schemas a scratch build must create before the extensions: names, not statements.

    A written ``SCHEMA`` the tree's own ``CREATE SCHEMA`` creates. The tree's
    statement is not replayed: it may carry ``AUTHORIZATION <role>`` or schema
    elements, and either can fail on a scratch server for a reason that has
    nothing to do with the extension. A schema the tree never creates is not
    named, so the scratch refuses the extension as the build would.
    """
    written = {identifier_identity(e.schema): e.schema for e in extensions if e.schema_written}
    if not written:
        return frozenset()
    created = {
        ref.name for ref in declared_objects(files, uncreated).objects if ref.kind == "schema"
    }
    return frozenset(spelled for folded, spelled in written.items() if folded in created)
