"""A distribution extends ``confiture`` through the ``confiture.plugins`` entry-point group.

Each entry point names a callable that receives the root Typer app before the
command tree is built. pgGit's ``branch`` and ``coordinate`` reach the CLI this way
from ``plugins/fraiseql-confiture-pggit/``, and its ``from-branch`` joins
``confiture generate``. A plugin that fails to load costs its own commands and a
warning, never the rest of ``confiture``; a name ``confiture`` already has stays
``confiture``'s, and the plugin is told so.
"""

from __future__ import annotations

import copy
from importlib.metadata import EntryPoint

import pytest
import typer
from typer.main import get_command
from typer.testing import CliRunner

from confiture.cli import main, plugins
from confiture.cli.commands.build import build as confiture_build
from confiture.cli.generate import alloc_filename
from confiture.cli.plugins import GROUP, load_plugins


def _register_hello(app: typer.Typer) -> None:
    @app.command("hello")
    def hello() -> None:
        typer.echo("hello from a plugin")


def _register_broken(app: typer.Typer) -> None:
    raise RuntimeError("the plugin's own import failed")


def _register_clashing(app: typer.Typer) -> None:
    """A group, a command and a command over a group, each named like one confiture ships."""
    migrate = typer.Typer()

    @migrate.command("up")
    def up() -> None:
        typer.echo("the plugin's migrate up")

    app.add_typer(migrate, name="migrate")

    @app.command("build")
    def build() -> None:
        typer.echo("the plugin's build")

    @app.command("seed")
    def seed() -> None:
        typer.echo("the plugin's seed")

    @app.command("extra")
    def extra() -> None:
        typer.echo("the plugin's own name")


def _register_callback(app: typer.Typer) -> None:
    @app.callback()
    def options() -> None:
        """The plugin's options for every command."""


def _register_exit(app: typer.Typer) -> None:
    raise SystemExit(3)


def _register_interrupted(app: typer.Typer) -> None:
    raise KeyboardInterrupt


def _register_half_then_fail(app: typer.Typer) -> None:
    _register_hello(app)
    raise RuntimeError("failed after its first command")


def _register_into_generate(app: typer.Typer) -> None:
    """pgGit's shape: new subcommands in a group confiture ships, and one that is not new."""
    (generate,) = [g.typer_instance for g in app.registered_groups if g.name == "generate"]
    assert generate is not None

    @generate.command("from-branch")
    def from_branch() -> None:
        typer.echo("a migration from a branch")

    @generate.command("alloc")
    def alloc() -> None:
        typer.echo("the plugin's alloc")


def _confiture_app() -> typer.Typer:
    """confiture's own command tree, copied so a plugin's registrations stay in this test."""
    return copy.deepcopy(main.app)


def _app() -> typer.Typer:
    app = typer.Typer()

    @app.command("builtin")
    def builtin() -> None:
        typer.echo("built in")

    return app


def _installed(monkeypatch: pytest.MonkeyPatch, *points: tuple[str, str]) -> None:
    found = [EntryPoint(name=name, value=value, group=GROUP) for name, value in points]
    monkeypatch.setattr(plugins, "entry_points", lambda *, group: found if group == GROUP else [])


def test_the_group_is_confiture_plugins() -> None:
    assert GROUP == "confiture.plugins"


def test_a_plugin_adds_its_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    _installed(monkeypatch, ("hello", f"{__name__}:_register_hello"))
    app = _app()

    assert load_plugins(app) == ["hello"]
    result = CliRunner().invoke(app, ["hello"])

    assert result.output.strip() == "hello from a plugin"


def test_a_plugin_that_fails_is_named_and_the_rest_still_runs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _installed(
        monkeypatch,
        ("broken", f"{__name__}:_register_broken"),
        ("hello", f"{__name__}:_register_hello"),
    )
    app = _app()

    assert load_plugins(app) == ["hello"]

    warning = capsys.readouterr().err
    assert "broken" in warning
    assert "the plugin's own import failed" in warning
    assert CliRunner().invoke(app, ["builtin"]).output.strip() == "built in"


def test_the_cli_loads_the_group(monkeypatch: pytest.MonkeyPatch) -> None:
    """``cli.main`` asks for the group; with nothing installed it adds nothing."""
    asked: list[str] = []
    monkeypatch.setattr(plugins, "entry_points", lambda *, group: asked.append(group) or [])

    assert load_plugins(_app()) == []
    assert asked == [GROUP]


def test_plugin_cannot_replace_a_builtin_name(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _installed(
        monkeypatch,
        ("clash", f"{__name__}:_register_clashing"),
        ("exits", f"{__name__}:_register_exit"),
    )
    app = _confiture_app()

    assert load_plugins(app) == ["clash"]

    tree = get_command(app).commands
    assert {"status", "up", "validate"} <= set(tree["migrate"].commands)
    assert tree["build"].callback.__wrapped__ is confiture_build
    assert {"validate", "apply"} <= set(tree["seed"].commands)
    assert "extra" in tree
    lines = capsys.readouterr().err.splitlines()
    for name in ("migrate", "build", "seed"):
        assert any("'clash'" in line and f"'confiture {name}'" in line for line in lines), name
    assert any("'exits'" in line for line in lines)


def test_a_plugin_adds_to_a_builtin_group_but_cannot_replace_its_commands(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _installed(monkeypatch, ("into", f"{__name__}:_register_into_generate"))
    app = _confiture_app()

    assert load_plugins(app) == ["into"]

    generate = get_command(app).commands["generate"].commands
    assert "from-branch" in generate
    assert generate["alloc"].callback.__wrapped__ is alloc_filename
    assert "'confiture generate alloc'" in capsys.readouterr().err


def test_a_plugin_that_fails_leaves_nothing_behind(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _installed(monkeypatch, ("half", f"{__name__}:_register_half_then_fail"))
    app = _confiture_app()

    assert load_plugins(app) == []

    assert "hello" not in get_command(app).commands
    assert "failed after its first command" in capsys.readouterr().err


def test_an_interrupt_is_not_a_plugin_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _installed(monkeypatch, ("interrupted", f"{__name__}:_register_interrupted"))

    with pytest.raises(KeyboardInterrupt):
        load_plugins(_app())


def test_a_plugin_cannot_replace_confiture_s_own_options(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _installed(monkeypatch, ("options", f"{__name__}:_register_callback"))
    app = _confiture_app()

    load_plugins(app)

    assert app.registered_callback is not None
    assert app.registered_callback.callback is main.main
    assert "'options'" in capsys.readouterr().err
