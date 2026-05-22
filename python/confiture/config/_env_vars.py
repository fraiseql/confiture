"""Shared ``${VAR}`` expansion for Confiture YAML configuration.

Used by the ``acls:`` block in :mod:`confiture.config.environment` and by
the ``hooks.notifications`` package.  Missing variables fail loud — they
never expand to an empty string.

Supported syntax: ``${UPPER_NAME}`` where the name matches the strict form
``[A-Z_][A-Z0-9_]*``.  Anything that looks like a reference but doesn't
match the strict form (``${VAR:-default}``, ``${lower}``, ``${VAR``)
raises :class:`ConfigurationError` with a diagnostic that names the
unsupported syntax.  Expansion is single-pass: a value like ``${INNER}``
in the result is not re-scanned, so nested references are rejected
explicitly rather than producing surprising one-pass-only behavior.
"""

from __future__ import annotations

import os
import re
from typing import Any

from confiture.exceptions import ConfigurationError

# Strict, supported form: uppercase identifier inside ``${...}``.
_STRICT_ENV_VAR_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")
# Permissive scan: anything that looks like an env-var reference, used
# to detect near-misses that we want to reject loudly.
_LOOSE_ENV_VAR_RE = re.compile(r"\$\{([^}]*)\}")


def _diagnose_invalid_reference(inner: str, context: str) -> str:
    """Return a specific diagnostic for an unsupported ``${...}`` form."""
    if not inner:
        return (
            f"Empty env-var reference '${{}}' in {context}.  "
            f"Use ``${{UPPER_NAME}}`` with a non-empty variable name."
        )
    if ":-" in inner or ":=" in inner or ":?" in inner or ":+" in inner:
        return (
            f"Unsupported env-var syntax '${{{inner}}}' in {context}: "
            f"bash-style defaults (``${{VAR:-default}}``) are not supported.  "
            f"Use a plain ``${{VAR}}`` reference and ensure the variable is set, "
            f"or set the desired literal in the YAML directly."
        )
    if inner != inner.upper() or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", inner):
        upper_hint = inner.upper() if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", inner) else None
        suffix = f" Did you mean ``${{{upper_hint}}}``?" if upper_hint else ""
        return (
            f"Invalid env-var name '${{{inner}}}' in {context}: "
            f"only ``[A-Z_][A-Z0-9_]*`` is supported (uppercase letters, digits, "
            f"and underscores; the first character cannot be a digit)."
            f"{suffix}"
        )
    return f"Unsupported env-var syntax '${{{inner}}}' in {context}."


def _expand_string(value: str, context: str) -> str:
    """Expand strict references; raise on any near-miss; single pass.

    Scans with :data:`_LOOSE_ENV_VAR_RE`, replaces each match either by
    its env-var value (strict form) or by raising on anything else.
    Also detects unclosed ``${`` and residual ``${...}`` in the result
    (which would indicate nested-expansion intent).
    """
    # Unclosed ``${`` — the loose regex requires a closing ``}``, so an
    # opener without one would not match.  Detect it explicitly.
    open_idx = value.find("${")
    if open_idx != -1 and "}" not in value[open_idx:]:
        raise ConfigurationError(
            f"Unclosed env-var reference in {context}: "
            f"found ``${{`` without a matching ``}}`` at position {open_idx}."
        )

    def _sub(match: re.Match[str]) -> str:
        inner = match.group(1)
        if not _STRICT_ENV_VAR_RE.fullmatch(match.group(0)):
            raise ConfigurationError(_diagnose_invalid_reference(inner, context))
        if inner not in os.environ:
            raise ConfigurationError(
                f"Environment variable {inner!r} referenced in {context} "
                f"is not set.  Missing variables fail loud — they never expand "
                f"to an empty string."
            )
        return os.environ[inner]

    result = _LOOSE_ENV_VAR_RE.sub(_sub, value)

    # Single-pass: a residual ``${...}`` in *result* means the substituted
    # value itself contained a reference.  We deliberately don't recurse;
    # raise instead so users don't get unexpectedly partial expansion.
    residual = _LOOSE_ENV_VAR_RE.search(result)
    if residual is not None:
        raise ConfigurationError(
            f"Nested env-var expansion is not supported in {context}: "
            f"after expanding the outer reference the result still contains "
            f"'{residual.group(0)}'.  Resolve the nesting in the environment, "
            f"not in the YAML."
        )
    return result


def expand_env_vars(value: Any, *, context: str = "config") -> Any:
    """Walk *value* recursively, expanding ``${VAR}`` in any string.

    Args:
        value: Anything nestable as YAML — dict, list, str, scalar.
        context: Short label included in the error message when a variable
            is unset (e.g. ``"acls"``, ``"notifications config"``).

    Raises:
        ConfigurationError: If a referenced variable is not present in
            ``os.environ``, if the reference uses an unsupported syntax
            (``${VAR:-default}``, lowercase, nested), or if a ``${``
            opens without a matching ``}``.  Empty strings are never
            substituted.
    """
    if isinstance(value, str):
        return _expand_string(value, context)
    if isinstance(value, dict):
        return {k: expand_env_vars(v, context=context) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env_vars(v, context=context) for v in value]
    return value
