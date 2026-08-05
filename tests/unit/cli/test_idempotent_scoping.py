"""`migrate validate --idempotent` scoping to changed migrations (#181).

⚠️ Read before adding a test here.

**No golden/snapshot assertions.** Rich soft-wraps at console width mid-path,
absolute `tmp_path`s leak into messages and into JSON `scanned_files`, and
pglast presence changes *which* violations are detected.  Assert contracts:
parsed JSON, counts, and basename sets.

**No test may assert only "zero" or only "exit 0".** "Zero files selected" is
the shared symptom of every way this feature can be silently broken — a test
asserting it passes while the gate scans nothing.  Every scoping test asserts a
**positive** expected selection: the count, the basenames present, and the
untouched basenames absent.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app

runner = CliRunner()


# ── real-git helpers (mocking subprocess would test the mock) ─────────────────


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _init(repo: Path) -> None:
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@t.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "commit.gpgsign", "false")


def _default_branch(repo: Path) -> str:
    return _git(repo, "rev-parse", "--abbrev-ref", "HEAD")


IDEMPOTENT = "CREATE TABLE IF NOT EXISTS {name} (id int);\n"
NON_IDEMPOTENT = "CREATE TABLE {name} (id int);\n"


def _migration(repo: Path, version: str, name: str, *, idempotent: bool) -> Path:
    body = (IDEMPOTENT if idempotent else NON_IDEMPOTENT).format(name=name)
    path = repo / "db" / "migrations" / f"{version}_{name}.up.sql"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


def _run_json(migrations_dir: Path, *extra: str, cwd: Path | None = None) -> tuple[int, dict]:
    """Invoke `migrate validate --idempotent --format json` and parse stdout."""
    import os

    prev = Path.cwd()
    if cwd is not None:
        os.chdir(cwd)
    try:
        result = runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--idempotent",
                "--migrations-dir",
                str(migrations_dir),
                "--format",
                "json",
                *extra,
            ],
        )
    finally:
        os.chdir(prev)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:  # pragma: no cover - diagnostic path
        pytest.fail(f"non-JSON stdout (exit {result.exit_code}):\n{result.output}")
    return result.exit_code, payload


def _basenames(payload: dict) -> set[str]:
    return {Path(p).name for p in payload.get("scanned_files", [])}


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def bare_dir(tmp_path: Path) -> Path:
    """A non-git migrations directory with three idempotent migrations."""
    d = tmp_path / "db" / "migrations"
    d.mkdir(parents=True)
    for version, name in (
        ("20260101000000", "alpha"),
        ("20260102000000", "beta"),
        ("20260103000000", "gamma"),
    ):
        (d / f"{version}_{name}.up.sql").write_text(IDEMPOTENT.format(name=name))
    return d


# ── Cycle 1: unscoped behaviour is frozen by contract ────────────────────────


class TestUnscopedBehaviourUnchanged:
    """The 0.36.0 contract. These must pass on unmodified code and after.

    `--base-ref` defaults to the truthy string "origin/main", so threading it
    unconditionally would scope every run — and, per D3, make a plain
    `--idempotent` in a non-git tree exit 7.  The `meta`-has-no-`scope`
    assertion below is the direct regression guard for that.
    """

    def test_no_flags_scans_everything(self, bare_dir: Path) -> None:
        exit_code, payload = _run_json(bare_dir)

        assert exit_code == 0
        assert payload["status"] == "ok"
        assert payload["files_scanned"] == 3
        assert _basenames(payload) == {
            "20260101000000_alpha.up.sql",
            "20260102000000_beta.up.sql",
            "20260103000000_gamma.up.sql",
        }
        assert payload["violation_count"] == 0

    def test_no_flags_emits_no_scope_key(self, bare_dir: Path) -> None:
        """THE load-bearing assertion: an unscoped run must not report scope."""
        _, payload = _run_json(bare_dir)

        assert "scope" not in payload["meta"]

    def test_no_flags_works_outside_a_git_repo(self, bare_dir: Path) -> None:
        """A bare tmp_path is not a git repo — this must not become exit 7."""
        exit_code, payload = _run_json(bare_dir)

        assert exit_code == 0
        assert payload["files_scanned"] == 3

    def test_violations_still_reported_unscoped(self, bare_dir: Path) -> None:
        (bare_dir / "20260104000000_delta.up.sql").write_text(NON_IDEMPOTENT.format(name="delta"))

        exit_code, payload = _run_json(bare_dir)

        assert exit_code == 1
        assert payload["files_scanned"] == 4
        assert payload["violation_count"] >= 1
        assert "scope" not in payload["meta"]


# ── real-repo fixture ────────────────────────────────────────────────────────


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo with three committed idempotent migrations on the default branch.

    HEAD is on a `feature` branch that has not diverged yet, so each test
    decides what "changed" means for itself.
    """
    root = tmp_path / "repo"
    root.mkdir()
    _init(root)
    for version, name in (
        ("20260101000000", "alpha"),
        ("20260102000000", "beta"),
        ("20260103000000", "gamma"),
    ):
        _migration(root, version, name, idempotent=True)
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "base")
    return root


