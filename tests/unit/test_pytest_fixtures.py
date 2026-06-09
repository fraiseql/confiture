"""Unit tests for the per-worker xdist fixtures (#158 Phase 05).

The fixtures are exercised by calling their underlying functions directly
(``fixture.__wrapped__``) with a stub provisioner — no database required. The
focus is the RAM-tablespace threading and the "never ``pytest.exit()`` in a
worker" guarantee.
"""

from __future__ import annotations

import ast
import inspect
from types import SimpleNamespace

import pytest

import confiture.core.test_db as test_db_mod
from confiture.testing import pytest_plugin


class _StubProvisioner:
    """Records clone() calls; tablespace_usable answers from a configured set."""

    usable_names: set[str] = set()
    clone_calls: list[dict] = []

    def __init__(self, url: str) -> None:
        self.url = url

    def drop(self, target: str) -> bool:  # noqa: ARG002 - signature parity
        return False

    def tablespace_usable(self, name: str) -> bool:
        return name in _StubProvisioner.usable_names

    def clone(self, template: str, target: str, *, tablespace: str | None = None) -> object:
        _StubProvisioner.clone_calls.append(
            {"template": template, "target": target, "tablespace": tablespace}
        )
        return SimpleNamespace(target_url=f"postgresql://localhost/{target}")


@pytest.fixture(autouse=True)
def _reset_stub() -> None:
    _StubProvisioner.usable_names = set()
    _StubProvisioner.clone_calls = []


class TestRamTablespaceFixture:
    def test_reads_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONFITURE_TEST_RAM_TABLESPACE", "ram_tbl")
        assert pytest_plugin.confiture_ram_tablespace.__wrapped__() == "ram_tbl"

    def test_none_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CONFITURE_TEST_RAM_TABLESPACE", raising=False)
        assert pytest_plugin.confiture_ram_tablespace.__wrapped__() is None


class TestRamTablespaceUsableMemo:
    def test_none_when_tablespace_unset(self) -> None:
        memo = pytest_plugin.confiture_ram_tablespace_usable.__wrapped__
        assert memo(confiture_ram_tablespace=None, confiture_test_server_url="url") is None

    def test_gated_by_probe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(test_db_mod, "TestDbProvisioner", _StubProvisioner)
        _StubProvisioner.usable_names = {"good_ts"}
        memo = pytest_plugin.confiture_ram_tablespace_usable.__wrapped__
        assert (
            memo(confiture_ram_tablespace="good_ts", confiture_test_server_url="url") == "good_ts"
        )
        assert memo(confiture_ram_tablespace="bad_ts", confiture_test_server_url="url") is None


class TestWorkerDbThreadsTablespace:
    def _run(self, ram_tablespace: str | None) -> dict:
        gen = pytest_plugin.confiture_worker_db.__wrapped__(
            confiture_template_db="tmpl",
            confiture_test_server_url="postgresql://localhost/x",
            confiture_worker_id=None,
            confiture_ram_tablespace_usable=ram_tablespace,
        )
        next(gen)  # advance to the yield (the clone happens here)
        gen.close()  # run teardown
        return _StubProvisioner.clone_calls[-1]

    def test_passes_ram_tablespace_when_usable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(test_db_mod, "TestDbProvisioner", _StubProvisioner)
        call = self._run(ram_tablespace="ram_tbl")
        assert call["tablespace"] == "ram_tbl"
        assert call["target"] == "tmpl_db"

    def test_passes_none_when_no_tablespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(test_db_mod, "TestDbProvisioner", _StubProvisioner)
        call = self._run(ram_tablespace=None)
        assert call["tablespace"] is None


class TestNoPytestExitInWorker:
    def test_plugin_never_calls_pytest_exit(self) -> None:
        # pytest.exit() inside an xdist worker surfaces as an opaque INTERNALERROR
        # attributed to a random test (#158 gotcha). Fixtures degrade via the disk
        # fallback and reserve pytest.skip for total DB-unavailability. AST-based so
        # a docstring that merely mentions pytest.exit() (like ours) doesn't trip it.
        tree = ast.parse(inspect.getsource(pytest_plugin))
        exit_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "exit"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "pytest"
        ]
        assert not exit_calls, f"pytest.exit() called at lines {[n.lineno for n in exit_calls]}"
