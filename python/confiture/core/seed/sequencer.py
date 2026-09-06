"""Sequential seed application for ``confiture build --sequential``.

Owns the connection for the seed pass — open, apply every seed file in order
through :class:`~confiture.core.seed_applier.SeedApplier`, close — and reports
the result; the CLI renders it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from confiture.exceptions import ConfigurationError, SeedError

if TYPE_CHECKING:
    from pathlib import Path

    from confiture.config.environment import SeedProfile
    from confiture.core.seed_applier import ApplyResult


def apply_seed_files(
    database_url: str | None,
    seeds_dir: Path,
    *,
    env: str,
    profile: SeedProfile | None = None,
    continue_on_error: bool = False,
    console: Any = None,
) -> ApplyResult:
    """Apply the seed files under *seeds_dir* sequentially against *database_url*.

    Raises:
        ConfigurationError: ``CONFIG_010`` without a URL, ``CONFIG_006`` when the
            connection fails.
        SeedError: A seed file failed and ``continue_on_error`` is False, or the
            pass failed outright.
    """
    from confiture.core.seed_applier import SeedApplier

    if not database_url:
        raise ConfigurationError(
            "Database URL required for --sequential mode",
            error_code="CONFIG_010",
            resolution_hint="Provide via --database-url or in the environment config.",
        )
    try:
        import psycopg

        connection = psycopg.connect(database_url)
    except Exception as e:
        raise ConfigurationError(
            f"Failed to connect to database: {e}", error_code="CONFIG_006"
        ) from e
    try:
        applier = SeedApplier(seeds_dir=seeds_dir, env=env, connection=connection, console=console)
        result = applier.apply_sequential(continue_on_error=continue_on_error, profile=profile)
    except (ConfigurationError, SeedError):
        raise
    except Exception as e:
        raise SeedError(f"Seed application failed: {e}") from e
    finally:
        connection.close()
    if result.failed > 0 and not continue_on_error:
        raise SeedError(
            f"{result.failed} seed file(s) failed during sequential apply.",
            resolution_hint=(
                "Re-run with --continue-on-error to skip failures, or fix the failing seed files."
            ),
        )
    return result
