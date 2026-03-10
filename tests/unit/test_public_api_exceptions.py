"""Test that all exceptions are importable from top-level confiture module."""

import confiture


def test_lazy_imports_in_sync_with_all() -> None:
    """Every item in _LAZY_IMPORTS should be in __all__."""
    for name in confiture._LAZY_IMPORTS:
        assert name in confiture.__all__, f"{name} in _LAZY_IMPORTS but not in __all__"


def test_all_non_metadata_items_in_lazy_or_eager() -> None:
    """Every non-metadata item in __all__ should be lazily or eagerly importable."""
    metadata = {"__version__", "__author__", "__email__"}
    eager = {"SchemaLinter", "ExternalGeneratorError"}
    for name in confiture.__all__:
        if name in metadata or name in eager:
            continue
        assert name in confiture._LAZY_IMPORTS, f"{name} in __all__ but not in _LAZY_IMPORTS"


def test_confiture_error_importable_from_top_level() -> None:
    """Test that ConfiturError can be imported from confiture."""
    from confiture import ConfiturError

    assert ConfiturError is not None
    # Verify it's the base class for Confiture errors
    assert issubclass(ConfiturError, Exception)


def test_all_exceptions_importable_from_top_level() -> None:
    """Test that all major exceptions are importable from top-level."""
    exceptions_to_test = [
        "ConfiturError",
        "ConfigurationError",
        "MigrationError",
        "SchemaError",
        "SQLError",
        "RollbackError",
        "SeedError",
        "RestoreError",
        "PreconditionError",
        "PreconditionValidationError",
    ]

    for exc_name in exceptions_to_test:
        # This should not raise AttributeError
        exc_cls = getattr(__import__("confiture"), exc_name)
        assert exc_cls is not None
        assert issubclass(exc_cls, Exception)


def test_exception_inheritance_chain() -> None:
    """Test that exceptions inherit from ConfiturError."""
    from confiture import (
        ConfigurationError,
        ConfiturError,
        MigrationError,
        SchemaError,
        SeedError,
    )

    for exc_cls in [ConfigurationError, MigrationError, SchemaError, SeedError]:
        assert issubclass(exc_cls, ConfiturError)
