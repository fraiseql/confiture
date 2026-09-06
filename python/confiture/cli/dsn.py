"""Database-URL resolution for the CLI (#152 precedence contract) and the option help it documents."""

import os
from pathlib import Path
from typing import Any

from confiture.exceptions import ConfigurationError
from confiture.url_redaction import redact_url as redact_url  # re-export (layering)

# The two recognized DSN env vars, treated *differently* by intent (#152):
#   - CONFITURE_DATABASE_URL: canonical, confiture-specific, set on purpose.
#   - DATABASE_URL: ambient, ubiquitous in CI/deploy; must never silently
#     clobber a config.
_CONFITURE_DSN_ENV = "CONFITURE_DATABASE_URL"


_AMBIENT_DSN_ENV = "DATABASE_URL"


_DATABASE_URL_ENV_VARS = (_CONFITURE_DSN_ENV, _AMBIENT_DSN_ENV)


# Shared --help text for the --no-config flag across the migrate family (#152).
NO_CONFIG_OPTION_HELP = (
    "Suppress config-file discovery entirely; the environment "
    "(CONFITURE_DATABASE_URL, else DATABASE_URL) becomes the sole DSN source. "
    "Use this for runtime-resolved DSNs that must not be exposed in argv."
)


# Shared --help text for the --database-url flag across the migrate family (#140).
DATABASE_URL_OPTION_HELP = (
    "PostgreSQL DSN for the tracking database. Always wins over --config / --env "
    "and the env vars. The canonical CONFITURE_DATABASE_URL beats a *default* "
    "--config but conflicts with an *explicit* one (CONFIG_007); the ambient "
    "DATABASE_URL never overrides a present config. Pass --no-config to make the "
    "environment the sole source. When a DSN is supplied, no YAML is required "
    "(tracking table defaults to tb_confiture). SSH-tunnel configs still require "
    "--config."
)


def resolve_database_url(
    flag: str | None,
    config_path: Path | None,
    *,
    config_explicit: bool = False,
    no_config: bool = False,
    require_intentional_source: bool = False,
) -> str | None:
    """Resolve the tracking-database DSN under the #152 precedence contract.

    Principle: **explicit-and-singular wins; ambiguity fails loud** — the secure
    default for a tool that touches production. Order:

    1. ``--database-url`` flag — always wins (validated).
    2. ``--no-config`` — config discovery is suppressed, the environment is the
       sole source: ``CONFITURE_DATABASE_URL`` preferred over the ambient
       ``DATABASE_URL``; neither set → ``CONFIG_010`` (fail loud).
    3. An **explicit** ``--config``/``--env`` **and** ``CONFITURE_DATABASE_URL``
       both present → ``CONFIG_007`` (fail loud; two explicit sources are never
       silently reconciled — no DSN normalization, no "pick one").
    4. An explicit ``--config``/``--env`` only → defer to the config (``None``);
       an ambient ``DATABASE_URL`` does NOT override an explicit config.
    5. ``CONFITURE_DATABASE_URL`` set while the config is only the **default** →
       the canonical var (it beats a default config — the bug #152 fixes).
    6. A present config file (even the default) → defer to it (``None``); it
       beats the ambient ``DATABASE_URL``.
    7. Otherwise the ambient ``DATABASE_URL`` — unless
       ``require_intentional_source`` (mutating commands), where an ambient-only
       DSN raises ``CONFIG_010`` rather than silently migrating against it.
    8. Nothing resolved → ``None`` (the caller has no source).

    Args:
        flag: ``--database-url`` value (``None`` if not given).
        config_path: The resolved ``--config`` path. Its default is a *present*
            file, so existence alone cannot tell default from explicit — hence
            ``config_explicit``.
        config_explicit: Whether ``--config`` or ``--env`` was set explicitly
            (vs defaulted). The command recovers this via ``config_is_explicit``
            from ``ctx.get_parameter_source`` for the ``config`` and ``env``
            parameters.
        no_config: Whether ``--no-config`` was passed (suppress config discovery).
        require_intentional_source: For mutating commands (``up``/``down``):
            refuse to run against a merely-ambient ``DATABASE_URL``.

    Returns:
        The DSN to use as ``database_url_override``, or ``None`` to defer to the
        config file.

    Raises:
        ConfigurationError: ``CONFIG_003`` (malformed flag DSN), ``CONFIG_007``
            (two explicit sources), or ``CONFIG_010`` (no usable source).
    """

    # (1) An explicit flag always wins.
    if flag:
        if not flag.startswith(("postgresql://", "postgres://")):
            raise ConfigurationError(
                f"Invalid --database-url: must start with postgresql:// or "
                f"postgres://, got: {flag}",
                error_code="CONFIG_003",
                resolution_hint="Use format: postgresql://user:password@host:port/database",
            )
        return flag

    confiture_url = os.environ.get(_CONFITURE_DSN_ENV)
    ambient_url = os.environ.get(_AMBIENT_DSN_ENV)

    # (2) --no-config: the environment is the sole source.
    if no_config:
        if confiture_url:
            return confiture_url
        if ambient_url:
            return ambient_url
        raise ConfigurationError(
            "--no-config was given but no DSN is set in the environment",
            error_code="CONFIG_010",
            resolution_hint=(
                "Set CONFITURE_DATABASE_URL (or DATABASE_URL), or drop --no-config "
                "to use a config file."
            ),
        )

    # (3) Two explicit sources → fail loud, period (present-at-all, not differing).
    if config_explicit and confiture_url:
        raise ConfigurationError(
            "Both an explicit --config/--env and CONFITURE_DATABASE_URL are set",
            error_code="CONFIG_007",
            resolution_hint=(
                "Pass exactly one explicit source: drop --config/--env, unset "
                "CONFITURE_DATABASE_URL, or pass --no-config."
            ),
        )

    # (4) Explicit config (no canonical var) → use it; ambient never overrides it.
    if config_explicit:
        return None

    # config_path is at most the DEFAULT below here.
    # (5) The canonical var beats a default config.
    if confiture_url:
        return confiture_url

    # (6) A present (default) config beats the ambient DATABASE_URL.
    if config_path is not None and config_path.exists():
        return None

    # (7) Ambient DATABASE_URL — refused for mutating commands.
    if ambient_url:
        if require_intentional_source:
            raise ConfigurationError(
                "No intentional DSN source for a mutating command; refusing to run "
                "against an ambient DATABASE_URL",
                error_code="CONFIG_010",
                resolution_hint=(
                    "Pass --database-url, set CONFITURE_DATABASE_URL, or point "
                    "--config at a config file."
                ),
            )
        return ambient_url

    # (8) No source.
    return None


