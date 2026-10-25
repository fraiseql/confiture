"""``confiture migrate schema-to-schema`` — Medium 4 (FDW) CLI.

Wires ``core.schema_to_schema.SchemaToSchemaMigrator`` to a CLI subcommand
group matching docs/guides/04-schema-to-schema.md:
``setup``, ``analyze``, ``migrate``, ``migrate-table``, ``verify``, ``cleanup``.

Each command resolves a ``--source`` and ``--target`` database (env name →
``db/environments/{name}.yaml``, a config path, or a raw DSN), constructs the
migrator, runs the operation, and routes failures through the ``fail()``
boundary. Errors emit the #145 envelope in ``--format json``.
"""

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import typer
import yaml

from confiture.cli.error_json import cli_boundary
from confiture.cli.helpers import console, emit, is_json
from confiture.cli.markup import markup
from confiture.cli.options import format_option
from confiture.core.connection import open_target, resolve_target
from confiture.core.schema_to_schema import SchemaToSchemaMigrator
from confiture.error_codes import FINDINGS
from confiture.exceptions import ConfigurationError

schema_to_schema_app = typer.Typer(
    help="Medium 4: zero-downtime schema migration via Foreign Data Wrapper (FDW).",
    no_args_is_help=True,
)

_SOURCE_OPTION = typer.Option(
    ...,
    "--source",
    help="Source (old) database: environment name (its ssh_tunnel is used), .yaml config file or URL.",
)
_TARGET_OPTION = typer.Option(
    ...,
    "--target",
    help="Target (new) database: environment name (its ssh_tunnel is used), .yaml config file or URL.",
)
_FORMAT_OPTION = format_option("text", "json")


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


@contextmanager
def _migrator(source: str, target: str) -> Generator[SchemaToSchemaMigrator]:
    """The migrator over both databases, each opened through its tunnel when it has one."""
    with (
        open_target(resolve_target(source, flag="--source")) as source_conn,
        open_target(resolve_target(target, flag="--target")) as target_conn,
    ):
        yield SchemaToSchemaMigrator(source_conn, target_conn)


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
    with _migrator(source, target) as m:
        m.setup_fdw(skip_import=skip_import)
        if json_mode:
            emit({"skip_import": skip_import})
        else:
            console.print("[green]✅ FDW configured[/green] (target → source)")


@schema_to_schema_app.command("analyze")
@cli_boundary
def s2s_analyze(
    source: str = _SOURCE_OPTION,
    target: str = _TARGET_OPTION,
    schema: str = typer.Option("public", "--schema", help="The source's schema to size."),
    format_output: str = _FORMAT_OPTION,
) -> None:
    """Size the source's tables and recommend a per-table strategy (FDW vs COPY)."""
    json_mode = is_json(format_output)
    with _migrator(source, target) as m:
        recommendations = m.analyze_tables(schema=schema)
        if json_mode:
            emit({"tables": recommendations})
        else:
            console.print(t"[cyan]Strategy recommendations for schema '{schema}':[/cyan]")
            for table, info in recommendations.items():
                strat = info.get("recommended_strategy", info.get("strategy", "?"))
                rows = info.get("row_count", info.get("rows", "?"))
                console.print(t"  • {table}: [bold]{strat}[/bold] ({rows} rows)")


@schema_to_schema_app.command("migrate")
@cli_boundary
def s2s_migrate(
    source: str = _SOURCE_OPTION,
    target: str = _TARGET_OPTION,
    mapping: Path = typer.Option(
        ..., "--mapping", help="Per-table column-mapping YAML (see the guide)."
    ),
    strategy: str = typer.Option("fdw", "--strategy", help="Migration strategy: fdw or copy."),
    format_output: str = _FORMAT_OPTION,
) -> None:
    """Migrate every table declared in the column-mapping YAML."""
    json_mode = is_json(format_output)
    if strategy not in ("fdw", "copy"):
        raise ConfigurationError(f"Invalid --strategy {strategy!r}. Use 'fdw' or 'copy'.")
    spec = _load_mapping_file(mapping)
    with _migrator(source, target) as m:
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
            emit({"strategy": strategy, "migrated": results})
        else:
            for table, rows in results.items():
                console.print(t"  • {table}: [green]{rows}[/green] rows migrated")
            console.print(t"[green]✅ Migrated {len(results)} table(s) via {strategy}[/green]")


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
    strategy: str = typer.Option("fdw", "--strategy", help="fdw or copy."),
    format_output: str = _FORMAT_OPTION,
) -> None:
    """Migrate a single table with an inline column mapping."""
    json_mode = is_json(format_output)
    if strategy not in ("fdw", "copy"):
        raise ConfigurationError(f"Invalid --strategy {strategy!r}. Use 'fdw' or 'copy'.")
    column_mapping = _parse_inline_mapping(mapping)
    with _migrator(source, target) as m:
        fn = m.migrate_table if strategy == "fdw" else m.migrate_table_copy
        rows = fn(
            source_table=source_table, target_table=target_table, column_mapping=column_mapping
        )
        if json_mode:
            emit({"target_table": target_table, "rows": rows})
        else:
            console.print(t"[green]✅ {target_table}: {rows} rows migrated[/green]")


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
    with _migrator(source, target) as m:
        report = m.verify_migration(
            tables=table_list,
            source_schema=source_schema,
            target_schema=target_schema,
            source_tables=sources,
        )
        mismatches = [t for t, info in report.items() if not info.get("match", False)]
        if json_mode:
            emit({"tables": report, "matched": not mismatches})
        else:
            for table, info in report.items():
                ok = info.get("match", False)
                mark = "[green]✓[/green]" if ok else "[red]✗[/red]"
                console.print(
                    t"  {markup(mark)} {table}: source={info.get('source_count', '?')} "
                    t"target={info.get('target_count', '?')}"
                )
            if mismatches:
                console.print(t"[red]❌ Row-count mismatch: {', '.join(mismatches)}[/red]")
            else:
                console.print("[green]✅ All tables match[/green]")
        if mismatches:
            raise typer.Exit(FINDINGS)  # success-signal: verification found a mismatch


@schema_to_schema_app.command("cleanup")
@cli_boundary
def s2s_cleanup(
    source: str = _SOURCE_OPTION,
    target: str = _TARGET_OPTION,
    format_output: str = _FORMAT_OPTION,
) -> None:
    """Remove the FDW server + foreign schema from the target after cutover."""
    json_mode = is_json(format_output)
    with _migrator(source, target) as m:
        m.cleanup_fdw()
        if json_mode:
            emit({})
        else:
            console.print("[green]✅ FDW removed from target[/green]")
