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
duplicate readers were deleted; `python scripts/gen_port_boundary.py --sizes` prints
what each table holds today. The page records placements only, so it changes when a
module moves, not when one grows.

<!-- BEGIN GENERATED: port-boundary -->

### The crate

| Module | Bucket |
|---|---|
| `_pglast_enums.py` | DDL transform |
| `change_order.py` | DDL transform |
| `change_set/` | DDL transform |
| `cor_extractor.py` | DDL transform |
| `data_assertions.py` | DDL transform |
| `ddl_clauses.py` | DDL transform |
| `ddl_objects.py` | DDL transform |
| `ddl_walk.py` | DDL transform |
| `destructive.py` | DDL transform |
| `differ.py` | DDL transform |
| `differ_sql.py` | DDL transform |
| `expand_contract.py` | DDL transform |
| `fk_extractor.py` | DDL transform |
| `function_body_checker.py` | DDL transform |
| `function_body_normalizer.py` | DDL transform |
| `function_signature_checker.py` | DDL transform |
| `idempotency/` | DDL transform |
| `introspection/dependency_graph.py` | DDL transform |
| `linting/` | DDL transform |
| `lock_profile.py` | DDL transform |
| `migration_analyzer.py` | DDL transform |
| `migration_grant_extractor.py` | DDL transform |
| `model_facts.py` | DDL transform |
| `parser_info.py` | DDL transform |
| `path_globs.py` | DDL transform |
| `plpgsql_fragments.py` | DDL transform |
| `plpgsql_parse.py` | DDL transform |
| `replica/` | DDL transform |
| `risk_tier.py` | DDL transform |
| `schema_change.py` | DDL transform |
| `schema_identity.py` | DDL transform |
| `schema_model.py` | DDL transform |
| `schema_read.py` | DDL transform |
| `sql_lexer.py` | DDL transform |
| `strategy.py` | DDL transform |
| `tree_prefix.py` | DDL transform |
| `tview_preflight.py` | DDL transform |
| `type_lattice.py` | DDL transform |

### Python I/O glue behind the same JSON contract

| Module | Bucket |
|---|---|
| `__init__.py` | neutral |
| `_migrator/` | database orchestration |
| `anonymization/` | database orchestration |
| `backfill.py` | database orchestration |
| `baseline_detector.py` | database orchestration |
| `bootstrap.py` | database orchestration |
| `builder.py` | database orchestration |
| `checksum.py` | database orchestration |
| `connection.py` | database orchestration |
| `cte_debugger.py` | database orchestration |
| `dependent_objects.py` | database orchestration |
| `desired_state.py` | database orchestration |
| `drift.py` | database orchestration |
| `dry_run.py` | database orchestration |
| `dry_run_summary.py` | neutral |
| `error_context.py` | neutral |
| `error_handler.py` | neutral |
| `expected_db.py` | database orchestration |
| `function_body_drift.py` | database orchestration |
| `function_signature_drift.py` | database orchestration |
| `git.py` | neutral |
| `git_accompaniment.py` | neutral |
| `git_schema.py` | neutral |
| `grant_accompaniment.py` | database orchestration |
| `introspection/` | database orchestration |
| `introspection/type_mapping.py` | neutral |
| `large_tables.py` | database orchestration |
| `ledger.py` | database orchestration |
| `linting/baseline.py` | neutral |
| `linting/bodies.py` | database orchestration |
| `linting/libraries/security_definer.py` | database orchestration |
| `linting/schema_linter.py` | database orchestration |
| `linting/selection.py` | database orchestration |
| `linting/unresolved.py` | database orchestration |
| `live_catalog.py` | database orchestration |
| `locking.py` | database orchestration |
| `migration_generator.py` | database orchestration |
| `migration_verifier.py` | database orchestration |
| `migrator.py` | database orchestration |
| `ownership_fixer.py` | database orchestration |
| `pgtap_generator.py` | neutral |
| `preconditions.py` | database orchestration |
| `preflight.py` | database orchestration |
| `progress.py` | neutral |
| `psql_applier.py` | database orchestration |
| `restorer.py` | database orchestration |
| `scaffold/` | neutral |
| `schema_analyzer.py` | database orchestration |
| `schema_artifact.py` | database orchestration |
| `schema_exporter.py` | neutral |
| `schema_facts.py` | database orchestration |
| `schema_snapshot.py` | database orchestration |
| `schema_sources.py` | database orchestration |
| `schema_to_schema.py` | database orchestration |
| `seed/` | database orchestration |
| `server_constants.py` | database orchestration |
| `sql_path.py` | database orchestration |
| `sql_utils.py` | neutral |
| `squash.py` | database orchestration |
| `ssh_tunnel.py` | database orchestration |
| `step_runner.py` | database orchestration |
| `stub_generator.py` | neutral |
| `syncer.py` | database orchestration |
| `temp_database.py` | database orchestration |
| `test_db.py` | database orchestration |
| `tree_allocator.py` | database orchestration |
| `tree_renumber.py` | database orchestration |
| `unified_linter.py` | database orchestration |
| `validation/` | database orchestration |
| `view_body_drift.py` | database orchestration |
| `view_manager.py` | database orchestration |

### What does not port

| Module | Bucket |
|---|---|
| `_migrator/loader.py` | Python-bound |
| `anonymization/plugins/` | Python-bound |
| `hooks/` | Python-bound |
| `idempotency/python_migration_extractor.py` | Python-bound |
| `idempotency/static_eval/` | Python-bound |
| `import_checker.py` | Python-bound |
| `mcp_http.py` | Python-bound |
| `mcp_server.py` | Python-bound |
| `migration_reads.py` | Python-bound |

<!-- END GENERATED: port-boundary -->
