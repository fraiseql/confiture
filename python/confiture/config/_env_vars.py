"""Shared ``${VAR}`` expansion for Confiture YAML configuration.

Used by the connection settings (``database_url``, ``scratch_url``, a
``database:`` block) and the ``acls:``, ``ownership:`` and
``function_coverage:`` blocks of :mod:`confiture.config.environment`, and by
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

import os
import re
from typing import Any

from confiture.exceptions import ConfigurationError
from confiture.url_redaction import redact_url

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


def _expand_string(value: str, context: str, keep: frozenset[str]) -> str:
    """Expand strict references; raise on any near-miss; single pass.

    Scans with :data:`_LOOSE_ENV_VAR_RE`, replaces each match either by
    its env-var value (strict form) or by raising on anything else.
    Also detects unclosed ``${`` and a substituted value that itself holds a
    reference (nested-expansion intent). A name in *keep* is left as written.
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
        if inner in keep:
            return match.group(0)
        if inner not in os.environ:
            raise ConfigurationError(
                f"Environment variable {inner!r} referenced in {context} "
                f"is not set.  Missing variables fail loud — they never expand "
                f"to an empty string."
            )
        expanded = os.environ[inner]
        # Single pass: the value is not re-scanned. A reference inside it is
        # refused rather than left half-expanded, and named by the variable that
        # holds it, never quoted: the value may be a password.
        if _LOOSE_ENV_VAR_RE.search(expanded) is not None:
            raise ConfigurationError(
                f"Nested env-var expansion is not supported in {context}: "
                f"the value of {inner!r} itself holds a ``${{…}}`` reference.  "
                f"Resolve the nesting in the environment, not in the YAML."
            )
        return expanded

    return _LOOSE_ENV_VAR_RE.sub(_sub, value)


def expand_env_vars(
    value: Any, *, context: str = "config", keep: frozenset[str] = frozenset()
) -> Any:
    """Walk *value* recursively, expanding ``${VAR}`` in any string.

    Args:
        value: Anything nestable as YAML — dict, list, str, scalar.
        context: Short label included in the error message when a variable
            is unset (e.g. ``"acls"``, ``"notifications config"``).
        keep: Names that are placeholders another part of confiture fills in,
            left as written (``${TUNNEL_LOCAL_PORT}``).

    Raises:
        ConfigurationError: If a referenced variable is not present in
            ``os.environ``, if the reference uses an unsupported syntax
            (``${VAR:-default}``, lowercase, nested), or if a ``${``
            opens without a matching ``}``.  Empty strings are never
            substituted.
    """
    if isinstance(value, str):
        return _expand_string(value, context, keep)
    if isinstance(value, dict):
        return {k: expand_env_vars(v, context=context, keep=keep) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env_vars(v, context=context, keep=keep) for v in value]
    return value


#: The placeholder ``ssh_tunnel`` fills with the local port it opened: written in a
#: connection URL like a variable, read from no environment.
TUNNEL_LOCAL_PORT = "TUNNEL_LOCAL_PORT"


def references(value: str, *, context: str) -> tuple[str, ...]:
    """The variables *value* names, its ``${…}`` syntax checked without reading the environment.

    What a load can say about a value it does not expand yet: a malformed or
    lowercase reference is refused as :func:`expand_env_vars` would refuse it.
    """
    open_idx = value.find("${")
    if open_idx != -1 and "}" not in value[open_idx:]:
        raise ConfigurationError(
            f"Unclosed env-var reference in {context}: "
            f"found ``${{`` without a matching ``}}`` at position {open_idx}."
        )
    names: list[str] = []
    for match in _LOOSE_ENV_VAR_RE.finditer(value):
        if not _STRICT_ENV_VAR_RE.fullmatch(match.group(0)):
            raise ConfigurationError(_diagnose_invalid_reference(match.group(1), context))
        names.append(match.group(1))
    return tuple(names)


def expand_connection(value: Any, *, context: str) -> Any:
    """Expand ``${VAR}`` in a connection setting, leaving ``${TUNNEL_LOCAL_PORT}`` for the tunnel.

    The one expansion of ``database_url``, ``scratch_url`` and a ``database:``
    block, for ``Environment.load`` and the raw-config path alike.
    """
    return expand_env_vars(value, context=context, keep=frozenset({TUNNEL_LOCAL_PORT}))


_POSTGRESQL_SCHEMES = ("postgresql://", "postgres://")


def expand_connection_url(written: str, *, field: str) -> str:
    """A connection URL with its ``${VAR}`` references expanded, at the moment it is used.

    An expansion that is not a PostgreSQL URL is refused quoting the value as it is
    written: ``redact_url`` cannot mask a password in a value it cannot read as a URL,
    so no error ever prints the expansion.
    """
    expanded = expand_connection(written, context=field)
    if expanded != written and not expanded.startswith(_POSTGRESQL_SCHEMES):
        raise ConfigurationError(
            f"Invalid {field}: {redact_url(written)} does not expand to a URL starting "
            "with postgresql:// or postgres://",
            error_code="CONFIG_003",
        )
    return expanded
