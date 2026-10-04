"""Whether a build order survived a renumbering: the build's selection at a git ref against the working tree.

A renumbering that arrives by merge, by vendoring or by a hand ``git mv`` is not
made by ``generate renumber``, which checks its own moves. This compares what
``build --list-files`` selects at a ref with what it selects now: renamed files
are paired through git's rename detection, so a rename is one file and not a
delete plus an add, and only the files whose *relative* order moved are
reported — the fewest files whose move explains the change.

Both sides are the build's own answer. The ref's tree is extracted with
``git archive`` into a temporary directory (nothing in the repository is
written) and :meth:`SchemaBuilder.selection_report` runs there, reading the
environment file the ref holds.
"""

import bisect
import io
import subprocess
import tarfile
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from confiture.core.builder import SchemaBuilder
from confiture.core.git import GitRepository, validate_ref
from confiture.exceptions import ConfigurationError, GitError

#: Seconds a git command may take: an archive of a large repository is the slow one.
_GIT_TIMEOUT = 120


@dataclass(frozen=True)
class Move:
    """A file whose place among the others changed, with its neighbours on each side.

    Attributes:
        path: The file, by its name in the working tree.
        was_after: The file before it at the ref (``None`` when it was first).
        was_before: The file after it at the ref (``None`` when it was last).
        now_after: The file before it now.
        now_before: The file after it now.
    """

    path: str
    was_after: str | None
    was_before: str | None
    now_after: str | None
    now_before: str | None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "path": self.path,
            "was_after": self.was_after,
            "was_before": self.was_before,
            "now_after": self.now_after,
            "now_before": self.now_before,
        }


@dataclass(frozen=True)
class OrderComparison:
    """Two build orders compared.

    Attributes:
        files: How many files the working tree's build selects.
        renamed: ``(at the ref, now)`` for each renamed file selected on both sides.
        added: Selected now and not at the ref (by name, after pairing renames).
        removed: Selected at the ref and not now.
        moved: The files whose relative order changed, in working-tree order.
        allowed: The moved files an ``--allow`` names.
    """

    files: int
    renamed: tuple[tuple[str, str], ...]
    added: tuple[str, ...]
    removed: tuple[str, ...]
    moved: tuple[Move, ...]
    allowed: tuple[str, ...]

    @property
    def refused(self) -> tuple[Move, ...]:
        """The moves no ``--allow`` names: what makes the comparison fail."""
        return tuple(move for move in self.moved if move.path not in self.allowed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "files": self.files,
            "renamed": [{"from": old, "to": new} for old, new in self.renamed],
            "added": list(self.added),
            "removed": list(self.removed),
            "moved": [move.to_dict() for move in self.moved],
            "allowed": list(self.allowed),
        }


def _longest_increasing(values: Sequence[int]) -> set[int]:
    """The indexes of one longest strictly increasing subsequence of *values*."""
    tails: list[int] = []  # the smallest tail value of an increasing run of each length
    tail_index: list[int] = []
    previous: list[int | None] = []
    for index, value in enumerate(values):
        length = bisect.bisect_left(tails, value)
        if length == len(tails):
            tails.append(value)
            tail_index.append(index)
        else:
            tails[length] = value
            tail_index[length] = index
        previous.append(tail_index[length - 1] if length else None)
    kept: set[int] = set()
    cursor = tail_index[-1] if tail_index else None
    while cursor is not None:
        kept.add(cursor)
        cursor = previous[cursor]
    return kept


def _neighbours(order: Sequence[str], position: int) -> tuple[str | None, str | None]:
    before = order[position - 1] if position > 0 else None
    after = order[position + 1] if position + 1 < len(order) else None
    return before, after


def compare_orders(
    old: Sequence[str],
    new: Sequence[str],
    renames: Mapping[str, str],
    allow: Iterable[str] = (),
) -> OrderComparison:
    """Compare the order *old* (at the ref) with *new* (now), pairing *renames*.

    Over the files on both sides, the files kept in place are one longest run
    whose new positions increase in old order; every other common file moved.
    A move's neighbours are read among the common files, each side by its own
    names. Added and removed files are counted, never moves.

    Args:
        old: The selection at the ref, in build order.
        new: The selection now, in build order.
        renames: ``{name at the ref: name now}`` (git's rename detection).
        allow: Reviewed moves, each named exactly by its name now or at the ref.

    Returns:
        The comparison.
    """
    new_set = set(new)
    as_now = {path: renames.get(path, path) for path in old}
    paired = {path: now for path, now in as_now.items() if now in new_set}
    was = {now: path for path, now in paired.items()}

    old_common = [path for path in old if path in paired]
    new_common = [path for path in new if path in was]
    position = {path: index for index, path in enumerate(new_common)}
    kept = _longest_increasing([position[paired[path]] for path in old_common])
    moved_now = {paired[path] for index, path in enumerate(old_common) if index not in kept}
    old_position = {path: index for index, path in enumerate(old_common)}

    moves = []
    for index, path in enumerate(new_common):
        if path not in moved_now:
            continue
        was_after, was_before = _neighbours(old_common, old_position[was[path]])
        now_after, now_before = _neighbours(new_common, index)
        moves.append(Move(path, was_after, was_before, now_after, now_before))

    allowed_names = set(allow)
    return OrderComparison(
        files=len(new),
        renamed=tuple(
            (path, paired[path]) for path in old if path in paired and paired[path] != path
        ),
        added=tuple(path for path in new if path not in was),
        removed=tuple(path for path in old if path not in paired),
        moved=tuple(moves),
        allowed=tuple(move.path for move in moves if {move.path, was[move.path]} & allowed_names),
    )


