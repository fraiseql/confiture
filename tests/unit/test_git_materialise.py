"""``GitRepository.materialise``: a ref's tree, copied safely into a scratch directory.

Hostile trees are written with ``git mktree`` — a tree git would never check out
can still be fetched, and the copy must write nothing outside its destination.
"""

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from confiture.core import git as git_module
from confiture.core.git import GitRepository
from confiture.exceptions import GitError

BLOB = "100644"
LINK = "120000"


def _git(repo: Path, *args: str, stdin: bytes | None = None) -> str:
    return (
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, input=stdin)
        .stdout.decode()
        .strip()
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t.com")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "core.autocrlf", "false")
    return root


def _blob(repo: Path, content: bytes) -> str:
    return _git(repo, "hash-object", "-w", "--stdin", stdin=content)


def _tree(repo: Path, entries: Mapping[str, tuple[str, str]]) -> str:
    """A tree holding *entries* (``path → (mode, oid)``), nested by ``/``; nothing is validated."""
    here: list[str] = []
    below: dict[str, dict[str, tuple[str, str]]] = {}
    for path, (mode, oid) in entries.items():
        head, _, rest = path.partition("/")
        if rest:
            below.setdefault(head, {})[rest] = (mode, oid)
        else:
            kind = "commit" if mode == "160000" else "blob"
            here.append(f"{mode} {kind} {oid}\t{head}")
    here.extend(f"040000 tree {_tree(repo, sub)}\t{name}" for name, sub in below.items())
    return _git(repo, "mktree", "--missing", stdin=("\n".join(here) + "\n").encode())


def _files(repo: Path, files: Mapping[str, bytes]) -> str:
    return _tree(repo, {path: (BLOB, _blob(repo, data)) for path, data in files.items()})


def _commit_files(repo: Path, files: Mapping[str, bytes]) -> None:
    for name, data in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_bytes(data)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "c")


def _everything_under(path: Path) -> list[str]:
    return sorted(p.relative_to(path).as_posix() for p in path.rglob("*"))


def _schema(repo: Path) -> list[Path]:
    return [repo / "db" / "schema"]


def test_blobs_arrive_as_written(repo: Path, tmp_path: Path) -> None:
    (repo / ".gitattributes").write_text("*.sql -text\n")
    _commit_files(repo, {"db/schema/a.sql": b"-- a\r\nSELECT 1;\r\n"})
    dest = tmp_path / "out" / "repo"

    GitRepository(repo).materialise("HEAD", _schema(repo), dest)

    assert (dest / "db/schema/a.sql").read_bytes() == b"-- a\r\nSELECT 1;\r\n"


def test_reads_a_tree_oid(repo: Path, tmp_path: Path) -> None:
    tree = _files(repo, {"db/schema/a.sql": b"-- a\n"})
    dest = tmp_path / "out" / "repo"

    assert GitRepository(repo).materialise(tree, _schema(repo), dest) == tree
    assert _everything_under(dest) == ["db", "db/schema", "db/schema/a.sql"]


def test_returns_the_tree_a_commit_holds(repo: Path, tmp_path: Path) -> None:
    _commit_files(repo, {"db/schema/a.sql": b"-- a\n"})

    oid = GitRepository(repo).materialise("HEAD", _schema(repo), tmp_path / "out" / "repo")

    assert oid == _git(repo, "rev-parse", "HEAD^{tree}")


def test_only_the_paths_asked_for_are_copied(repo: Path, tmp_path: Path) -> None:
    tree = _files(repo, {"db/schema/a.sql": b"-- a\n", "db/schema2/b.sql": b"-- b\n"})
    dest = tmp_path / "out" / "repo"

    GitRepository(repo).materialise(tree, _schema(repo), dest)

    assert _everything_under(dest) == ["db", "db/schema", "db/schema/a.sql"]


def test_none_copies_the_whole_tree(repo: Path, tmp_path: Path) -> None:
    tree = _files(repo, {"db/schema/a.sql": b"-- a\n", "README": b"r\n"})
    dest = tmp_path / "out" / "repo"

    GitRepository(repo).materialise(tree, None, dest)

    assert _everything_under(dest) == ["README", "db", "db/schema", "db/schema/a.sql"]


def test_path_absent_at_ref_is_skipped(repo: Path, tmp_path: Path) -> None:
    tree = _files(repo, {"db/schema/a.sql": b"-- a\n"})
    dest = tmp_path / "out" / "repo"

    GitRepository(repo).materialise(tree, [repo / "db" / "seeds", *_schema(repo)], dest)

    assert _everything_under(dest) == ["db", "db/schema", "db/schema/a.sql"]


def test_an_unknown_ref_is_a_git_error(repo: Path, tmp_path: Path) -> None:
    _commit_files(repo, {"db/schema/a.sql": b"-- a\n"})

    with pytest.raises(GitError, match="nope"):
        GitRepository(repo).materialise("nope", _schema(repo), tmp_path / "out" / "repo")


