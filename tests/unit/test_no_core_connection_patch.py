"""No test patches ``confiture.core.connection.create_connection`` (Phase 04, Cycle 9).

That name is core's own factory. Replacing it from a test reached every caller
through an in-function import, so a CLI test could pass while the command it
exercised opened its connection somewhere else entirely. Connections are now
injected: ``core.connection.open_connection(config, factory=...)`` for library
code, and the CLI's one seam ``confiture.cli.helpers.create_connection`` (what
``cli.helpers.open_connection`` calls) for command tests.
"""

from __future__ import annotations

import re
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = re.compile(r"[\"']confiture\.core\.connection\.create_connection[\"']")


def find_core_factory_patches(root: Path) -> list[str]:
    findings: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if path.name == Path(__file__).name or "fixtures" in path.parts:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if FORBIDDEN.search(line):
                findings.append(f"{path.relative_to(root.parent).as_posix()}:{lineno}")
    return findings


def test_no_test_patches_core_create_connection() -> None:
    findings = find_core_factory_patches(TESTS_ROOT)
    assert findings == [], (
        f"{len(findings)} test(s) patch confiture.core.connection.create_connection:\n  "
        + "\n  ".join(findings[:15])
        + "\nInject the connection instead: patch `confiture.cli.helpers.create_connection` "
        "for a CLI command, or pass `factory=` to `open_connection`."
    )