@pytest.fixture
def base(repo: Path) -> str:
    return _default_branch(repo)


class TestExplicitFlagDetection:
    """T1: the option's truthy default must not scope; the flag must."""

    def test_default_base_ref_does_not_scope(self, repo: Path, base: str) -> None:
        """Inside a real repo where the base ref exists and differs from HEAD.

        Rev 1's design would have scoped here — this is the test that catches it.
        """
        _git(repo, "checkout", "-b", "feature")
        _migration(repo, "20260104000000", "delta", idempotent=True)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "delta")

        exit_code, payload = _run_json(repo / "db" / "migrations", cwd=repo)

        assert exit_code == 0
        assert payload["files_scanned"] == 4
        assert "scope" not in payload["meta"]

    def test_explicit_base_ref_scopes(self, repo: Path, base: str) -> None:
        _git(repo, "checkout", "-b", "feature")
        _migration(repo, "20260104000000", "delta", idempotent=True)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "delta")

        exit_code, payload = _run_json(repo / "db" / "migrations", "--base-ref", base, cwd=repo)

        assert exit_code == 0
        assert payload["meta"]["scope"]["mode"] == "base-ref"
        assert payload["meta"]["scope"]["base_ref"] == base
        assert payload["files_scanned"] == 1
        assert _basenames(payload) == {"20260104000000_delta.up.sql"}


class TestScopingSelectsOnlyChanged:
    def test_base_ref_selects_only_changed(self, repo: Path, base: str) -> None:
        """Two changed of four; the three untouched must not be scanned."""
        _git(repo, "checkout", "-b", "feature")
        _migration(repo, "20260104000000", "delta", idempotent=False)
        _migration(repo, "20260102000000", "beta", idempotent=False)  # modify existing
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "work")

        exit_code, payload = _run_json(repo / "db" / "migrations", "--base-ref", base, cwd=repo)

        assert payload["files_scanned"] == 2
        assert _basenames(payload) == {
            "20260104000000_delta.up.sql",
            "20260102000000_beta.up.sql",
        }
        assert "20260101000000_alpha.up.sql" not in _basenames(payload)
        assert "20260103000000_gamma.up.sql" not in _basenames(payload)
        assert exit_code == 1
        assert payload["violation_count"] >= 2

    def test_untouched_violations_are_not_reported(self, repo: Path, base: str) -> None:
        """A pre-existing violation in an untouched file stays out of scope.

        This is #181's whole point: a backlog of non-idempotent migrations
        must not block a branch that didn't touch them.
        """
        # Commit a non-idempotent migration onto the base branch first.
        _migration(repo, ["20260100000000", " legacy"][0], "legacy", idempotent=False)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "legacy backlog")

        _git(repo, "checkout", "-b", "feature")
        _migration(repo, "20260104000000", "delta", idempotent=True)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "clean work")

        exit_code, payload = _run_json(repo / "db" / "migrations", "--base-ref", base, cwd=repo)

        assert payload["files_scanned"] == 1
        assert _basenames(payload) == {"20260104000000_delta.up.sql"}
        assert exit_code == 0
        assert payload["violation_count"] == 0

        # ...and unscoped, the very same tree DOES fail. Proves the scoped
        # pass was a real selection, not an accidental zero.
        unscoped_exit, unscoped = _run_json(repo / "db" / "migrations", cwd=repo)
        assert unscoped_exit == 1
        assert unscoped["violation_count"] >= 1


