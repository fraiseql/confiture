"""CLI commands for the `confiture generate` subcommand group.

Commands
--------
alloc       Return the next sort-stable filename for a schema subtree.
scaffold    Write SQL files emitted by a pluggable emitter.
renumber    Move a file or subtree and rewrite cross-references.
from-branch Generate migrations from a pgGit branch.
preview     Preview what migrations would be generated from a branch.
diff        Show a detailed diff between two pgGit branches.
pgtap       Generate pgTAP test scaffolds for stored functions.
stubs       Generate typed Python wrapper functions for stored procedures.

Usage:
    confiture generate alloc db/schema/functions/catalog/ --verb create
    confiture generate from-branch feature/payments
    confiture generate from-branch feature/payments --combined
    confiture generate preview feature/payments
"""

from __future__ import annotations

import importlib
import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from confiture.core.scaffold.emitter import EmittedFunction
from confiture.core.scaffold.orchestrator import ScaffoldOrchestrator
from confiture.core.tree_allocator import TreeAllocator
from confiture.core.tree_renumber import TreeRenumber


def _detect_repo_root(schema_dir: Path) -> Path | None:
    """Detect the repo root for cross-repo reference scanning.

    Tries ``git rev-parse --show-toplevel`` first.  When that fails (no
    git repo, git not installed), falls back to the canonical layout
    ``<repo>/db/schema/`` — but only if ``schema_dir.parent.name == "db"``.
    Otherwise returns ``None`` to signal "no scannable repo root":
    :class:`TreeRenumber` then skips the cross-repo scan rather than
    walking an unrelated parent directory (e.g. a pytest session dir
    when the test layout is ``tmp_path/schema/`` rather than
    ``tmp_path/db/schema/``).
    """
    resolved = schema_dir.resolve()
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(resolved if resolved.exists() else Path.cwd()),
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if out.returncode == 0:
            top = out.stdout.strip()
            if top:
                return Path(top)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    # Canonical layout fallback only — don't guess outside it.
    if resolved.parent.name == "db":
        return resolved.parent.parent
    return None


# Create Rich console for pretty output
console = Console()

# Create generate subcommand group
generate_app = typer.Typer(
    help="Generate migrations and SQL function tree files",
    no_args_is_help=True,
)


@generate_app.command("alloc")
def alloc_filename(
    target_dir: Path = typer.Argument(
        ...,
        help="Directory in which to allocate the next filename (must be within --schema-dir).",
        exists=False,  # validated manually so we can emit a clean error message
    ),
    schema_dir: Path = typer.Option(
        Path("db/schema"),
        "--schema-dir",
        help="Root of the schema tree (default: db/schema).",
    ),
    verb: str | None = typer.Option(
        None,
        "--verb",
        help="Verb suffix appended after the prefix, e.g. 'create' → '00001_create.sql'.",
    ),
    output_json: bool = typer.Option(
        False,
        "--json",
        help="Emit a JSON object {path: ...} instead of plain text.",
    ),
) -> None:
    """Return the next sort-stable filename for a schema subtree.

    Scans TARGET_DIR for existing ``.sql`` files, auto-detects the
    numbering scheme (decimal or hex) and prefix width, then prints the
    next available filename.

    Examples::

        confiture generate alloc db/schema/functions/catalog/manufacturer/
        confiture generate alloc db/schema/functions/ --verb create
        confiture generate alloc db/schema/functions/ --verb create --json
    """
    try:
        allocator = TreeAllocator(schema_dir)
        next_path = allocator.alloc(target_dir, verb=verb)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    if output_json:
        print(json.dumps({"path": str(next_path)}))
    else:
        typer.echo(str(next_path))


# ---------------------------------------------------------------------------
# generate scaffold
# ---------------------------------------------------------------------------


