"""CLI commands for the `confiture generate` subcommand group.

Commands
--------
alloc       Return the next sort-stable filename for a schema subtree.
scaffold    Write SQL files emitted by a pluggable emitter.
renumber    Move a file or subtree and rewrite cross-references.
pgtap       Generate pgTAP test scaffolds for stored functions.
stubs       Generate typed Python wrapper functions for stored procedures.

Usage:
    confiture generate alloc db/schema/functions/catalog/ --verb create
"""

from __future__ import annotations

import importlib
import subprocess
from collections.abc import Callable
from pathlib import Path

import typer
from rich.console import Console

from confiture.cli.error_json import cli_boundary, fail
from confiture.cli.helpers import emit
from confiture.cli.options import database_url_option, output_option
from confiture.core.connection import DatabaseError, connect_url
from confiture.core.git import GitRepository
from confiture.core.pgtap_generator import PgTAPGenerator
from confiture.core.scaffold.emitter import EmittedFunction
from confiture.core.scaffold.orchestrator import ScaffoldOrchestrator
from confiture.core.stub_generator import StubGenerator
from confiture.core.tree_allocator import TreeAllocator
from confiture.core.tree_renumber import TreeRenumber
from confiture.error_codes import FINDINGS
from confiture.exceptions import ConfigurationError, ConfiturError


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
        return GitRepository(resolved if resolved.exists() else Path.cwd()).get_repo_root()
    except (ConfiturError, FileNotFoundError, subprocess.TimeoutExpired):
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
@cli_boundary
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
        fail(ConfigurationError(str(exc)), json_mode=output_json)

    if output_json:
        emit({"path": str(next_path)})
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
    return getattr(module, callable_name)


@generate_app.command("scaffold")
@cli_boundary
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
        fail(ConfigurationError(str(exc)), json_mode=output_json)

    functions: list[EmittedFunction] = factory()

    orchestrator = ScaffoldOrchestrator(
        schema_dir=schema_dir,
        overrides_dir=overrides_dir,
        dry_run=dry_run,
    )
    results = orchestrator.run(functions)

    if output_json:
        emit({"results": [{"path": str(r.path), "action": r.action} for r in results]})
        return

    dry_tag = " [dim](dry run)[/dim]" if dry_run else ""
    for r in results:
        icon = "[yellow]~[/yellow]" if r.action == "skip" else "[green]✓[/green]"
        console.print(f"{icon} {r.action}{dry_tag}: {r.path}")


# ---------------------------------------------------------------------------
# generate renumber
# ---------------------------------------------------------------------------


@generate_app.command("renumber")
@cli_boundary
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
    stem changes.  Exits with code 1 when dangling references remain after
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
        fail(ConfigurationError(str(exc)), json_mode=output_json)

    try:
        result = renumber.execute(plans, dry_run=dry_run, force=force)
    except ValueError as exc:
        fail(ConfigurationError(str(exc)), json_mode=output_json)

    if output_json:
        emit(
            {
                "moves": [{"old": str(p.old_path), "new": str(p.new_path)} for p in result.plans],
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
        # success-signal: the renumber completed and already emitted its full
        # result (incl. dangling_refs); exit 1 flags "completed with unresolved
        # refs" the way diff/lint do. Routing through fail() here would emit a
        # second JSON object after the result.
        raise typer.Exit(FINDINGS)


@generate_app.command("pgtap")
@cli_boundary
def generate_pgtap(
    database_url: str = database_url_option(...),
    schema: str = typer.Option("public", "--schema", "-s", help="Schema to introspect"),
    output: Path | None = output_option(),
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

    try:
        with connect_url(database_url) as conn:
            gen = PgTAPGenerator(
                conn,
                schema=schema,
                name_pattern=include,
                include_volatility=not no_volatility,
                include_return_type=not no_return_type,
            )
            pgtap_file = gen.generate()
    except DatabaseError as e:
        fail(
            ConfigurationError(f"Error connecting to database: {e}", error_code="CONFIG_006"),
            json_mode=False,
        )

    sql = pgtap_file.render()

    if output is None:
        # The artifact itself, raw: Rich wraps at the terminal width and reads
        # `[…]` as markup, which broke the SQL a pipe received.
        typer.echo(sql, nl=False)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(sql)
        console.print(f"[green]pgTAP tests written to {output}[/green]")
        console.print(
            f"[dim]{pgtap_file.function_count} function(s), {len(pgtap_file.tests)} test(s).[/dim]"
        )


@generate_app.command("stubs")
@cli_boundary
def generate_stubs(
    database_url: str = database_url_option(...),
    schema: str = typer.Option("public", "--schema", "-s", help="Schema to introspect"),
    output: Path | None = output_option(),
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

    try:
        with connect_url(database_url) as conn:
            gen = StubGenerator(conn, schema=schema, name_pattern=include)
            stub_file = gen.generate()
    except DatabaseError as e:
        fail(
            ConfigurationError(f"Error connecting to database: {e}", error_code="CONFIG_006"),
            json_mode=False,
        )

    code = stub_file.render(output_format=output_format)

    if output is None:
        typer.echo(code, nl=False)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(code)
        console.print(f"[green]Generated stubs written to {output}[/green]")
        console.print(f"[dim]{len(stub_file.functions)} function(s) exported.[/dim]")
