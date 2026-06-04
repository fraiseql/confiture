"""Public-API exposure + no-limbo consistency guard (Phase 04, ARCH-H1).

Phase 04 promoted three previously-orphaned modules (blue_green, pg_version,
rollback_generator) to the documented library surface. These tests pin that
they are reachable via ``import confiture`` and, more importantly, add the
comprehensive consistency check the per-feature tests lacked: every name in
``__all__`` resolves, and every ``_LAZY_IMPORTS`` key is advertised in
``__all__`` — so a future orphan can't be half-exposed (in one but not the
other) and slip back into "tested-but-unreachable" limbo.
"""

from __future__ import annotations

import confiture
from confiture import _LAZY_IMPORTS

# Names promoted to the public library surface in Phase 04.
_BLUE_GREEN = (
    "BlueGreenOrchestrator",
    "BlueGreenConfig",
    "TrafficController",
    "MigrationPhase",
    "MigrationState",
    "HealthCheckResult",
)
_PG_VERSION = (
    "detect_version",
    "parse_version_string",
    "check_version_compatibility",
    "get_recommended_settings",
    "PGVersionInfo",
    "PGFeature",
    "VersionAwareSQL",
)
_ROLLBACK_GEN = (
    "generate_rollback",
    "generate_rollback_script",
    "suggest_backup_for_destructive_operations",
    "RollbackSuggestion",
    "RollbackTester",
    "RollbackTestResult",
)
# Built-in migration lifecycle hooks (opt-in via Migrator.register_hook).
_BUILTIN_HOOKS = (
    "AuditHook",
    "AuditConfig",
    "BackupHook",
    "BackupConfig",
    "HookPhase",
)
_NEWLY_EXPOSED = _BLUE_GREEN + _PG_VERSION + _ROLLBACK_GEN + _BUILTIN_HOOKS


def test_newly_exposed_symbols_resolve() -> None:
    """Each Phase-04 library symbol imports from the top-level package."""
    for name in _NEWLY_EXPOSED:
        assert name in confiture.__all__, f"{name} missing from __all__"
        assert getattr(confiture, name) is not None


def test_blue_green_orchestrator_is_real() -> None:
    from confiture import BlueGreenConfig, BlueGreenOrchestrator

    assert BlueGreenOrchestrator.__name__ == "BlueGreenOrchestrator"
    assert BlueGreenConfig.__name__ == "BlueGreenConfig"


def test_pg_version_detect_is_callable() -> None:
    from confiture import detect_version

    assert callable(detect_version)


def test_rollback_generator_is_callable() -> None:
    from confiture import generate_rollback

    assert callable(generate_rollback)


def test_builtin_hooks_are_real() -> None:
    from confiture import AuditHook, BackupHook, HookPhase

    assert AuditHook.__name__ == "AuditHook"
    assert BackupHook.__name__ == "BackupHook"
    # The phase enum a user needs to register them.
    assert HookPhase.BEFORE_EXECUTE.value == "before_execute"


# ---------------------------------------------------------------------------
# No-limbo consistency: __all__ ⇄ _LAZY_IMPORTS
# ---------------------------------------------------------------------------

_METADATA = {"__version__", "__author__", "__email__"}


def test_every_all_entry_resolves() -> None:
    """Every non-metadata name in ``__all__`` is importable via __getattr__."""
    unresolved: list[str] = []
    for name in confiture.__all__:
        if name in _METADATA:
            continue
        try:
            getattr(confiture, name)
        except AttributeError:
            unresolved.append(name)
    assert not unresolved, f"__all__ names that do not resolve: {unresolved}"


def test_every_lazy_import_is_advertised() -> None:
    """Every ``_LAZY_IMPORTS`` key appears in ``__all__`` (no hidden exports)."""
    missing = [name for name in _LAZY_IMPORTS if name not in confiture.__all__]
    assert not missing, f"_LAZY_IMPORTS keys missing from __all__: {missing}"


def test_every_lazy_import_resolves() -> None:
    """Every ``_LAZY_IMPORTS`` symbol actually imports from its target module.

    Direct reachability check: each lazy entry's ``(module, attr)`` pair must
    load — a stale module path or renamed symbol fails here, not at a user's
    first ``from confiture import X``.
    """
    broken: list[str] = []
    for name in _LAZY_IMPORTS:
        try:
            assert getattr(confiture, name) is not None
        except (AttributeError, ImportError):
            broken.append(name)
    assert not broken, f"_LAZY_IMPORTS symbols that fail to resolve: {broken}"
