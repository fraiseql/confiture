"""``confiture test-db``: provision isolated template/clone test databases.

A CI-path primitive (not the deploy ops-path). Composable subcommands a Dagger /
GitHub Actions / local script calls directly to build a template once and hand
out lock-free per-worker clones.
"""

from __future__ import annotations

from pathlib import Path

import typer

from confiture.cli.error_json import fail
from confiture.cli.helpers import _output_json, console, is_json, redact_url
from confiture.config.environment import Environment
from confiture.core.builder import SchemaBuilder
from confiture.core.test_db import TemplateState, TestDbProvisioner

test_db_app = typer.Typer(
    help="Provision isolated template/clone test databases for parallel CI."
)


def _resolve_server_url(database_url: str | None, env: str, project_dir: Path) -> str:
    """Resolve the PG server URL from --database-url or the environment config."""
    if database_url:
        return database_url
    return Environment.load(env, project_dir).database_url


@test_db_app.command("provision-template")
def provision_template(
    template: str = typer.Option(..., "--template", help="Template database name."),
    env: str = typer.Option("local", "--env", "-e", help="Environment to build."),
    project_dir: Path = typer.Option(Path("."), "--project-dir", help="Project directory."),
    from_artifact: Path = typer.Option(
        None,
        "--from-artifact",
        help="Restore a pg_dump -Fc/-Fd artifact (from 'build --dump') instead of "
        "applying DDL.",
    ),
    seed_profile: str = typer.Option(
        None,
        "--seed-profile",
        help="Apply only the named seed profile (seed.profiles.<name>) on the DDL path.",
    ),
    force: bool = typer.Option(
        False, "--force", help="Replace a same-named database even if not confiture-managed."
    ),
    database_url: str = typer.Option(
        None, "--database-url", help="PG server URL (default: from env config)."
    ),
    format_type: str = typer.Option("text", "--format", "-f", help="text or json."),
) -> None:
    """Build (or restore) a template database and stamp its db/ content hash."""
    try:
        builder = SchemaBuilder(env=env, project_dir=project_dir)
        schema_hash = builder.compute_hash()
        server_url = database_url or builder.env_config.database_url
        provisioner = TestDbProvisioner(server_url)

        if from_artifact is not None:
            status = provisioner.provision_template(
                template, schema_hash=schema_hash, from_artifact=from_artifact, force=force
            )
        else:
            schema_sql = builder.build(schema_only=True)
            _schema_files, seed_files = builder.categorize_sql_files()
            if seed_profile is not None:
                from confiture.core.seed_applier import _apply_profile_filter

                profile_obj = builder.env_config.seed.get_profile(seed_profile)
                seed_files = _apply_profile_filter(seed_files, profile_obj)
            status = provisioner.provision_template(
                template,
                schema_hash=schema_hash,
                schema_sql=schema_sql,
                seed_files=seed_files or None,
                force=force,
            )

        if is_json(format_type):
            _output_json(status.to_dict(), None, console)
        else:
            console.print(
                f"[green]✅ Template '{template}' provisioned ({status.state.value})[/green]"
            )
    except typer.Exit:
        raise
    except Exception as e:  # noqa: BLE001 - routed through the fail() envelope boundary
        fail(e, json_mode=is_json(format_type))


@test_db_app.command("clone")
def clone(
    template: str = typer.Option(..., "--template", help="Source template database."),
    target: str = typer.Option(..., "--target", help="Clone database name to create."),
    env: str = typer.Option("local", "--env", "-e", help="Environment (for server URL)."),
    project_dir: Path = typer.Option(Path("."), "--project-dir", help="Project directory."),
    database_url: str = typer.Option(None, "--database-url", help="PG server URL."),
    format_type: str = typer.Option("text", "--format", "-f", help="text or json."),
) -> None:
    """Clone a template into a fresh database via CREATE DATABASE … WITH TEMPLATE."""
    try:
        provisioner = TestDbProvisioner(_resolve_server_url(database_url, env, project_dir))
        result = provisioner.clone(template, target)
        if is_json(format_type):
            payload = result.to_dict()
            payload["target_url"] = redact_url(payload["target_url"])  # no DSN creds in logs
            _output_json(payload, None, console)
        else:
            console.print(f"[green]✅ Cloned '{template}' → '{target}'[/green]")
    except typer.Exit:
        raise
    except Exception as e:  # noqa: BLE001 - fail() envelope boundary
        fail(e, json_mode=is_json(format_type))


