"""A custom strategy is import-linted, then run in-process.

``plugins/sandbox.py`` rejected files that import ``os`` or ``subprocess`` and
then executed the module with ``importlib`` — the same interpreter, the same
privileges, no isolation. Calling that a sandbox invites someone to load a
plugin they would not otherwise trust. D10: name it what it is (an import
lint), say so when a plugin is loaded, and stop the docs from promising more.
"""

from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path

import pytest

from confiture.exceptions import ConfiturError

_REPO_ROOT = Path(__file__).resolve().parents[3]
_API_DOC = _REPO_ROOT / "docs" / "api" / "anonymization.md"

_VALID_STRATEGY = """
from confiture.core.anonymization.strategy import AnonymizationStrategy


class TestStrategy(AnonymizationStrategy):
    def anonymize(self, value):
        return f"anonymized_{value}"

    def validate(self, value):
        return isinstance(value, str)
"""


@pytest.fixture
def strategy_file(tmp_path: Path) -> Path:
    path = tmp_path / "valid_strategy.py"
    path.write_text(_VALID_STRATEGY)
    return path


class TestLoadingWarns:
    def test_load_strategy_warns_and_logs_in_process_execution(
        self, strategy_file: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from confiture.core.anonymization.plugins.import_lint import (
            InProcessPluginWarning,
            load_strategy,
        )

        with (
            caplog.at_level(logging.WARNING),
            pytest.warns(InProcessPluginWarning, match="in-process"),
        ):
            loaded = load_strategy(strategy_file)

        assert loaded.__name__ == "TestStrategy"
        messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("in-process" in m and strategy_file.name in m for m in messages), messages

    def test_registry_register_from_file_warns_too(self, strategy_file: Path) -> None:
        from confiture.core.anonymization.plugins.import_lint import InProcessPluginWarning
        from confiture.core.anonymization.registry import StrategyRegistry

        with pytest.warns(InProcessPluginWarning):
            name = StrategyRegistry.register_from_file(str(strategy_file))
        StrategyRegistry.unregister(name)


class TestHonestNames:
    def test_import_lint_is_the_implementation(self) -> None:
        from confiture.core.anonymization.plugins import import_lint

        assert callable(import_lint.load_strategy)
        assert issubclass(import_lint.BlockedImportError, ConfiturError)
        assert "sandbox" not in (import_lint.__doc__ or "").lower()

    def test_blocked_import_is_a_blocked_import_error(self, tmp_path: Path) -> None:
        from confiture.core.anonymization.plugins.import_lint import (
            BlockedImportError,
            load_strategy,
        )

        path = tmp_path / "dangerous.py"
        path.write_text("import os\n" + _VALID_STRATEGY)
        with pytest.raises(BlockedImportError, match="os"):
            load_strategy(path)

    def test_package_exports_the_honest_names(self) -> None:
        from confiture.core.anonymization import plugins

        for name in ("load_strategy", "BlockedImportError", "execute_timed", "TimedResult"):
            assert name in plugins.__all__, name
            assert getattr(plugins, name) is getattr(plugins.import_lint, name)

    def test_sandbox_module_is_gone(self) -> None:
        """The deprecated ``plugins.sandbox`` alias left with 1.0.0."""
        sys.modules.pop("confiture.core.anonymization.plugins.sandbox", None)
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("confiture.core.anonymization.plugins.sandbox")

    def test_registry_does_not_import_the_shim(self) -> None:
        source = (
            _REPO_ROOT / "python" / "confiture" / "core" / "anonymization" / "registry.py"
        ).read_text()
        assert "plugins.sandbox" not in source


class TestDocs:
    def test_api_doc_does_not_call_it_a_sandbox(self) -> None:
        assert "sandbox" not in _API_DOC.read_text().lower()

    def test_api_doc_states_in_process_execution(self) -> None:
        assert "in-process" in _API_DOC.read_text()