class TestSinceParity:
    def test_since_is_equivalent_to_base_ref(self, repo: Path, base: str) -> None:
        _git(repo, "checkout", "-b", "feature")
        _migration(repo, "20260104000000", "delta", idempotent=False)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "delta")

        by_since = _run_json(repo / "db" / "migrations", "--since", base, cwd=repo)[1]
        by_base = _run_json(repo / "db" / "migrations", "--base-ref", base, cwd=repo)[1]

        assert by_since["files_scanned"] == 1
        assert _basenames(by_since) == {"20260104000000_delta.up.sql"}
        assert _basenames(by_since) == _basenames(by_base)


class TestSubdirectoryCwd:
    """T2: diff paths are repo-root-relative regardless of cwd."""

    def test_scoping_with_cwd_in_subdirectory(self, repo: Path, base: str) -> None:
        subdir = repo / "backend"
        subdir.mkdir()
        (subdir / "marker.txt").write_text("x")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "subdir")

        _git(repo, "checkout", "-b", "feature")
        _migration(repo, "20260104000000", "delta", idempotent=False)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "delta")

        exit_code, payload = _run_json(repo / "db" / "migrations", "--base-ref", base, cwd=subdir)

        # POSITIVE assertion — a zero here is exactly the T2 failure mode.
        assert payload["files_scanned"] == 1
        assert _basenames(payload) == {"20260104000000_delta.up.sql"}
        assert exit_code == 1


class TestShallowClone:
    """T3: three-dot dies on shallow clones; merge-base + two-dot survives."""

    def test_unfetched_base_ref_names_the_remedy(self, repo: Path, tmp_path: Path) -> None:
        clone = tmp_path / "shallow"
        subprocess.run(
            ["git", "clone", "--depth", "1", "--no-local", f"file://{repo}", str(clone)],
            check=True,
            capture_output=True,
        )

        import os

        prev = Path.cwd()
        os.chdir(clone)
        try:
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "validate",
                    "--idempotent",
                    "--migrations-dir",
                    str(clone / "db" / "migrations"),
                    "--base-ref",
                    "origin/does-not-exist",
                ],
            )
        finally:
            os.chdir(prev)

        assert result.exit_code == 7
        # Rich soft-wraps at console width, so assert on short fragments only.
        assert "fetch-depth: 0" in result.output

    def test_fetched_but_shallow_base_ref_still_scopes(
        self, repo: Path, base: str, tmp_path: Path
    ) -> None:
        """Ref present, no merge base: must SUCCEED via two-dot, not exit 7."""
        _git(repo, "checkout", "-b", "feature")
        _migration(repo, "20260104000000", "delta", idempotent=False)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "delta")

        clone = tmp_path / "shallow2"
        subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--no-local",
                "--branch",
                "feature",
                f"file://{repo}",
                str(clone),
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "fetch", "--depth", "1", "origin", f"{base}:refs/remotes/origin/{base}"],
            cwd=clone,
            check=True,
            capture_output=True,
        )

        exit_code, payload = _run_json(
            clone / "db" / "migrations", "--base-ref", f"origin/{base}", cwd=clone
        )

        # POSITIVE: a real selection, not an exit 7 and not an empty scope.
        assert exit_code == 1
        assert payload["files_scanned"] == 1
        assert _basenames(payload) == {"20260104000000_delta.up.sql"}


