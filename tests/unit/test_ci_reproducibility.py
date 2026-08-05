"""Convention test: a CI run must be a function of the commit alone (issue #191).

``uv.lock`` was gitignored, so every workflow re-resolved the whole dependency
tree on every run, on every branch. That is not a theoretical hazard: pglast 8.2
shipped 2026-07-10, ``main`` had last run green on 2026-07-08, and the next PR
opened (#183) resolved into it and failed ``Type Check`` with three
``unresolved-attribute`` errors in a file it never touched.

These guards keep the fix from eroding. They are deliberately written against
the workflow *text* rather than against uv's behaviour, because the failure
mode is a contributor adding a fresh-resolving install step next to a locked
one — which no runtime assertion can see.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOWS = _REPO_ROOT / ".github" / "workflows"

# Steps that install a *standalone tool* into the venv rather than confiture's
# dependency tree. These are already version-pinned inline (or are single
# leaf tools with no bearing on what confiture resolves), so they do not
# re-resolve the project's tree and are out of this guard's scope.
_STANDALONE_TOOL_INSTALL = re.compile(
    r"""uv\s+(pip\s+install|tool\s+install)\s+
        ['"]?(ruff|ty|bandit|maturin)\b""",
    re.VERBOSE,
)

# An install that pulls confiture's own dependency tree: `.`, `.[extras]`, or a
# built wheel with extras. These re-resolve from scratch unless they defer to
# the lockfile.
_PROJECT_TREE_INSTALL = re.compile(
    r"""uv\s+pip\s+install\s+           # the install verb
        (?![-]{2})                       # not a bare flag
        ['"]?(?:\$?\{?\w*WHEEL\w*\}?|\.) # a wheel variable, or `.`
        """,
    re.VERBOSE,
)


def _workflow_files() -> list[Path]:
    files = sorted(_WORKFLOWS.glob("*.yml")) + sorted(_WORKFLOWS.glob("*.yaml"))
    assert files, f"no workflows found under {_WORKFLOWS}"
    return files


def _install_lines(path: Path) -> list[tuple[int, str]]:
    """Return (lineno, stripped-line) for every line invoking a uv installer."""
    out: list[tuple[int, str]] = []
    for i, raw in enumerate(path.read_text().splitlines(), start=1):
        line = raw.strip()
        if line.startswith("#"):
            continue
        if re.search(r"\buv\s+(pip\s+install|sync|tool\s+install)\b", line):
            out.append((i, line))
    return out


# ---------------------------------------------------------------------------
# The lockfile itself
# ---------------------------------------------------------------------------


def test_uv_lock_is_tracked_in_git() -> None:
    """``uv.lock`` must be committed, or CI cannot be reproducible."""
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "uv.lock"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert tracked.returncode == 0, (
        "uv.lock is not tracked by git. CI re-resolves the dependency tree on "
        "every run, so an unrelated upstream release can turn any PR red "
        "(issue #191). Fix: `uv lock && git add uv.lock`."
    )


@pytest.mark.parametrize("lockfile", ["uv.lock", "Cargo.lock"])
def test_lockfile_is_not_gitignored(lockfile: str) -> None:
    """A tracked-but-ignored lockfile is a trap for the next `git add -A`."""
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", lockfile],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ignored.returncode != 0, (
        f"{lockfile} matches a .gitignore rule. Remove that entry so lockfile "
        "updates are not silently dropped."
    )


def test_cargo_lock_is_tracked_in_git() -> None:
    """``confiture-core`` is a cdylib — a final artefact, so its lock is committed.

    The "libraries do not commit Cargo.lock" convention is about crates other
    Rust crates depend on. This one is bundled into the published wheel.
    """
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "Cargo.lock"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert tracked.returncode == 0, (
        "Cargo.lock is not tracked by git, so `cargo clippy -- -D warnings` "
        "resolves crates.io fresh on every run (issue #191)."
    )