@pytest.mark.parametrize("component", ["..", ".git", ".GIT", "."])
def test_a_hostile_component_is_refused(repo: Path, tmp_path: Path, component: str) -> None:
    tree = _files(repo, {f"db/schema/{component}/x.sql": b"-- x\n"})
    dest = tmp_path / "out" / "repo"

    with pytest.raises(GitError, match="refused") as caught:
        GitRepository(repo).materialise(tree, _schema(repo), dest)

    assert caught.value.error_code == "GIT_001"
    assert not (tmp_path / "out" / "x.sql").exists()
    assert not dest.exists()


def test_dotdot_component_is_refused(repo: Path, tmp_path: Path) -> None:
    tree = _files(repo, {"db/schema/../../x.sql": b"-- x\n"})

    with pytest.raises(GitError, match=r"db/schema/\.\./\.\./x\.sql"):
        GitRepository(repo).materialise(tree, _schema(repo), tmp_path / "out" / "repo")

    assert not (tmp_path / "out" / "x.sql").exists()


def test_dot_git_component_is_refused(repo: Path, tmp_path: Path) -> None:
    tree = _files(repo, {"db/schema/.GIT/hooks/pre-commit": b"#!/bin/sh\n"})

    with pytest.raises(GitError, match=r"\.GIT"):
        GitRepository(repo).materialise(tree, _schema(repo), tmp_path / "out" / "repo")


def test_unknown_mode_is_refused() -> None:
    # git canonicalises a file's mode when it lists a tree, so a mode it does not
    # know reaches the reader only from a listing git itself would not write.
    listing = b"100664 blob " + b"0" * 40 + b"\tdb/schema/a.sql\0"

    with pytest.raises(GitError, match="100664"):
        git_module._tree_entries(listing, "HEAD")


def test_submodule_is_refused(repo: Path, tmp_path: Path) -> None:
    _commit_files(repo, {"README": b"r\n"})
    head = _git(repo, "rev-parse", "HEAD")
    tree = _tree(repo, {"db/schema/vendored": ("160000", head)})

    with pytest.raises(GitError, match="submodule"):
        GitRepository(repo).materialise(tree, _schema(repo), tmp_path / "out" / "repo")


@pytest.mark.parametrize(
    "names", [("a.sql", "a.sql"), ("A.sql", "a.sql")], ids=["equal", "casefold"]
)
def test_duplicate_and_casefold_paths_are_refused(
    repo: Path, tmp_path: Path, names: tuple[str, str]
) -> None:
    oid = _blob(repo, b"-- a\n")
    entries = "".join(f"{BLOB} blob {oid}\t{name}\n" for name in names)
    schema = _git(repo, "mktree", stdin=entries.encode())
    db = _git(repo, "mktree", stdin=f"040000 tree {schema}\tschema\n".encode())
    tree = _git(repo, "mktree", stdin=f"040000 tree {db}\tdb\n".encode())

    with pytest.raises(GitError, match="collide"):
        GitRepository(repo).materialise(tree, _schema(repo), tmp_path / "out" / "repo")


def test_write_through_symlinked_parent_is_refused(repo: Path, tmp_path: Path) -> None:
    outside = tmp_path / "x"
    outside.mkdir()
    tree = _tree(
        repo,
        {
            "db/schema": (LINK, _blob(repo, str(outside).encode())),
            "db/schema/a.sql": (BLOB, _blob(repo, b"-- a\n")),
        },
    )

    with pytest.raises(GitError, match="refused"):
        GitRepository(repo).materialise(tree, [repo / "db"], tmp_path / "out" / "repo")

    assert list(outside.iterdir()) == []


def test_a_parent_that_resolves_outside_is_refused(tmp_path: Path) -> None:
    dest = tmp_path / "out" / "repo"
    (dest / "db").mkdir(parents=True)
    outside = tmp_path / "x"
    outside.mkdir()
    (dest / "db" / "schema").symlink_to(outside)

    with pytest.raises(GitError, match="outside"):
        git_module._place(dest, "db/schema/a.sql", b"-- a\n", executable=False)

    assert list(outside.iterdir()) == []


