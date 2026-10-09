"""CI runs what it says it runs.

The Python matrix declared three interpreters and ran 3.11 three times: ``uv
venv`` without ``--python`` picks its own interpreter and ignores the one
``setup-python`` installed (#209). And the examples were never run anywhere.
These checks read the workflow files, so a regression is a failing unit test
rather than a green badge over an untested claim.
"""

import os
import re
import subprocess
import tomllib
from pathlib import Path
from typing import ClassVar
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


def _supported() -> list[str]:
    """Every CPython the package declares, from its ``Programming Language`` classifiers."""
    classifiers = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"][
        "classifiers"
    ]
    prefix = "Programming Language :: Python :: 3."
    return [f"3.{c.removeprefix(prefix)}" for c in classifiers if c.startswith(prefix)]


SUPPORTED = _supported()


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

    def test_the_supported_interpreter_runs_the_suite_on_every_pull_request(self) -> None:
        gate = _steps("quality-gate.yml", "test")
        (setup,) = [step for step in gate if step.get("uses") == "./.github/actions/python-uv"]
        assert [setup["with"]["python-version"]] == SUPPORTED

    def test_the_matrix_runs_the_next_cpython_by_hand(self) -> None:
        """No final CPython above the floor builds the package yet, so no leg is listed.

        A matrix cannot be empty, so the workflow takes the version to try as an
        input; a pull request never waits for it.
        """
        data = yaml.safe_load((WORKFLOWS / "python-version-matrix.yml").read_text())
        triggers = data[True]  # YAML 1.1 reads the bare key `on` as true
        assert set(triggers) == {"workflow_dispatch"}
        versions = data["jobs"]["test-matrix"]["strategy"]["matrix"]["python-version"]
        assert versions == ["${{ inputs.python-version }}"]

    def test_every_job_runs_the_supported_interpreter(self) -> None:
        """A job on another interpreter tests a package nobody can install there."""
        offenders = []
        for path in sorted(WORKFLOWS.glob("*.yml")):
            if path.name == "python-version-matrix.yml":
                continue
            data = yaml.safe_load(path.read_text())
            for name, job in data["jobs"].items():
                for step in job.get("steps", []):
                    version = (step.get("with") or {}).get("python-version")
                    if version is not None and str(version).split() != SUPPORTED:
                        offenders.append(f"{path.name}:{name}: {version}")
        assert offenders == []

    def test_the_project_interpreter_is_the_supported_one(self) -> None:
        """``uv venv`` with no ``--python`` reads ``.python-version``."""
        assert (REPO_ROOT / ".python-version").read_text().split() == SUPPORTED


class TestQualityGate:
    def test_one_pglast_major_needs_no_matrix(self) -> None:
        """``pglast>=8.5`` is one major; the lock pins it and the suite runs it."""
        data = yaml.safe_load((WORKFLOWS / "quality-gate.yml").read_text())
        assert "pglast-matrix" not in data["jobs"]

    def test_the_suite_runs_on_every_core(self) -> None:
        script = _run_scripts(_steps("quality-gate.yml", "test"))
        assert "-m pytest tests/" in script and "-n auto" in script, script

    def test_coverage_is_collected_once(self) -> None:
        """By the quality gate's run, across its workers; no other leg measures."""
        gate = _run_scripts(_steps("quality-gate.yml", "test"))
        assert "coverage combine" in gate
        matrix = _run_scripts(_steps("python-version-matrix.yml", "test-matrix"))
        assert "--cov" not in matrix and "coverage run" not in matrix

    def test_coverage_is_judged_on_both_servers_combined(self) -> None:
        """One floor check, over what the 16 and the 18 legs measured together.

        A floor checked per leg would fail a file whose lines only one server reaches;
        a floor checked on one leg would ignore the other. The legs upload their data,
        one job combines it, and that job is the one the floors read.
        """
        test = _run_scripts(_steps("quality-gate.yml", "test"))
        assert "coverage_floors.py" not in test and "coverage report" not in test
        uploads = [
            step
            for step in _steps("quality-gate.yml", "test")
            if step.get("uses", "").startswith("actions/upload-artifact")
        ]
        assert len(uploads) == 1, uploads
        assert "${{ matrix.postgres }}" in uploads[0]["with"]["name"]
        combined = _run_scripts(_steps("quality-gate.yml", "coverage"))
        assert "coverage combine" in combined
        assert "scripts/coverage_floors.py --check" in combined
        data = yaml.safe_load((WORKFLOWS / "quality-gate.yml").read_text())
        assert data["jobs"]["coverage"]["needs"] in ("test", ["test"])
        assert "coverage" in data["jobs"]["quality-gate"]["needs"]
        assert "needs.coverage.result" in _run_scripts(_steps("quality-gate.yml", "quality-gate"))

    def test_no_job_runs_a_suite_the_test_job_already_runs(self) -> None:
        data = yaml.safe_load((WORKFLOWS / "quality-gate.yml").read_text())
        assert "integration-parallel" not in data["jobs"]


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


