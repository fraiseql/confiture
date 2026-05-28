"""Shared helper for loading the ``function_coverage:`` block from a raw config dict.

Used by ``confiture migrate validate --check-function-uniqueness`` (issue #136).
Mirrors :mod:`confiture.cli.ownership_loader`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from pydantic import ValidationError

from confiture.cli.helpers import error_console
from confiture.config._env_vars import expand_env_vars
from confiture.config.environment import FunctionCoverage


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
        config_path: Path the config came from — included in error
            messages.
        require: When ``True``, missing ``function_coverage:`` exits
            with code 2.  When ``False`` (the lint rule's "no-op when
            absent" semantics), ``None`` is returned.

    Returns:
        The validated :class:`FunctionCoverage`, or ``None`` when the
        block is absent and ``require=False``.
    """
    raw = config_data.get("function_coverage")
    if not raw:
        if require:
            error_console.print(
                "[red]❌ --check-function-uniqueness requires a "
                f"`function_coverage:` block in {config_path}[/red]"
            )
            raise typer.Exit(2)
        return None

    expanded = expand_env_vars(raw, context="function_coverage")
    try:
        return FunctionCoverage.model_validate(expanded)
    except ValidationError as exc:
        error_console.print(
            f"[red]❌ Invalid function_coverage: block in {config_path}: {exc}[/red]"
        )
        raise typer.Exit(2) from exc
