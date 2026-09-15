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
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
EXAMPLES = REPO_ROOT / "examples"
MIN_SEED_FILES = 6


def _tracked(pathspec: str) -> list[Path]:
    """Tracked files matching the git pathspec, as absolute paths.

    ``git ls-files`` rather than ``glob``: a clean checkout sees exactly this, and a
    build that left SQL under ``examples/`` cannot satisfy a check about what ships.
    """
    out = subprocess.run(
        ["git", "ls-files", "--", pathspec],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(REPO_ROOT / line for line in out.splitlines() if line)


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

    def test_every_seed_file_is_applied_by_the_run_script_of_its_example(self) -> None:
        """A seed file no run applies is data that has never loaded.

        ``examples/05`` shipped two fixtures that inserted a task as ``'done'`` with no
        ``completed_at``, which its own ``tasks_completed_when_done`` forbids. Its
        ``run.sh`` built ``db/schema`` and stopped there, so applying them was nobody's
        job and the violation sat in the tree unreported (#266). ``examples/basic``
        shipped four more whose only route into a database is a ``confiture build`` its
        ``run.sh`` never ran.

        A seed file counts as applied when the run script names the directory it lives
        in, or when that directory is inside an ``include_dirs`` entry of an environment
        the script builds. Both are literal readings of the script — no path globbing,
        which is ``core/path_globs.py``'s job alone.
        """
        seeds = _tracked("examples/*/db/seeds/**/*.sql")
        assert len(seeds) >= MIN_SEED_FILES, "the examples lost their seed files"

        unapplied: list[str] = []
        for script in sorted(EXAMPLES.glob("*/run.sh")):
            example = script.parent
            # Comments are not application: a run script that mentions db/seeds/test in
            # a comment and never reads it leaves the file exactly as unexercised as one
            # that does not mention it at all. Everything from an unquoted `#` goes.
            code = "\n".join(line.split("#", 1)[0] for line in script.read_text().splitlines())
            built = set(re.findall(r"--env\s+([A-Za-z0-9_-]+)", code))
            included = {
                entry["path"] if isinstance(entry, dict) else entry
                for env_file in sorted((example / "db" / "environments").glob("*.yaml"))
                if env_file.stem in built
                for entry in (yaml.safe_load(env_file.read_text()) or {}).get("include_dirs") or []
            }
            for seed in (s for s in seeds if example in s.parents):
                directory = seed.parent.relative_to(example).as_posix()
                named = directory in code
                built_in = any(
                    directory == entry or directory.startswith(f"{entry.rstrip('/')}/")
                    for entry in included
                )
                if not (named or built_in):
                    unapplied.append(f"{example.name}: {seed.relative_to(example)}")
        assert unapplied == [], (
            "these seed files are applied by nothing, so nothing checks that they still "
            f"load against the schema shipped beside them: {unapplied}"
        )

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


class TestMigrationPerformance:
    """The benchmark leg is told which databases to use; something has to create them.

    `psql -h … -U confiture -d postgres -c "SELECT 1" confiture_source_test` reads as an
    existence probe and is not one: psql's positional arguments are `[dbname [username]]`
    and `-d`/`-U` had already filled both, so the name was discarded with a warning that
    the line's own `>/dev/null 2>&1` swallowed. The probe asked `postgres` instead, always
    succeeded, and the `||` branch that creates the database never ran — so every test
    reaching for `confiture_source_test` errored at setup, nightly, unnoticed.
    """

    WORKFLOW = "migration-performance.yml"
    JOB = "performance-monitoring"

    @staticmethod
    def _database_names(env: dict) -> set[str]:
        names = set()
        for key, value in env.items():
            if key != "DATABASE_URL" and not key.endswith("_DB_URL"):
                continue
            path = urlparse(str(value)).path.lstrip("/")
            if path:
                names.add(path)
        return names

    @staticmethod
    def _unconditionally_created(script: str) -> set[str]:
        """Databases this script creates on the path that always runs.

        A `CREATE DATABASE` behind a `||` runs only when the probe to its left fails,
        and the probe here could not fail — so the text was present and the database
        was not. Creation has to be unconditional to count.
        """
        always_runs = "\n".join(line.split("||")[0] for line in script.splitlines())
        return set(re.findall(r"CREATE DATABASE\s+(\w+)", always_runs))

    def test_every_database_the_tests_are_given_is_created_first(self) -> None:
        data = yaml.safe_load((WORKFLOWS / self.WORKFLOW).read_text())
        job = data["jobs"][self.JOB]
        # The service container creates its own POSTGRES_DB before any step runs.
        available = {
            service.get("env", {}).get("POSTGRES_DB")
            for service in job.get("services", {}).values()
        } - {None}
        missing: list[str] = []
        for step in job["steps"]:
            missing.extend(
                f"{step.get('name', '?')}: {name}"
                for name in sorted(self._database_names(step.get("env", {})))
                if name not in available
            )
            available.update(self._unconditionally_created(step.get("run", "")))
        assert missing == [], (
            "these databases are named in a step's environment but nothing creates them "
            f"beforehand, so the tests that use them error at setup: {missing}"
        )


class TestPsqlInvocations:
    """A positional after `-d` is not the database psql will connect to."""

    # psql takes at most `[dbname [username]]`. `-d` fills the first slot, so any
    # positional that follows can only land in `username` — never the database the
    # author meant — and once `-U` has filled that too it is discarded with a warning.
    _CALL = re.compile(r'psql\s(?P<args>[^\n]*?)-c\s+"[^"]*"\s+(?P<trailing>\S+)')
    _NOT_AN_ARGUMENT = re.compile(r"^(?:[0-9]*[<>]|[|&;)]|\\$|-)")

    def test_no_positional_database_follows_an_explicit_d_flag(self) -> None:
        offenders = []
        for workflow in sorted(WORKFLOWS.glob("*.yml")):
            data = yaml.safe_load(workflow.read_text())
            for job in data.get("jobs", {}).values():
                for step in job.get("steps", []):
                    for line in step.get("run", "").splitlines():
                        for match in self._CALL.finditer(line):
                            trailing = match.group("trailing")
                            if self._NOT_AN_ARGUMENT.match(trailing):
                                continue
                            if not re.search(r"(?:^|\s)-d\s", match.group("args")):
                                continue  # no -d: the positional legitimately is the dbname
                            offenders.append(f"{workflow.name}: {line.strip()}")
        assert offenders == [], (
            "`-d` has already filled psql's `dbname` slot, so this positional is read as a "
            f"username or discarded outright — it is not the database being asked: {offenders}"
        )


class TestNoWorkflowOpensAPullRequest:
    """The `fraiseql` org forbids Actions from creating pull requests.

        ##[error]GitHub Actions is not permitted to create or approve pull requests.

    `Lockfile Bump` failed on that every Monday: `uv lock --upgrade` ran, the branch
    pushed, and only the last step failed — so the run was red for a reason no commit
    could cause and no log line above it hinted at. The policy is organisation-wide
    (a repository-level `can_approve_pull_request_reviews` cannot override it), so a
    workflow that opens a PR is a workflow that fails after doing all of its work.
    Push the branch and say so somewhere a person will look.
    """

    _PR_CREATORS = (
        "peter-evans/create-pull-request",
        "gh pr create",
        "repos/{owner}/{repo}/pulls",
    )

    def test_no_workflow_step_creates_a_pull_request(self) -> None:
        offenders = []
        for workflow in sorted(WORKFLOWS.glob("*.yml")):
            text = workflow.read_text()
            offenders.extend(
                f"{workflow.name}: {creator}" for creator in self._PR_CREATORS if creator in text
            )
        assert offenders == [], (
            "the organisation blocks Actions from creating pull requests, so this step "
            f"fails after the job has already done its work: {offenders}"
        )