def _git(repo_root: Path, *args: str) -> bytes:
    """Run git in *repo_root*; its stdout, or a ``GitError`` carrying its stderr."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            timeout=_GIT_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise GitError(f"git {args[0]} timed out after {_GIT_TIMEOUT}s") from e
    if result.returncode != 0:
        raise GitError(f"git {args[0]} failed: {result.stderr.decode(errors='replace').strip()}")
    return result.stdout


def _repository(project_dir: Path, ref: str) -> Path:
    """The root of the repository *project_dir* is in, once *ref* is known to name a commit."""
    validate_ref(ref)
    repo = GitRepository(project_dir)
    repo.require_ref(ref)
    return repo.get_repo_root().resolve()


def _named(path: Path, roots: Sequence[Path]) -> str:
    """*path* relative to the first of *roots* it is under; absolute when under none."""
    resolved = path.resolve()
    for root in roots:
        if resolved.is_relative_to(root):
            return resolved.relative_to(root).as_posix()
    return resolved.as_posix()


def _selection(project_dir: Path, env: str, roots: Sequence[Path]) -> list[str]:
    report = SchemaBuilder(env, project_dir=project_dir).selection_report()
    return [_named(selected.path, roots) for selected in report.files]


def selection_here(project_dir: Path, env: str) -> list[str]:
    """What ``build --list-files`` selects in the working tree, named relative to the repository root."""
    root = GitRepository(project_dir).get_repo_root().resolve()
    return _selection(project_dir, env, [root])


def _extract(archive: bytes, into: Path) -> None:
    """Unpack a ``git archive`` tarball; a member the ``data`` filter refuses is left out.

    That filter refuses a symlink that leaves the tree and a path that does;
    neither can be a file the ref's build reads from inside it.
    """
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar:
            try:
                tar.extract(member, into, filter="data")
            except tarfile.FilterError:
                continue


def selection_at_ref(project_dir: Path, env: str, ref: str) -> list[str]:
    """What ``build --list-files`` selected at *ref*, named relative to the repository root.

    Args:
        project_dir: The project, in the working tree (any directory in the repository).
        env: The environment whose file, as the ref holds it, makes the selection.
        ref: A git revision.

    Returns:
        The ref's selection in build order.

    Raises:
        GitError: *ref* is option-shaped or names no commit, or git failed.
        ConfigurationError: The ref has no environment file *env*.
    """
    root = _repository(project_dir, ref)
    relative = project_dir.resolve().relative_to(root)
    with tempfile.TemporaryDirectory(prefix="confiture-compare-") as scratch:
        tree = Path(scratch).resolve()
        _extract(_git(root, "archive", "--format=tar", ref), tree)
        at_ref = tree / relative
        env_file = (relative / "db" / "environments" / f"{env}.yaml").as_posix()
        if not (at_ref / "db" / "environments" / f"{env}.yaml").is_file():
            raise ConfigurationError(
                f"{env_file} does not exist at {ref}",
                resolution_hint="Compare against a ref that tracks the environment file, "
                "or commit it.",
            )
        return _selection(at_ref, env, [tree, root])


def renames_since(project_dir: Path, ref: str) -> dict[str, str]:
    """``{path at ref: path now}`` for each file git's rename detection pairs, ref against the working tree.

    A rename git sees is a tracked one: a moved file it has not been told of
    (``mv`` without ``git add``) is a removal and an untracked file.
    """
    root = _repository(project_dir, ref)
    fields = _git(root, "diff", "-M", "--name-status", "-z", ref, "--").decode().split("\0")
    renames: dict[str, str] = {}
    index = 0
    while index < len(fields) and fields[index]:
        status = fields[index]
        if status.startswith("R"):
            renames[fields[index + 1]] = fields[index + 2]
            index += 3
        else:
            index += 2
    return renames


def compare_to_ref(
    project_dir: Path, env: str, ref: str, allow: Iterable[str] = ()
) -> OrderComparison:
    """The build order at *ref* against the working tree's, renames paired.

    Args:
        project_dir: The project, in the working tree.
        env: The environment both sides select for, each reading its own file.
        ref: A git revision.
        allow: Reviewed moves, named relative to the repository root.

    Returns:
        The comparison.

    Raises:
        GitError: *ref* is option-shaped or names no commit, or git failed.
        ConfigurationError: An environment file is missing on either side.
    """
    validate_ref(ref)
    return compare_orders(
        selection_at_ref(project_dir, env, ref),
        selection_here(project_dir, env),
        renames_since(project_dir, ref),
        allow,
    )
