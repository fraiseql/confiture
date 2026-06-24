"""Unit tests for per-worker DB name/URL resolution (P3, Cycle 1)."""

from __future__ import annotations

import pytest

from confiture.testing.worker_db import (
    _CI_ENV_VARS,
    _MAX_CLONE_CONCURRENCY_VAR,
    current_worker_id,
    is_ci,
    resolve_clone_concurrency,
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
        url = resolve_worker_db_url("postgresql://u:p@host:5433/app", worker_id="gw0")
        assert url == "postgresql://u:p@host:5433/app_gw0"

    def test_no_worker_keeps_url(self) -> None:
        assert (
            resolve_worker_db_url("postgresql://localhost/app", worker_id=None)
            == "postgresql://localhost/app"
        )


class TestIsCi:
    @pytest.mark.parametrize(
        ("env", "expected"),
        [
            ({}, False),
            ({"CI": "true"}, True),
            ({"CI": "1"}, True),
            ({"CI": "false"}, False),  # false-y string → not CI
            ({"CI": ""}, False),  # present-but-empty → not CI
            ({"CI": "off"}, False),
            ({"GITHUB_ACTIONS": "true"}, True),
            ({"GITLAB_CI": "true"}, True),
            ({"BUILDKITE": "true"}, True),
            ({"DAGGER_SESSION_PORT": "54321"}, True),
            ({"JENKINS_URL": "http://ci.example"}, True),
        ],
    )
    def test_permutations(
        self, monkeypatch: pytest.MonkeyPatch, env: dict[str, str], expected: bool
    ) -> None:
        for var in _CI_ENV_VARS:
            monkeypatch.delenv(var, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        assert is_ci() is expected


class TestResolveCloneConcurrency:
    """The cap resolver for bounded clone concurrency (#166)."""

    def test_auto_throttles_on_fsync_on(self) -> None:
        # No override + fsync=on → the small default cap (concurrent clones thrash).
        assert resolve_clone_concurrency(fsync_on=True, env={}) == 2

    def test_auto_unbounded_on_fsync_off(self) -> None:
        # No override + fsync=off (typical CI) → unbounded; clones are cheap there.
        assert resolve_clone_concurrency(fsync_on=False, env={}) is None

    def test_override_caps_regardless_of_fsync(self) -> None:
        env = {_MAX_CLONE_CONCURRENCY_VAR: "4"}
        assert resolve_clone_concurrency(fsync_on=False, env=env) == 4
        assert resolve_clone_concurrency(fsync_on=True, env=env) == 4

    def test_override_one_is_serial(self) -> None:
        env = {_MAX_CLONE_CONCURRENCY_VAR: "1"}
        assert resolve_clone_concurrency(fsync_on=True, env=env) == 1

    @pytest.mark.parametrize("raw", ["0", "-1", "-5"])
    def test_override_non_positive_forces_unbounded(self, raw: str) -> None:
        # An explicit opt-out (<= 0) wins even on fsync=on.
        env = {_MAX_CLONE_CONCURRENCY_VAR: raw}
        assert resolve_clone_concurrency(fsync_on=True, env=env) is None

    def test_override_whitespace_is_stripped(self) -> None:
        env = {_MAX_CLONE_CONCURRENCY_VAR: "  3  "}
        assert resolve_clone_concurrency(fsync_on=True, env=env) == 3

    @pytest.mark.parametrize("raw", ["abc", "2.5", ""])
    def test_override_invalid_falls_through_to_auto(self, raw: str) -> None:
        env = {_MAX_CLONE_CONCURRENCY_VAR: raw}
        assert resolve_clone_concurrency(fsync_on=True, env=env) == 2
        assert resolve_clone_concurrency(fsync_on=False, env=env) is None

    def test_defaults_to_os_environ(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(_MAX_CLONE_CONCURRENCY_VAR, "5")
        assert resolve_clone_concurrency(fsync_on=False) == 5


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
