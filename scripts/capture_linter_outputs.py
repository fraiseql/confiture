"""Record what squawk and sqlfluff really emit, for ``lint-unified``'s parsers to be tested on.

``tests/unit/test_unified_linter.py`` once fed ``SquawkRunner`` an output invented in
the shape it expected; squawk 2.x emits another, and no finding reached the report
(#358). The unit tests parse these recordings instead. Each file names the tool's
version, so a new major is recorded beside the old rather than over it.

The tools are not confiture dependencies. Run it where both are installed::

    uv run --with sqlfluff --with squawk-cli python scripts/capture_linter_outputs.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "unified_lint"


def _squawk(files: list[Path]) -> tuple[str, dict[str, object]]:
    version = subprocess.run(
        ["squawk", "--version"], capture_output=True, text=True, check=True
    ).stdout.split()[-1]
    outputs: dict[str, object] = {}
    for path in files:
        result = subprocess.run(
            ["squawk", "--reporter=json", "--", path.name],
            capture_output=True,
            text=True,
            check=False,
            cwd=FIXTURES,
        )
        outputs[path.name] = json.loads(result.stdout or "[]")
    return version, outputs


def _sqlfluff(files: list[Path]) -> tuple[str, dict[str, object]]:
    # Reason: sqlfluff is not a confiture dependency; this helper runs where it is installed
    import sqlfluff  # ty: ignore[unresolved-import]
    from sqlfluff.api import simple  # ty: ignore[unresolved-import]

    outputs = {path.name: simple.lint(path.read_text(), dialect="postgres") for path in files}
    return sqlfluff.__version__, outputs


def main() -> None:
    files = sorted(FIXTURES.glob("*.sql"))
    if shutil.which("squawk") is None:
        raise SystemExit("squawk is not on PATH")
    for tool, capture in (("squawk", _squawk), ("sqlfluff", _sqlfluff)):
        version, outputs = capture(files)
        target = FIXTURES / f"{tool}-{version}.json"
        payload = {"tool": tool, "version": version, "outputs": outputs}
        target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        print(f"wrote {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
