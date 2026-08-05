"""``migrate validate --check-live-drift`` logic.

Compares the live database schema against a DDL schema file. Requires a config
(for the connection) and an explicit ``--schema`` file.

``load_config`` / ``create_connection`` / ``SchemaDriftDetector`` are imported
at module scope so tests can patch them on this module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from confiture.core.connection import create_connection, load_config
from confiture.core.drift import SchemaDriftDetector
from confiture.exceptions import ConfigurationError

if TYPE_CHECKING:
    from pathlib import Path

    from confiture.core.validation.context import ValidationContext


def check_live_drift(  # noqa: ANN201
    config_path: Path,
    schema_file: Path | None,
    ctx: ValidationContext | None = None,
):
    """Compare the live schema against *schema_file*.

    Args:
        config_path: Config file resolving the database connection.
        schema_file: The DDL schema file to compare against (required).
        ctx: Shared per-run resources. When given, the connection comes from
            there — which is also how this check finally honours ``--ssh``, a
            tunnel its help text has always advertised but ``create_connection``
            never opened.

    Returns:
        The :class:`~confiture.core.drift.DriftReport`.

    Raises:
        ConfigurationError: the config file is missing, ``--schema`` was not
            given, or the database connection fails (``CONFIG_006``).
    """
    if not config_path.exists():
        raise ConfigurationError(f"Config file not found: {config_path}", error_code="CONFIG_004")
    if schema_file is None:
        raise ConfigurationError("--schema is required with --check-live-drift")

    if ctx is not None:
        try:
            shared = ctx.connection()
        except ConfigurationError:
            raise
        except Exception as exc:
            raise ConfigurationError(
                f"Database connection failed: {exc}", error_code="CONFIG_006"
            ) from exc
        return SchemaDriftDetector(shared).compare_with_schema_file(str(schema_file))

    config_data = load_config(config_path)
    try:
        conn = create_connection(config_data)
    except Exception as exc:
        raise ConfigurationError(
            f"Database connection failed: {exc}", error_code="CONFIG_006"
        ) from exc

    try:
        return SchemaDriftDetector(conn).compare_with_schema_file(str(schema_file))
    finally:
        conn.close()