def test_cargo_invocations_are_locked() -> None:
    """CI's cargo legs must resolve from the committed Cargo.lock."""
    # Two invocation forms, and only these — a step `name:` or a docstring
    # mentioning "cargo clippy" is prose, not a command.
    shell_form = re.compile(r"^(?:-\s*)?(?:run:\s*)?cargo\s+(clippy|build|test)\b")
    list_form = re.compile(r"""["']cargo["']\s*,\s*["'](clippy|build|test)["']""")

    offenders: list[str] = []
    for path in [*_workflow_files(), _REPO_ROOT / "ci" / "local_ci.py"]:
        for i, raw in enumerate(path.read_text().splitlines(), start=1):
            line = raw.strip()
            if line.startswith("#"):
                continue
            # `cargo fmt` reads no manifest dependencies, so it needs no lock.
            if (shell_form.search(line) or list_form.search(line)) and "--locked" not in line:
                offenders.append(f"  {path.name}:{i}  {line}")
    assert not offenders, (
        "cargo invocations that resolve dependencies must pass --locked:\n" + "\n".join(offenders)
    )


# ---------------------------------------------------------------------------
# The workflows
# ---------------------------------------------------------------------------


def test_local_dagger_gate_mounts_the_tracked_lockfile() -> None:
    """The local gate must not exclude uv.lock from the container it tests in.

    0.22.0's two red pushes came from exactly this divergence, in the other
    direction: the gate mounted a local lock CI did not use. Now that CI syncs
    with --locked, excluding the tracked lock recreates the same class of
    false green.
    """
    gate = _REPO_ROOT / "ci" / "local_ci.py"
    source = gate.read_text()
    excluded = re.search(r"^\s*['\"]uv\.lock['\"]\s*,", source, re.MULTILINE)
    assert excluded is None, (
        "ci/local_ci.py excludes uv.lock from the mounted source, so the local "
        "gate resolves dependencies CI will not use. Remove it from "
        "SOURCE_EXCLUDE."
    )


@pytest.mark.parametrize("workflow", _workflow_files(), ids=lambda p: p.name)
def test_uv_sync_defers_to_the_lockfile(workflow: Path) -> None:
    """Every `uv sync` must assert the lock is current (`--locked`).

    ``--frozen`` is not enough: it uses the lockfile as-is and stays silent
    when it has drifted from ``pyproject.toml``. ``--locked`` fails loudly,
    which is what makes a stale lock a CI error rather than a mystery.
    """
    offenders = [
        (n, line)
        for n, line in _install_lines(workflow)
        if re.search(r"\buv\s+sync\b", line) and "--locked" not in line
    ]
    assert not offenders, (
        f"{workflow.name}: `uv sync` without --locked re-resolves (or silently "
        f"accepts a stale lock):\n"
        + "\n".join(f"  :{n}  {line}" for n, line in offenders)
        + "\nFix: add --locked."
    )


@pytest.mark.parametrize("workflow", _workflow_files(), ids=lambda p: p.name)
def test_project_tree_is_never_installed_by_fresh_resolution(workflow: Path) -> None:
    """`uv pip install .[extras]` / `$WHEEL[extras]` bypasses the lockfile.

    The dependency tree must come from `uv sync --locked`. A wheel may still be
    installed to exercise the built artefact, but with `--no-deps` so it
    contributes no resolution of its own.
    """
    offenders = [
        (n, line)
        for n, line in _install_lines(workflow)
        if _PROJECT_TREE_INSTALL.search(line)
        and "--no-deps" not in line
        and not _STANDALONE_TOOL_INSTALL.search(line)
    ]
    assert not offenders, (
        f"{workflow.name}: installs confiture's dependency tree by fresh "
        f"resolution, ignoring uv.lock:\n"
        + "\n".join(f"  :{n}  {line}" for n, line in offenders)
        + "\nFix: `uv sync --locked ...` for the tree; add --no-deps if a built "
        "wheel must also be installed."
    )
