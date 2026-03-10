"""Tests that all exception types in confiture.exceptions have default error codes."""

from pathlib import Path

import pytest

from confiture.exceptions import (
    ConfigurationError,
    ConfiturError,
    DifferError,
    ExternalGeneratorError,
    GitError,
    GrantAccompanimentError,
    MigrationConflictError,
    MigrationError,
    MigrationOverwriteError,
    NotAGitRepositoryError,
    RebuildError,
    RestoreError,
    RollbackError,
    SchemaError,
    SeedError,
    SQLError,
    SyncError,
    ValidationError,
    VerifyFileError,
)


def _make_exception(cls: type[ConfiturError]) -> ConfiturError:
    """Construct an exception instance with minimal required args."""
    if cls is SQLError:
        return cls("SELECT 1", None, RuntimeError("db down"))
    if cls is MigrationOverwriteError:
        return cls(Path("/tmp/001_init.up.sql"))
    return cls("test error")


_EXCEPTION_CODES: list[tuple[type[ConfiturError], str]] = [
    (ConfigurationError, "CONFIG_001"),
    (MigrationError, "MIGR_001"),
    (MigrationConflictError, "MIGR_106"),
    (MigrationOverwriteError, "MIGR_004"),
    (SchemaError, "SCHEMA_001"),
    (SyncError, "SYNC_001"),
    (DifferError, "DIFF_001"),
    (ValidationError, "VALID_001"),
    (VerifyFileError, "VERIFY_001"),
    (RollbackError, "ROLLBACK_001"),
    (SQLError, "SQL_001"),
    (GitError, "GIT_001"),
    (NotAGitRepositoryError, "GIT_002"),
    (GrantAccompanimentError, "GRANT_001"),
    (ExternalGeneratorError, "GEN_001"),
    (RebuildError, "REBUILD_001"),
    (RestoreError, "RESTORE_001"),
    (SeedError, "SEED_001"),
]


@pytest.mark.parametrize(
    ("exc_cls", "expected_code"),
    _EXCEPTION_CODES,
    ids=[cls.__name__ for cls, _ in _EXCEPTION_CODES],
)
def test_all_exception_types_have_default_error_code(
    exc_cls: type[ConfiturError],
    expected_code: str,
) -> None:
    """Each ConfiturError subclass provides a non-None default error_code."""
    exc = _make_exception(exc_cls)
    assert exc.error_code is not None
    assert exc.error_code == expected_code


def test_error_code_can_be_overridden() -> None:
    """Passing error_code= to a subclass overrides the default."""
    exc = ConfigurationError("bad config", error_code="CUSTOM_001")
    assert exc.error_code == "CUSTOM_001"


def test_error_code_prefix_consistency() -> None:
    """No exception type uses the old 'MIGRATION_' prefix."""
    for exc_cls, _ in _EXCEPTION_CODES:
        exc = _make_exception(exc_cls)
        assert not exc.error_code.startswith("MIGRATION_"), (
            f"{exc_cls.__name__} uses deprecated 'MIGRATION_' prefix: {exc.error_code}"
        )


def test_resolution_hints_are_actionable() -> None:
    """resolution_hint is stored on the exception when provided."""
    hint = "Check your YAML configuration file"
    exc = ConfigurationError("bad config", resolution_hint=hint)
    assert exc.resolution_hint == hint

    hint_migration = "Run confiture migrate status first"
    exc_m = MigrationError("failed", resolution_hint=hint_migration)
    assert exc_m.resolution_hint == hint_migration

    hint_git = "Initialize a git repository with git init"
    exc_g = NotAGitRepositoryError("not a repo", resolution_hint=hint_git)
    assert exc_g.resolution_hint == hint_git
