#!/usr/bin/env python3
"""Keep the Rust port's boundary tables in ``docs/architecture/rust-port-boundary.md`` measured.

Every module under ``python/confiture/core/`` is placed by the most specific row of
:data:`ROWS` that covers it — a module, or a package and everything under it — in
one of three tables, with the review's bucket for it. Line counts are measured
here, over the files ``git`` tracks (``gen_tree``'s own walker), never quoted:
the review's ~20K for the crate was measured before the duplicate readers went.

    python scripts/gen_port_boundary.py --check   # exit 1 when the tables are stale
    python scripts/gen_port_boundary.py --write   # regenerate them

``tests/unit/docs/test_port_boundary_lists_every_module.py`` holds the rows to the tree.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# The tree generator's walker counts the lines: loaded from beside this script.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_tree import _tracked

REPO = Path(__file__).resolve().parents[1]
CORE = Path("python/confiture/core")
DOC = REPO / "docs" / "architecture" / "rust-port-boundary.md"
BEGIN = "<!-- BEGIN GENERATED: port-boundary -->"
END = "<!-- END GENERATED: port-boundary -->"

CRATE = "The crate"
GLUE = "Python I/O glue behind the same JSON contract"
STAYS = "What does not port"
TABLES = (CRATE, GLUE, STAYS)

TRANSFORM = "DDL transform"
ORCHESTRATION = "database orchestration"
NEUTRAL = "neutral"
PYTHON = "Python-bound"

#: path under ``core/`` → (table, the review's bucket).
ROWS: dict[str, tuple[str, str]] = {
    # The crate: text in, model or verdict out; no database, no file system.
    "_pglast_enums.py": (CRATE, TRANSFORM),
    "change_set": (CRATE, TRANSFORM),
    "cor_extractor.py": (CRATE, TRANSFORM),
    "data_assertions.py": (CRATE, TRANSFORM),
    "ddl_clauses.py": (CRATE, TRANSFORM),
    "ddl_objects.py": (CRATE, TRANSFORM),
    "ddl_walk.py": (CRATE, TRANSFORM),
    "destructive.py": (CRATE, TRANSFORM),
    "differ.py": (CRATE, TRANSFORM),
    "differ_sql.py": (CRATE, TRANSFORM),
    "expand_contract.py": (CRATE, TRANSFORM),
    "fk_extractor.py": (CRATE, TRANSFORM),
    "function_body_checker.py": (CRATE, TRANSFORM),
    "function_body_normalizer.py": (CRATE, TRANSFORM),
    "function_signature_checker.py": (CRATE, TRANSFORM),
    "idempotency": (CRATE, TRANSFORM),
    "introspection/dependency_graph.py": (CRATE, TRANSFORM),
    "linting": (CRATE, TRANSFORM),
    "lock_profile.py": (CRATE, TRANSFORM),
    "migration_analyzer.py": (CRATE, TRANSFORM),
    "migration_grant_extractor.py": (CRATE, TRANSFORM),
    "model_facts.py": (CRATE, TRANSFORM),
    "parser_info.py": (CRATE, TRANSFORM),
    "path_globs.py": (CRATE, TRANSFORM),
    "plpgsql_fragments.py": (CRATE, TRANSFORM),
    "plpgsql_parse.py": (CRATE, TRANSFORM),
    "replica": (CRATE, TRANSFORM),
    "risk_tier.py": (CRATE, TRANSFORM),
    "schema_change.py": (CRATE, TRANSFORM),
    "schema_identity.py": (CRATE, TRANSFORM),
    "schema_model.py": (CRATE, TRANSFORM),
    "sql_lexer.py": (CRATE, TRANSFORM),
    "strategy.py": (CRATE, TRANSFORM),
    "tree_prefix.py": (CRATE, TRANSFORM),
    "type_lattice.py": (CRATE, TRANSFORM),
    # Glue: talks to a database, a file system, git or a process, and hands the
    # crate text and the caller JSON.
    "_migrator": (GLUE, ORCHESTRATION),
    "anonymization": (GLUE, ORCHESTRATION),
    "backfill.py": (GLUE, ORCHESTRATION),
    "baseline_detector.py": (GLUE, ORCHESTRATION),
    "bootstrap.py": (GLUE, ORCHESTRATION),
    "builder.py": (GLUE, ORCHESTRATION),
    "checksum.py": (GLUE, ORCHESTRATION),
    "connection.py": (GLUE, ORCHESTRATION),
    "cte_debugger.py": (GLUE, ORCHESTRATION),
    "dependent_objects.py": (GLUE, ORCHESTRATION),
    "desired_state.py": (GLUE, ORCHESTRATION),
    "drift.py": (GLUE, ORCHESTRATION),
    "dry_run.py": (GLUE, ORCHESTRATION),
    "expected_db.py": (GLUE, ORCHESTRATION),
    "function_body_drift.py": (GLUE, ORCHESTRATION),
    "function_signature_drift.py": (GLUE, ORCHESTRATION),
    "grant_accompaniment.py": (GLUE, ORCHESTRATION),
    "introspection": (GLUE, ORCHESTRATION),
    "large_tables.py": (GLUE, ORCHESTRATION),
    "ledger.py": (GLUE, ORCHESTRATION),
    "linting/bodies.py": (GLUE, ORCHESTRATION),
    "linting/libraries/security_definer.py": (GLUE, ORCHESTRATION),
    "linting/schema_linter.py": (GLUE, ORCHESTRATION),
    "linting/selection.py": (GLUE, ORCHESTRATION),
    "linting/unresolved.py": (GLUE, ORCHESTRATION),
    "live_catalog.py": (GLUE, ORCHESTRATION),
    "locking.py": (GLUE, ORCHESTRATION),
    "migration_generator.py": (GLUE, ORCHESTRATION),
    "migration_verifier.py": (GLUE, ORCHESTRATION),
    "migrator.py": (GLUE, ORCHESTRATION),
    "ownership_fixer.py": (GLUE, ORCHESTRATION),
    "preconditions.py": (GLUE, ORCHESTRATION),
    "preflight.py": (GLUE, ORCHESTRATION),
    "psql_applier.py": (GLUE, ORCHESTRATION),
    "restorer.py": (GLUE, ORCHESTRATION),
    "schema_analyzer.py": (GLUE, ORCHESTRATION),
    "schema_artifact.py": (GLUE, ORCHESTRATION),
    "schema_facts.py": (GLUE, ORCHESTRATION),
    "schema_snapshot.py": (GLUE, ORCHESTRATION),
    "schema_sources.py": (GLUE, ORCHESTRATION),
    "schema_to_schema.py": (GLUE, ORCHESTRATION),
    "seed": (GLUE, ORCHESTRATION),
    "sql_path.py": (GLUE, ORCHESTRATION),
    "ssh_tunnel.py": (GLUE, ORCHESTRATION),
    "step_runner.py": (GLUE, ORCHESTRATION),
    "syncer.py": (GLUE, ORCHESTRATION),
    "temp_database.py": (GLUE, ORCHESTRATION),
    "test_db.py": (GLUE, ORCHESTRATION),
    "tree_allocator.py": (GLUE, ORCHESTRATION),
    "tree_renumber.py": (GLUE, ORCHESTRATION),
    "unified_linter.py": (GLUE, ORCHESTRATION),
    "validation": (GLUE, ORCHESTRATION),
    "view_body_drift.py": (GLUE, ORCHESTRATION),
    "view_manager.py": (GLUE, ORCHESTRATION),
    "__init__.py": (GLUE, NEUTRAL),
    "dry_run_summary.py": (GLUE, NEUTRAL),
    "error_context.py": (GLUE, NEUTRAL),
    "error_handler.py": (GLUE, NEUTRAL),
    "git.py": (GLUE, NEUTRAL),
    "git_accompaniment.py": (GLUE, NEUTRAL),
    "git_schema.py": (GLUE, NEUTRAL),
    "introspection/type_mapping.py": (GLUE, NEUTRAL),
    "linting/baseline.py": (GLUE, NEUTRAL),
    "pgtap_generator.py": (GLUE, NEUTRAL),
    "progress.py": (GLUE, NEUTRAL),
    "scaffold": (GLUE, NEUTRAL),
    "schema_exporter.py": (GLUE, NEUTRAL),
    "sql_utils.py": (GLUE, NEUTRAL),
    "stub_generator.py": (GLUE, NEUTRAL),
    # What does not port: it executes, loads or reads Python, or serves it.
    "_migrator/loader.py": (STAYS, PYTHON),
    "anonymization/plugins": (STAYS, PYTHON),
    "hooks": (STAYS, PYTHON),
    "idempotency/python_migration_extractor.py": (STAYS, PYTHON),
    "idempotency/static_eval": (STAYS, PYTHON),
    "import_checker.py": (STAYS, PYTHON),
    "mcp_http.py": (STAYS, PYTHON),
    "mcp_server.py": (STAYS, PYTHON),
}


def core_modules() -> list[str]:
    """Every tracked module under ``core/``, as a path relative to it."""
    root = REPO / CORE
    return sorted(
        path.relative_to(root).as_posix()
        for path in _tracked(REPO)
        if path.suffix == ".py" and path.is_relative_to(root)
    )


def row_for(module: str, *, above: bool = False) -> str | None:
    """The most specific row covering *module* — or, with *above*, covering its parent."""
    parts = module.split("/")
    candidates = [] if above else [module]
    candidates += ["/".join(parts[:i]) for i in range(len(parts) - 1, 0, -1)]
    return next((row for row in candidates if row in ROWS), None)


def _lines(module: str) -> int:
    return len((REPO / CORE / module).read_text(encoding="utf-8").splitlines())


def render() -> str:
    """The generated block, markers included."""
    modules = core_modules()
    counted: dict[str, int] = {}
    for module in modules:
        row = row_for(module)
        if row is not None:
            counted[row] = counted.get(row, 0) + _lines(module)
    total = sum(counted.values())
    lines = [BEGIN, ""]
    for table in TABLES:
        rows = sorted(row for row, (where, _) in ROWS.items() if where == table)
        size = sum(counted.get(row, 0) for row in rows)
        lines += [
            f"### {table}",
            "",
            f"{size:,} lines, {size * 100 // total}% of `core/`.",
            "",
            "| Module | Lines | Bucket |",
            "|---|---:|---|",
        ]
        for row in rows:
            name = f"`{row}/`" if not row.endswith(".py") else f"`{row}`"
            lines.append(f"| {name} | {counted.get(row, 0):,} | {ROWS[row][1]} |")
        lines.append("")
    lines.append(END)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    text = DOC.read_text(encoding="utf-8")
    if BEGIN not in text or END not in text:
        print("rust-port-boundary.md has no generated block")
        return 1
    head, rest = text.split(BEGIN, 1)
    current, tail = rest.split(END, 1)
    block = render()
    if args.check:
        if BEGIN + current + END != block:
            print("rust-port-boundary.md is stale: run scripts/gen_port_boundary.py --write")
            return 1
        print("rust-port-boundary.md is in sync")
        return 0
    DOC.write_text(f"{head}{block}{tail}", encoding="utf-8")
    print(f"wrote {DOC}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
