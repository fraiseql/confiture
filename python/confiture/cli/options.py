"""Shared CLI option factories and the option aliases more than one command takes.

``format_option`` is the one ``--format`` validator: an invalid value exits 5
with the error on stderr — the same way on every command — before the command
body runs, so nothing is printed to stdout and no database is touched.

An option two commands take is declared **once**, here. ``--schemas`` was
declared twice — in ``migrate validate`` and in ``migrate fix-signatures`` — and
the two help strings had already drifted apart before one of them changed its
default (#303). The second of those commands executes ``DROP FUNCTION``.

The six options most commands take — ``--config``, ``--env``, ``--database-url``,
``--migrations-dir``, ``--output``, ``--verbose`` — each come from one factory
below, and ``tests/unit/test_common_options_have_one_factory.py`` fails on any
other declaration of their flags. A factory fixes the flag, its short form and its
help; it takes the command's default, because a default is a lookup a caller relies
on (``migrate validate`` reads ``./confiture.yaml``, ``migrate up`` reads
``db/environments/local.yaml``, ``migrate status`` reads none).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

from confiture.cli.error_json import fail
from confiture.exceptions import ValidationError

#: ``--config``'s three defaults, each a different lookup.
LOCAL_CONFIG = Path("db/environments/local.yaml")
#: The sentinel ``_resolve_config`` reads as "no --config given", so ``--env`` resolves.
CONFITURE_YAML = Path("confiture.yaml")
MIGRATIONS_DIR = Path("db/migrations")

_ENV_LOOKUP = "reads db/environments/<name>.yaml"


def _option(default: Any, names: tuple[str, ...], help: str, **kwargs: Any) -> Any:
    return typer.Option(default, *names, help=help, **kwargs)


def _names(flag: str, short: str, *, short_form: bool, aliases: tuple[str, ...]) -> tuple[str, ...]:
    return (flag, *((short,) if short_form else ()), *aliases)


def config_option(
    default: Any = LOCAL_CONFIG, *, help: str | None = None, short: bool = True, **kwargs: Any
) -> Any:
    """``--config/-c``: the environment file, defaulting to what this command reads."""
    if help is None:
        if default is None:
            help = "Configuration file (optional)"
        elif default == CONFITURE_YAML:
            help = f"Configuration file (default: {CONFITURE_YAML}); --env {_ENV_LOOKUP}"
        else:
            help = f"Configuration file (default: {default})"
    return _option(default, _names("--config", "-c", short_form=short, aliases=()), help, **kwargs)


def env_option(default: str | None = "local", *, help: str | None = None, **kwargs: Any) -> Any:
    """``--env/-e``: an environment name, read as ``db/environments/<name>.yaml``."""
    if help is None:
        suffix = f" (default: {default})" if default else ", instead of --config"
        help = f"Environment name: {_ENV_LOOKUP}{suffix}"
    return _option(default, ("--env", "-e"), help, **kwargs)


def database_url_option(
    default: Any = None, *, help: str | None = None, short: bool = True, **kwargs: Any
) -> Any:
    """``--database-url/-d``. Its help says which database: the ledger's, a server, a target."""
    names = _names("--database-url", "-d", short_form=short, aliases=())
    return _option(default, names, help or "PostgreSQL connection URL", **kwargs)


def migrations_dir_option(
    default: Any = MIGRATIONS_DIR, *, help: str | None = None, **kwargs: Any
) -> Any:
    """``--migrations-dir``: where the migration files are."""
    return _option(
        default,
        ("--migrations-dir",),
        help or f"Migrations directory (default: {default})",
        **kwargs,
    )


def output_option(
    default: Any = None,
    *aliases: str,
    help: str | None = None,
    short: bool = True,
    **kwargs: Any,
) -> Any:
    """``--output/-o``: where to write what would otherwise go to stdout."""
    names = _names("--output", "-o", short_form=short, aliases=aliases)
    return _option(
        default, names, help or "Write the output to this file instead of stdout", **kwargs
    )


def verbose_option(*, help: str, **kwargs: Any) -> Any:
    """``--verbose/-v``: what "more" means is the command's to say."""
    return _option(False, ("--verbose", "-v"), help, **kwargs)


def format_option(*allowed: str, default: str | None = None, help: str | None = None) -> Any:
    """``--format/-f`` restricted to *allowed*; the first value is the default.

    Example:
        >>> format_output: str = format_option("text", "json")
    """
    if not allowed:
        raise ValueError("format_option needs at least one allowed value")
    chosen_default = default if default is not None else allowed[0]
    if chosen_default not in allowed:
        raise ValueError(f"default {chosen_default!r} is not one of {allowed}")
    choices = ", ".join(f"'{value}'" for value in allowed)

    def _validate(value: str) -> str:
        if value not in allowed:
            fail(
                ValidationError(
                    f"Invalid --format {value!r}: use {choices}.",
                    context={"format": value, "allowed": list(allowed)},
                ),
                json_mode=False,
            )
        return value

    return typer.Option(
        chosen_default,
        "--format",
        "-f",
        callback=_validate,
        help=help or f"Output format: {' or '.join(allowed)} (default: {chosen_default})",
    )


#: The modes that only look. A command whose ``--mode`` defaults to anything else
#: would act when run bare, which is what ``--mode`` exists to prevent.
PREVIEW_MODES = frozenset({"check", "plan"})


def mode_option(*modes: str, help: str) -> Any:
    """``--mode`` for a command that previews unless told to act; the first mode is the default.

    A command that acts by default takes ``--dry-run`` to preview instead. The two
    never meet on one command (``tests/unit/test_dry_run_is_one_flag.py``), and the
    first mode — the default — must be one of :data:`PREVIEW_MODES`: running
    ``migrate fix-signatures`` bare prints the ``DROP FUNCTION`` it would run, it
    does not run it.
    """
    if not modes or modes[0] not in PREVIEW_MODES:
        raise ValueError(f"mode_option's default {modes[:1]} is not a preview mode")
    choices = ", ".join(f"'{mode}'" for mode in modes)

    def _validate(value: str) -> str:
        if value not in modes:
            fail(
                ValidationError(
                    f"Invalid --mode {value!r}: use {choices}.",
                    context={"mode": value, "allowed": list(modes)},
                ),
                json_mode=False,
            )
        return value

    return typer.Option(
        modes[0], "--mode", callback=_validate, help=f"{help} (default: {modes[0]})"
    )


#: ``--project-dir`` for the commands that read a project tree (``build``, ``lint``).
ProjectDirOpt = Annotated[
    Path, typer.Option("--project-dir", help="Project directory (default: current directory)")
]


#: ``--schemas`` for the signature checks. ``None`` means "each reader's own
#: default": the schemas the parsed source declares for ``--check-signatures``
#: and ``migrate fix-signatures``, and ``public`` for the three other checks that
#: read this option (#303).
CheckSignatureSchemasOpt = Annotated[
    str | None,
    typer.Option(
        "--schemas",
        help="Comma-separated list of schemas to inspect. Defaults to the schemas "
        "the source declares, which is what --check-live-drift derives from the "
        "same DDL.",
    ),
]
