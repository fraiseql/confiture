"""One session signature: what a ``MigratorSession`` verb accepts is written once.

``MigratorSession`` is a delegating facade — a keyword-only signature, a
Google-style docstring, one line of lock resolution, and a pass-through to
``_apply_loop`` / ``_rollback_loop`` / ``_replay`` / ``_reporting`` or the engine.
Each verb's signature is therefore *echoed* three times: in the docstring's
``Args:`` block, in the argument list handed to the delegate, and in the
hand-copied fence in ``docs/api/migrator.md`` (pinned by
``tests/unit/docs/test_doc_api_symbols.py``).

An echo nothing checks drifts, and both unchecked ones had: ``up()`` grew
``allow_destructive``, ``online`` and ``backfill`` and documented none of them,
and the doc page still showed a thirteen-parameter ``up()``. Forwarding is the
echo where drift is a *behaviour* bug rather than a documentation one — a
parameter added to the signature and forgotten in the call is silently ignored,
so a caller's explicit argument does nothing and nothing says so. This guard is
what makes that impossible; it is prevention, not a fix, because forwarding is
the one echo that had not drifted.

Three agreements, per delegating verb:

1. every parameter the verb declares reaches the delegate. Positional forwarding
   counts: ``apply_one``, ``down_to`` and ``run_against`` forward positionally,
   which a keyword-only check misreads as four dropped parameters.
2. every name forwarded is one the delegate accepts, so a rename on the delegate
   side cannot pass silently as an unexpected keyword at runtime.
3. every parameter the delegate declares receives an argument, so a delegate that
   grows one cannot quietly fall back to its default forever. ``NOT_SURFACED``
   holds the deliberate exceptions, each with its reason.

``DELEGATES`` is exhaustive by assertion: a verb added to the facade without an
entry fails, and an entry naming a verb that no longer delegates fails too, as in
the one-lexer and one-path-matcher guards.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any

import confiture
from confiture.core._migrator import apply_loop, replay, reporting, rollback_loop
from confiture.core._migrator.engine import Migrator
from confiture.core._migrator.session import MigratorSession

SESSION_PY = Path(confiture.__file__).resolve().parent / "core" / "_migrator" / "session.py"

# Every delegating verb on MigratorSession and the callable it hands its
# parameters to. `reinit` and `rebuild` delegate to the engine, the rest to a
# module in `core/_migrator/`.
DELEGATES: dict[str, Any] = {
    "status": reporting.status,
    "current_revision": reporting.current_revision,
    "preflight": reporting.preflight,
    "up": apply_loop.up,
    "apply_one": apply_loop.apply_one,
    "down": rollback_loop.down,
    "down_to": rollback_loop.down_to,
    "run_against": replay.run_against,
    "reinit": Migrator.reinit,
    "rebuild": Migrator.rebuild,
}

# Public methods that carry their own logic instead of delegating, with the
# reason. They have no signature to echo, so the three agreements say nothing
# about them.
NOT_DELEGATING: dict[str, str] = {
    "is_locked": "builds a `MigrationLock` on the session's connection and asks it directly",
    "get_lock_holder": "as `is_locked` — a lock query, not a migration verb",
}

# Delegate parameters the facade deliberately does not surface, with the reason.
# An entry that stops matching fails, as in the one-lexer guard.
NOT_SURFACED: dict[tuple[str, str], str] = {
    ("rebuild", "schema_dir"): (
        "the session does not let a caller redirect the DDL source; `baseline.rebuild` "
        "defaults it to `db/schema`. Surfacing it widens the public library API"
    ),
    ("rebuild", "seeds_dir"): (
        "as `schema_dir` — `baseline.rebuild` defaults it to `db/seeds`, and the session "
        "has no parameter for it"
    ),
}


def _session_class() -> ast.ClassDef:
    """The parsed ``MigratorSession`` class body."""
    tree = ast.parse(SESSION_PY.read_text())
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "MigratorSession":
            return node
    raise AssertionError(f"MigratorSession not found in {SESSION_PY}")


def _declared(fn: ast.FunctionDef) -> list[str]:
    """The parameter names a method declares, ``self`` excluded, in call order."""
    args = fn.args
    positional = [a.arg for a in args.posonlyargs + args.args if a.arg != "self"]
    return positional + [a.arg for a in args.kwonlyargs]


def _delegate_call(fn: ast.FunctionDef) -> ast.Call:
    """The call a delegating verb returns."""
    returns = [n for n in fn.body if isinstance(n, ast.Return)]
    assert returns, f"MigratorSession.{fn.name} has no return statement"
    value = returns[-1].value
    assert isinstance(value, ast.Call), (
        f"MigratorSession.{fn.name} does not return a call — it is listed in "
        f"DELEGATES but no longer delegates"
    )
    return value


def _delegate_params(delegate: Any) -> list[str]:
    """The delegate's parameters, receiver excluded.

    The receiver is the leading parameter either way: ``session`` for a module
    function the facade calls as ``_apply_loop.up(self, ...)``, ``self`` for an
    engine method the facade calls on a bound instance.
    """
    return list(inspect.signature(delegate).parameters)[1:]


def _forwarding(call: ast.Call, delegate_params: list[str]) -> tuple[dict[str, str], set[str]]:
    """Map delegate parameter -> forwarded name, plus every name forwarded.

    A leading positional ``self`` is the receiver, not an argument.
    """
    positional = list(call.args)
    if positional and isinstance(positional[0], ast.Name) and positional[0].id == "self":
        positional = positional[1:]

    bound: dict[str, str] = {}
    names: set[str] = set()
    for index, arg in enumerate(positional):
        assert index < len(delegate_params), (
            f"positional argument {index} has no matching delegate parameter"
        )
        param = delegate_params[index]
        if isinstance(arg, ast.Name):
            bound[param] = arg.id
            names.add(arg.id)
        else:
            bound[param] = "<expression>"

    for keyword in call.keywords:
        assert keyword.arg is not None, "**kwargs forwarding defeats this guard"
        if isinstance(keyword.value, ast.Name):
            bound[keyword.arg] = keyword.value.id
            names.add(keyword.value.id)
        else:
            bound[keyword.arg] = "<expression>"

    return bound, names


def _is_accessor(fn: ast.FunctionDef) -> bool:
    """A property, a setter, a classmethod or a staticmethod — not a verb."""
    for decorator in fn.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id in {
            "property",
            "classmethod",
            "staticmethod",
        }:
            return True
        if isinstance(decorator, ast.Attribute) and decorator.attr in {"setter", "getter"}:
            return True
    return False


def _public_verbs() -> dict[str, ast.FunctionDef]:
    """The facade's public methods, accessors and dunders excluded."""
    return {
        node.name: node
        for node in _session_class().body
        if isinstance(node, ast.FunctionDef)
        and not node.name.startswith("_")
        and not _is_accessor(node)
    }


