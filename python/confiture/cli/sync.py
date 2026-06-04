"""``confiture sync`` — Medium 3 (Production Data Sync) CLI.

Wires the previously-orphaned ``core.syncer.ProductionSyncer`` to a top-level
``confiture sync`` command matching ``docs/guides/03-production-sync.md``: copy
data from a production database to a local/staging target, optionally masking
PII on the way.

``--from`` / ``--to`` each resolve a database from an **environment name**
(``db/environments/{name}.yaml``) or a raw **DSN** (``postgresql://…``).
Anonymization is **opt-in** via ``--anonymize``, driven by a YAML config
(``db/sync/anonymization.yaml`` by default) of the documented shape::

    users:
      - column: email
        strategy: email
        seed: 12345
      - column: ssn
        strategy: redact

Failures route through the ``fail()`` boundary (the #145 ``{ok: false, error}``
envelope in ``--format json``).

Safety posture (owner decision Q3 = *warn*): without ``--anonymize`` the sync
copies data verbatim, so a prominent warning is emitted — real PII would land
**unmasked** in the target. Anonymization stays opt-in to match the published
guide's "Basic sync"; the warning makes the risk legible (text → stderr, JSON →
the ``warnings`` array).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from confiture.cli.error_json import fail
from confiture.cli.helpers import console, error_console, is_json
from confiture.exceptions import ConfigurationError, ConfiturError

if TYPE_CHECKING:
    from confiture.config.environment import DatabaseConfig
    from confiture.core.syncer import AnonymizationRule, ProductionSyncer

_DEFAULT_ANON_CONFIG = Path("db/sync/anonymization.yaml")

_PLAINTEXT_WARNING = (
    "Anonymization is OFF — data is copied verbatim. Real PII would land "
    "UNMASKED in the target. Pass --anonymize (with db/sync/anonymization.yaml) "
    "to mask it."
)


def _resolve_database(spec: str) -> DatabaseConfig:
    """Resolve a ``--from``/``--to`` spec to a :class:`DatabaseConfig`.

    - A DSN (``postgres://`` / ``postgresql://``) → ``DatabaseConfig.from_url``.
    - Otherwise an environment name → ``db/environments/{name}.yaml``.

    Raises:
        ConfigurationError: the DSN is malformed (``CONFIG_003``) or the
            environment config cannot be found (``Environment.load`` →
            ``CONFIG_001``).
    """
    from confiture.config.environment import DatabaseConfig, Environment

    if spec.startswith(("postgres://", "postgresql://")):
        try:
            return DatabaseConfig.from_url(spec)
        except ValueError as exc:
            raise ConfigurationError(
                f"Invalid database DSN: {spec}", error_code="CONFIG_003"
            ) from exc
    return Environment.load(spec).database


def _load_anonymization(path: Path) -> dict[str, list[AnonymizationRule]]:
    """Load the anonymization YAML into ``{table: [AnonymizationRule, …]}``.

    The shape matches ``docs/guides/03-production-sync.md``: a mapping of table
    name → list of ``{column, strategy, seed?}`` rules.

    Raises:
        ConfigurationError: the file is missing (``CONFIG_004``) or malformed.
    """
    import yaml

    from confiture.core.syncer import AnonymizationRule

    if not path.exists():
        raise ConfigurationError(
            f"Anonymization config not found: {path}",
            error_code="CONFIG_004",
            resolution_hint=(
                "Create a YAML file mapping each table to a list of "
                "{column, strategy, seed} rules, or drop --anonymize to copy "
                "data verbatim."
            ),
        )
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ConfigurationError(
            f"Anonymization config {path} must map table names to rule lists.",
            error_code="CONFIG_002",
        )
    rules: dict[str, list[AnonymizationRule]] = {}
    for table, entries in data.items():
        if not isinstance(entries, list):
            raise ConfigurationError(
                f"Anonymization rules for {table!r} must be a list of rules.",
                error_code="CONFIG_002",
            )
        parsed: list[AnonymizationRule] = []
        for entry in entries:
            if not isinstance(entry, dict) or "column" not in entry or "strategy" not in entry:
                raise ConfigurationError(
                    f"Each rule for {table!r} needs 'column' and 'strategy' keys.",
                    error_code="CONFIG_002",
                )
            parsed.append(
                AnonymizationRule(
                    column=entry["column"],
                    strategy=entry["strategy"],
                    seed=entry.get("seed"),
                )
            )
        rules[table] = parsed
    return rules


def _build_syncer(source: DatabaseConfig, target: DatabaseConfig) -> ProductionSyncer:
    """Factory seam (patched in tests) → a ``ProductionSyncer`` over both configs."""
    from confiture.core.syncer import ProductionSyncer

    return ProductionSyncer(source, target)


def _split_csv(value: str | None) -> list[str] | None:
    """Split a comma-separated option into a clean list, or ``None`` if empty."""
    if not value:
        return None
    items = [v.strip() for v in value.split(",") if v.strip()]
    return items or None


def sync(
    from_: str = typer.Option(..., "--from", help="Source database: env name or DSN."),
    to: str = typer.Option(..., "--to", help="Target database: env name or DSN."),
    anonymize: bool = typer.Option(
        False, "--anonymize", help="Mask PII during the copy (see --anonymization-config)."
    ),
    anonymization_config: Path = typer.Option(
        _DEFAULT_ANON_CONFIG,
        "--anonymization-config",
        help="Anonymization rules YAML (default: db/sync/anonymization.yaml).",
    ),
    tables: str | None = typer.Option(
        None, "--tables", help="Comma-separated tables to include (default: all)."
    ),
    exclude: str | None = typer.Option(
        None, "--exclude", help="Comma-separated tables to exclude."
    ),
    batch_size: int = typer.Option(
        5000, "--batch-size", help="Rows per batch for anonymized inserts."
    ),
    checkpoint: Path | None = typer.Option(
        None, "--checkpoint", help="Checkpoint file for resumable syncs."
    ),
    resume: bool = typer.Option(
        False, "--resume", help="Resume from --checkpoint, skipping completed tables."
    ),
    format_output: str = typer.Option(
        "text", "--format", "-f", help="Output format: text or json."
    ),
) -> None:
    """Copy data from a production database to a local/staging target (Medium 3).

    Without ``--anonymize`` the copy is verbatim (a plaintext-PII warning is
    emitted). Add ``--anonymize`` to apply the rules in
    ``db/sync/anonymization.yaml``.
    """
    json_mode = is_json(format_output)
    try:
        from confiture.core.syncer import SyncConfig, TableSelection

        source = _resolve_database(from_)
        target = _resolve_database(to)

        anonymization: dict[str, list[AnonymizationRule]] | None = None
        warnings: list[str] = []
        if anonymize:
            anonymization = _load_anonymization(anonymization_config)
        else:
            warnings.append(_PLAINTEXT_WARNING)
            if not json_mode:
                error_console.print(f"[yellow]⚠️  {_PLAINTEXT_WARNING}[/yellow]")

        config = SyncConfig(
            tables=TableSelection(include=_split_csv(tables), exclude=_split_csv(exclude)),
            anonymization=anonymization,
            batch_size=batch_size,
            resume=resume,
            show_progress=not json_mode,
            checkpoint_file=checkpoint,
        )

        with _build_syncer(source, target) as active:
            results = active.sync(config)

        total = sum(results.values())
        if json_mode:
            print(
                json.dumps(
                    {
                        "ok": True,
                        "command": "sync",
                        "anonymized": anonymize,
                        "tables": results,
                        "total_rows": total,
                        "warnings": warnings,
                    }
                )
            )
        else:
            for table, rows in results.items():
                console.print(f"  • {table}: [green]{rows}[/green] rows")
            mode = "anonymized" if anonymize else "verbatim"
            console.print(
                f"[green]✅ Synced {len(results)} table(s), {total} rows ({mode})[/green]"
            )
    except ConfiturError as e:
        fail(e, json_mode=json_mode)
    except Exception as e:
        fail(e, json_mode=json_mode)
