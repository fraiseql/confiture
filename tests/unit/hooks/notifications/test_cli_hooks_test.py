"""Tests for ``confiture hooks test`` — Phase 03 Cycle 8.

Pins:

- Default to ``--dry-run`` (swap the configured transport for
  :class:`StdoutTransport`, never call the real service).
- ``--id`` is required when more than one hook is configured.
- ``--no-dry-run`` is the only switch that lets the command call the real
  transport.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from typer.testing import CliRunner

from confiture.cli.main import app


def _write_env_yaml(tmp_path: Path, body: str) -> Path:
    """Drop a minimal environment YAML into ``tmp_path/db/environments/test.yaml``.

    Returns the path so callers can pass it through ``--config``.
    """
    env_dir = tmp_path / "db" / "environments"
    env_dir.mkdir(parents=True)
    schema_dir = tmp_path / "db" / "schema"
    schema_dir.mkdir(parents=True)
    (schema_dir / "00_dummy.sql").write_text("-- empty\n")
    cfg = env_dir / "test.yaml"
    cfg.write_text(body)
    return cfg


# ---------------------------------------------------------------------------
# Default --dry-run path.
# ---------------------------------------------------------------------------


class TestDryRunDefault:
    """``confiture hooks test`` defaults to dry-run."""

    def test_dry_run_default_uses_stdout_transport(self, tmp_path: Path) -> None:
        """When only one hook is configured and no flags are passed, the
        command swaps the real transport for ``StdoutTransport`` and prints
        the rendered payload to stdout."""
        cfg = _write_env_yaml(
            tmp_path,
            dedent(
                """\
                name: test
                database_url: postgresql://localhost/x
                include_dirs:
                  - db/schema
                notifications:
                  hooks:
                    - id: prod-slack
                      phase: after_execute
                      transport:
                        type: http
                        url: https://hooks.example.com/should-not-be-called
                      renderer:
                        type: raw_json
                """
            ),
        )
        runner = CliRunner()
        result = runner.invoke(app, ["hooks", "test", "--config", str(cfg)])
        assert result.exit_code == 0, result.output
        # RawJsonRenderer's canonical event field.
        assert "migration_completed" in result.output

    def test_dry_run_does_not_call_real_http_transport(self, tmp_path: Path, monkeypatch) -> None:
        """The HTTP transport's ``send`` method must never be reached in
        the default (dry-run) path."""
        from confiture.core.hooks.notifications import transport as tx_module

        called: list[bool] = []

        def _fail_send(self, payload):  # noqa: ANN001, ARG001
            called.append(True)
            raise AssertionError(
                "HttpTransport.send was called in dry-run mode — the CLI "
                "should have swapped the transport for StdoutTransport."
            )

        monkeypatch.setattr(tx_module.HttpTransport, "send", _fail_send)

        cfg = _write_env_yaml(
            tmp_path,
            dedent(
                """\
                name: test
                database_url: postgresql://localhost/x
                include_dirs:
                  - db/schema
                notifications:
                  hooks:
                    - id: only-one
                      transport:
                        type: http
                        url: https://example.com/x
                      renderer:
                        type: raw_json
                """
            ),
        )
        runner = CliRunner()
        result = runner.invoke(app, ["hooks", "test", "--config", str(cfg)])
        assert result.exit_code == 0, result.output
        assert called == [], "HttpTransport.send must not be invoked in dry-run"


# ---------------------------------------------------------------------------
# --id required when multiple hooks configured.
# ---------------------------------------------------------------------------


class TestIdSelection:
    """The user must disambiguate when multiple hooks are configured."""

    def test_id_required_when_multiple_hooks(self, tmp_path: Path) -> None:
        cfg = _write_env_yaml(
            tmp_path,
            dedent(
                """\
                name: test
                database_url: postgresql://localhost/x
                include_dirs:
                  - db/schema
                notifications:
                  hooks:
                    - id: prod-slack
                      transport: {type: stdout}
                      renderer: {type: slack}
                    - id: oncall-pagerduty
                      transport: {type: http, url: https://events.pagerduty.com/x}
                      renderer:
                        type: pagerduty
                        routing_key: r
                        service_name: s
                """
            ),
        )
        runner = CliRunner()
        result = runner.invoke(app, ["hooks", "test", "--config", str(cfg)])
        assert result.exit_code != 0
        assert "multiple" in result.output.lower() or "--id" in result.output

    def test_id_selects_specific_hook(self, tmp_path: Path) -> None:
        cfg = _write_env_yaml(
            tmp_path,
            dedent(
                """\
                name: test
                database_url: postgresql://localhost/x
                include_dirs:
                  - db/schema
                notifications:
                  hooks:
                    - id: prod-slack
                      transport: {type: stdout}
                      renderer: {type: slack}
                    - id: dev-raw
                      transport: {type: stdout}
                      renderer: {type: raw_json}
                """
            ),
        )
        runner = CliRunner()
        result = runner.invoke(app, ["hooks", "test", "--config", str(cfg), "--id", "dev-raw"])
        assert result.exit_code == 0, result.output
        assert "migration_completed" in result.output

    def test_unknown_id_errors(self, tmp_path: Path) -> None:
        cfg = _write_env_yaml(
            tmp_path,
            dedent(
                """\
                name: test
                database_url: postgresql://localhost/x
                include_dirs:
                  - db/schema
                notifications:
                  hooks:
                    - id: prod-slack
                      transport: {type: stdout}
                      renderer: {type: slack}
                """
            ),
        )
        runner = CliRunner()
        result = runner.invoke(
            app, ["hooks", "test", "--config", str(cfg), "--id", "does-not-exist"]
        )
        assert result.exit_code != 0
        assert "does-not-exist" in result.output


# ---------------------------------------------------------------------------
# --no-dry-run gates real transport calls.
# ---------------------------------------------------------------------------


class TestNoDryRunFlag:
    """Only ``--no-dry-run`` lets the command call the real transport."""

    def test_no_dry_run_invokes_real_transport(self, tmp_path: Path, monkeypatch) -> None:
        """With ``--no-dry-run`` the real ``HttpTransport.send`` is called."""
        from confiture.core.hooks.notifications import transport as tx_module

        called: list[str] = []

        def _record_send(self, payload):  # noqa: ANN001, ARG001
            called.append(self.url)

        monkeypatch.setattr(tx_module.HttpTransport, "send", _record_send)

        cfg = _write_env_yaml(
            tmp_path,
            dedent(
                """\
                name: test
                database_url: postgresql://localhost/x
                include_dirs:
                  - db/schema
                notifications:
                  hooks:
                    - id: only-one
                      transport:
                        type: http
                        url: https://example.com/real
                      renderer:
                        type: raw_json
                """
            ),
        )
        runner = CliRunner()
        result = runner.invoke(app, ["hooks", "test", "--config", str(cfg), "--no-dry-run"])
        assert result.exit_code == 0, result.output
        assert called == ["https://example.com/real"]


# ---------------------------------------------------------------------------
# Empty / missing config — friendly errors.
# ---------------------------------------------------------------------------


class TestEmptyConfig:
    """Friendly error when no hooks are configured."""

    def test_no_notifications_section_errors_cleanly(self, tmp_path: Path) -> None:
        cfg = _write_env_yaml(
            tmp_path,
            dedent(
                """\
                name: test
                database_url: postgresql://localhost/x
                include_dirs:
                  - db/schema
                """
            ),
        )
        runner = CliRunner()
        result = runner.invoke(app, ["hooks", "test", "--config", str(cfg)])
        assert result.exit_code != 0
        assert "no notification" in result.output.lower() or "hooks" in result.output.lower()

    def test_empty_hooks_list_errors_cleanly(self, tmp_path: Path) -> None:
        cfg = _write_env_yaml(
            tmp_path,
            dedent(
                """\
                name: test
                database_url: postgresql://localhost/x
                include_dirs:
                  - db/schema
                notifications:
                  hooks: []
                """
            ),
        )
        runner = CliRunner()
        result = runner.invoke(app, ["hooks", "test", "--config", str(cfg)])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Module import sanity — the CLI module must be importable.
# ---------------------------------------------------------------------------


def test_hooks_cli_module_importable() -> None:
    """The ``confiture.cli.commands.hooks`` module must exist and expose ``hooks_app``."""
    from confiture.cli.commands import hooks as hooks_module

    assert hasattr(hooks_module, "hooks_app")


def test_hooks_app_registered_on_main_app() -> None:
    """``confiture hooks --help`` must list the ``test`` command."""
    runner = CliRunner()
    result = runner.invoke(app, ["hooks", "--help"])
    assert result.exit_code == 0
    assert "test" in result.output
