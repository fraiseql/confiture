"""Shared helper for loading the ``ownership:`` block from a raw config dict.

Used by ``confiture drift --check-ownership`` and
``confiture migrate validate --check-ownership-coverage`` (issue #124).
Centralizes the ``${VAR}`` expansion + Pydantic validation logic so both
commands behave identically — mirrors :mod:`confiture.cli.acl_loader`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from pydantic import ValidationError

from confiture.cli.helpers import error_console
from confiture.config._env_vars import expand_env_vars
from confiture.config.environment import OwnershipExpectation


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
        config_path: Path the config came from — included in error
            messages.
        require: When ``True``, missing ``ownership:`` exits with code 2.
            When ``False`` (e.g. the lint rule's "no-op when absent"
            semantics), ``None`` is returned.

    Returns:
        The validated :class:`OwnershipExpectation`, or ``None`` when the
        block is absent and ``require=False``.
    """
    raw = config_data.get("ownership")
    if not raw:
        if require:
            error_console.print(
                f"[red]❌ --check-ownership requires an `ownership:` block in {config_path}[/red]"
            )
            raise typer.Exit(2)
        return None

    expanded = expand_env_vars(raw, context="ownership")
    try:
        return OwnershipExpectation.model_validate(expanded)
    except ValidationError as exc:
        error_console.print(
            f"[red]❌ Invalid ownership: block in {config_path}: {exc}[/red]"
        )
        raise typer.Exit(2) from exc


__all__ = ["load_ownership_expectation"]
