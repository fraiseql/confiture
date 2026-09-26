# The Rust port's boundary

confiture's 2.x line is a Rust crate that `fraisier-core` embeds as a library, planned
for Q3–Q4 2027 (ARCHITECTURE.md, Decision 8). This page states what goes into that crate,
what stays Python glue around it, and what does not port. It also states the test the
crate is accepted by. The tables at the end are generated from the tree
(`scripts/gen_port_boundary.py`), so their line counts are measured, not quoted.

## How the crate is accepted

**Byte identity on the parity corpus.** For every tree in
`tests/fixtures/model_goldens/model/`, the crate writes the same bytes that
`confiture schema dump-model` writes. That covers the repository's own schema, every
example, and a fixture that holds every kind of change.

For every before/after pair in `tests/fixtures/model_goldens/diff/`, the crate writes the
same `diff` wire (`*.wire.json`) and the same generated DDL (`*.up.sql`, `*.down.sql`).
Python is held to those bytes first, by `tests/unit/test_port_parity_corpus.py` and the
golden tests. A real tree with no recorded bytes joins through `CONFITURE_SCHEMA_CORPUS_DIR`.

**The exhaustiveness guards, as `match` arms.** Six tables in Python account for every
member of a pglast enum or of a closed set. In Rust each becomes an exhaustive `match`,
and a new variant becomes a compile error instead of a failing test. The reason attached
to each declined member carries over as a comment on its arm: that part no compiler
holds.

| What must be accounted for | Where Python accounts for it |
|---|---|
| `ConstrType` | `core.ddl_walk.MODELLED_CONSTRAINTS`, `core.ddl_walk.NOT_MODELLED_CONSTRAINTS` |
| `AlterTableType` | `core.ddl_walk.FOLDED`, `core.ddl_walk.MODELLED_ELSEWHERE`, `core.ddl_walk.NOT_AN_EXPECTED_SCHEMA_FACT` |
| every `Alter…`, `Drop…` and `Rename…Stmt` | `core.ddl_walk.FOLDED_STATEMENTS`, `core.ddl_walk.MODELLED_STATEMENTS`, `core.ddl_walk.NOT_AN_EXPECTED_SCHEMA_STATEMENT` |
| every `Create…Stmt` | `core.ddl_objects.TRACKED_NODES`, `core.ddl_objects.MODELLED_ELSEWHERE`, `core.ddl_objects.NOT_A_SCHEMA_OBJECT` |
| every kind of schema change | `core.schema_change.KINDS` |
| every parse-node enum member confiture reads | `core._pglast_enums.REQUIRED_MEMBERS` |

## The grammar the crate inherits

The Python package supports pglast 6 through 8, which embed the PostgreSQL 16, 17 and 18
grammars. A crate that links `libpg_query` links one of them. The crate targets
**PostgreSQL 18**, the grammar the lockfile pins today (pglast 8.4; `confiture --version`
names it on its second line). A 16 or 17 grammar is a build of the crate against that
`libpg_query`, not a switch at run time.