class TestOneToolchainSetup:
    """Every job gets Python and uv from ``.github/actions/python-uv``.

    The same setup-python / setup-uv / Rust / maturin steps were copied into twenty
    jobs over seven workflows, so a version bump had twenty places to miss.
    """

    ACTION = "./.github/actions/python-uv"

    def _jobs(self) -> list[tuple[str, str, list[str]]]:
        jobs = []
        for path in sorted(WORKFLOWS.glob("*.yml")):
            data = yaml.safe_load(path.read_text())
            for name, job in data["jobs"].items():
                uses = [step.get("uses", "").split("@")[0] for step in job.get("steps", [])]
                jobs.append((path.name, name, uses))
        return jobs

    def test_no_job_sets_up_python_and_uv_itself(self) -> None:
        by_hand = [
            f"{workflow}:{job}"
            for workflow, job, uses in self._jobs()
            if "actions/setup-python" in uses and "astral-sh/setup-uv" in uses
        ]
        assert by_hand == [], f"use {self.ACTION} instead: {by_hand}"

    def test_the_action_is_used(self) -> None:
        users = [job for _, job, uses in self._jobs() if self.ACTION in uses]
        assert len(users) >= 10


class TestReleaseWheels:
    """Every supported CPython gets a wheel on every platform (#586, #587)."""

    def test_the_declared_interpreter_is_the_floor(self) -> None:
        assert SUPPORTED == ["3.14"]

    def test_linux_builds_a_wheel_for_each(self) -> None:
        build = next(
            step["env"]["CIBW_BUILD"]
            for step in _steps("publish.yml", "build-wheels")
            if "cibuildwheel" in step.get("uses", "")
        )
        built = {tag.split("-")[0] for tag in build.split()}
        assert built == {f"cp3{v.split('.')[1]}" for v in SUPPORTED}

    def test_macos_and_windows_find_each_interpreter(self) -> None:
        setup = next(
            step
            for step in _steps("publish.yml", "build-wheels")
            if step.get("uses", "").startswith("actions/setup-python")
        )
        assert setup["with"]["python-version"].split() == SUPPORTED

    def test_the_publish_check_loops_over_the_supported_tags(self) -> None:
        script = _run_scripts(_steps("publish.yml", "validate"))
        tags = " ".join(f"cp3{v.split('.')[1]}" for v in SUPPORTED)
        assert f"for py in {tags}; do" in script

    def test_no_build_leans_on_forward_compatibility(self) -> None:
        """The wheels are version-specific; the flag only hid a missing one."""
        assert "PYO3_USE_ABI3_FORWARD_COMPATIBILITY" not in (WORKFLOWS / "publish.yml").read_text()

    def test_the_newest_is_installed_from_its_wheel_on_every_pull_request(self) -> None:
        script = _run_scripts(_steps("quality-gate.yml", "wheel-python-314"))
        assert "--only-binary fraiseql-confiture" in script and "--no-cache" in script
        assert SUPPORTED[-1] == "3.14"


