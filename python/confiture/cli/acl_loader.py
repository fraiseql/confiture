"""Shared helper for loading ``acls:`` expectations from a raw config dict.

Used by ``confiture drift --check-acls`` and
``confiture migrate validate --check-acl-coverage``.  Centralizes the
${VAR} expansion + Pydantic validation logic so both commands behave
identically.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from pydantic import ValidationError

from confiture.cli.helpers import error_console
from confiture.config._env_vars import expand_env_vars
from confiture.config.environment import AclExpectation


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
        config_path: Path the config came from — included in error
            messages.
        require: When ``True``, missing ``acls:`` exits with code 2.
            When ``False`` (e.g. the lint rule's "no-op when absent"
            semantics), an empty list is returned.

    Returns:
        The list of validated :class:`AclExpectation`s, possibly empty.
    """
    raw = config_data.get("acls")
    if not raw:
        if require:
            error_console.print(
                f"[red]❌ --check-acls requires an `acls:` block in {config_path}[/red]"
            )
            raise typer.Exit(2)
        return []

    expanded = expand_env_vars(raw, context="acls")
    try:
        return [AclExpectation.model_validate(item) for item in expanded]
    except ValidationError as exc:
        error_console.print(f"[red]❌ Invalid acls: block in {config_path}: {exc}[/red]")
        raise typer.Exit(2) from exc


__all__ = ["load_acl_expectations"]
