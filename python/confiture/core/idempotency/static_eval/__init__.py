r"""Static evaluation of what ``self.execute(...)`` / ``self.execute_file(...)`` receive.

The idempotency gate can only judge SQL it has read. A Python migration hands
its SQL to ``execute`` as an expression, and before 0.46.0 only three shapes
were read — a literal, a static f-string, a literal concatenation — so a
``CREATE TABLE`` hoisted into a module constant was invisible to the gate
(#213). This module evaluates the expression instead, for every form that is
a *pure function of the migration file's own text*, and refuses everything
else with the reason.

**Never imports, never executes.** ``ast`` supplies the tree, ``symtable``
supplies the interpreter's own scoping decisions, and the only side effect
is reading a SQL file that the shared resolver has confined to the project
root.

The grammar
===========

Values are ``Str`` (text, possibly read from a file), ``PathV`` (a path, made
concrete only when read), ``Seq`` (for ``*parts`` and ``.join``), or
``Unknown`` (a refusal carrying a :class:`Refusal` code and a sentence).

============================================== ======================================================
Expression                                     Value
============================================== ======================================================
``"…"``                                        ``Str``
``f"… {x} …"``                                 ``Str`` when every placeholder is a ``Str`` with no
                                               conversion and no format spec
``a + b``                                      ``Str`` when both sides are
``p / q``                                      ``PathV`` when ``p`` is one
``__file__``                                   this migration's path
``NAME``                                       scope lookup, below
``self.NAME`` / ``cls.NAME``                   class-attribute lookup, below
``p.parent``, ``p.parents[N]``                 ``PathV``
``Path(...)``, ``pathlib.Path(...)``           ``PathV`` joined from ``Str``/``PathV``/``*Seq`` args
``p.resolve()``, ``p.absolute()``              the same ``PathV``
``p.joinpath(...)``                            ``PathV``
``p.read_text(...)``                           ``Str`` from the file the shared resolver names
``s.replace/strip/lstrip/rstrip/upper/lower``  ``Str`` (static arguments only)
``s.format(...)``, ``sep.join(seq)``           ``Str`` (static arguments only)
``dedent(s)``, ``textwrap.dedent(s)``          ``Str``
``str(p)``                                     ``Str``
``(a, b)``, ``[a, b]``                         ``Seq``
``f(...)``, ``self.m(...)``                    a one-line reader helper, below
============================================== ======================================================

**Scope lookup** — a name resolves when it is bound *exactly once* in the
scope that reads it, by a plain assignment, at the top level of that scope,
to an expression in this grammar, and no other scope can rebind it at
runtime. Which scope reads it is decided by :mod:`symtable`, the compiler's
own analysis, so parameters, loop and ``with`` targets, comprehension
targets, walrus bindings, imports and nested ``def``\ s all count as
bindings without anyone maintaining a list. A ``global NAME`` plus an
assignment in any function refuses the module constant. A class attribute of
the same name does **not** shadow a module name inside a method — Python
does not look there either.

**Class-attribute lookup** — ``self.NAME`` resolves when ``NAME`` is bound
once in the class body and nothing anywhere in the file assigns
``self.NAME`` / ``cls.NAME`` or calls ``setattr`` on ``self``.

**Reader helpers** — a module-level ``def`` (or a method reached through
``self``) whose body is an optional docstring plus one ``return <expr>``;
no decorators. Parameters are bound from the call, ``*parts`` becomes a
``Seq``, defaults evaluate in the helper's own scope.

Depth is capped at :data:`MAX_DEPTH` names-or-helpers; cycles are refused.
Under-resolving is a warning the CLI shows with the reason; over-resolving
would be a wrong verdict, which is why every rule here errs toward refusal.
"""

from __future__ import annotations

from confiture.core.idempotency.static_eval import (
    file_io,  # noqa: F401 — the resolver seam tests patch
)
from confiture.core.idempotency.static_eval.evaluator import ModuleModel
from confiture.core.idempotency.static_eval.values import (
    MAX_DEPTH,
    REMEDIES,
    PathV,
    Refusal,
    Seq,
    Str,
    Trace,
    Unknown,
    Value,
)

__all__ = [
    "MAX_DEPTH",
    "ModuleModel",
    "PathV",
    "REMEDIES",
    "Refusal",
    "Seq",
    "Str",
    "Trace",
    "Unknown",
    "Value",
]
