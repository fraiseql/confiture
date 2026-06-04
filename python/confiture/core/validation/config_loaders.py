"""Load, expand, and validate optional lint config blocks.

These helpers pull a single block (``acls:`` / ``ownership:`` /
``function_coverage:``) out of a raw config dict, run ``${VAR}`` expansion, and
validate it into its Pydantic model. They are shared by ``confiture drift``,
``confiture migrate validate``, and ``confiture migrate bootstrap`` so every
command parses the block identically.

On a missing-but-required block or a malformed block they raise
:class:`~confiture.exceptions.ConfigurationError` (``CONFIG_001`` → exit 5). The
calling command catches it at its ``fail()`` boundary, which emits the #145
envelope. They never import ``typer`` or print directly — that keeps them pure
config-parsers and lets the orchestration layer decide how failures surface.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from confiture.config._env_vars import expand_env_vars
from confiture.config.environment import (
    AclExpectation,
    FunctionCoverage,
    OwnershipExpectation,
)
from confiture.exceptions import ConfigurationError


def load_acl_expectations(
    config_data: dict[str, Any],
    config_path: Path,
    *,
    require: bool,
) -> list[AclExpectation]:
    """Pull, expand, and validate the ``acls:`` block from a raw config dict.

    Args:
        config_data: Parsed YAML as returned by
            :func:`confiture.core.connection.load_config`.
        config_path: Path the config came from — included in error messages.
        require: When ``True``, a missing ``acls:`` block raises
            ``ConfigurationError``. When ``False`` (the lint rule's "no-op when
            absent" semantics), an empty list is returned.

    Returns:
        The list of validated :class:`AclExpectation`s, possibly empty.

    Raises:
        ConfigurationError: ``acls:`` is required but absent, or malformed.
    """
    raw = config_data.get("acls")
    if not raw:
        if require:
            raise ConfigurationError(f"--check-acls requires an `acls:` block in {config_path}")
        return []

    expanded = expand_env_vars(raw, context="acls")
    try:
        return [AclExpectation.model_validate(item) for item in expanded]
    except ValidationError as exc:
        raise ConfigurationError(f"Invalid acls: block in {config_path}: {exc}") from exc


def load_ownership_expectation(
    config_data: dict[str, Any],
    config_path: Path,
    *,
    require: bool,
) -> OwnershipExpectation | None:
    """Pull, expand, and validate the ``ownership:`` block from a raw config dict.

    Args:
        config_data: Parsed YAML as returned by
            :func:`confiture.core.connection.load_config`.
        config_path: Path the config came from — included in error messages.
        require: When ``True``, a missing ``ownership:`` block raises
            ``ConfigurationError``. When ``False`` (the lint rule's "no-op when
            absent" semantics), ``None`` is returned.

    Returns:
        The validated :class:`OwnershipExpectation`, or ``None`` when the block
        is absent and ``require=False``.

    Raises:
        ConfigurationError: ``ownership:`` is required but absent, or malformed.
    """
    raw = config_data.get("ownership")
    if not raw:
        if require:
            raise ConfigurationError(
                f"--check-ownership requires an `ownership:` block in {config_path}"
            )
        return None

    expanded = expand_env_vars(raw, context="ownership")
    try:
        return OwnershipExpectation.model_validate(expanded)
    except ValidationError as exc:
        raise ConfigurationError(f"Invalid ownership: block in {config_path}: {exc}") from exc


def load_function_coverage(
    config_data: dict[str, Any],
    config_path: Path,
    *,
    require: bool,
) -> FunctionCoverage | None:
    """Pull, expand, and validate the ``function_coverage:`` block.

    Args:
        config_data: Parsed YAML as returned by
            :func:`confiture.core.connection.load_config`.
        config_path: Path the config came from — included in error messages.
        require: When ``True``, a missing ``function_coverage:`` block raises
            ``ConfigurationError``. When ``False`` (the lint rule's "no-op when
            absent" semantics), ``None`` is returned.

    Returns:
        The validated :class:`FunctionCoverage`, or ``None`` when the block is
        absent and ``require=False``.

    Raises:
        ConfigurationError: ``function_coverage:`` is required but absent, or
            malformed.
    """
    raw = config_data.get("function_coverage")
    if not raw:
        if require:
            raise ConfigurationError(
                f"--check-function-uniqueness requires a `function_coverage:` block "
                f"in {config_path}"
            )
        return None

    expanded = expand_env_vars(raw, context="function_coverage")
    try:
        return FunctionCoverage.model_validate(expanded)
    except ValidationError as exc:
        raise ConfigurationError(
            f"Invalid function_coverage: block in {config_path}: {exc}"
        ) from exc


__all__ = [
    "load_acl_expectations",
    "load_function_coverage",
    "load_ownership_expectation",
]
