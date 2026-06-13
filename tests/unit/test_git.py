"""Tests for Git integration module.

Tests git operations like file retrieval, changed file detection, and staging.
"""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from confiture.core.git import GitRepository
from confiture.exceptions import GitError, NotAGitRepositoryError


class TestGitRepository:
    """Tests for GitRepository class."""

    def test_is_git_repo_true(self):
        """Test detection of valid git repository."""
        with TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            # Initialize git repo
            import subprocess

            subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)

            git_repo = GitRepository(repo_path)
            assert git_repo.is_git_repo() is True

    def test_is_git_repo_false(self):
        """Test detection of non-git directory."""
        with TemporaryDirectory() as tmpdir:
            git_repo = GitRepository(Path(tmpdir))
            assert git_repo.is_git_repo() is False

    def test_get_file_at_ref_exists(self):
        """Test retrieving existing file from git ref."""
        with TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            import subprocess

            # Initialize git repo
            subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )

            # Create and commit a file
            test_file = repo_path / "test.sql"
            test_file.write_text("CREATE TABLE users (id INT);")
            subprocess.run(
                ["git", "add", "test.sql"], cwd=repo_path, check=True, capture_output=True
            )
            subprocess.run(
                ["git", "commit", "-m", "Initial commit"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )

            git_repo = GitRepository(repo_path)
            content = git_repo.get_file_at_ref(Path("test.sql"), "HEAD")
            assert content == "CREATE TABLE users (id INT);"

    def test_get_file_at_ref_not_found(self):
        """Test retrieving non-existent file from git ref returns None."""
        with TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            import subprocess

            # Initialize git repo with initial commit
            subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )

            # Create initial commit
            readme = repo_path / "README.md"
            readme.write_text("# Test")
            subprocess.run(
                ["git", "add", "README.md"], cwd=repo_path, check=True, capture_output=True
            )
            subprocess.run(
                ["git", "commit", "-m", "Initial commit"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )

            git_repo = GitRepository(repo_path)
            content = git_repo.get_file_at_ref(Path("nonexistent.sql"), "HEAD")
            assert content is None

    def test_get_changed_files(self):
        """Test detection of changed files between refs."""
        with TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            import subprocess

            # Initialize repo
            subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )

            # First commit
            (repo_path / "file1.sql").write_text("CREATE TABLE users (id INT);")
            subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "Initial"], cwd=repo_path, check=True, capture_output=True
            )

            # Second commit with change
            (repo_path / "file1.sql").write_text("CREATE TABLE users (id INT, email TEXT);")
            (repo_path / "file2.sql").write_text("CREATE TABLE posts (id INT);")
            subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "Add email column and posts table"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )

            git_repo = GitRepository(repo_path)
            changed_files = git_repo.get_changed_files("HEAD~1", "HEAD")

            # Should find both changed and new files
            assert len(changed_files) == 2
            assert Path("file1.sql") in changed_files
            assert Path("file2.sql") in changed_files

    def test_get_staged_files(self):
        """Test detection of staged files."""
        with TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            import subprocess

            # Initialize repo with initial commit
            subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )

            # Initial commit
            (repo_path / "README.md").write_text("# Test")
            subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "Initial"], cwd=repo_path, check=True, capture_output=True
            )

            # Create and stage files
            (repo_path / "file1.sql").write_text("CREATE TABLE users (id INT);")
            (repo_path / "file2.sql").write_text("CREATE TABLE posts (id INT);")
            subprocess.run(
                ["git", "add", "file1.sql", "file2.sql"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )

            git_repo = GitRepository(repo_path)
            staged_files = git_repo.get_staged_files()

            assert len(staged_files) == 2
            assert Path("file1.sql") in staged_files
            assert Path("file2.sql") in staged_files

    def test_not_a_git_repo_error(self):
        """Test error when git operations called on non-git directory."""
        with TemporaryDirectory() as tmpdir:
            git_repo = GitRepository(Path(tmpdir))

            with pytest.raises(NotAGitRepositoryError):
                git_repo.get_file_at_ref(Path("test.sql"), "HEAD")

    def test_git_error_on_invalid_ref(self):
        """Test error when git ref is invalid."""
        with TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            import subprocess

            # Initialize repo
            subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )

            # Create initial commit
            (repo_path / "README.md").write_text("# Test")
            subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "Initial"], cwd=repo_path, check=True, capture_output=True
            )

            git_repo = GitRepository(repo_path)

            with pytest.raises(GitError):
                git_repo.get_file_at_ref(Path("test.sql"), "nonexistent_ref")