@test_db_app.command("drop")
def drop(
    target: str = typer.Option(..., "--target", help="Database to drop."),
    force: bool = typer.Option(
        False, "--force", help="Drop even if not confiture-managed (use with care)."
    ),
    env: str = typer.Option("local", "--env", "-e", help="Environment (for server URL)."),
    project_dir: Path = typer.Option(Path("."), "--project-dir", help="Project directory."),
    database_url: str = typer.Option(None, "--database-url", help="PG server URL."),
    format_type: str = typer.Option("text", "--format", "-f", help="text or json."),
) -> None:
    """Drop a confiture-managed clone or template (terminating its backends)."""
    try:
        provisioner = TestDbProvisioner(_resolve_server_url(database_url, env, project_dir))
        dropped = provisioner.drop(target, force=force)
        if is_json(format_type):
            _output_json({"target": target, "dropped": dropped}, None, console)
        elif dropped:
            console.print(f"[green]✅ Dropped '{target}'[/green]")
        else:
            console.print(f"[yellow]ℹ '{target}' did not exist[/yellow]")
    except typer.Exit:
        raise
    except Exception as e:  # noqa: BLE001 - fail() envelope boundary
        fail(e, json_mode=is_json(format_type))


@test_db_app.command("status")
def status(
    template: str = typer.Option(..., "--template", help="Template database name."),
    env: str = typer.Option("local", "--env", "-e", help="Environment to hash."),
    project_dir: Path = typer.Option(Path("."), "--project-dir", help="Project directory."),
    database_url: str = typer.Option(None, "--database-url", help="PG server URL."),
    format_type: str = typer.Option("text", "--format", "-f", help="text or json."),
) -> None:
    """Report template staleness vs the current db/ hash (exit 0 current, 1 stale/absent)."""
    try:
        builder = SchemaBuilder(env=env, project_dir=project_dir)
        current_hash = builder.compute_hash()
        server_url = database_url or builder.env_config.database_url
        provisioner = TestDbProvisioner(server_url)
        result = provisioner.template_status(template, current_hash)

        if is_json(format_type):
            _output_json(result.to_dict(), None, console)
        else:
            console.print(f"Template '{template}': [bold]{result.state.value}[/bold]")

        if result.state is not TemplateState.CURRENT:
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:  # noqa: BLE001 - fail() envelope boundary
        fail(e, json_mode=is_json(format_type))


@test_db_app.command("list")
def list_databases(
    env: str = typer.Option("local", "--env", "-e", help="Environment (for server URL)."),
    project_dir: Path = typer.Option(Path("."), "--project-dir", help="Project directory."),
    database_url: str = typer.Option(None, "--database-url", help="PG server URL."),
    format_type: str = typer.Option("text", "--format", "-f", help="text or json."),
) -> None:
    """List confiture-managed templates and clones on the server."""
    try:
        provisioner = TestDbProvisioner(_resolve_server_url(database_url, env, project_dir))
        databases = provisioner.list_databases()
        if is_json(format_type):
            _output_json({"databases": [d.to_dict() for d in databases]}, None, console)
        elif databases:
            for db in databases:
                console.print(f"  {db.kind:9} {db.name}  ({db.detail})")
        else:
            console.print("[yellow]ℹ No confiture-managed databases found[/yellow]")
    except typer.Exit:
        raise
    except Exception as e:  # noqa: BLE001 - fail() envelope boundary
        fail(e, json_mode=is_json(format_type))


@test_db_app.command("prune")
def prune(
    template: str = typer.Option(..., "--template", help="Template whose clones to drop."),
    env: str = typer.Option("local", "--env", "-e", help="Environment (for server URL)."),
    project_dir: Path = typer.Option(Path("."), "--project-dir", help="Project directory."),
    database_url: str = typer.Option(None, "--database-url", help="PG server URL."),
    format_type: str = typer.Option("text", "--format", "-f", help="text or json."),
) -> None:
    """Drop every clone of a template (reaps clones leaked by crashed workers)."""
    try:
        provisioner = TestDbProvisioner(_resolve_server_url(database_url, env, project_dir))
        dropped = provisioner.prune(template)
        if is_json(format_type):
            _output_json({"template": template, "dropped": dropped}, None, console)
        else:
            console.print(f"[green]✅ Pruned {len(dropped)} clone(s) of '{template}'[/green]")
    except typer.Exit:
        raise
    except Exception as e:  # noqa: BLE001 - fail() envelope boundary
        fail(e, json_mode=is_json(format_type))
