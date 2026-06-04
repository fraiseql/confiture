"""Executable guard: the hook docs describe the real hook API.

The hooks docs historically taught a fictional decorator API — a non-existent
``confiture.hooks`` module, a ``@register_hook('post_execute')`` decorator over
plain functions, and a ``HookContext`` with ``.migration`` / ``TableInfo`` /
``ColumnInfo`` attributes. The real API is class-based: subclass ``Hook[T]``,
implement ``async def execute(...) -> HookResult``, and register the instance
with ``Migrator.register_hook(HookPhase.X, hook)``.

This guard pins reality three ways: the two dedicated hook docs' ``confiture``
imports resolve and teach real symbols; and the old fictional decorator API can
never reappear in *any* doc that carries hook snippets.
"""

from __future__ import annotations

import pytest
from doc_snippets import assert_doc_imports_resolve, read_doc

from confiture import AuditHook, BackupHook, HookPhase
from confiture.core.hooks import Hook, HookContext, HookError, HookResult
from confiture.core.hooks.context import ExecutionContext

# The two dedicated hook docs are fully controlled — every confiture import in
# them must resolve.
HOOK_DOCS = ["docs/api/hooks.md", "docs/guides/hooks.md"]

# Every doc that carries a hook snippet — the fictional decorator API must be
# absent from all of them.
DOCS_WITH_HOOK_SNIPPETS = [
    *HOOK_DOCS,
    "docs/api/index.md",
    "docs/guides/compliance.md",
    "docs/guides/interactive-migration-wizard.md",
    "docs/guides/integrations.md",
]

# The fictional decorator API the rewrite removed.
FORBIDDEN_DECORATOR_API = [
    "confiture.hooks import",  # the module never existed (it is confiture.core.hooks)
    "@register_hook",  # decorator form — real API is Migrator.register_hook(phase, hook)
    "'post_execute'",
    '"post_execute"',
    "'pre_execute'",
    "'on_error'",
]

# Fictional context shapes specific to the dedicated hook docs.
FORBIDDEN_CONTEXT_TYPES = ["TableInfo", "ColumnInfo", "context.migration"]


@pytest.mark.parametrize("doc", HOOK_DOCS)
def test_every_confiture_import_in_the_doc_resolves(doc: str) -> None:
    """Each `from confiture… import X` in a python fence imports a real symbol."""
    checked = assert_doc_imports_resolve(doc)
    assert checked, f"expected at least one confiture import in {doc}"


def test_documented_symbols_are_real() -> None:
    """The classes/enums the docs teach exist with the documented shape."""
    assert issubclass(AuditHook, Hook) and issubclass(BackupHook, Hook)
    assert HookPhase.BEFORE_EXECUTE.value == "before_execute"
    assert HookPhase.AFTER_EXECUTE.value == "after_execute"
    assert {"success", "error"} <= set(HookResult.__dataclass_fields__)
    assert issubclass(HookError, Exception)
    assert "metadata" in ExecutionContext.__dataclass_fields__
    assert hasattr(HookContext, "get_data")


@pytest.mark.parametrize("doc", DOCS_WITH_HOOK_SNIPPETS)
def test_no_decorator_api_fiction(doc: str) -> None:
    """The fictional ``@register_hook`` decorator API never reappears."""
    text = read_doc(doc)
    leaked = [tok for tok in FORBIDDEN_DECORATOR_API if tok in text]
    assert not leaked, f"fictional hook decorator API present in {doc}: {leaked}"


@pytest.mark.parametrize("doc", HOOK_DOCS)
def test_no_fictional_context_types(doc: str) -> None:
    """The dedicated hook docs never reintroduce the fictional context shapes."""
    text = read_doc(doc)
    leaked = [tok for tok in FORBIDDEN_CONTEXT_TYPES if tok in text]
    assert not leaked, f"fictional hook context names present in {doc}: {leaked}"