def _run(repo_path: Path, *args: str) -> str:
    import subprocess

    result = subprocess.run(
        ["git", *args], cwd=repo_path, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _init_repo(repo_path: Path) -> None:
    _run(repo_path, "init")
    _run(repo_path, "config", "user.email", "test@test.com")
    _run(repo_path, "config", "user.name", "Test User")
    _run(repo_path, "config", "commit.gpgsign", "false")


class TestGitPlumbingIssue162:
    """Tests for the merge-base + staged-content plumbing (issue #162, Phase 3)."""

    def test_get_staged_file_content_returns_staged_blob(self):
        """Staged content is the index blob, not the (dirtier) working tree."""
        with TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            _init_repo(repo_path)
            f = repo_path / "g.sql"
            f.write_text("GRANT SELECT ON s.t TO r;\n")
            _run(repo_path, "add", "g.sql")
            # Working tree diverges from the index after staging.
            f.write_text("GRANT SELECT ON s.t TO r;\nGRANT INSERT ON s.t TO r;\n")

            git_repo = GitRepository(repo_path)
            staged = git_repo.get_staged_file_content(Path("g.sql"))
            assert staged == "GRANT SELECT ON s.t TO r;\n"

    def test_get_staged_file_content_none_when_not_staged(self):
        with TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            _init_repo(repo_path)
            (repo_path / "README.md").write_text("# Test")
            _run(repo_path, "add", ".")
            _run(repo_path, "commit", "-m", "init")

            git_repo = GitRepository(repo_path)
            assert git_repo.get_staged_file_content(Path("absent.sql")) is None

    def test_get_merge_base_returns_common_ancestor(self):
        """merge-base must be the fork point, not the tip of base."""
        with TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            _init_repo(repo_path)
            (repo_path / "a.txt").write_text("1")
            _run(repo_path, "add", ".")
            _run(repo_path, "commit", "-m", "c1")
            fork_point = _run(repo_path, "rev-parse", "HEAD")
            _run(repo_path, "branch", "feature")

            # Advance main (base) past the fork point.
            (repo_path / "a.txt").write_text("2")
            _run(repo_path, "commit", "-am", "c2-on-main")

            # Commit on the feature branch.
            _run(repo_path, "checkout", "feature")
            (repo_path / "b.txt").write_text("1")
            _run(repo_path, "add", ".")
            _run(repo_path, "commit", "-m", "c3-on-feature")

            git_repo = GitRepository(repo_path)
            mb = git_repo.get_merge_base("master", "feature")
            # Some git versions default the initial branch to "main".
            if mb is None or mb == "master":
                mb = git_repo.get_merge_base("main", "feature")
            assert mb == fork_point

    def test_get_merge_base_falls_back_on_unrelated_histories(self):
        """Unrelated histories have no merge-base → fall back to base_ref."""
        with TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            _init_repo(repo_path)
            (repo_path / "a.txt").write_text("1")
            _run(repo_path, "add", ".")
            _run(repo_path, "commit", "-m", "c1")
            # Orphan branch — a second root with no common ancestor.
            _run(repo_path, "checkout", "--orphan", "orphan")
            (repo_path / "c.txt").write_text("1")
            _run(repo_path, "add", ".")
            _run(repo_path, "commit", "-m", "orphan-root")

            git_repo = GitRepository(repo_path)
            base = git_repo.get_merge_base("master", "orphan")
            base = base if base not in (None, "master") else git_repo.get_merge_base("main", "orphan")
            assert base in ("master", "main")
