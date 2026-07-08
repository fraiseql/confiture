"""``migrate validate --check-body-views`` logic.

Detects when a live view's (or materialized view's) definition has drifted from
the committed DDL. Views are not stored verbatim, so both the expected and live
sides are read through the identical ``pg_get_viewdef`` deparser: the expected
side is built into a scratch database (:class:`ExpectedSchemaDB`) and read back
there, the live side is read from the target connection. See
:mod:`confiture.core.view_body_drift`.

Reuses ``_resolve_source_sql`` / ``_ssh_override`` from :mod:`signature_drift`
so the source-resolution and SSH-tunnel behaviour matches ``--check-signatures``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from confiture.core.connection import load_config, open_connection
from confiture.core.validation.signature_drift import _resolve_source_sql, _ssh_override
from confiture.exceptions import ConfigurationError

if TYPE_CHECKING:
    from pathlib import Path

    from confiture.core.view_body_drift import ViewBodyDriftReport


@dataclass
class ViewDriftResult:
    """Outcome of a view body-drift check.

    ``auto_built`` / ``ssh_target`` are progress signals the caller renders as
    text-mode hints; they carry no bearing on the gate decision.
    """

    view_report: ViewBodyDriftReport
    auto_built: bool
    ssh_target: str | None

    @property
    def has_drift(self) -> bool:
        return self.view_report.has_drift


def _config_database_url(config_data: Any) -> str | None:
    if hasattr(config_data, "database_url"):
        return config_data.database_url  # type: ignore[no-any-return]
    if isinstance(config_data, dict):
        return config_data.get("database_url")
    return None


def check_view_drift(
    *,
    config_path: Path,
    schema_file: Path | None,
    schemas: str,
    ssh_via: str | None,
    scratch_url: str | None = None,
) -> ViewDriftResult:
    """Detect view definition drift against the live database.

    The expected views are built into a scratch database on ``scratch_url``
    (default: the live server from the config) and read back through
    ``pg_get_viewdef`` so both sides normalise identically.

    Args:
        config_path: Config file resolving the live database connection.
        schema_file: Explicit source schema SQL; auto-built from DDL if ``None``.
        schemas: Comma-separated DB schema names to scan (e.g. ``"public,catalog"``).
        ssh_via: Optional ``user@host`` SSH tunnel for the *live* connection.
        scratch_url: Writable server on which to build the expected scratch DB.
            Required when ``ssh_via`` is set (the scratch DB cannot be built on a
            remote read-only live server through the tunnel).

    Raises:
        ConfigurationError: config missing, auto-build failed, or ``--ssh`` was
            used without ``--scratch-url``.
    """
    from confiture.core.expected_db import ExpectedSchemaDB
    from confiture.core.live_view_catalog import LiveViewCatalog
    from confiture.core.view_body_drift import ViewBodyDriftDetector

    if not config_path.exists():
        raise ConfigurationError(f"Config file not found: {config_path}", error_code="CONFIG_004")

    config_data = load_config(config_path)
    schema_list = [s.strip() for s in schemas.split(",") if s.strip()]

    source_sql, auto_built = _resolve_source_sql(config_data, schema_file)

    effective_config: Any = config_data
    if ssh_via:
        effective_config = _ssh_override(config_data, ssh_via)
        if scratch_url is None:
            raise ConfigurationError(
                "--check-body-views over --ssh requires --scratch-url: the scratch "
                "database is built on a writable local server, not the remote "
                "read-only live server.",
                resolution_hint="Pass --scratch-url postgresql://localhost/postgres (or a CI server).",
            )

    scratch = scratch_url or _config_database_url(config_data)
    if not scratch:
        raise ConfigurationError(
            "Cannot determine a scratch server URL for building the expected views.",
            resolution_hint="Set database_url in the config or pass --scratch-url.",
        )

    with open_connection(effective_config) as live_conn:
        live_defs = LiveViewCatalog(live_conn).get_view_definitions(schema_list)
        with ExpectedSchemaDB(scratch).from_source(schema_sql=source_sql) as scratch_conn:
            src_defs = LiveViewCatalog(scratch_conn).get_view_definitions(schema_list)
        view_report = ViewBodyDriftDetector().compare(src_defs, live_defs)

    return ViewDriftResult(
        view_report=view_report,
        auto_built=auto_built,
        ssh_target=ssh_via,
    )
