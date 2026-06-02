"""Tests for --database-url resolution precedence (issue #140).

Precedence: --database-url flag > CONFITURE_DATABASE_URL > DATABASE_URL > None
(None means: let MigratorSession/load_config resolve from --config).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from confiture.cli.helpers import resolve_database_url
from confiture.exceptions import ConfigurationError


def test_flag_wins_over_env_and_config(monkeypatch) -> None:
    monkeypatch.setenv("CONFITURE_DATABASE_URL", "postgresql://env/db")
    assert resolve_database_url("postgresql://flag/db", Path("env.yaml")) == "postgresql://flag/db"


def test_env_used_when_no_flag(monkeypatch) -> None:
    monkeypatch.setenv("CONFITURE_DATABASE_URL", "postgresql://env/db")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert resolve_database_url(None, None) == "postgresql://env/db"


def test_canonical_env_wins_over_bare(monkeypatch) -> None:
    monkeypatch.setenv("CONFITURE_DATABASE_URL", "postgresql://canonical/db")
    monkeypatch.setenv("DATABASE_URL", "postgresql://bare/db")
    assert resolve_database_url(None, None) == "postgresql://canonical/db"


def test_bare_database_url_fallback(monkeypatch) -> None:
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://bare/db")
    assert resolve_database_url(None, None) == "postgresql://bare/db"


def test_returns_none_when_only_config(monkeypatch) -> None:
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    # No flag, no env → caller falls back to config_path.
    assert resolve_database_url(None, Path("env.yaml")) is None


def test_malformed_flag_dsn_raises_config_003(monkeypatch) -> None:
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ConfigurationError) as exc_info:
        resolve_database_url("mysql://nope/db", None)
    assert exc_info.value.error_code == "CONFIG_003"
    assert exc_info.value.exit_code == 5  # #146: CONFIG family → config invalid


# ---------------------------------------------------------------------------
# Issue #152 — the secure precedence contract (0.20.0, flagged-breaking).
#
# Contract: "explicit-and-singular wins; ambiguity fails loud."
#   a) --database-url flag                              → flag
#   b) explicit --config/--env AND CONFITURE_DATABASE_URL both present → CONFIG_007
#   c) explicit --config/--env only                    → config (None)
#   d) CONFITURE_DATABASE_URL set, config is only the default → canonical var
#   e) default config present (no canonical var)       → config; else ambient; else fail
#   --no-config                                        → env is the sole source
# ---------------------------------------------------------------------------


def test_canonical_env_beats_decoy_default_config(monkeypatch, tmp_path) -> None:
    """THE BUG: an injected canonical var must win over a *default* config file.

    A present default config no longer silently shadows CONFITURE_DATABASE_URL.
    """
    monkeypatch.setenv("CONFITURE_DATABASE_URL", "postgresql://canonical/db")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    decoy = tmp_path / "local.yaml"
    decoy.write_text("database_url: postgresql://decoy/local\n")
    # config_explicit=False → the path is a mere default.
    assert resolve_database_url(None, decoy, config_explicit=False) == "postgresql://canonical/db"


def test_two_explicit_sources_raise_config_007(monkeypatch, tmp_path) -> None:
    """An explicit --config plus an explicit CONFITURE_DATABASE_URL → fail loud."""
    monkeypatch.setenv("CONFITURE_DATABASE_URL", "postgresql://canonical/db")
    cfg = tmp_path / "prod.yaml"
    cfg.write_text("database_url: postgresql://cfg/db\n")
    with pytest.raises(ConfigurationError) as exc_info:
        resolve_database_url(None, cfg, config_explicit=True)
    assert exc_info.value.error_code == "CONFIG_007"
    assert exc_info.value.exit_code == 5


def test_config_007_fires_even_when_dsns_match(monkeypatch, tmp_path) -> None:
    """Row (b) is present-at-all, not 'differing' — no DSN normalization."""
    monkeypatch.setenv("CONFITURE_DATABASE_URL", "postgresql://same/db")
    cfg = tmp_path / "prod.yaml"
    cfg.write_text("database_url: postgresql://same/db\n")
    with pytest.raises(ConfigurationError) as exc_info:
        resolve_database_url(None, cfg, config_explicit=True)
    assert exc_info.value.error_code == "CONFIG_007"


def test_explicit_config_only_returns_none(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    cfg = tmp_path / "prod.yaml"
    cfg.write_text("database_url: postgresql://cfg/db\n")
    assert resolve_database_url(None, cfg, config_explicit=True) is None


def test_explicit_config_ignores_ambient_database_url(monkeypatch, tmp_path) -> None:
    """An explicit config wins over a merely-ambient DATABASE_URL."""
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://ambient/db")
    cfg = tmp_path / "prod.yaml"
    cfg.write_text("database_url: postgresql://cfg/db\n")
    assert resolve_database_url(None, cfg, config_explicit=True) is None


def test_present_default_config_beats_ambient_database_url(monkeypatch, tmp_path) -> None:
    """A present default config beats ambient DATABASE_URL (preserves tracking_table)."""
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://ambient/db")
    default_cfg = tmp_path / "local.yaml"
    default_cfg.write_text("database_url: postgresql://default/db\n")
    assert resolve_database_url(None, default_cfg, config_explicit=False) is None


def test_no_config_uses_canonical_env(monkeypatch, tmp_path) -> None:
    """--no-config: the canonical var is authoritative; config is never read."""
    monkeypatch.setenv("CONFITURE_DATABASE_URL", "postgresql://canonical/db")
    monkeypatch.setenv("DATABASE_URL", "postgresql://ambient/db")
    present = tmp_path / "local.yaml"
    present.write_text("database_url: postgresql://decoy/db\n")
    assert (
        resolve_database_url(None, present, config_explicit=False, no_config=True)
        == "postgresql://canonical/db"
    )


def test_no_config_uses_ambient_when_no_canonical(monkeypatch) -> None:
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://ambient/db")
    assert resolve_database_url(None, None, no_config=True) == "postgresql://ambient/db"


def test_no_config_without_env_raises_config_010(monkeypatch) -> None:
    """--no-config with no env DSN → fail loud (CONFIG_010)."""
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ConfigurationError) as exc_info:
        resolve_database_url(None, None, no_config=True)
    assert exc_info.value.error_code == "CONFIG_010"


def test_require_intentional_rejects_ambient_only(monkeypatch) -> None:
    """Mutating commands (up/down) must not silently run on ambient DATABASE_URL."""
    monkeypatch.delenv("CONFITURE_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://ambient/db")
    with pytest.raises(ConfigurationError) as exc_info:
        resolve_database_url(None, None, require_intentional_source=True)
    assert exc_info.value.error_code == "CONFIG_010"


def test_require_intentional_accepts_canonical(monkeypatch) -> None:
    monkeypatch.setenv("CONFITURE_DATABASE_URL", "postgresql://canonical/db")
    assert (
        resolve_database_url(None, None, require_intentional_source=True)
        == "postgresql://canonical/db"
    )


# ---------------------------------------------------------------------------
# config_is_explicit — the parameter-source linchpin. Must recognize an
# explicit --env, not just --config (preflight carries both); #152 gate.
# ---------------------------------------------------------------------------


class _Src:
    """Stand-in for a ParameterSource enum member (carries only ``.name``).

    Deliberately avoids importing ``click``: config_is_explicit compares by
    member name precisely so it never imports the (transitive-only) click
    package, and these tests must not reintroduce that dependency (CI installs
    do not guarantee a bare ``import click`` resolves).
    """

    def __init__(self, name: str) -> None:
        self.name = name


class _FakeCtx:
    """Minimal stand-in for a click/typer Context's get_parameter_source."""

    def __init__(self, sources: dict) -> None:
        self._sources = sources

    def get_parameter_source(self, name: str):  # noqa: ANN201
        return self._sources.get(name)


def test_config_is_explicit_detects_explicit_env() -> None:
    from confiture.cli.helpers import config_is_explicit

    ctx = _FakeCtx({"config": _Src("DEFAULT"), "env": _Src("COMMANDLINE")})
    assert config_is_explicit(ctx) is True


def test_config_is_explicit_false_when_all_defaulted() -> None:
    from confiture.cli.helpers import config_is_explicit

    ctx = _FakeCtx({"config": _Src("DEFAULT"), "env": _Src("DEFAULT_MAP")})
    assert config_is_explicit(ctx) is False


def test_config_is_explicit_detects_explicit_config() -> None:
    from confiture.cli.helpers import config_is_explicit

    ctx = _FakeCtx({"config": _Src("COMMANDLINE")})  # command with no "env" param
    assert config_is_explicit(ctx) is True