def _delegating_methods() -> dict[str, ast.FunctionDef]:
    """The public verbs that delegate, i.e. the ones DELEGATES covers."""
    return {name: fn for name, fn in _public_verbs().items() if name in DELEGATES}


def test_delegate_table_is_exhaustive() -> None:
    """Every entry in DELEGATES is a real facade verb, and none is missing."""
    public = set(_public_verbs())
    assert set(DELEGATES) <= public, (
        f"DELEGATES names methods MigratorSession does not have: {sorted(set(DELEGATES) - public)}"
    )
    uncovered = public - set(DELEGATES) - set(NOT_DELEGATING)
    assert not uncovered, (
        f"MigratorSession gained public verbs with no DELEGATES entry: {sorted(uncovered)}. "
        f"Add each one and its delegate, or this guard stops covering them."
    )
    stale = set(NOT_DELEGATING) - public
    assert not stale, f"NOT_DELEGATING names methods that no longer exist: {sorted(stale)}"


def test_not_delegating_methods_really_do_not_delegate() -> None:
    """A method excused from the agreements must not be a pass-through after all."""
    for name, reason in NOT_DELEGATING.items():
        assert reason.strip(), f"NOT_DELEGATING[{name}] must state a reason"
        fn = _public_verbs()[name]
        returns = [n for n in fn.body if isinstance(n, ast.Return)]
        forwards = any(
            isinstance(r.value, ast.Call)
            and any(isinstance(a, ast.Name) and a.id == "self" for a in r.value.args)
            for r in returns
        )
        assert not forwards, (
            f"MigratorSession.{name} is excused as non-delegating but hands `self` to a "
            f"delegate — give it a DELEGATES entry instead"
        )