def param_is_explicit(ctx: Any, *params: str) -> bool:
    """Whether any named parameter was set on the command line / via env.

    The generic core of :func:`config_is_explicit`. A typer option with a
    truthy default cannot be told apart from an operator-supplied value by
    inspecting the value alone — ``--base-ref`` defaults to ``"origin/main"``,
    so ``if base_ref:`` is always true. Click's parameter source can tell them
    apart, and that distinction is what keeps an unscoped ``--idempotent`` run
    unscoped (#181).

    Compares the ``click.core.ParameterSource`` enum by member name rather than
    importing it: ``click`` is only a transitive dependency (via typer), so a
    direct ``import click`` is not guaranteed to resolve. ``ctx`` is already a
    typer/click Context, so no import is needed.

    Args:
        ctx: The typer/click context.
        params: Parameter names to check. A parameter the command does not
            declare yields no source and is ignored, so passing a superset is
            safe.

    Returns:
        True if *any* named parameter was set explicitly; False defensively
        when no source is available.
    """
    for param in params:
        try:
            source = ctx.get_parameter_source(param)
        except Exception:
            continue
        name = getattr(source, "name", None)
        if name is not None and name not in ("DEFAULT", "DEFAULT_MAP"):
            return True
    return False


def config_is_explicit(ctx: Any, *params: str) -> bool:
    """Whether ``--config`` or ``--env`` was set explicitly, not defaulted (#152).

    The migrate family defaults ``--config`` to a *present* file
    (``db/environments/local.yaml``), so the resolved ``Path`` cannot tell a
    default from an operator-supplied one. Click's parameter source can — this
    is the linchpin that makes the precedence contract expressible.

    Checks ``config`` and ``env`` by default (a command may carry either —
    ``preflight`` has both). A parameter the command does not declare yields no
    source and is ignored, so passing the full set is always safe. Returns
    ``True`` if *any* checked parameter was set on the command line / via env
    rather than defaulted; ``False`` defensively when no source is available.

    Compares the ``click.core.ParameterSource`` enum by member name rather than
    importing it: ``click`` is only a transitive dependency (via typer), so a
    direct ``import click`` is not guaranteed to resolve. ``ctx`` is already a
    typer/click Context, so no import is needed.

    Thin wrapper over :func:`param_is_explicit` supplying the ``#152`` default
    parameter set; the mechanism is shared, the defaults are not.
    """
    return param_is_explicit(ctx, *(params or ("config", "env")))


def has_intentional_dsn_source(ctx: Any, flag: str | None, no_config: bool) -> bool:
    """Whether an *intentional* DSN source is present (#152, for ``status``).

    True for a ``--database-url`` flag, ``--no-config``, an explicit
    ``--config``/``--env``, or the canonical ``CONFITURE_DATABASE_URL``. A
    merely-ambient ``DATABASE_URL`` does NOT count — ``migrate status`` stays in
    its no-connect "status-unknown" state (exit 0) rather than auto-connecting
    to whatever ``DATABASE_URL`` happens to be in the environment.
    """
    return (
        bool(flag)
        or no_config
        or config_is_explicit(ctx)
        or bool(os.environ.get(_CONFITURE_DSN_ENV))
    )
