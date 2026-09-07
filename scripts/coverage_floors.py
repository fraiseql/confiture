#!/usr/bin/env python3
"""Per-file coverage floors that can only rise.

``tests/coverage_floors.json`` names the modules whose line coverage must stay at or
above a floor (the review's lowest files, held at 70 % by behaviour tests). The
package-level floor is ``[tool.coverage.report] fail_under`` in pyproject.toml and is
enforced by coverage.py itself; this script enforces the per-file floors from a
``--cov-report=json`` file, because coverage.py has no per-file threshold.

Usage:
    uv run python scripts/coverage_floors.py --check coverage.json   # exit 1 below a floor
    uv run python scripts/coverage_floors.py --report coverage.json  # print the named files
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FLOORS = REPO_ROOT / "tests" / "coverage_floors.json"


def load_floors() -> dict[str, float]:
    return json.loads(FLOORS.read_text(encoding="utf-8"))["files"]


def measured(report: Path) -> dict[str, float]:
    data = json.loads(report.read_text(encoding="utf-8"))
    out: dict[str, float] = {}
    for filename, entry in data["files"].items():
        marker = "python/confiture/"
        if marker in filename:
            out[filename.split(marker, 1)[1]] = float(entry["summary"]["percent_covered"])
    return out


def check(report: Path) -> list[str]:
    floors = load_floors()
    actual = measured(report)
    failures = []
    for rel, floor in sorted(floors.items()):
        pct = actual.get(rel)
        if pct is None:
            failures.append(
                f"{rel}: not in the coverage report (moved or deleted? update the floors)"
            )
        elif pct < floor:
            failures.append(f"{rel}: {pct:.1f}% < floor {floor:.0f}%")
    return failures


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] not in ("--check", "--report"):
        print(__doc__, file=sys.stderr)
        return 2
    report = Path(argv[1])
    if argv[0] == "--report":
        actual = measured(report)
        for rel, floor in sorted(load_floors().items()):
            print(f"{actual.get(rel, float('nan')):6.1f}%  (floor {floor:.0f}%)  {rel}")
        return 0
    failures = check(report)
    for line in failures:
        print("BELOW FLOOR " + line)
    if failures:
        return 1
    print(f"coverage floors: all {len(load_floors())} files at or above their floor")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
