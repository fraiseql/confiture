"""What git tracks is source, not output: no logs, no one-off scripts, no stray sample trees.

``git ls-files`` is the ground truth (a clean CI checkout sees exactly that), so the
checks here cannot be satisfied by a local ``.gitignore`` alone — the file has to be
untracked. ``testpaths`` must name directories that exist, or pytest silently
collects from fewer places than the configuration promises.
"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Tracked paths that must not exist: (glob or exact path, why).
FORBIDDEN_TRACKED: tuple[tuple[str, str], ...] = (
    ("*.log", "test output committed by accident"),
    (
        "RELEASE_COMMANDS.sh",
        "a one-off v0.6.0 release script; releases are the tag + Publish workflow",
    ),
    ("python/db/*", "a stray sample project tree; the examples live under examples/"),
)


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, check=True
    ).stdout.decode()
    return [p for p in out.split("\0") if p]


def test_no_forbidden_paths_are_tracked() -> None:
    tracked = _tracked_files()
    findings = []
    for pattern, why in FORBIDDEN_TRACKED:
        hits = [p for p in tracked if Path(p).match(pattern) or p.startswith(pattern.rstrip("*"))]
        if hits:
            findings.append(f"{pattern} ({why}): {hits[:5]}")
    assert findings == [], "tracked files that should not be:\n" + "\n".join(findings)


def test_gitignore_covers_logs() -> None:
    rules = {
        line.strip()
        for line in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert "*.log" in rules, ".gitignore has no `*.log` rule"


def test_pytest_testpaths_exist() -> None:
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        testpaths = tomllib.load(fh)["tool"]["pytest"]["ini_options"]["testpaths"]
    missing = [p for p in testpaths if not (REPO_ROOT / p).is_dir()]
    assert missing == [], f"testpaths names directories that do not exist: {missing}"