def _load_emitter_callable(spec: str) -> Callable[[], list[EmittedFunction]]:
    """Load and return an emitter callable from a ``module.path:name`` spec.

    Args:
        spec: Dotted-module path and callable name separated by ``":"``,
            e.g. ``"myproject.generators:emit_crud"``.

    Returns:
        A callable that, when invoked with no arguments, returns a list of
        :class:`~confiture.core.scaffold.emitter.EmittedFunction`.

    Raises:
        ValueError: If *spec* is malformed, the module cannot be imported,
            or the attribute does not exist.
    """
    if ":" not in spec:
        raise ValueError(f"Invalid --from format '{spec}': expected 'module.path:callable_name'")
    module_path, callable_name = spec.rsplit(":", 1)
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise ValueError(f"Cannot import emitter module '{module_path}': {exc}") from exc
    if not hasattr(module, callable_name):
        raise ValueError(f"Module '{module_path}' has no attribute '{callable_name}'")
    return getattr(module, callable_name)  # type: ignore[no-any-return]


@generate_app.command("scaffold")
def scaffold_functions(
    from_spec: str = typer.Option(
        ...,
        "--from",
        help="Emitter callable as 'module.path:callable_name'. Called with no args; "
        "must return list[EmittedFunction].",
    ),
    schema_dir: Path = typer.Option(
        Path("db/schema"),
        "--schema-dir",
        help="Root of the schema tree (default: db/schema).",
    ),
    overrides_dir: Path | None = typer.Option(
        None,
        "--overrides-dir",
        help="Override mirror directory. Files present here are skipped during scaffold.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be written without touching disk.",
    ),
    output_json: bool = typer.Option(
        False,
        "--json",
        help="Emit a JSON object {results: [{path, action}, ...]} instead of plain text.",
    ),
) -> None:
    """Write SQL files produced by a pluggable framework emitter.

    Loads the callable identified by ``--from``, calls it with no arguments
    to obtain a list of :class:`EmittedFunction` objects, allocates
    sort-stable filenames for each, and writes them with a ``-- GENERATED``
    header.  Files with a matching path in ``--overrides-dir`` are skipped.

    Examples::

        confiture generate scaffold --from myproject.gen:emit_crud
        confiture generate scaffold --from myproject.gen:emit_crud --dry-run
        confiture generate scaffold --from myproject.gen:emit_crud --json
    """
    try:
        factory = _load_emitter_callable(from_spec)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    functions: list[EmittedFunction] = factory()

    orchestrator = ScaffoldOrchestrator(
        schema_dir=schema_dir,
        overrides_dir=overrides_dir,
        dry_run=dry_run,
    )
    results = orchestrator.run(functions)

    if output_json:
        print(json.dumps({"results": [{"path": str(r.path), "action": r.action} for r in results]}))
        return

    dry_tag = " [dim](dry run)[/dim]" if dry_run else ""
    for r in results:
        icon = "[yellow]~[/yellow]" if r.action == "skip" else "[green]✓[/green]"
        console.print(f"{icon} {r.action}{dry_tag}: {r.path}")


# ---------------------------------------------------------------------------
# generate renumber
# ---------------------------------------------------------------------------


