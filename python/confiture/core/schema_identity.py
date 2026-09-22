"""Where an unqualified schema object lands: the one default schema.

``CREATE TABLE t`` and ``CREATE TABLE public.t`` are the same table, so a reader
deciding whether two statements are about one object folds a missing qualifier
to this. Every such reader folds it to the *same* thing, which is why the
constant has one home and the literal ``"public"`` appears beside a schema
variable nowhere else — ``tests/unit/test_one_object_identity.py`` fails on a
second spelling of it (#313).

Import-safe on purpose. ``core/linting/inventory`` decides object identity but
imports pglast, and a module that only needs to resolve a bare relation name for
a catalogue query — a batched backfill, an idempotency suggestion — should not
pay for a parser to learn one word: made to, it is tempted to write the word
instead. The identity is the fold; the *spelling* an object prints is
:func:`~confiture.core.schema_model.qualified_name`, which never invents a
qualifier the author did not write.
"""

from __future__ import annotations

#: Where an unqualified ``CREATE`` lands, for the purpose of deciding whether
#: two statements define the same object: ``f()`` and ``public.f()`` are one.
DEFAULT_SCHEMA = "public"