def test_regular_files_are_written_before_symlinks(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = _tree(
        repo,
        {
            "db/schema/a.sql": (BLOB, _blob(repo, b"-- a\n")),
            "db/schema/b.sql": (LINK, _blob(repo, b"a.sql")),
            "db/schema/c.sql": (BLOB, _blob(repo, b"-- c\n")),
        },
    )
    written: list[str] = []
    real_place, real_symlink = git_module._place, os.symlink

    def place(dest: Path, path: str, data: bytes, *, executable: bool) -> None:
        written.append(path)
        real_place(dest, path, data, executable=executable)

    def symlink(src: str, dst: Path, *args: bool) -> None:
        written.append(Path(dst).name)
        real_symlink(src, dst, *args)

    monkeypatch.setattr(git_module, "_place", place)
    monkeypatch.setattr(git_module.os, "symlink", symlink)
    dest = tmp_path / "out" / "repo"

    GitRepository(repo).materialise(tree, _schema(repo), dest)

    assert written == ["db/schema/a.sql", "db/schema/c.sql", "b.sql"]
    assert (dest / "db/schema/b.sql").read_text() == "-- a\n"


def test_symlink_leaving_the_repo_is_refused(repo: Path, tmp_path: Path) -> None:
    tree = _tree(repo, {"db/schema/a.sql": (LINK, _blob(repo, b"../../../etc/passwd"))})

    with pytest.raises(GitError, match="leaves the repository"):
        GitRepository(repo).materialise(tree, _schema(repo), tmp_path / "out" / "repo")


def test_an_absolute_symlink_is_refused(repo: Path, tmp_path: Path) -> None:
    tree = _tree(repo, {"db/schema/a.sql": (LINK, _blob(repo, b"/etc/passwd"))})

    with pytest.raises(GitError, match="leaves the repository"):
        GitRepository(repo).materialise(tree, _schema(repo), tmp_path / "out" / "repo")


def test_in_repo_symlink_target_is_materialised(repo: Path, tmp_path: Path) -> None:
    tree = _tree(
        repo,
        {
            "db/schema/10.sql": (BLOB, _blob(repo, b"-- 10\n")),
            "db/schema/50.sql": (LINK, _blob(repo, b"../../shared/x.sql")),
            "shared/x.sql": (LINK, _blob(repo, b"y.sql")),
            "shared/y.sql": (BLOB, _blob(repo, b"-- shared y\n")),
            "shared/unrelated.sql": (BLOB, _blob(repo, b"-- no\n")),
        },
    )
    dest = tmp_path / "out" / "repo"

    GitRepository(repo).materialise(tree, _schema(repo), dest)

    assert (dest / "db/schema/50.sql").read_text() == "-- shared y\n"
    assert not (dest / "shared/unrelated.sql").exists()


def test_a_directory_symlink_is_kept_as_a_link(repo: Path, tmp_path: Path) -> None:
    tree = _tree(
        repo,
        {
            "db/schema/a.sql": (BLOB, _blob(repo, b"-- a\n")),
            "db/schema/more": (LINK, _blob(repo, b"../../shared")),
            "shared/x.sql": (BLOB, _blob(repo, b"-- x\n")),
        },
    )
    dest = tmp_path / "out" / "repo"

    GitRepository(repo).materialise(tree, _schema(repo), dest)

    assert (dest / "db/schema/more").is_symlink()
    assert (dest / "db/schema/more").resolve() == (dest / "shared").resolve()


def test_symlink_privilege_error_is_refused_with_a_hint(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = _tree(
        repo,
        {
            "db/schema/a.sql": (BLOB, _blob(repo, b"-- a\n")),
            "db/schema/b.sql": (LINK, _blob(repo, b"a.sql")),
        },
    )

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise OSError(1314, "A required privilege is not held by the client")

    monkeypatch.setattr(git_module.os, "symlink", refuse)

    with pytest.raises(GitError, match=r"db/schema/b\.sql") as caught:
        GitRepository(repo).materialise(tree, _schema(repo), tmp_path / "out" / "repo")

    assert "Developer Mode" in (caught.value.resolution_hint or "")


def test_include_dir_outside_the_repo_is_refused(repo: Path, tmp_path: Path) -> None:
    _commit_files(repo, {"db/schema/a.sql": b"-- a\n"})

    with pytest.raises(GitError, match="outside the repository"):
        GitRepository(repo).materialise("HEAD", [tmp_path / "elsewhere"], tmp_path / "out" / "r")


def test_one_deadline_for_the_tree(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _commit_files(repo, {"db/schema/a.sql": b"-- a\n"})
    real_popen = subprocess.Popen

    def stalling(argv: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        if "cat-file" in argv:
            argv = ["sleep", "10"]
        return real_popen(argv, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(git_module, "_TREE_TIMEOUT", 0.5)
    monkeypatch.setattr(git_module.subprocess, "Popen", stalling)

    with pytest.raises(GitError, match=r"timed out after 0\.5s"):
        GitRepository(repo).materialise("HEAD", _schema(repo), tmp_path / "out" / "repo")


def _spy(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    real_popen = subprocess.Popen

    def popen(argv: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        calls.append(next(arg for arg in argv[1:] if not arg.startswith("-")))
        return real_popen(argv, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(git_module.subprocess, "Popen", popen)
    return calls


def test_three_git_processes_per_ref(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _commit_files(repo, {"db/schema/a.sql": b"-- a\n", "db/schema/b.sql": b"-- b\n"})
    git_repo = GitRepository(repo)
    git_repo.get_repo_root()
    calls = _spy(monkeypatch)

    git_repo.materialise("HEAD", _schema(repo), tmp_path / "out" / "repo")

    assert calls == ["rev-parse", "ls-tree", "cat-file"]


def test_each_symlink_round_is_one_more_listing_and_fetch(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = _tree(
        repo,
        {
            "db/schema/50.sql": (LINK, _blob(repo, b"../../shared/x.sql")),
            "shared/x.sql": (BLOB, _blob(repo, b"-- x\n")),
        },
    )
    git_repo = GitRepository(repo)
    git_repo.get_repo_root()
    calls = _spy(monkeypatch)

    git_repo.materialise(tree, _schema(repo), tmp_path / "out" / "repo")

    assert calls == ["rev-parse", "ls-tree", "cat-file", "ls-tree", "cat-file"]
