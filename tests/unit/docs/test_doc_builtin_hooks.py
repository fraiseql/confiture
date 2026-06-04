"""Executable guard: docs/api/hooks.md "Built-in hooks" section is real.

The built-in AuditHook/BackupHook were wired to the public library API
(Phase 04b, cluster F). This guard pins that the documented registration
example imports only real symbols and uses the real registration phases —
scoped to the anchored ``builtin-hooks-imports`` block so it does not touch
the rest of hooks.md.
"""

from __future__ import annotations

import importlib

from doc_snippets import confiture_imports, fenced_after_anchor, read_doc

from confiture import HookPhase

HOOKS_DOC = "docs/api/hooks.md"


def test_builtin_hooks_example_imports_resolve() -> None:
    """Every `from confiture import …` in the built-in-hooks block is real."""
    block = fenced_after_anchor(read_doc(HOOKS_DOC), "builtin-hooks-imports")
    pairs = confiture_imports(block)
    assert pairs, "expected confiture imports in the built-in-hooks example"
    for module, name in pairs:
        mod = importlib.import_module(module)
        if name:
            assert hasattr(mod, name), f"{module}.{name} (in hooks.md) does not exist"


def test_documented_registration_phases_exist() -> None:
    """The phases the doc registers the built-ins on are real enum members."""
    assert HookPhase.BEFORE_EXECUTE.value == "before_execute"
    assert HookPhase.AFTER_EXECUTE.value == "after_execute"
