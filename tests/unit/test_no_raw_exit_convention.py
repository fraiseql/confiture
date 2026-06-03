"""Ratchet convention test: failure paths route through ``fail()``, not raw Exit.

The #145/#146 machine contract is that every CLI failure emits the unified
``{ok: false, error: {...}}`` envelope and exits with the registry-derived code,
funneled through the single boundary in ``cli/error_json.py`` (``fail()``).
A bare ``raise typer.Exit(<int-literal>)`` in a command body bypasses that
boundary — it produces no envelope and pins an ad-hoc integer that the
canonical exit-code contract never sees.

This test AST-walks every module under ``python/confiture/cli/`` (except
``error_json.py``, which *is* the boundary) and counts integer-literal
``typer.Exit(N)`` constructions. It is a **ratchet**: ``_ALLOWLIST`` records the
per-module count, and the assertion is exact equality. The number can only ever
go **down** — converting a site to ``fail()`` means lowering the allowlist entry;
adding a new raw Exit means the test goes red until you route it through the
boundary instead.

Two kinds of entries live in ``_ALLOWLIST``:

1. **Permanent success-signal sites** — legitimate non-error exits expressed as
   literals (``diff`` → 1 on changes, ``status`` → 1 on pending, idempotency
   gate → 1 on findings). These carry an inline ``# success-signal`` note and
   stay put.
2. **Not-yet-converted failure sites** — debt this phase (and Phase 03, for the
   ``migrate_validate`` god-command) pays down. Each carries a ``# TODO`` note.

When the allowlist contains only success-signal entries, the contract is fully
universalized. Mirrors the spirit of ``test_exit_code_convention.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

_CLI_ROOT = Path(__file__).resolve().parents[2] / "python" / "confiture" / "cli"

# Modules whose integer-literal ``typer.Exit`` count is known and frozen. Keys
# are paths relative to ``python/confiture/cli/``. The boundary module
# ``error_json.py`` is excluded entirely (it owns the one legitimate
# ``raise typer.Exit(err.exit_code)`` — a non-literal, so it would not count
# anyway, but we exclude it for intent).
#
# RATCHET RULE: an entry may only ever DECREASE. Convert a failure path to
# ``fail()`` → lower the number here. Never raise a number to "make it pass" —
# route the new failure through ``fail()`` instead.
_ALLOWLIST: dict[str, int] = {
    # ---- Phase 03 territory: the migrate_validate god-command decomposition ----
    "commands/migrate_analysis.py": 52,  # TODO(phase-03): structural decomposition
    # ---- migrate_core: status/up/down/generate/estimate ----
    # Mix of success-signal (status→1 pending) and not-yet-converted failures;
    # already partially routed through fail(). Paid down opportunistically.
    "commands/migrate_core.py": 33,  # TODO(phase-02/03): mixed success-signal + debt
    # ---- Cycle 1 conversion cohort (this phase) ----
    "seed.py": 32,  # TODO(phase-02): convert to fail()
    "commands/migrate_state.py": 16,  # TODO(phase-02): convert to fail()
    "branch.py": 14,  # TODO(phase-02): convert to fail()
    "generate.py": 13,  # TODO(phase-02): convert to fail()
    "coordinate.py": 13,  # TODO(phase-02): convert to fail()
    "commands/schema.py": 12,  # TODO(phase-02): convert to fail()
    "commands/bootstrap.py": 12,  # TODO(phase-02): convert to fail()
    "commands/apply_as.py": 10,  # TODO(phase-02): convert to fail()
    "commands/admin.py": 9,  # TODO(phase-02): convert to fail()
    "commands/drift.py": 8,  # TODO(phase-02): convert to fail()
    "commands/hooks.py": 6,  # TODO(phase-02): convert to fail()
    "commands/debug.py": 5,  # TODO(phase-02): convert to fail()
    # commands/diff.py: fully converted (Cycle 2) — success exit is an IfExp,
    # not a literal, so it no longer appears here.
    "ownership_loader.py": 2,  # TODO(phase-02): convert to fail()
    "helpers.py": 2,  # success-signal: idempotency gate → Exit(1) on findings
    "function_coverage_loader.py": 2,  # TODO(phase-02): convert to fail()
    "commands/mcp.py": 2,  # TODO(phase-02): convert to fail()
    "acl_loader.py": 2,  # TODO(phase-02): convert to fail()
}

_EXCLUDED = {"error_json.py"}


def _is_int_literal_typer_exit(node: ast.AST) -> bool:
    """True for a ``typer.Exit(<int-literal>)`` call (the contract target).

    Non-literal forms — ``typer.Exit(err.exit_code)``, ``typer.Exit(code)`` —
    are excluded: they already defer the integer to the registry / a computed
    success-signal, which is exactly what the contract wants.
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not (
        isinstance(func, ast.Attribute)
        and func.attr == "Exit"
        and isinstance(func.value, ast.Name)
        and func.value.id == "typer"
    ):
        return False
    if not node.args:
        return False
    first = node.args[0]
    return (
        isinstance(first, ast.Constant)
        and isinstance(first.value, int)
        and not isinstance(first.value, bool)
    )


def _count_literal_exits(path: Path) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return sum(1 for node in ast.walk(tree) if _is_int_literal_typer_exit(node))


def _actual_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in sorted(_CLI_ROOT.rglob("*.py")):
        if path.name in _EXCLUDED:
            continue
        n = _count_literal_exits(path)
        if n:
            counts[path.relative_to(_CLI_ROOT).as_posix()] = n
    return counts


def test_no_unaccounted_raw_exit_literals() -> None:
    """Every integer-literal ``typer.Exit`` is accounted for, and the count only falls.

    Failure modes and their fixes:

    - A module appears in ``actual`` but not ``_ALLOWLIST`` (or its count is
      **higher**) → a new raw ``typer.Exit(<int>)`` was added on a failure path.
      Route it through ``fail(exc, json_mode=..., output_file=...)`` instead.
    - A module's count is **lower** than ``_ALLOWLIST`` → you converted sites
      (good!). Lower the allowlist entry to match so the ratchet locks in the win.
    """
    actual = _actual_counts()

    regressions: list[str] = []
    for module, count in actual.items():
        allowed = _ALLOWLIST.get(module, 0)
        if count > allowed:
            regressions.append(
                f"  {module}: {count} literal typer.Exit (allowlist: {allowed}) — "
                f"route the new failure path(s) through fail(), not raw typer.Exit(<int>)"
            )

    stale: list[str] = []
    for module, allowed in _ALLOWLIST.items():
        count = actual.get(module, 0)
        if count < allowed:
            stale.append(
                f"  {module}: {count} literal typer.Exit (allowlist: {allowed}) — "
                f"you converted sites; lower the allowlist entry to {count}"
            )

    msg_parts: list[str] = []
    if regressions:
        msg_parts.append("New raw Exit literals (regressions):\n" + "\n".join(regressions))
    if stale:
        msg_parts.append("Allowlist is stale (ratchet must tighten):\n" + "\n".join(stale))
    assert not msg_parts, "\n\n".join(msg_parts)


def test_allowlist_has_no_dead_entries() -> None:
    """No allowlist key points at a module that no longer exists.

    Keeps the ratchet honest: a deleted/renamed module must drop out of the
    allowlist rather than linger as a phantom budget.
    """
    missing = [m for m in _ALLOWLIST if not (_CLI_ROOT / m).exists()]
    assert not missing, f"allowlist references missing modules: {missing}"
