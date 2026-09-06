"""``except Exception`` in ``cli/`` is a budget that may only shrink (ARC-01, ENG-08).

A broad handler turns every bug into the same message. Since Cycle 2 every
command runs under :func:`confiture.cli.error_json.cli_boundary`, so the
trailing ``except Exception as e: fail(e)`` in a command body is redundant, and
the best-effort probes (``# noqa: BLE001 — <reason>``) are the only handlers
that legitimately stay broad. Each file's count is pinned here and may only go
down: narrow one, or delete it, and lower the number.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import confiture.cli

CLI_ROOT = Path(confiture.cli.__file__).resolve().parent

# Lower a number when you narrow or delete a handler. Never raise one; a file
# that is not listed has a budget of zero.
BASELINE: dict[str, int] = {
    "branch.py": 10,
    "commands/admin.py": 3,
    "commands/debug.py": 1,
    "commands/diff.py": 1,
    "commands/drift.py": 1,
    "commands/mcp.py": 1,
    "commands/migrate/_settings.py": 1,
    "commands/migrate/current.py": 1,
    "commands/migrate/diff.py": 1,
    "commands/migrate/down.py": 2,
    "commands/migrate/estimate.py": 1,
    "commands/migrate/fix.py": 1,
    "commands/migrate/fix_signatures.py": 3,
    "commands/migrate/generate.py": 2,
    "commands/migrate/introspect.py": 1,
    "commands/migrate/preflight.py": 5,
    "commands/migrate/rebuild.py": 1,
    "commands/migrate/status.py": 2,
    "commands/migrate/up.py": 1,
    "commands/migrate/validate.py": 1,
    "commands/migrate/verify.py": 1,
    "commands/schema.py": 10,
    "commands/validate_checks.py": 4,
    "coordinate.py": 8,
    "dry_run_summary.py": 1,
    "dsn.py": 1,
    "error_json.py": 1,
    "generate.py": 5,
    "helpers.py": 2,
    "schema_to_schema.py": 7,
    "seed.py": 10,
    "sync.py": 1,
    "test_db.py": 7,
}


def broad_handlers(path: Path) -> list[int]:
    """Line numbers of ``except Exception``, ``except BaseException`` and bare ``except:``."""
    found: list[int] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if node.type is None:
            found.append(node.lineno)
            continue
        names = list(node.type.elts) if isinstance(node.type, ast.Tuple) else [node.type]
        if any(isinstance(n, ast.Name) and n.id in ("Exception", "BaseException") for n in names):
            found.append(node.lineno)
    return found


def _cli_files() -> list[str]:
    return sorted(p.relative_to(CLI_ROOT).as_posix() for p in CLI_ROOT.rglob("*.py"))


@pytest.mark.parametrize("rel", _cli_files())
def test_broad_except_does_not_grow(rel: str) -> None:
    lines = broad_handlers(CLI_ROOT / rel)
    budget = BASELINE.get(rel, 0)
    assert len(lines) <= budget, (
        f"{rel} has {len(lines)} broad handlers (budget {budget}) at lines {lines}. "
        "Narrow the new one, or let the boundary decorator handle it."
    )


def test_baseline_is_current() -> None:
    """The baseline records the real counts: lower an entry when its count drops."""
    actual = {rel: len(broad_handlers(CLI_ROOT / rel)) for rel in _cli_files()}
    actual = {k: v for k, v in actual.items() if v}
    assert actual == BASELINE, "set BASELINE to:\n" + "\n".join(
        f'    "{k}": {v},' for k, v in sorted(actual.items())
    )