def test_the_guard_reaches_its_subject() -> None:
    """The walker inspects every verb — a guard that inspects nothing passes vacuously."""
    methods = _delegating_methods()
    assert set(methods) == set(DELEGATES), (
        f"expected to inspect {sorted(DELEGATES)}, inspected {sorted(methods)}"
    )
    for name, fn in methods.items():
        assert isinstance(_delegate_call(fn), ast.Call), f"{name} resolves to no delegate call"


def test_every_declared_parameter_reaches_the_delegate() -> None:
    """Agreement 1: nothing a verb accepts is dropped on the way to the delegate."""
    for name, fn in _delegating_methods().items():
        params = _delegate_params(DELEGATES[name])
        _, forwarded = _forwarding(_delegate_call(fn), params)
        dropped = [p for p in _declared(fn) if p not in forwarded]
        assert not dropped, (
            f"MigratorSession.{name} accepts {dropped} but never forwards them — a caller "
            f"passing one gets silence, not an error"
        )


def test_every_forwarded_name_is_a_delegate_parameter() -> None:
    """Agreement 2: the delegate accepts everything the facade hands it."""
    for name, fn in _delegating_methods().items():
        params = _delegate_params(DELEGATES[name])
        bound, _ = _forwarding(_delegate_call(fn), params)
        unknown = [p for p in bound if p not in params]
        assert not unknown, (
            f"MigratorSession.{name} forwards {unknown}, which "
            f"{DELEGATES[name].__qualname__} does not accept"
        )


def test_every_delegate_parameter_receives_an_argument() -> None:
    """Agreement 3: a delegate that grows a parameter cannot silently default it."""
    for name, fn in _delegating_methods().items():
        params = _delegate_params(DELEGATES[name])
        bound, _ = _forwarding(_delegate_call(fn), params)
        missing = [p for p in params if p not in bound and (name, p) not in NOT_SURFACED]
        assert not missing, (
            f"{DELEGATES[name].__qualname__} declares {missing}, which "
            f"MigratorSession.{name} never passes — it silently takes the delegate's "
            f"default. Surface it, or add a NOT_SURFACED entry saying why not."
        )


def test_not_surfaced_entries_still_match() -> None:
    """An exception that stops applying is deleted, never left to rot."""
    stale = []
    for (name, param), reason in NOT_SURFACED.items():
        assert reason.strip(), f"NOT_SURFACED[{name}, {param}] must state a reason"
        if name not in DELEGATES:
            stale.append((name, param))
            continue
        params = _delegate_params(DELEGATES[name])
        bound, _ = _forwarding(_delegate_call(_delegating_methods()[name]), params)
        if param not in params or param in bound:
            stale.append((name, param))
    assert not stale, f"NOT_SURFACED entries that no longer match anything: {stale}"


def test_runtime_signature_matches_the_parsed_one() -> None:
    """The AST the guard reads is the class Python imported, not a stale file."""
    for name, fn in _delegating_methods().items():
        live = list(inspect.signature(getattr(MigratorSession, name)).parameters)
        assert live[1:] == _declared(fn), (
            f"MigratorSession.{name} on disk and in memory disagree — the guard is "
            f"reading a different file from the one under test"
        )
