"""``migrate validate --check-body-replay`` logic.

Provides the *replay-based* function-body drift signal (#179): rebuild the
expected database deterministically by replaying base + all migrations into a
throwaway scratch DB, then diff ``pg_proc.prosrc`` against live. The difference
is exactly the definitions no migration produced — true out-of-band hot-patches.

Unlike ``--check-body`` (whose expected side is built from source DDL and is thus
dominated by the build-vs-migrate backlog), this path builds the expected side
from ``ExpectedSchemaDB.from_base_plus_migrations()``. Both sides are real
databases introspected identically via :class:`LiveFunctionCatalog`, so the
signature pairing is exact — this sidesteps the text-parse asymmetry class of bug
(#176) entirely.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from typing import TYPE_CHECKING

from confiture.core.connection import load_config, open_connection
from confiture.core.validation.signature_drift import _ssh_override
from confiture.core.validation.view_drift import _config_database_url
from confiture.exceptions import ConfigurationError

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any

    from confiture.core.function_body_drift import FunctionBodyDriftReport
    from confiture.core.validation.context import ValidationContext


@dataclass
class ReplayDriftResult:
    """Outcome of a replay-based body-drift check.

    ``ssh_target`` is a progress signal the caller renders as a text-mode hint.
    """

    body_report: FunctionBodyDriftReport
    ssh_target: str | None

    @property
    def has_drift(self) -> bool:
        return self.body_report.has_drift


def check_replay_drift(
    *,
    config_path: Path,
    migrations_dir: Path,
    schemas: str,
    ssh_via: str | None,
    scratch_url: str | None = None,
    ctx: ValidationContext | None = None,
) -> ReplayDriftResult:
    """Detect function-body drift between live and a fresh migration replay.

    Builds the expected database by replaying every migration in
    ``migrations_dir`` into a scratch DB on ``scratch_url`` (default: the live
    server from the config), then compares live ``prosrc`` against it.

    Args:
        config_path: Config file resolving the live database connection.
        migrations_dir: Directory of migration files to replay.
        schemas: Comma-separated DB schema names to scan (e.g. ``"public,auth"``).
        ssh_via: Optional ``user@host`` SSH tunnel for the *live* connection.
        scratch_url: Writable server on which to replay the migrations. Required
            when ``ssh_via`` is set.
        ctx: Shared per-run resources supplying the config and the *live*
            connection. The scratch database is necessarily its own connection.

    Raises:
        ConfigurationError: config missing, or ``--ssh`` without ``--scratch-url``.
        SchemaError: a migration failed during replay (surfaced, not treated as
            false drift).
    """
    from confiture.core.expected_db import ExpectedSchemaDB
    from confiture.core.function_body_drift import FunctionBodyDriftDetector
    from confiture.core.live_function_catalog import LiveFunctionCatalog

    if not config_path.exists():
        raise ConfigurationError(f"Config file not found: {config_path}", error_code="CONFIG_004")

    config_data = ctx.config_data if ctx is not None else load_config(config_path)
    schema_list = [s.strip() for s in schemas.split(",") if s.strip()]

    effective_config: Any = config_data
    if ssh_via:
        effective_config = _ssh_override(config_data, ssh_via)
        if scratch_url is None:
            raise ConfigurationError(
                "--check-body-replay over --ssh requires --scratch-url: the migrations "
                "are replayed on a writable local server, not the remote read-only live "
                "server.",
                resolution_hint="Pass --scratch-url postgresql://localhost/postgres (or a CI server).",
            )

    scratch = scratch_url or _config_database_url(config_data)
    if not scratch:
        raise ConfigurationError(
            "Cannot determine a scratch server URL for the migration replay.",
            resolution_hint="Set database_url in the config or pass --scratch-url.",
        )

    conn_cm = (
        nullcontext(ctx.connection()) if ctx is not None else open_connection(effective_config)
    )
    with conn_cm as live_conn:
        live_bodies = LiveFunctionCatalog(live_conn).get_bodies(schemas=schema_list)
        with ExpectedSchemaDB(
            scratch, migrations_dir=migrations_dir
        ).from_base_plus_migrations() as scratch_conn:
            replayed_bodies = LiveFunctionCatalog(scratch_conn).get_bodies(schemas=schema_list)
        body_report = FunctionBodyDriftDetector().compare(replayed_bodies, live_bodies)

    return ReplayDriftResult(body_report=body_report, ssh_target=ssh_via)
