"""`GitRepository.get_repo_root()` — the T2 fix for #181.

`repo_path` is the subprocess cwd, not the repository root (it defaults to
`Path.cwd()`), while `git diff --name-only` reports paths relative to the
*root* regardless of cwd. Joining diff output onto `repo_path` therefore
produces garbage from any subdirectory — an ordinary monorepo layout — and the
resulting empty intersection reads as a passing gate.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from confiture.core.git import GitRepository
from confiture.exceptions import NotAGitRepositoryError


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "t@t.com")
    _git(root, "config", "user.name", "t")
    (root / "backend" / "db").mkdir(parents=True)
    (root / "backend" / "db" / "x.sql").write_text("SELECT 1;")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "base")
    return root


def test_get_repo_root_from_root(repo: Path) -> None:
    assert GitRepository(repo).get_repo_root().resolve() == repo.resolve()


def test_get_repo_root_from_subdirectory(repo: Path) -> None:
    """The whole point: from a subdir, the ROOT comes back — not the subdir."""
    subdir = repo / "backend" / "db"

    root = GitRepository(subdir).get_repo_root()

    assert root.resolve() == repo.resolve()
    assert root.resolve() != subdir.resolve()


def test_repo_path_is_not_the_root_from_a_subdirectory(repo: Path) -> None:
    """Pins the distinction the docstring used to get wrong."""
    subdir = repo / "backend" / "db"
    git_repo = GitRepository(subdir)

    assert git_repo.repo_path.resolve() == subdir.resolve()
    assert git_repo.get_repo_root().resolve() == repo.resolve()


def test_diff_paths_resolve_against_root_not_repo_path(repo: Path) -> None:
    """The end-to-end invariant that T2 broke."""
    base = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    _git(repo, "checkout", "-b", "feature")
    (repo / "backend" / "db" / "y.sql").write_text("SELECT 2;")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "y")

    from_subdir = GitRepository(repo / "backend" / "db")
    changed = from_subdir.get_changed_files_two_dot(base, "HEAD")

    assert changed == [Path("backend/db/y.sql")]
    resolved = [(from_subdir.get_repo_root() / p).resolve() for p in changed]
    assert resolved == [(repo / "backend" / "db" / "y.sql").resolve()]
    # The buggy form would have produced <repo>/backend/db/backend/db/y.sql.
    assert all(p.exists() for p in resolved)


def test_get_repo_root_outside_a_repo(tmp_path: Path) -> None:
    with pytest.raises(NotAGitRepositoryError):
        GitRepository(tmp_path).get_repo_root()