The majors do not agree on the parse-node enums. PostgreSQL 18 inserted an
`AlterTableType` member, which shifted every member from index 13 on down by one. A
literal ordinal then stopped matching `AT_DropColumn`, and replica-unsafe migrations
reported `window_safe: true` (#192). `core/_pglast_enums.py` resolves each member by
name when first used. In the crate, that layer becomes the compile-time enum of the
linked grammar. It is the most translatable piece of the port, and the one whose failure
mode is loudest.

## What does not port

- **`.py` migrations.** `_migrator/loader.py` imports and runs them.
  `idempotency/static_eval/` reads them with the standard library's `symtable`, the
  CPython compiler's own scope analysis. A Rust version would need a Python parser and a
  Python scope model, which is a different project. `idempotency/python_migration_extractor.py`
  and `import_checker.py` read Python in the same way.
- **Hooks.** A hook is a Python callable a user registers, and a notification renders a
  Jinja template.
- **Anonymization plugins.** A custom strategy is loaded as Python.
- **The MCP server** (`mcp_server.py`, `mcp_http.py`), which runs on FastAPI.
- Outside `core/`: the pytest plugin (`confiture.testing`) and the Typer CLI.

A 2.x distribution keeps these in a Python package over the crate, or drops them.

## The three tables

Each row names a module or a package under `python/confiture/core/`. The most specific
row covering a module decides where it goes, and
`tests/unit/docs/test_port_boundary_lists_every_module.py` fails on a module no row
covers, on a row naming nothing, and on a row that repeats its package's row.

The bucket is one of the architecture review's four: DDL transform, database
orchestration, Python-bound, neutral. The review measured their shares (29%, 46%, 4%,
21%) but assigned no module to any of them. Each placement below is this page's, one
decision per row. The review's ~20K lines for the crate were measured before the
duplicate readers were deleted. The count below is what the port translates.

<!-- BEGIN GENERATED: port-boundary -->

### The crate

26,447 lines, 35% of `core/`.

| Module | Lines | Bucket |
|---|---:|---|
| `_pglast_enums.py` | 143 | DDL transform |
| `change_order.py` | 184 | DDL transform |
| `change_set/` | 1,267 | DDL transform |
| `cor_extractor.py` | 135 | DDL transform |
| `data_assertions.py` | 546 | DDL transform |
| `ddl_clauses.py` | 137 | DDL transform |
| `ddl_objects.py` | 662 | DDL transform |
| `ddl_walk.py` | 1,417 | DDL transform |
| `destructive.py` | 180 | DDL transform |
| `differ.py` | 767 | DDL transform |
| `differ_sql.py` | 674 | DDL transform |
| `expand_contract.py` | 273 | DDL transform |
| `fk_extractor.py` | 458 | DDL transform |
| `function_body_checker.py` | 210 | DDL transform |
| `function_body_normalizer.py` | 69 | DDL transform |
| `function_signature_checker.py` | 187 | DDL transform |
| `idempotency/` | 2,712 | DDL transform |
| `introspection/dependency_graph.py` | 203 | DDL transform |
| `linting/` | 9,996 | DDL transform |
| `lock_profile.py` | 491 | DDL transform |
| `migration_analyzer.py` | 137 | DDL transform |
| `migration_grant_extractor.py` | 525 | DDL transform |
| `model_facts.py` | 196 | DDL transform |
| `parser_info.py` | 116 | DDL transform |
| `path_globs.py` | 158 | DDL transform |
| `plpgsql_fragments.py` | 265 | DDL transform |
| `plpgsql_parse.py` | 400 | DDL transform |
| `replica/` | 740 | DDL transform |
| `risk_tier.py` | 76 | DDL transform |
| `schema_change.py` | 899 | DDL transform |
| `schema_identity.py` | 71 | DDL transform |
| `schema_model.py` | 757 | DDL transform |
| `sql_lexer.py` | 637 | DDL transform |
| `strategy.py` | 68 | DDL transform |
| `tree_prefix.py` | 180 | DDL transform |
| `type_lattice.py` | 511 | DDL transform |

### Python I/O glue behind the same JSON contract

41,685 lines, 55% of `core/`.

| Module | Lines | Bucket |
|---|---:|---|
| `__init__.py` | 124 | neutral |
| `_migrator/` | 4,889 | database orchestration |
| `anonymization/` | 4,437 | database orchestration |
| `backfill.py` | 124 | database orchestration |
| `baseline_detector.py` | 248 | database orchestration |
| `bootstrap.py` | 411 | database orchestration |
| `builder.py` | 1,018 | database orchestration |
| `checksum.py` | 432 | database orchestration |
| `connection.py` | 283 | database orchestration |
| `cte_debugger.py` | 198 | database orchestration |
| `dependent_objects.py` | 162 | database orchestration |
| `desired_state.py` | 73 | database orchestration |
| `drift.py` | 1,331 | database orchestration |
| `dry_run.py` | 239 | database orchestration |
| `dry_run_summary.py` | 156 | neutral |
| `error_context.py` | 286 | neutral |
| `error_handler.py` | 284 | neutral |
| `expected_db.py` | 217 | database orchestration |
| `function_body_drift.py` | 211 | database orchestration |
| `function_signature_drift.py` | 375 | database orchestration |
| `git.py` | 521 | neutral |
| `git_accompaniment.py` | 348 | neutral |
| `git_schema.py` | 258 | neutral |
| `grant_accompaniment.py` | 380 | database orchestration |
| `introspection/` | 302 | database orchestration |
| `introspection/type_mapping.py` | 112 | neutral |
| `large_tables.py` | 929 | database orchestration |
| `ledger.py` | 505 | database orchestration |
| `linting/baseline.py` | 153 | neutral |
| `linting/bodies.py` | 465 | database orchestration |
| `linting/libraries/security_definer.py` | 405 | database orchestration |
| `linting/schema_linter.py` | 1,184 | database orchestration |
| `linting/selection.py` | 378 | database orchestration |
| `linting/unresolved.py` | 379 | database orchestration |
| `live_catalog.py` | 894 | database orchestration |
| `locking.py` | 625 | database orchestration |
| `migration_generator.py` | 563 | database orchestration |
| `migration_verifier.py` | 229 | database orchestration |
| `migrator.py` | 206 | database orchestration |
| `ownership_fixer.py` | 243 | database orchestration |
| `pgtap_generator.py` | 63 | neutral |
| `preconditions.py` | 655 | database orchestration |
| `preflight.py` | 187 | database orchestration |
| `progress.py` | 206 | neutral |
| `psql_applier.py` | 274 | database orchestration |
| `restorer.py` | 856 | database orchestration |
| `scaffold/` | 296 | neutral |
| `schema_analyzer.py` | 663 | database orchestration |
| `schema_artifact.py` | 214 | database orchestration |
| `schema_exporter.py` | 196 | neutral |
| `schema_facts.py` | 132 | database orchestration |
| `schema_snapshot.py` | 104 | database orchestration |
| `schema_sources.py` | 316 | database orchestration |
| `schema_to_schema.py` | 634 | database orchestration |
| `seed/` | 5,823 | database orchestration |
| `sql_path.py` | 135 | database orchestration |
| `sql_utils.py` | 74 | neutral |
| `ssh_tunnel.py` | 138 | database orchestration |
| `step_runner.py` | 298 | database orchestration |
| `stub_generator.py` | 137 | neutral |
| `syncer.py` | 654 | database orchestration |
| `temp_database.py` | 275 | database orchestration |
| `test_db.py` | 1,017 | database orchestration |
| `tree_allocator.py` | 266 | database orchestration |
| `tree_renumber.py` | 486 | database orchestration |
| `unified_linter.py` | 186 | database orchestration |
| `validation/` | 2,101 | database orchestration |
| `view_body_drift.py` | 198 | database orchestration |
| `view_manager.py` | 524 | database orchestration |

### What does not port

6,852 lines, 9% of `core/`.

| Module | Lines | Bucket |
|---|---:|---|
| `_migrator/loader.py` | 133 | Python-bound |
| `anonymization/plugins/` | 302 | Python-bound |
| `hooks/` | 3,274 | Python-bound |
| `idempotency/python_migration_extractor.py` | 294 | Python-bound |
| `idempotency/static_eval/` | 1,730 | Python-bound |
| `import_checker.py` | 493 | Python-bound |
| `mcp_http.py` | 191 | Python-bound |
| `mcp_server.py` | 435 | Python-bound |

<!-- END GENERATED: port-boundary -->
