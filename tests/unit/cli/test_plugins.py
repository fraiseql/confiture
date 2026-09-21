"""A distribution extends ``confiture`` through the ``confiture.plugins`` entry-point group.

Each entry point names a callable that receives the root Typer app before the
command tree is built. pgGit's ``branch`` and ``coordinate`` reach the CLI this way
from ``plugins/fraiseql-confiture-pggit/``. A plugin that fails to load costs its
own commands and a warning, never the rest of ``confiture``.
"""

from __future__ import annotations

from importlib.metadata import EntryPoint

import pytest
import typer
from typer.testing import CliRunner

from confiture.cli import plugins
from confiture.cli.plugins import GROUP, load_plugins


def _register_hello(app: typer.Typer) -> None:
    @app.command("hello")
    def hello() -> None:
        typer.echo("hello from a plugin")


def _register_broken(app: typer.Typer) -> None:
    raise RuntimeError("the plugin's own import failed")


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