class TestStagedScoping:
    """T4/D4: base..HEAD cannot see a pre-commit change; --staged can."""

    def test_staged_migration_is_validated(self, repo: Path) -> None:
        _migration(repo, "20260104000000", "delta", idempotent=False)
        _git(repo, "add", "-A")  # staged, NOT committed

        exit_code, payload = _run_json(repo / "db" / "migrations", "--staged", cwd=repo)

        assert payload["meta"]["scope"]["mode"] == "staged"
        assert payload["files_scanned"] == 1
        assert _basenames(payload) == {"20260104000000_delta.up.sql"}
        assert exit_code == 1
        assert payload["violation_count"] >= 1

    def test_staged_content_differs_from_worktree(self, repo: Path) -> None:
        """Stage a clean version, then dirty the tree: the INDEX is judged."""
        path = _migration(repo, "20260104000000", "delta", idempotent=True)
        _git(repo, "add", "-A")
        path.write_text(NON_IDEMPOTENT.format(name="delta"))  # worktree now dirty

        exit_code, payload = _run_json(repo / "db" / "migrations", "--staged", cwd=repo)

        assert payload["files_scanned"] == 1
        assert _basenames(payload) == {"20260104000000_delta.up.sql"}
        # The staged blob is idempotent, so this passes despite the dirty tree.
        assert exit_code == 0
        assert payload["violation_count"] == 0

    def test_staged_wins_over_base_ref(self, repo: Path, base: str) -> None:
        _git(repo, "checkout", "-b", "feature")
        _migration(repo, "20260104000000", "delta", idempotent=True)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "committed delta")
        _migration(repo, "20260105000000", "epsilon", idempotent=False)
        _git(repo, "add", "-A")  # staged only

        exit_code, payload = _run_json(
            repo / "db" / "migrations", "--staged", "--base-ref", base, cwd=repo
        )

        assert payload["meta"]["scope"]["mode"] == "staged"
        assert _basenames(payload) == {"20260105000000_epsilon.up.sql"}
        assert exit_code == 1


class TestDeletionsAndRenames:
    def test_deleted_migration_is_skipped(self, repo: Path, base: str) -> None:
        _git(repo, "checkout", "-b", "feature")
        _git(repo, "rm", "-q", "db/migrations/20260101000000_alpha.up.sql")
        _migration(repo, "20260104000000", "delta", idempotent=False)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "delete alpha, add delta")

        exit_code, payload = _run_json(repo / "db" / "migrations", "--base-ref", base, cwd=repo)

        # The deleted file is in the diff but not on disk: glob ∩ diff drops it.
        assert payload["files_scanned"] == 1
        assert _basenames(payload) == {"20260104000000_delta.up.sql"}
        assert exit_code == 1

    def test_renamed_migration_validates_new_path(self, repo: Path, base: str) -> None:
        _git(repo, "checkout", "-b", "feature")
        _git(
            repo,
            "mv",
            "db/migrations/20260101000000_alpha.up.sql",
            "db/migrations/20260104000000_alpha.up.sql",
        )
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "rename")

        exit_code, payload = _run_json(repo / "db" / "migrations", "--base-ref", base, cwd=repo)

        # --name-only reports a rename as delete+add; the new path is selected.
        assert payload["files_scanned"] == 1
        assert _basenames(payload) == {"20260104000000_alpha.up.sql"}
        assert exit_code == 0

    def test_changed_down_sql_alone_scopes_to_zero(self, repo: Path, base: str) -> None:
        _git(repo, "checkout", "-b", "feature")
        down = repo / "db" / "migrations" / "20260101000000_alpha.down.sql"
        down.write_text("DROP TABLE alpha;\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "down only")

        exit_code, payload = _run_json(repo / "db" / "migrations", "--base-ref", base, cwd=repo)

        assert exit_code == 0
        assert payload["meta"]["scope"]["files_selected"] == 0
        assert payload["meta"]["scope"]["files_skipped"] == 3


class TestZeroScopeReporting:
    def test_zero_changed_migrations_message_is_distinct(self, repo: Path, base: str) -> None:
        _git(repo, "checkout", "-b", "feature")
        (repo / "README.md").write_text("docs only\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "docs")

        exit_code, payload = _run_json(repo / "db" / "migrations", "--base-ref", base, cwd=repo)

        assert exit_code == 0
        assert payload["status"] == "ok"
        assert base in payload["message"]
        # Distinct from the empty-directory message — different remedies.
        assert "contains no files" not in payload["message"]
        assert payload["message"] != "No migration files found"

    def test_zero_scope_is_proven_real_not_an_artefact(self, repo: Path, base: str) -> None:
        """A deliberately-changed file WOULD be selected under the same ref.

        Without this, a zero could equally be T1/T2/T4 silently scanning nothing.
        """
        _git(repo, "checkout", "-b", "feature")
        (repo / "README.md").write_text("docs only\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "docs")

        _, zero = _run_json(repo / "db" / "migrations", "--base-ref", base, cwd=repo)
        assert zero["meta"]["scope"]["files_selected"] == 0

        _migration(repo, "20260104000000", "delta", idempotent=False)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "now a migration")

        exit_code, payload = _run_json(repo / "db" / "migrations", "--base-ref", base, cwd=repo)
        assert payload["files_scanned"] == 1
        assert _basenames(payload) == {"20260104000000_delta.up.sql"}
        assert exit_code == 1


class TestOutsideRepo:
    def test_dir_outside_repo_errors_clearly(self, repo: Path, tmp_path: Path) -> None:
        """A dir that can never intersect the diff must fail loud, not pass."""
        outside = tmp_path / "elsewhere" / "migrations"
        outside.mkdir(parents=True)
        (outside / "20260101000000_x.up.sql").write_text(NON_IDEMPOTENT.format(name="x"))

        import os

        prev = Path.cwd()
        os.chdir(repo)
        try:
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "validate",
                    "--idempotent",
                    "--migrations-dir",
                    str(outside),
                    "--base-ref",
                    _default_branch(repo),
                ],
            )
        finally:
            os.chdir(prev)

        assert result.exit_code != 0
        assert "outside the repository" in result.output

    def test_scoping_outside_a_git_repo_fails_loud(self, bare_dir: Path) -> None:
        """Explicit scoping in a non-git tree is an error, never a silent zero."""
        import os

        prev = Path.cwd()
        os.chdir(bare_dir.parent.parent)
        try:
            result = runner.invoke(
                app,
                [
                    "migrate",
                    "validate",
                    "--idempotent",
                    "--migrations-dir",
                    str(bare_dir),
                    "--base-ref",
                    "origin/main",
                ],
            )
        finally:
            os.chdir(prev)

        assert result.exit_code == 7


