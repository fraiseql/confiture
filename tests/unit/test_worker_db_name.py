"""Unit tests for per-worker DB name/URL resolution (P3, Cycle 1)."""

from __future__ import annotations

import pytest

from confiture.testing.worker_db import (
    current_worker_id,
    resolve_worker_db_name,
    resolve_worker_db_url,
)


class TestResolveWorkerDbName:
    def test_gw0_appends_suffix(self) -> None:
        assert resolve_worker_db_name("app", worker_id="gw0") == "app_gw0"

    def test_gw11_appends_suffix(self) -> None:
        assert resolve_worker_db_name("app", worker_id="gw11") == "app_gw11"

    def test_none_returns_base(self) -> None:
        assert resolve_worker_db_name("app", worker_id=None) == "app"

    def test_master_returns_base(self) -> None:
        assert resolve_worker_db_name("app", worker_id="master") == "app"

    def test_idempotent_same_suffix(self) -> None:
        assert resolve_worker_db_name("app_gw0", worker_id="gw0") == "app_gw0"

    def test_re_resolves_different_worker(self) -> None:
        # An already-suffixed base must not double-suffix.
        assert resolve_worker_db_name("app_gw0", worker_id="gw1") == "app_gw1"

    def test_unknown_worker_form_falls_back_to_base(self) -> None:
        assert resolve_worker_db_name("app", worker_id="weird") == "app"

    def test_reads_env_var_when_unspecified(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw3")
        assert resolve_worker_db_name("app") == "app_gw3"


class TestResolveWorkerDbUrl:
    def test_replaces_dbname(self) -> None:
        assert (
            resolve_worker_db_url("postgresql://localhost/app", worker_id="gw2")
            == "postgresql://localhost/app_gw2"
        )

    def test_preserves_credentials_and_port(self) -> None:
        url = resolve_worker_db_url(
            "postgresql://u:p@host:5433/app", worker_id="gw0"
        )
        assert url == "postgresql://u:p@host:5433/app_gw0"

    def test_no_worker_keeps_url(self) -> None:
        assert (
            resolve_worker_db_url("postgresql://localhost/app", worker_id=None)
            == "postgresql://localhost/app"
        )


class TestCurrentWorkerId:
    def test_none_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
        assert current_worker_id() is None

    def test_master_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYTEST_XDIST_WORKER", "master")
        assert current_worker_id() is None

    def test_returns_worker(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw5")
        assert current_worker_id() == "gw5"
