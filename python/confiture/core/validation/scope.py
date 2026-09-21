"""Which migrations a git-scoped check reads: the ones changed on this branch, or staged (#181)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from confiture.core.git import GitRepository
from confiture.exceptions import ConfigurationError, NotAGitRepositoryError


def scope_to_git(
    candidates: list[Path],
    migrations_dir: Path,
    *,
    base_ref: str | None,
    staged: bool,
) -> tuple[list[Path], dict[str, Any]]:
    """Narrow ``candidates`` to the files changed on this branch or staged (#181).

    Intersects **glob ∩ diff** rather than iterating the diff, which makes
    deletions safe by construction: a deleted migration appears in the diff but
    not in the glob, so it is never handed to the analyzer.

    Args:
        candidates: The full globbed file set (already on disk).
        migrations_dir: The directory those files were globbed from.
        base_ref: Git ref to scope against, or None when ``staged``.
        staged: Scope to the staging index instead of a ref comparison.

    Returns:
        ``(selected_files, scope_meta)``.

    Raises:
        GitError: ``GIT_003`` when the base ref is unreachable in this
            checkout, or the diff cannot be computed.
        NotAGitRepositoryError: ``GIT_002`` when not in a git repository.
        ConfigurationError: When ``migrations_dir`` lies outside the repository,
            where the intersection could only ever be empty.
    """

    repo = GitRepository()
    if not repo.is_git_repo():
        raise NotAGitRepositoryError(
            f"Not a git repository: {Path.cwd()}",
            resolution_hint=(
                "--base-ref/--since/--staged scope against git history. Run from "
                "inside a repository, or drop the flag to scan every migration."
            ),
        )

    # `git diff --name-only` reports paths relative to the repository ROOT
    # regardless of the directory git runs in, so they must be resolved against
    # the root — not against cwd. Getting this wrong yields an empty
    # intersection and a green gate that scanned nothing.
    repo_root = repo.get_repo_root().resolve()

    resolved_dir = migrations_dir.resolve()
    if not resolved_dir.is_relative_to(repo_root):
        raise ConfigurationError(
            f"Cannot scope by git: migrations directory {resolved_dir} is outside "
            f"the repository at {repo_root}",
            error_code="CONFIG_004",
            resolution_hint=(
                "Point --migrations-dir at a directory inside the repository, or "
                "drop --base-ref/--since/--staged to scan every migration."
            ),
        )

    scope_meta: dict[str, Any]
    if staged or base_ref is None:
        changed = repo.get_staged_files()
        scope_meta = {"mode": "staged"}
    else:
        # Preflight the ref so an unfetched origin/main names its own remedy
        # rather than surfacing git's wording.
        repo.require_ref(base_ref)
        # Merge-base + two-dot rather than three-dot: equivalent whenever a
        # merge base exists, and survives shallow clones, where three-dot fails
        # with "no merge base". get_merge_base already degrades to base_ref.
        anchor = repo.get_merge_base(base_ref, "HEAD") or base_ref
        changed = repo.get_changed_files_two_dot(anchor, "HEAD")
        scope_meta = {"mode": "base-ref", "base_ref": base_ref}

    changed_abs = {(repo_root / path).resolve() for path in changed}
    selected = [path for path in candidates if path.resolve() in changed_abs]

    scope_meta["files_selected"] = len(selected)
    scope_meta["files_skipped"] = len(candidates) - len(selected)
    return selected, scope_meta


def read_staged_content(paths: list[Path]) -> dict[Path, str]:
    """Read each path's blob from the staging index (``git show :<path>``).

    The index blob is what is about to be committed; it differs from the
    working tree whenever a file was staged and then edited further. A
    pre-commit gate must judge the former.
    """

    repo = GitRepository()
    repo_root = repo.get_repo_root().resolve()

    content: dict[Path, str] = {}
    for path in paths:
        rel = path.resolve().relative_to(repo_root)
        blob = repo.get_staged_file_content(rel)
        if blob is not None:
            content[path] = blob
    return content
