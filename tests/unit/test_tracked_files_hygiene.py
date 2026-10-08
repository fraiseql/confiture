"""What git tracks is source, not output: no logs, no one-off scripts, no stray sample trees,
no merge-conflict markers.

``git ls-files`` is the ground truth (a clean CI checkout sees exactly that), so the
checks here cannot be satisfied by a local ``.gitignore`` alone — the file has to be
untracked. ``testpaths`` must name directories that exist, or pytest silently
collects from fewer places than the configuration promises.
"""

import re
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

# A line git writes into a file it could not merge. The `=======` separator is matched
# whole: an underline of `=` that is longer is a heading, not a marker.
CONFLICT_MARKER = re.compile(r"^(?:(?:<{7}|\|{7}|>{7})(?: |$)|={7}$)", re.MULTILINE)


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


def _text(path: Path) -> str | None:
    data = path.read_bytes()
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def test_no_tracked_text_file_holds_a_conflict_marker() -> None:
    findings = []
    for name in _tracked_files():
        path = REPO_ROOT / name
        if not path.is_file() or (text := _text(path)) is None:
            continue
        findings.extend(
            f"{name}:{text.count(chr(10), 0, match.start()) + 1}: {match.group(0)}"
            for match in CONFLICT_MARKER.finditer(text)
        )
    assert findings == [], "merge-conflict markers in tracked files:\n" + "\n".join(findings)


def test_conflict_marker_pattern_reads_markers_not_headings() -> None:
    markers = [
        "<<<<<<< HEAD",
        "||||||| parent of 2e64a062 (fix)",
        "=======",
        ">>>>>>> main",
        ">>>>>>>",
    ]
    not_markers = ["=" * 80, "========", "<<<<<<<<", "a <<<<<<< b", "=======  "]
    assert [m for m in markers if not CONFLICT_MARKER.search(m)] == []
    assert [m for m in not_markers if CONFLICT_MARKER.search(m)] == []


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
