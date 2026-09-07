"""``import confiture`` is a promise, not a payload.

The package advertises a lazy surface (``_LAZY_IMPORTS``) but imported the
linter eagerly, which pulled the whole rule library in for every ``import
confiture``. Two names in the public API meant the same thing (``export_all`` /
``export_all_schemas``), and the ``verify`` CLI alias outlived the one release it
was promised for (0.19.0). This test pins the surface as narrow as the code.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
from typer.testing import CliRunner

import confiture
from confiture.cli.main import app

runner = CliRunner()

_PROBE = """
import json, sys, time
started = time.perf_counter()
import confiture
elapsed_ms = (time.perf_counter() - started) * 1000
print(json.dumps({
    "linting_loaded": "confiture.core.linting" in sys.modules,
    "schema_linter_loaded": "confiture.core.linting.schema_linter" in sys.modules,
    "elapsed_ms": elapsed_ms,
}))
"""


def _probe() -> dict:
    out = subprocess.run([sys.executable, "-c", _PROBE], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_import_confiture_leaves_the_linter_unloaded() -> None:
    result = _probe()
    assert result["linting_loaded"] is False, result
    assert result["schema_linter_loaded"] is False, result


@pytest.mark.benchmark
def test_import_confiture_is_cheap() -> None:
    """The confiture portion of ``import confiture`` stays under 30 ms (a fresh interpreter)."""
    result = _probe()
    assert result["elapsed_ms"] < 30, result


def test_schema_linter_and_external_generator_error_are_lazy() -> None:
    assert "SchemaLinter" in confiture._LAZY_IMPORTS
    assert "ExternalGeneratorError" in confiture._LAZY_IMPORTS
    assert confiture.SchemaLinter.__name__ == "SchemaLinter"  # still reachable on demand


def test_one_name_for_the_schema_exporter() -> None:
    assert "export_all" in confiture.__all__
    assert "export_all_schemas" not in confiture.__all__
    assert not hasattr(confiture, "export_all_schemas")


def test_the_deprecated_verify_alias_is_gone() -> None:
    result = runner.invoke(app, ["verify", "--help"])
    assert result.exit_code == 2, result.output
    assert "No such command" in result.output