def _service_jobs() -> list[tuple[str, str, dict]]:
    """Every job that starts a PostgreSQL service container, with its workflow."""
    jobs = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        data = yaml.safe_load(path.read_text())
        for name, job in data["jobs"].items():
            if "postgres" in (job.get("services") or {}):
                jobs.append((path.name, name, job))
    return jobs


class TestPostgresServers:
    """CI tests the floor and the newest server: PostgreSQL 16 and 18 (#608).

    PostgreSQL 18 changed what the catalog says (NOT NULL rows in ``pg_constraint``,
    ``conenforced``, virtual generated columns). Every service container was
    ``postgres:16``, so the one server a developer is likeliest to run locally was
    tested nowhere a pull request waits for.
    """

    SERVERS: ClassVar[list[str]] = ["16", "18"]
    BOTH: ClassVar[set[tuple[str, str]]] = {
        ("quality-gate.yml", "test"),
        ("quality-gate.yml", "plpgsql-check"),
        ("examples.yml", "examples"),
    }

    @staticmethod
    def _job(workflow: str, job: str) -> dict:
        return yaml.safe_load((WORKFLOWS / workflow).read_text())["jobs"][job]

    def test_the_gate_and_the_examples_run_on_both_servers(self) -> None:
        for workflow, name in sorted(self.BOTH):
            job = self._job(workflow, name)
            assert job["strategy"]["matrix"]["postgres"] == self.SERVERS, (workflow, name)
            assert job["strategy"].get("fail-fast") is False, (workflow, name)
            assert "${{ matrix.postgres }}" in job["name"], (workflow, name)

    def test_a_service_job_on_both_servers_takes_its_image_from_the_matrix(self) -> None:
        both = [(w, n, j) for w, n, j in _service_jobs() if (w, n) in self.BOTH]
        assert {(w, n) for w, n, _ in both} == {
            ("quality-gate.yml", "test"),
            ("examples.yml", "examples"),
        }
        for workflow, name, job in both:
            image = job["services"]["postgres"]["image"]
            assert image == "postgres:${{ matrix.postgres }}", (workflow, name, image)

    def test_every_other_database_job_runs_the_floor(self) -> None:
        """A release and a deployment path are proved on the oldest server confiture supports."""
        offenders = [
            f"{workflow}:{name}: {job['services']['postgres']['image']}"
            for workflow, name, job in _service_jobs()
            if (workflow, name) not in self.BOTH
            and job["services"]["postgres"]["image"] != "postgres:16"
        ]
        assert offenders == []

    def test_body_analysis_builds_its_server_from_the_matrix(self) -> None:
        script = _run_scripts(_steps("quality-gate.yml", "plpgsql-check"))
        assert "postgresql-${{ matrix.postgres }}-plpgsql-check" in script
        assert "FROM postgres:${{ matrix.postgres }}@${{ matrix.digest }}" in script
        include = self._job("quality-gate.yml", "plpgsql-check")["strategy"]["matrix"]["include"]
        digests = {row["postgres"]: row["digest"] for row in include}
        assert set(digests) == set(self.SERVERS)
        assert all(re.fullmatch(r"sha256:[0-9a-f]{64}", d) for d in digests.values()), digests

    def test_the_test_leg_dumps_with_a_client_as_new_as_its_server(self) -> None:
        """pg_dump refuses a server newer than itself; the runner's stock client is 16."""
        script = _run_scripts(_steps("quality-gate.yml", "test"))
        assert "postgresql-client-${{ matrix.postgres }}" in script
        assert "/usr/lib/postgresql/${{ matrix.postgres }}/bin" in script

    def test_no_workflow_names_a_server_below_the_floor(self) -> None:
        offenders = [
            f"{path.relative_to(REPO_ROOT)}: {match.group(0)}"
            for path in [*sorted(WORKFLOWS.glob("*.yml")), *_tracked("ci")]
            for match in re.finditer(r"postgres(?:ql)?[-:](\d+)", path.read_text())
            if int(match.group(1)) < 16
        ]
        assert offenders == []
