"""Where an unqualified schema object lands: the one default schema.

``CREATE TABLE t`` and ``CREATE TABLE public.t`` are the same table, so a reader
deciding whether two statements are about one object folds a missing qualifier
to this. Every such reader folds it to the *same* thing, which is why the
constant has one home and the literal ``"public"`` appears beside a schema
variable nowhere else — ``tests/unit/test_one_object_identity.py`` fails on a
second spelling of it (#313).

Import-safe on purpose. It lived in ``core/linting/inventory``, which is the
module that decides object identity but which also imports pglast; modules that
only need to resolve a bare relation name for a catalogue query — a batched
backfill, an idempotency suggestion — were paying a parser to learn one word, so
they wrote the word instead. The identity is the fold; the *spelling* an object
prints is :func:`~confiture.core.schema_model.qualified_name`, which never invents a
qualifier the author did not write.
"""

from __future__ import annotations

#: Where an unqualified ``CREATE`` lands, for the purpose of deciding whether
#: two statements define the same object: ``f()`` and ``public.f()`` are one.
DEFAULT_SCHEMA = "public"
