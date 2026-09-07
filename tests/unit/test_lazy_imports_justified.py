"""A function-level import says why it is there, or counts against a budget that only shrinks.

An import inside a function is legitimate for three reasons — an optional
dependency that may be absent, a genuine import cycle, or a deliberate deferral
of a heavy module off the CLI's startup path — and a fourth that is not: it was
easier than scrolling up. Each such import either carries a ``# Reason:``
comment (on its line or the line above) or is covered by its file's budget
below. Budgets may only go down: hoist an import, or give it a reason, and
lower the number. A file that is not listed has a budget of zero.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import confiture

PACKAGE_ROOT = Path(confiture.__file__).resolve().parent

# Function-level imports without a ``# Reason:`` comment, per module. Lower a
# number when you hoist or justify one; never raise one.
BASELINE: dict[str, int] = {
    "cli/branch.py": 1,
    "cli/commands/admin.py": 10,
    "cli/commands/apply_as.py": 2,
    "cli/commands/bootstrap.py": 1,
    "cli/commands/debug.py": 2,
    "cli/commands/mcp.py": 2,
    "cli/commands/migrate/_dry_run_render.py": 3,
    "cli/commands/migrate/_settings.py": 4,
    "cli/commands/migrate/baseline.py": 7,
    "cli/commands/migrate/current.py": 2,
    "cli/commands/migrate/diff.py": 4,
    "cli/commands/migrate/down.py": 7,
    "cli/commands/migrate/estimate.py": 3,
    "cli/commands/migrate/fix_signatures.py": 8,
    "cli/commands/migrate/generate.py": 3,
    "cli/commands/migrate/introspect.py": 4,
    "cli/commands/migrate/preflight.py": 22,
    "cli/commands/migrate/rebuild.py": 2,
    "cli/commands/migrate/reinit.py": 1,
    "cli/commands/migrate/status.py": 9,
    "cli/commands/migrate/up.py": 8,
    "cli/commands/migrate/validate.py": 2,
    "cli/commands/migrate/verify.py": 7,
    "cli/commands/schema.py": 26,
    "cli/commands/validate_checks.py": 25,
    "cli/coordinate.py": 2,
    "cli/dry_run.py": 2,
    "cli/dry_run_summary.py": 1,
    "cli/error_json.py": 5,
    "cli/formatters/validate_formatter.py": 4,
    "cli/generate.py": 6,
    "cli/helpers.py": 2,
    "cli/idempotency.py": 7,
    "cli/main.py": 4,
    "cli/options.py": 1,
    "cli/ownership.py": 5,
    "cli/prep_seed_formatter.py": 1,
    "cli/schema_to_schema.py": 4,
    "cli/seed.py": 11,
    "cli/sync.py": 5,
    "cli/test_db.py": 1,
    "config/environment.py": 1,
    "core/_migrator/apply.py": 2,
    "core/_migrator/apply_loop.py": 2,
    "core/_migrator/baseline.py": 13,
    "core/_migrator/engine.py": 1,
    "core/_migrator/factory.py": 3,
    "core/_migrator/policy.py": 3,
    "core/_migrator/replay.py": 1,
    "core/_migrator/reporting.py": 6,
    "core/_migrator/rollback_loop.py": 6,
    "core/_migrator/session.py": 8,
    "core/_migrator/state.py": 1,
    "core/anonymization/registry.py": 1,
    "core/builder.py": 2,
    "core/change_set/__init__.py": 1,
    "core/change_set/walker.py": 1,
    "core/connection.py": 4,
    "core/cor_extractor.py": 1,
    "core/cte_debugger.py": 1,
    "core/drift.py": 4,
    "core/error_handler.py": 2,
    "core/expected_db.py": 2,
    "core/function_body_checker.py": 1,
    "core/function_signature_parser.py": 1,
    "core/git_accompaniment.py": 2,
    "core/git_schema.py": 1,
    "core/hooks/notifications/factory.py": 1,
    "core/idempotency/ast_detector.py": 2,
    "core/idempotency/models.py": 1,
    "core/idempotency/validator.py": 1,
    "core/import_checker.py": 5,
    "core/linting/libraries/acl.py": 1,
    "core/linting/libraries/functions.py": 1,
    "core/linting/libraries/ownership.py": 2,
    "core/linting/libraries/replica.py": 1,
    "core/linting/libraries/security_definer.py": 2,
    "core/linting/schema_linter.py": 6,
    "core/locking.py": 1,
    "core/mcp_http.py": 2,
    "core/mcp_server.py": 5,
    "core/migration_grant_extractor.py": 7,
    "core/preflight.py": 1,
    "core/progress.py": 1,
    "core/replica/classifier.py": 1,
    "core/schema_snapshot.py": 1,
    "core/seed/bridge.py": 1,
    "core/seed/sequencer.py": 2,
    "core/syncer.py": 1,
    "core/validation/acl_coverage.py": 3,
    "core/validation/config_validator.py": 2,
    "core/validation/context.py": 2,
    "core/validation/function_uniqueness.py": 3,
    "core/validation/live_drift.py": 1,
    "core/validation/ownership_coverage.py": 3,
    "core/validation/replay_drift.py": 3,
    "core/validation/security_definer.py": 7,
    "core/validation/signature_drift.py": 6,
    "core/validation/view_drift.py": 3,
    "exceptions.py": 1,
    "models/migration.py": 1,
    "models/sql_file_migration.py": 3,
    "testing/frameworks/mutation.py": 1,
    "testing/pytest_plugin.py": 10,
    "testing/sandbox.py": 3,
}


def _unjustified(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source)
    seen: set[int] = set()
    found: list[str] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if not isinstance(node, (ast.Import, ast.ImportFrom)) or id(node) in seen:
                continue
            seen.add(id(node))
            own = lines[node.lineno - 1]
            above = lines[node.lineno - 2] if node.lineno >= 2 else ""
            if "# Reason:" in own or above.strip().startswith("# Reason:"):
                continue
            module = node.module if isinstance(node, ast.ImportFrom) else node.names[0].name
            found.append(f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{node.lineno}: {module}")
    return found


def _by_file() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        hits = _unjustified(path)
        if hits:
            result[path.relative_to(PACKAGE_ROOT).as_posix()] = hits
    return result


def test_every_file_stays_within_its_budget() -> None:
    over = {rel: hits for rel, hits in _by_file().items() if len(hits) > BASELINE.get(rel, 0)}
    detail = "\n".join(
        f"  {rel}: {len(hits)} (budget {BASELINE.get(rel, 0)})\n    " + "\n    ".join(hits[:5])
        for rel, hits in sorted(over.items())
    )
    assert over == {}, f"function-level imports without a '# Reason:' beyond budget:\n{detail}"


def test_the_baseline_is_current() -> None:
    """A budget above the real count hides a regression — lower it."""
    actual = {rel: len(hits) for rel, hits in _by_file().items()}
    stale = {
        rel: (budget, actual.get(rel, 0))
        for rel, budget in BASELINE.items()
        if actual.get(rel, 0) < budget
    }
    assert stale == {}, f"budgets above the real count (lower them): {stale}"


@pytest.mark.parametrize("marker", ["# Reason:"])
def test_reasons_name_a_cause(marker: str) -> None:
    """A reason says which optional dependency, which cycle, or 'startup' — not just 'lazy'."""
    vague: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if marker in line:
                reason = line.split(marker, 1)[1].strip().lower()
                if len(reason) < 8 or reason in {"lazy", "lazy import", "perf", "performance"}:
                    vague.append(
                        f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{lineno}: {reason!r}"
                    )
    assert vague == [], "reasons that explain nothing:\n" + "\n".join(vague)