@generate_app.command("renumber")
def renumber_path(
    old_path: Path = typer.Argument(
        ...,
        help="Source file or directory to move.",
    ),
    new_path: Path = typer.Argument(
        ...,
        help="Target file path or directory. "
        "When a directory is given, the next available prefix is allocated automatically.",
    ),
    schema_dir: Path = typer.Option(
        Path("db/schema"),
        "--schema-dir",
        help="Root of the schema tree (default: db/schema).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would move and what refs would be rewritten, without touching disk.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Proceed even if the old filename is referenced outside the db/ tree "
        "(e.g. by application code that loads SQL files by literal path).",
    ),
    output_json: bool = typer.Option(
        False,
        "--json",
        help="Emit structured JSON output.",
    ),
) -> None:
    """Move a SQL file or subtree and rewrite cross-references.

    Allocates sort-stable filenames at the target, scans the schema tree
    for calls to the moved function(s), and rewrites them when the function
    stem changes.  Exits with code 2 when dangling references remain after
    the rewrite pass (e.g. inside string literals).  Refuses to proceed
    when the old filename is referenced outside the ``db/`` tree (e.g. by
    application code that loads SQL files by literal path) — use
    ``--force`` to override.

    Examples::

        confiture generate renumber db/schema/functions/00001_create_item.sql \\
                                    db/schema/functions/00005_create_item.sql
        confiture generate renumber db/schema/functions/catalog/ \\
                                    db/schema/functions/public/ --dry-run
    """
    repo_root = _detect_repo_root(schema_dir)
    renumber = TreeRenumber(schema_dir, repo_root=repo_root)

    try:
        plans = renumber.build_plans(old_path, new_path)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    try:
        result = renumber.execute(plans, dry_run=dry_run, force=force)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    if output_json:
        print(
            json.dumps(
                {
                    "moves": [
                        {"old": str(p.old_path), "new": str(p.new_path)} for p in result.plans
                    ],
                    "ref_rewrites": [
                        {
                            "file": str(rw.ref_file),
                            "old_name": rw.old_name,
                            "new_name": rw.new_name,
                        }
                        for rw in result.ref_rewrites
                    ],
                    "dangling_refs": [
                        {"file": str(f), "name": name} for f, name in result.dangling_refs
                    ],
                    "cross_repo_refs": [str(p) for p in result.cross_repo_refs],
                }
            )
        )
    else:
        dry_tag = " [dim](dry run)[/dim]" if dry_run else ""
        for plan in result.plans:
            console.print(f"[green]→[/green] move{dry_tag}: {plan.old_path} → {plan.new_path}")
        for rw in result.ref_rewrites:
            if rw.old_name != rw.new_name:
                console.print(
                    f"[cyan]~[/cyan] rewrite{dry_tag}: {rw.ref_file} "
                    f"({rw.old_name} → {rw.new_name})"
                )
            else:
                console.print(f"[dim]ℹ refs:[/dim] {rw.ref_file} calls {rw.old_name}")
        for ref_file, name in result.dangling_refs:
            console.print(
                f"[red]⚠ dangling:[/red] {ref_file} still references '{name}' "
                f"(likely inside a string literal — fix manually)"
            )
        if result.cross_repo_refs:
            console.print("[yellow]⚠ proceeded with --force despite cross-repo refs:[/yellow]")
            for p in result.cross_repo_refs:
                console.print(f"  {p}")

    if result.dangling_refs:
        raise typer.Exit(2)


def _get_generator(config_path: Path):
    """Create a MigrationGenerator from config file.

    Args:
        config_path: Path to environment config file

    Returns:
        Tuple of (MigrationGenerator, Connection)

    Raises:
        typer.Exit: If pgGit is not available
    """
    from confiture.core.connection import create_connection
    from confiture.integrations.pggit import (
        MigrationGenerator,
        PgGitNotAvailableError,
        is_pggit_available,
    )

    # Load config and create connection
    conn = create_connection(config_path)

    # Check if pgGit is available
    if not is_pggit_available(conn):
        console.print("[red]pgGit extension is not installed on this database.[/red]")
        console.print("\n[yellow]To install pgGit:[/yellow]")
        console.print("  CREATE EXTENSION pggit CASCADE;")
        console.print("\n[dim]Note: pgGit is for development databases only.[/dim]")
        conn.close()
        raise typer.Exit(1)

    try:
        generator = MigrationGenerator(conn)
        return generator, conn
    except PgGitNotAvailableError as e:
        console.print(f"[red]{e}[/red]")
        conn.close()
        raise typer.Exit(1) from e


