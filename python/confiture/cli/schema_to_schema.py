"""``confiture migrate schema-to-schema`` — Medium 4 (FDW) CLI.

Wires ``core.schema_to_schema.SchemaToSchemaMigrator`` to a CLI subcommand
group matching docs/guides/04-schema-to-schema.md:
``setup``, ``analyze``, ``migrate``, ``migrate-table``, ``verify``, ``cleanup``.

Each command resolves a ``--source`` and ``--target`` database (env name →
``db/environments/{name}.yaml``, a config path, or a raw DSN), constructs the
migrator, runs the operation, and routes failures through the ``fail()``
boundary. Errors emit the #145 envelope in ``--format json``.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

import typer
import yaml

from confiture.cli.error_json import cli_boundary
from confiture.cli.helpers import connect, console, emit, is_json
from confiture.cli.markup import markup, verbatim
from confiture.cli.options import format_option
from confiture.core import connection as _core_connection
from confiture.core.schema_to_schema import SchemaToSchemaMigrator
from confiture.error_codes import FINDINGS
from confiture.exceptions import ConfigurationError, ConfiturError
from confiture.url_redaction import redact_url

schema_to_schema_app = typer.Typer(
    help="Medium 4: zero-downtime schema migration via Foreign Data Wrapper (FDW).",
    no_args_is_help=True,
)

_SOURCE_OPTION = typer.Option(
    ...,
    "--source",
    help="Source (old) database: env name, config path, or DSN.",
)
_TARGET_OPTION = typer.Option(
    ...,
    "--target",
    help="Target (new) database: env name, config path, or DSN.",
)
_FORMAT_OPTION = format_option("text", "json")


def _resolve_connection(spec: str) -> Any:
    """Open a connection from an env name, a config path, or a raw DSN.

    Resolution order:
      1. Looks like a DSN (``postgres://`` / ``postgresql://``) → connect directly.
      2. A ``.yaml`` path or existing file → ``load_config`` + the CLI connection seam.
      3. Otherwise treat as an environment name → ``db/environments/{name}.yaml``.

    Raises:
        ConfigurationError: the spec can't be resolved or the connection fails.
    """

    try:
        if spec.startswith(("postgres://", "postgresql://")):
            return _core_connection.connect_url(spec)

        candidate = Path(spec)
        if not (spec.endswith(".yaml") or candidate.exists()):
            candidate = Path("db") / "environments" / f"{spec}.yaml"
        if not candidate.exists():
            raise ConfigurationError(
                f"Could not resolve database '{spec}'. Pass an env name "
                f"(db/environments/{spec}.yaml), a config path, or a DSN.",
                error_code="CONFIG_004",
            )
        return connect(_core_connection.load_config(candidate))
    except ConfiturError:
        raise
    except (_core_connection.DatabaseError, OSError) as exc:
        raise ConfigurationError(
            f"Could not connect to '{redact_url(spec)}': {exc}", error_code="CONFIG_006"
        ) from exc


def _parse_inline_mapping(mapping: str) -> dict[str, str]:
    """Parse a ``"a:b,c:d"`` inline column mapping into ``{"a": "b", "c": "d"}``."""
    result: dict[str, str] = {}
    for raw_pair in mapping.split(","):
        pair = raw_pair.strip()
        if not pair:
            continue
        if ":" not in pair:
            raise ConfigurationError(
                f"Invalid --mapping entry {pair!r}; expected 'source_col:target_col'."
            )
        src, dst = pair.split(":", 1)
        result[src.strip()] = dst.strip()
    return result


def _load_mapping_file(path: Path) -> dict[str, dict[str, Any]]:
    """Load the per-table column-mapping YAML (see the schema-to-schema guide)."""

    if not path.exists():
        raise ConfigurationError(f"Mapping file not found: {path}", error_code="CONFIG_004")
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ConfigurationError(f"Mapping file {path} must be a mapping of table entries.")
    return data


def _source_tables(spec: dict[str, dict[str, Any]]) -> dict[str, str]:
    """``{target table: source table}``, as ``migrate`` reads each mapping entry."""
    pairs: dict[str, str] = {}
    for table, entry in spec.items():
        if not isinstance(entry, dict):
            raise ConfigurationError(f"Mapping entry for {table!r} must be a mapping.")
        pairs[entry.get("target_table", table)] = entry.get("source_table", table)
    return pairs


def _migrator(source: str, target: str):

    return SchemaToSchemaMigrator(_resolve_connection(source), _resolve_connection(target))


@schema_to_schema_app.command("setup")
@cli_boundary
def s2s_setup(
    source: str = _SOURCE_OPTION,
    target: str = _TARGET_OPTION,
    skip_import: bool = typer.Option(
        False, "--skip-import", help="Create the FDW server without importing the foreign schema."
    ),
    format_output: str = _FORMAT_OPTION,
) -> None:
    """Set up the Foreign Data Wrapper from target → source.

    Safe to run again: a second run keeps the one server and user mapping and
    re-imports the source's tables, replacing the foreign tables the first run
    imported (never a table of your own).
    """
    json_mode = is_json(format_output)
    m = None
    try:
        m = _migrator(source, target)
        m.setup_fdw(skip_import=skip_import)
        if json_mode:
            emit({"ok": True, "command": "setup", "skip_import": skip_import})
        else:
            console.print("[green]✅ FDW configured[/green] (target → source)")
    finally:
        _close(m)


@schema_to_schema_app.command("analyze")
@cli_boundary
def s2s_analyze(
    source: str = _SOURCE_OPTION,
    target: str = _TARGET_OPTION,
    schema: str = typer.Option(
        "public", "--schema", help="The source's schema to size (default: public)."
    ),
    format_output: str = _FORMAT_OPTION,
) -> None:
    """Size the source's tables and recommend a per-table strategy (FDW vs COPY)."""
    json_mode = is_json(format_output)
    m = None
    try:
        m = _migrator(source, target)
        recommendations = m.analyze_tables(schema=schema)
        if json_mode:
            emit({"command": "analyze", "tables": recommendations})
        else:
            console.print(f"[cyan]Strategy recommendations for schema '{verbatim(schema)}':[/cyan]")
            for table, info in recommendations.items():
                strat = info.get("recommended_strategy", info.get("strategy", "?"))
                rows = info.get("row_count", info.get("rows", "?"))
                console.print(
                    f"  • {verbatim(table)}: [bold]{verbatim(strat)}[/bold] ({verbatim(rows)} rows)"
                )
    finally:
        _close(m)


@schema_to_schema_app.command("migrate")
@cli_boundary
def s2s_migrate(
    source: str = _SOURCE_OPTION,
    target: str = _TARGET_OPTION,
    mapping: Path = typer.Option(
        ..., "--mapping", help="Per-table column-mapping YAML (see the guide)."
    ),
    strategy: str = typer.Option(
        "fdw", "--strategy", help="Migration strategy: fdw or copy (default: fdw)."
    ),
    format_output: str = _FORMAT_OPTION,
) -> None:
    """Migrate every table declared in the column-mapping YAML."""
    json_mode = is_json(format_output)
    m = None
    try:
        if strategy not in ("fdw", "copy"):
            raise ConfigurationError(f"Invalid --strategy {strategy!r}. Use 'fdw' or 'copy'.")
        spec = _load_mapping_file(mapping)
        m = _migrator(source, target)
        results: dict[str, int] = {}
        for table, entry in spec.items():
            if not isinstance(entry, dict):
                raise ConfigurationError(f"Mapping entry for {table!r} must be a mapping.")
            src_table = entry.get("source_table", table)
            dst_table = entry.get("target_table", table)
            columns = entry.get("columns", {})
            fn = m.migrate_table if strategy == "fdw" else m.migrate_table_copy
            results[table] = fn(
                source_table=src_table, target_table=dst_table, column_mapping=columns
            )
        if json_mode:
            emit({"command": "migrate", "strategy": strategy, "migrated": results})
        else:
            for table, rows in results.items():
                console.print(
                    f"  • {verbatim(table)}: [green]{verbatim(rows)}[/green] rows migrated"
                )
            console.print(
                f"[green]✅ Migrated {len(results)} table(s) via {verbatim(strategy)}[/green]"
            )
    finally:
        _close(m)


@schema_to_schema_app.command("migrate-table")
@cli_boundary
def s2s_migrate_table(
    source: str = _SOURCE_OPTION,
    target: str = _TARGET_OPTION,
    source_table: str = typer.Option(..., "--source-table", help="Source table name."),
    target_table: str = typer.Option(..., "--target-table", help="Target table name."),
    mapping: str = typer.Option(
        ..., "--mapping", help="Inline column mapping 'src_col:dst_col,...'."
    ),
    strategy: str = typer.Option("fdw", "--strategy", help="fdw or copy (default: fdw)."),
    format_output: str = _FORMAT_OPTION,
) -> None:
    """Migrate a single table with an inline column mapping."""
    json_mode = is_json(format_output)
    m = None
    try:
        if strategy not in ("fdw", "copy"):
            raise ConfigurationError(f"Invalid --strategy {strategy!r}. Use 'fdw' or 'copy'.")
        column_mapping = _parse_inline_mapping(mapping)
        m = _migrator(source, target)
        fn = m.migrate_table if strategy == "fdw" else m.migrate_table_copy
        rows = fn(
            source_table=source_table, target_table=target_table, column_mapping=column_mapping
        )
        if json_mode:
            emit({"command": "migrate-table", "target_table": target_table, "rows": rows})
        else:
            console.print(
                f"[green]✅ {verbatim(target_table)}: {verbatim(rows)} rows migrated[/green]"
            )
    finally:
        _close(m)


@schema_to_schema_app.command("verify")
@cli_boundary
def s2s_verify(
    source: str = _SOURCE_OPTION,
    target: str = _TARGET_OPTION,
    tables: str | None = typer.Option(
        None,
        "--tables",
        help="Comma-separated target tables to verify (default: every table --mapping maps).",
    ),
    mapping: Path | None = typer.Option(
        None,
        "--mapping",
        help="The column-mapping YAML migrate read: where each target table came from.",
    ),
    source_schema: str = typer.Option("old_schema", "--source-schema"),
    target_schema: str = typer.Option("public", "--target-schema"),
    format_output: str = _FORMAT_OPTION,
) -> None:
    """Verify row-count integrity between source and target (exit 1 on mismatch).

    A table the mapping renames (``source_table: old_users``, ``target_table:
    users``) is counted against its source table; pass the ``--mapping`` file
    ``migrate`` read.
    """
    json_mode = is_json(format_output)
    m = None
    try:
        sources = _source_tables(_load_mapping_file(mapping)) if mapping else {}
        if tables:
            table_list = [t.strip() for t in tables.split(",") if t.strip()]
        elif sources:
            table_list = list(sources)
        else:
            raise ConfigurationError(
                "Nothing to verify: pass --tables, --mapping, or both.",
                error_code="CONFIG_001",
            )
        m = _migrator(source, target)
        report = m.verify_migration(
            tables=table_list,
            source_schema=source_schema,
            target_schema=target_schema,
            source_tables=sources,
        )
        mismatches = [t for t, info in report.items() if not info.get("match", False)]
        if json_mode:
            emit({"command": "verify", "tables": report, "matched": not mismatches})
        else:
            for table, info in report.items():
                ok = info.get("match", False)
                mark = "[green]✓[/green]" if ok else "[red]✗[/red]"
                console.print(
                    f"  {markup(mark)} {verbatim(table)}: source={verbatim(info.get('source_count', '?'))} "
                    f"target={verbatim(info.get('target_count', '?'))}"
                )
            if mismatches:
                console.print(
                    f"[red]❌ Row-count mismatch: {verbatim(', '.join(mismatches))}[/red]"
                )
            else:
                console.print("[green]✅ All tables match[/green]")
        if mismatches:
            raise typer.Exit(FINDINGS)  # success-signal: verification found a mismatch
    finally:
        _close(m)


@schema_to_schema_app.command("cleanup")
@cli_boundary
def s2s_cleanup(
    source: str = _SOURCE_OPTION,
    target: str = _TARGET_OPTION,
    format_output: str = _FORMAT_OPTION,
) -> None:
    """Remove the FDW server + foreign schema from the target after cutover."""
    json_mode = is_json(format_output)
    m = None
    try:
        m = _migrator(source, target)
        m.cleanup_fdw()
        if json_mode:
            emit({"ok": True, "command": "cleanup"})
        else:
            console.print("[green]✅ FDW removed from target[/green]")
    finally:
        _close(m)


def _close(migrator: Any) -> None:
    """Close both connections held by the migrator, ignoring teardown errors."""

    if migrator is None:
        return
    for attr in ("source_connection", "target_connection"):
        conn = getattr(migrator, attr, None)
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.close()
