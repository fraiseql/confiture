"""Executable guard: docs/api/migrator.md references only real symbols.

DOCS-C2 / DOCS-L3 anti-drift guard. The API doc historically described a
``Migrator`` surface that does not exist (``apply_all``, ``rollback_to``,
``connect_async``, ``MigrationAlreadyApplied`` …). This guard pins the doc to
the real public API three ways:

1. every ``confiture`` import in a python fence resolves (kills fictional
   classes / exceptions);
2. the methods the doc teaches actually exist on the live objects;
3. the specific fictional names can never reappear in the doc text.

Only *import* statements are resolved — fence bodies are never executed.
"""

from __future__ import annotations

import inspect

from doc_snippets import assert_doc_imports_resolve, read_doc

from confiture import Migrator, MigratorSession

API_DOC = "docs/api/migrator.md"

# The real public MigratorSession surface a user drives.
DOCUMENTED_SESSION_METHODS = [
    "status",
    "current_revision",
    "up",
    "down",
    "down_to",
    "reinit",
    "rebuild",
    "preflight",
    "run_against",
]

# Names from the old fictional API that must never re-enter the doc.
FORBIDDEN_TOKENS = [
    "apply_all",
    "rollback_to",
    "connect_async",
    "get_applied_versions",
    "find_pending",
    "table_name=",
    "MigrationAlreadyApplied",
    "MigrationNotApplied",
    "MigrationResult",
    "AppliedMigration",
    "MigrationStatus",
    "confiture_migrations",
]


def test_every_confiture_import_in_the_doc_resolves() -> None:
    """Each `from confiture... import X` in the doc imports a real symbol."""
    checked = assert_doc_imports_resolve(API_DOC)
    assert checked, "expected at least one confiture import in the API doc"


def test_documented_session_methods_exist() -> None:
    """Every MigratorSession method the doc teaches is real and callable."""
    for method in DOCUMENTED_SESSION_METHODS:
        attr = getattr(MigratorSession, method, None)
        assert callable(attr), f"MigratorSession.{method} (documented) is missing"


def test_from_config_is_the_documented_entrypoint() -> None:
    """Migrator.from_config exists and the ctor uses migration_table, not table_name."""
    assert hasattr(Migrator, "from_config"), "Migrator.from_config (documented) is missing"
    params = inspect.signature(Migrator.__init__).parameters
    assert "migration_table" in params, "ctor should accept migration_table"
    assert "table_name" not in params, "ctor uses migration_table, not the fictional table_name"


def test_no_fictional_api_names_in_the_doc() -> None:
    """The old fictional API names never reappear in the doc."""
    text = read_doc(API_DOC)
    leaked = [tok for tok in FORBIDDEN_TOKENS if tok in text]
    assert not leaked, f"fictional API names present in {API_DOC}: {leaked}"