class TestFlagCombinationComposes:
    """`--idempotent --require-migration` runs both checks (0.41.0).

    0.37.0 rejected this combination outright, because the dispatch of the day
    ran the git branch and silently skipped idempotency — #181's own defect. A
    loud error was the right answer while that was true. Composition landed in
    0.40.0 and the guard came off one release later, so what has to be pinned
    now is not the rejection but the thing the rejection stood in for: the
    idempotency scan really runs, over a positive selection, next to the git
    check.
    """

    @pytest.fixture
    def git_double(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        """Stand in for the accompaniment check, recording that it ran.

        Patched on ``confiture.cli.git_validation`` because the git group
        imports the sub-checks lazily from there. Without the double the check
        would build an expected schema from real refs, which is
        ``test_cli_git_validation.py``'s job, not this file's.
        """
        ran: list[str] = []

        def fake_accompaniment(**_: object) -> dict[str, object]:
            ran.append("accompaniment")
            return {"is_valid": True, "violations": []}

        monkeypatch.setattr(
            "confiture.cli.git_validation.validate_migration_accompaniment",
            fake_accompaniment,
        )
        return ran

    def test_both_checks_run(self, repo: Path, git_double: list[str]) -> None:
        exit_code, payload = _run_json(repo / "db" / "migrations", "--require-migration", cwd=repo)

        assert git_double == ["accompaniment"], "the git check did not run"
        assert payload["checks"]["git_accompaniment"] == {
            "status": "passed",
            "checks": ["accompaniment"],
        }
        idempotent = payload["checks"]["idempotent"]
        assert idempotent["files_scanned"] == 3
        assert _basenames(idempotent) == {
            "20260101000000_alpha.up.sql",
            "20260102000000_beta.up.sql",
            "20260103000000_gamma.up.sql",
        }
        assert exit_code == 0

    def test_a_passing_git_check_does_not_mask_a_violation(
        self, repo: Path, git_double: list[str]
    ) -> None:
        """The failure mode the guard existed to prevent, now prevented by composing."""
        _migration(repo, "20260104000000", "delta", idempotent=False)

        exit_code, payload = _run_json(repo / "db" / "migrations", "--require-migration", cwd=repo)

        assert git_double == ["accompaniment"]
        assert payload["status"] == "failed"
        assert payload["checks"]["idempotent"]["violation_count"] >= 1
        assert "20260104000000_delta.up.sql" in _basenames(payload["checks"]["idempotent"])
        assert exit_code == 1
