"""CI runs what it says it runs.

The Python matrix declared three interpreters and ran 3.11 three times: ``uv
venv`` without ``--python`` picks its own interpreter and ignores the one
``setup-python`` installed (#209). And the examples were never run anywhere.
These checks read the workflow files, so a regression is a failing unit test
rather than a green badge over an untested claim.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
EXAMPLES = REPO_ROOT / "examples"


def _steps(workflow: str, job: str) -> list[dict]:
    data = yaml.safe_load((WORKFLOWS / workflow).read_text())
    return data["jobs"][job]["steps"]


def _run_scripts(steps: list[dict]) -> str:
    return "\n".join(step.get("run", "") for step in steps)


class TestPythonMatrix:
    def test_venv_is_built_on_the_matrix_interpreter(self) -> None:
        script = _run_scripts(_steps("python-version-matrix.yml", "test-matrix"))
        assert re.search(
            r"uv venv\s+--python\s+\"?\$\{\{\s*matrix\.python-version\s*\}\}", script
        ), (
            "`uv venv` must pass --python ${{ matrix.python-version }}; without it uv picks its "
            "own interpreter and every leg runs the same Python (#209)"
        )

    def test_a_step_proves_the_interpreter_version(self) -> None:
        script = _run_scripts(_steps("python-version-matrix.yml", "test-matrix"))
        assert "sys.version_info[:2]" in script and "matrix.python-version" in script, (
            "a step must assert `sys.version_info[:2]` against the matrix entry"
        )

    def test_uv_python_is_pinned_to_the_matrix_entry(self) -> None:
        """`uv sync`/`uv run` re-resolve the interpreter; UV_PYTHON is what they honour."""
        data = yaml.safe_load((WORKFLOWS / "python-version-matrix.yml").read_text())
        env = data["jobs"]["test-matrix"].get("env", {})
        assert env.get("UV_PYTHON") == "${{ matrix.python-version }}", env

    def test_matrix_declares_three_interpreters(self) -> None:
        data = yaml.safe_load((WORKFLOWS / "python-version-matrix.yml").read_text())
        versions = data["jobs"]["test-matrix"]["strategy"]["matrix"]["python-version"]
        assert versions == ["3.11", "3.12", "3.13"]


class TestExamplesJob:
    def test_examples_workflow_runs_every_run_script(self) -> None:
        workflow = WORKFLOWS / "examples.yml"
        assert workflow.exists(), "no examples workflow: the examples are never run"
        data = yaml.safe_load(workflow.read_text())
        script = "\n".join(
            step.get("run", "") for job in data["jobs"].values() for step in job["steps"]
        )
        assert "run.sh" in script, "the workflow must iterate the examples' run.sh scripts"

    def test_at_least_three_examples_are_runnable(self) -> None:
        scripts = sorted(EXAMPLES.glob("*/run.sh"))
        assert len(scripts) >= 3, [p.parent.name for p in scripts]

    def test_every_run_script_is_executable_and_strict(self) -> None:
        offenders = []
        for script in sorted(EXAMPLES.glob("*/run.sh")):
            text = script.read_text()
            if not os.access(script, os.X_OK):
                offenders.append(f"{script.parent.name}: not executable")
            if not text.startswith("#!/usr/bin/env bash"):
                offenders.append(f"{script.parent.name}: missing bash shebang")
            if "set -euo pipefail" not in text:
                offenders.append(f"{script.parent.name}: missing `set -euo pipefail`")
        assert offenders == []
