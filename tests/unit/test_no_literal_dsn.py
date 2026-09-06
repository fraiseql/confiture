"""Database tests reach their server through the shared fixtures, never a literal DSN (TST-02).

A hard-coded ``postgresql://localhost/postgres`` works on a developer laptop
with a trusting local server and nowhere else: in CI, where the role has a
password, the connection fails and the test *skips*, so the suite is green and
the test never ran. Fifty-odd database tests were in that state (#207's
neighbour). Every connection string in ``tests/integration`` and ``tests/e2e``
comes from ``tests/conftest.py`` — which reads ``CONFITURE_TEST_DB_URL`` and,
when it is set, treats a failed connection as a failure — or is one of the
sentinel URLs below, which are written into config files for CLI tests that
never dial them, or dial them to prove a failure path.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parents[1]
SCANNED_DIRS = ("integration", "e2e")

_DSN = re.compile(r"postgres(?:ql)?://[^\s\"'\\{}<>]*")

# Sentinels: never dialled, or dialled to prove a failure. Adding one here is a
# claim that no test relies on it resolving to a real server.
SENTINEL_DSNS: frozenset[str] = frozenset(
    {
        "postgresql://localhost/test",
        "postgresql://localhost/test_db",
        "postgresql://localhost/test_confiture",
        "postgresql://localhost/app",
        "postgresql://localhost/nonexistent",
        "postgresql://localhost/nonexistent_for_fix_test",
        "postgresql://prod-host/db",
        "postgresql://x/y",
    }
)


def _string_constants(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value


def find_literal_dsns(root: Path) -> tuple[list[str], set[str]]:
    """``(offending sites, sentinel values actually used)``."""
    findings: list[str] = []
    used: set[str] = set()
    for sub in SCANNED_DIRS:
        for path in sorted((root / sub).rglob("*.py")):
            if path.name == "conftest.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for lineno, text in _string_constants(tree):
                for dsn in _DSN.findall(text):
                    if dsn in SENTINEL_DSNS:
                        used.add(dsn)
                        continue
                    findings.append(f"{path.relative_to(root.parent).as_posix()}:{lineno}: {dsn}")
    return findings, used


def test_no_literal_dsn_outside_conftest() -> None:
    findings, _ = find_literal_dsns(TESTS_ROOT)
    assert findings == [], (
        f"{len(findings)} literal connection strings in database tests:\n  "
        + "\n  ".join(findings)
        + "\nUse the `test_db_url` / `maintenance_url` / `fresh_database` fixtures from "
        "tests/conftest.py, or add a sentinel to SENTINEL_DSNS if the URL is never dialled."
    )


def test_every_sentinel_is_still_used() -> None:
    _, used = find_literal_dsns(TESTS_ROOT)
    stale = sorted(SENTINEL_DSNS - used)
    assert stale == [], f"sentinel DSNs no test uses any more: {stale}"


def test_detector_catches_fstring_prefix_and_yaml_text() -> None:
    tree = ast.parse(
        'a = f"postgresql://localhost/{name}"\n'
        'b = "database_url: postgresql://localhost/confiture_test\\n"\n'
        'c = "postgresql://localhost/test"\n'
    )
    found = {d for _, t in _string_constants(tree) for d in _DSN.findall(t)}
    assert found == {
        "postgresql://localhost/",
        "postgresql://localhost/confiture_test",
        "postgresql://localhost/test",
    }