@generate_app.command("from-branch")
def generate_from_branch(
    branch: str = typer.Argument(..., help="Branch name to generate migrations from"),
    base: str = typer.Option(
        "main",
        "--base",
        "-b",
        help="Base branch to compare against (default: main)",
    ),
    output: Path = typer.Option(
        Path("db/migrations"),
        "--output",
        "-o",
        help="Output directory for migration files (default: db/migrations)",
    ),
    combined: bool = typer.Option(
        False,
        "--combined",
        "-c",
        help="Generate single combined migration (default: off)",
    ),
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        help="Configuration file (default: db/environments/local.yaml)",
    ),
) -> None:
    """Generate migrations from a pgGit branch.

    Analyzes commits on BRANCH that aren't in BASE and generates
    Confiture migration files that can be deployed to production.

    Examples:
        confiture generate from-branch feature/payments
        confiture generate from-branch feature/payments --combined
        confiture generate from-branch feature/payments -o db/migrations
        confiture generate from-branch hotfix/bug-123 --base release/1.0
    """
    try:
        generator, conn = _get_generator(config)

        console.print(f"[cyan]Generating migrations from branch '{branch}'...[/cyan]")
        console.print(f"[dim]Base branch: {base}[/dim]\n")

        if combined:
            migration = generator.generate_combined(branch, base, output)
            if migration:
                console.print("[green]Generated combined migration:[/green]")
                console.print(f"  File: {output / f'{migration.version}_{migration.name}.py'}")
                console.print(f"  Changes: {migration.metadata.get('changes_count', 'N/A')}")
            else:
                console.print("[yellow]No changes between branches - nothing to generate.[/yellow]")
        else:
            migrations = generator.generate_from_branch(branch, base, output)
            if migrations:
                console.print(f"[green]Generated {len(migrations)} migration(s):[/green]")
                for m in migrations:
                    console.print(f"  - {m.version}_{m.name}.py")
                console.print(f"\n[dim]Output directory: {output.absolute()}[/dim]")
            else:
                console.print("[yellow]No changes between branches - nothing to generate.[/yellow]")

        conn.close()

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error generating migrations: {e}[/red]")
        raise typer.Exit(1) from e


@generate_app.command("preview")
def preview_generation(
    branch: str = typer.Argument(..., help="Branch name to preview"),
    base: str = typer.Option(
        "main",
        "--base",
        "-b",
        help="Base branch to compare against (default: main)",
    ),
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        help="Configuration file (default: db/environments/local.yaml)",
    ),
) -> None:
    """Preview what migrations would be generated.

    Shows changes without writing any files. Use this to review
    what would be generated before running `generate from-branch`.

    Examples:
        confiture generate preview feature/payments
        confiture generate preview feature/payments --base develop
    """
    try:
        generator, conn = _get_generator(config)

        console.print(f"[cyan]Previewing migrations from '{branch}' vs '{base}'...[/cyan]\n")

        changes = generator.preview(branch, base)

        if not changes:
            console.print("[yellow]No changes between branches.[/yellow]")
            conn.close()
            return

        # Create table
        table = Table(title=f"Changes: {base} → {branch}")
        table.add_column("Operation", style="cyan")
        table.add_column("Type", style="magenta")
        table.add_column("Name", style="white")
        table.add_column("Has DDL", style="dim")

        for change in changes:
            op = change["operation"]
            op_color = {
                "CREATE": "green",
                "ALTER": "yellow",
                "DROP": "red",
            }.get(op, "white")

            has_ddl = "Yes" if change["has_new_ddl"] else "No"

            table.add_row(
                f"[{op_color}]{op}[/{op_color}]",
                change["object_type"],
                change["object_name"],
                has_ddl,
            )

        console.print(table)
        console.print(f"\n[dim]Total changes: {len(changes)}[/dim]")
        console.print(
            "\n[dim]Run 'confiture generate from-branch' to generate migration files.[/dim]"
        )

        conn.close()

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error previewing: {e}[/red]")
        raise typer.Exit(1) from e


