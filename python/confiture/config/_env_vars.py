"""Shared ``${VAR}`` expansion for Confiture YAML configuration.

Used by the ``acls:`` block in :mod:`confiture.config.environment` and by
the ``hooks.notifications`` package.  Missing variables fail loud — they
never expand to an empty string.
"""

from __future__ import annotations

import os
import re
from typing import Any

from confiture.exceptions import ConfigurationError

_ENV_VAR_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def expand_env_vars(value: Any, *, context: str = "config") -> Any:
    """Walk *value* recursively, expanding ``${VAR}`` in any string.

    Args:
        value: Anything nestable as YAML — dict, list, str, scalar.
        context: Short label included in the error message when a variable
            is unset (e.g. ``"acls"``, ``"notifications config"``).

    Raises:
        ConfigurationError: If a referenced variable is not present in
            ``os.environ``.  Empty strings are never substituted.
    """
    if isinstance(value, str):

        def _sub(match: re.Match[str]) -> str:
            var = match.group(1)
            if var not in os.environ:
                raise ConfigurationError(
                    f"Environment variable {var!r} referenced in {context} "
                    f"is not set.  Missing variables fail loud — they never expand "
                    f"to an empty string."
                )
            return os.environ[var]

        return _ENV_VAR_RE.sub(_sub, value)
    if isinstance(value, dict):
        return {k: expand_env_vars(v, context=context) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env_vars(v, context=context) for v in value]
    return value
