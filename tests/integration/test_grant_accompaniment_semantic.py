"""Integration tests for the semantic grant-accompaniment engine (issue #162).

These drive ``GrantAccompanimentChecker`` against a *real* git repository so
the file-content diffing, the merge-base anchoring (D10), and the
``.py``-at-ref read (D11) are exercised end to end — none of which MagicMock
can prove.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from confiture.core.grant_accompaniment import GrantAccompanimentChecker


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _init(repo: Path) -> None:
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@t.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "db" / "7_grant").mkdir(parents=True)
    (repo / "db" / "migrations").mkdir(parents=True)


def _write(repo: Path, rel: str, content: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _default_branch(repo: Path) -> str:
    return _git(repo, "rev-parse", "--abbrev-ref", "HEAD")


@pytest.fixture
def repo():
    with TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class TestSemanticAccompanimentRefMode:
    def test_matching_grant_in_migration_passes(self, repo: Path):
        _init(repo)
        _write(repo, "README.md", "# r")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "init")
        base = _default_branch(repo)

        _git(repo, "checkout", "-b", "feature")
        _write(repo, "db/7_grant/71_grant.sql", "GRANT SELECT ON s.t TO reporter;\n")
        _write(
            repo,
            "db/migrations/20260613130000_x.up.sql",
            "GRANT SELECT ON s.t TO reporter;\n",
        )
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "grant + migration")

        checker = GrantAccompanimentChecker(repo_path=repo)
        report = checker.check_accompaniment(base_ref=base, target_ref="feature")
        assert report.is_valid is True
        assert report.unmatched_grants == []

    def test_missing_grant_in_migration_fails(self, repo: Path):
        _init(repo)
        _write(repo, "README.md", "# r")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "init")
        base = _default_branch(repo)

        _git(repo, "checkout", "-b", "feature")
        _write(repo, "db/7_grant/71_grant.sql", "GRANT SELECT ON s.t TO reporter;\n")
        _write(
            repo,
            "db/migrations/20260613130000_x.up.sql",
            "GRANT SELECT ON other.tbl TO someone;\n",
        )
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "grant + wrong migration")

        checker = GrantAccompanimentChecker(repo_path=repo)
        report = checker.check_accompaniment(base_ref=base, target_ref="feature")
        assert report.is_valid is False
        assert len(report.unmatched_grants) == 1
        assert report.unmatched_grants[0]["grantee"] == "reporter"

    def test_python_migration_carries_grant_at_ref(self, repo: Path):
        """D11: the .py covered-set is read from the committed ref."""
        _init(repo)
        _write(repo, "README.md", "# r")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "init")
        base = _default_branch(repo)

        _git(repo, "checkout", "-b", "feature")
        _write(repo, "db/7_grant/71_grant.sql", "GRANT SELECT ON s.t TO reporter;\n")
        _write(
            repo,
            "db/migrations/20260613130000_x.py",
            "from confiture import Migration\n"
            "class M(Migration):\n"
            "    def up(self):\n"
            "        self.execute('GRANT SELECT ON s.t TO reporter;')\n",
        )
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "grant + py migration")

        checker = GrantAccompanimentChecker(repo_path=repo)
        report = checker.check_accompaniment(base_ref=base, target_ref="feature")
        assert report.is_valid is True
        assert report.unmatched_grants == []

    def test_merge_base_anchoring_ignores_post_fork_base_grant(self, repo: Path):
        """D10: a grant added on base *after* the fork must not be 'required'.

        Three commits: fork point, a grant added on base after it, and a
        feature branch that touches an unrelated file. The feature branch
        introduces no grant change of its own, so the gate must pass — the
        base-side grant lives past the merge-base and must not leak into the
        required set as a phantom unaccompanied grant.
        """
        _init(repo)
        _write(repo, "db/7_grant/71_grant.sql", "GRANT SELECT ON s.a TO r;\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "fork point")
        base = _default_branch(repo)

        # Feature branch forks here and changes only an unrelated file.
        _git(repo, "checkout", "-b", "feature")
        _write(repo, "db/migrations/README.md", "notes")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "unrelated change on feature")

        # Base advances past the fork with a brand-new grant (no migration).
        _git(repo, "checkout", base)
        _write(
            repo,
            "db/7_grant/71_grant.sql",
            "GRANT SELECT ON s.a TO r;\nGRANT SELECT ON s.b TO r;\n",
        )
        _git(repo, "commit", "-am", "add grant on base after fork")

        checker = GrantAccompanimentChecker(repo_path=repo)
        report = checker.check_accompaniment(base_ref=base, target_ref="feature")

        # If the diff anchored on the base *tip* (not the merge-base), the
        # s.a-vs-{s.a,s.b} delta would surface s.b as removed/required and the
        # branch would spuriously fail. Merge-base anchoring sees no grant
        # change on the feature branch at all.
        assert report.has_grant_changes is False
        assert report.is_valid is True

    def test_unmodeled_grant_without_migration_fails(self, repo: Path):
        """D9 end-to-end: an unmodeled object class degrades and fails sans migration."""
        _init(repo)
        _write(repo, "README.md", "# r")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "init")
        base = _default_branch(repo)

        _git(repo, "checkout", "-b", "feature")
        _write(repo, "db/7_grant/71_grant.sql", "GRANT CONNECT ON DATABASE app TO reporter;\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "database grant, no migration")

        checker = GrantAccompanimentChecker(repo_path=repo)
        report = checker.check_accompaniment(base_ref=base, target_ref="feature")
        assert report.is_valid is False
        assert report.unverifiable_notes


class TestSemanticAccompanimentStagedMode:
    def test_staged_match_passes(self, repo: Path):
        _init(repo)
        _write(repo, "README.md", "# r")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "init")

        _write(repo, "db/7_grant/71_grant.sql", "GRANT SELECT ON s.t TO reporter;\n")
        _write(
            repo,
            "db/migrations/20260613130000_x.up.sql",
            "GRANT SELECT ON s.t TO reporter;\n",
        )
        _git(repo, "add", "db/7_grant/71_grant.sql", "db/migrations/20260613130000_x.up.sql")

        checker = GrantAccompanimentChecker(repo_path=repo)
        report = checker.check_accompaniment(staged_only=True)
        assert report.is_valid is True
        assert report.unmatched_grants == []

    def test_staged_mismatch_fails(self, repo: Path):
        _init(repo)
        _write(repo, "README.md", "# r")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "init")

        _write(repo, "db/7_grant/71_grant.sql", "GRANT SELECT ON s.t TO reporter;\n")
        _write(
            repo,
            "db/migrations/20260613130000_x.up.sql",
            "GRANT INSERT ON s.t TO reporter;\n",
        )
        _git(repo, "add", "db/7_grant/71_grant.sql", "db/migrations/20260613130000_x.up.sql")

        checker = GrantAccompanimentChecker(repo_path=repo)
        report = checker.check_accompaniment(staged_only=True)
        assert report.is_valid is False
        assert len(report.unmatched_grants) == 1