@generate_app.command("diff")
def show_diff(
    branch: str = typer.Argument(..., help="Branch name to diff"),
    base: str = typer.Option(
        "main",
        "--base",
        "-b",
        help="Base branch to compare against (default: main)",
    ),
    show_sql: bool = typer.Option(
        False,
        "--show-sql",
        "-s",
        help="Show the actual SQL for each change (default: off)",
    ),
    config: Path = typer.Option(
        Path("db/environments/local.yaml"),
        "--config",
        help="Configuration file (default: db/environments/local.yaml)",
    ),
) -> None:
    """Show detailed diff between branches.

    Similar to preview but can show the actual SQL statements.

    Examples:
        confiture generate diff feature/payments
        confiture generate diff feature/payments --show-sql
    """
    try:
        from confiture.core.connection import create_connection
        from confiture.integrations.pggit import PgGitClient, is_pggit_available

        conn = create_connection(config)

        if not is_pggit_available(conn):
            console.print("[red]pgGit not available.[/red]")
            conn.close()
            raise typer.Exit(1)

        client = PgGitClient(conn)
        diff = client.diff(base, branch)

        if not diff:
            console.print("[yellow]No differences between branches.[/yellow]")
            conn.close()
            return

        console.print(f"[cyan]Diff: {base} → {branch}[/cyan]\n")

        for entry in diff:
            op = entry.operation
            op_color = {"CREATE": "green", "ALTER": "yellow", "DROP": "red"}.get(op, "white")

            console.print(
                f"[{op_color}]{op}[/{op_color}] {entry.object_type} [bold]{entry.object_name}[/bold]"
            )

            if show_sql and entry.new_ddl:
                console.print(
                    f"[dim]  {entry.new_ddl[:200]}{'...' if len(entry.new_ddl) > 200 else ''}[/dim]"
                )

        console.print(f"\n[dim]Total: {len(diff)} change(s)[/dim]")

        conn.close()

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e


@generate_app.command("pgtap")
def generate_pgtap(
    database_url: str = typer.Option(..., "--database-url", "-d", help="PostgreSQL connection URL"),
    schema: str = typer.Option("public", "--schema", "-s", help="Schema to introspect"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Output file path"),
    include: str | None = typer.Option(
        None, "--include", help="SQL LIKE pattern to filter functions"
    ),
    no_volatility: bool = typer.Option(
        False, "--no-volatility", help="Skip volatility tests (default: include)"
    ),
    no_return_type: bool = typer.Option(
        False, "--no-return-type", help="Skip return type tests (default: include)"
    ),
) -> None:
    """Generate pgTAP test scaffolds for PostgreSQL stored functions."""
    import psycopg

    from confiture.core.pgtap_generator import PgTAPGenerator

    try:
        with psycopg.connect(database_url) as conn:
            gen = PgTAPGenerator(
                conn,
                schema=schema,
                name_pattern=include,
                include_volatility=not no_volatility,
                include_return_type=not no_return_type,
            )
            pgtap_file = gen.generate()
    except Exception as e:
        console.print(f"[red]Error connecting to database: {e}[/red]")
        raise typer.Exit(1) from e

    sql = pgtap_file.render()

    if output is None:
        console.print(sql)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(sql)
        console.print(f"[green]pgTAP tests written to {output}[/green]")
        console.print(
            f"[dim]{pgtap_file.function_count} function(s), {len(pgtap_file.tests)} test(s).[/dim]"
        )


@generate_app.command("stubs")
def generate_stubs(
    database_url: str = typer.Option(..., "--database-url", "-d", help="PostgreSQL connection URL"),
    schema: str = typer.Option("public", "--schema", "-s", help="Schema to introspect"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Output file path"),
    output_format: str = typer.Option(
        "pydantic",
        "--format",
        help="Output format: pydantic|dataclass|typeddict",
    ),
    include: str | None = typer.Option(
        None, "--include", help="SQL LIKE pattern to filter functions"
    ),
) -> None:
    """Generate typed Python wrapper functions for stored procedures."""
    import psycopg

    from confiture.core.stub_generator import StubGenerator

    try:
        with psycopg.connect(database_url) as conn:
            gen = StubGenerator(conn, schema=schema, name_pattern=include)
            stub_file = gen.generate()
    except Exception as e:
        console.print(f"[red]Error connecting to database: {e}[/red]")
        raise typer.Exit(1) from e

    code = stub_file.render(output_format=output_format)

    if output is None:
        console.print(code)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(code)
        console.print(f"[green]Generated stubs written to {output}[/green]")
        console.print(f"[dim]{len(stub_file.functions)} function(s) exported.[/dim]")
