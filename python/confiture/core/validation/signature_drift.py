"""``migrate validate --check-signatures`` (+ ``--check-body``) logic.

Compares function signatures (and optionally bodies) declared in the source
schema against the live database, detecting stale overloads left behind by
``CREATE OR REPLACE`` with changed parameter types.

``load_config`` / ``open_connection`` are imported at module scope so tests can
patch them on this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from confiture.core.connection import load_config, open_connection
from confiture.exceptions import ConfigurationError

if TYPE_CHECKING:
    from confiture.core.function_body_drift import FunctionBodyDriftReport
    from confiture.core.function_signature_drift import FunctionSignatureDriftReport


@dataclass
class SignatureDriftResult:
    """Outcome of a signature (and optional body) drift check.

    ``auto_built`` / ``ssh_target`` are progress signals the caller renders as
    text-mode hints; they carry no bearing on the gate decision.
    """

    drift_report: FunctionSignatureDriftReport
    body_report: FunctionBodyDriftReport | None
    auto_built: bool
    ssh_target: str | None

    @property
    def has_any_drift(self) -> bool:
        return self.drift_report.has_critical_drift or (
            self.body_report is not None and self.body_report.has_drift
        )


def _ssh_override(config_data: Any, ssh_via: str) -> Any:
    """Layer an ssh_tunnel onto *config_data* from a ``user@host`` / ``host`` spec."""
    from confiture.config.environment import SshTunnelConfig

    parts = ssh_via.split("@", 1)
    ssh_host = parts[1] if len(parts) == 2 else parts[0]
    ssh_user = parts[0] if len(parts) == 2 else None

    class _SshOverride:  # noqa: N801
        """Thin adapter that layers an ssh_tunnel onto config_data."""

        def __init__(self, base: Any, tunnel: SshTunnelConfig) -> None:
            self._base = base
            self.ssh_tunnel = tunnel

        @property
        def database_url(self) -> str:
            if hasattr(self._base, "database_url"):
                return self._base.database_url  # type: ignore[no-any-return]
            return self._base.get("database_url", "")

        def get(self, key: str, default: Any = None) -> Any:  # noqa: ANN401
            return getattr(self._base, key, None) or (
                self._base.get(key, default) if isinstance(self._base, dict) else default
            )

    return _SshOverride(config_data, SshTunnelConfig(host=ssh_host, user=ssh_user))


def _resolve_source_sql(
    config_data: Any, schema_file: Path | None
) -> tuple[str, bool]:
    """Return ``(source_sql, auto_built)`` from an explicit file or a fresh build.

    Raises:
        ConfigurationError: ``--schema`` was omitted and the auto-build failed.
    """
    if schema_file is not None:
        return schema_file.read_text(), False

    try:
        from confiture.core.builder import SchemaBuilder

        env_name = (
            config_data.get("name")
            if isinstance(config_data, dict)
            else getattr(config_data, "name", None)
        )
        if not env_name:
            raise ValueError(
                "Config has no 'name' field — cannot auto-build schema. "
                "Pass --schema explicitly."
            )
        return SchemaBuilder(env=env_name).build(schema_only=True), True
    except Exception as build_exc:
        raise ConfigurationError(
            f"--schema not provided and auto-build failed: {build_exc}. "
            "Either run 'confiture build' first or pass --schema explicitly."
        ) from build_exc


def check_signature_drift(
    *,
    config_path: Path,
    schema_file: Path | None,
    schemas: str,
    check_body: bool,
    ssh_via: str | None,
) -> SignatureDriftResult:
    """Detect signature (and optional body) drift against the live database.

    Args:
        config_path: Config file resolving the database connection.
        schema_file: Explicit source schema SQL; auto-built from DDL if ``None``.
        schemas: Comma-separated DB schema names to scan (e.g. ``"public,auth"``).
        check_body: Also compare function bodies (heavier).
        ssh_via: Optional ``user@host`` SSH tunnel target overriding the config.

    Raises:
        ConfigurationError: config missing, auto-build failed, or connection failed.
    """
    from confiture.core.function_signature_drift import FunctionSignatureDriftDetector
    from confiture.core.function_signature_parser import FunctionSignatureParser
    from confiture.core.live_function_catalog import LiveFunctionCatalog

    if not config_path.exists():
        raise ConfigurationError(
            f"Config file not found: {config_path}", error_code="CONFIG_004"
        )

    config_data = load_config(config_path)
    schema_list = [s.strip() for s in schemas.split(",") if s.strip()]

    source_sql, auto_built = _resolve_source_sql(config_data, schema_file)
    source_sigs = FunctionSignatureParser().parse(source_sql)

    effective_config: Any = config_data
    if ssh_via:
        effective_config = _ssh_override(config_data, ssh_via)

    with open_connection(effective_config) as conn:
        live_catalog = LiveFunctionCatalog(conn)
        live_sigs = live_catalog.get_signatures(schemas=schema_list)
        drift_report = FunctionSignatureDriftDetector().compare(
            source_sigs, live_sigs, schemas_checked=schema_list
        )

        body_report = None
        if check_body:
            from confiture.core.function_body_drift import FunctionBodyDriftDetector

            source_with_bodies = FunctionSignatureParser().parse_with_bodies(source_sql)
            source_bodies: dict[str, str | None] = {
                sig.signature_key(): body for sig, body in source_with_bodies
            }
            live_bodies = live_catalog.get_bodies(
                schemas=schema_list, sig_keys=set(source_bodies)
            )
            body_report = FunctionBodyDriftDetector().compare(source_bodies, live_bodies)

    return SignatureDriftResult(
        drift_report=drift_report,
        body_report=body_report,
        auto_built=auto_built,
        ssh_target=ssh_via,
    )
