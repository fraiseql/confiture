# Confiture Development Guide

**Project**: Confiture - PostgreSQL Migrations, Sweetly Done 🍓
**Version**: 1.17.0
**Last Updated**: September 22, 2026
**Current Status**: Production-Ready

> **Status**: Production-ready. Actively used in production since March 2026.

---

## 🎯 Project Overview

**Confiture** is a modern PostgreSQL migration tool for Python with a **build-from-scratch philosophy** and **4 migration strategies**. This document guides AI-assisted development.

### Core Philosophy

> **"Build from DDL, not migration history"**

The `db/schema/` directory is the **single source of truth**. Migrations are derived, not primary.

### The Four Mediums

1. **Build from DDL** (`confiture build`) - Fresh databases in <1s
2. **Incremental Migrations** (`confiture migrate up`) - ALTER for simple changes
3. **Production Sync** (`confiture sync`) - Copy data with anonymization
4. **Schema-to-Schema** (`confiture migrate schema-to-schema`) - Zero-downtime via FDW

---

## 📚 Essential Reading

Before coding, read these documents in order:

1. **[PRD.md](./PRD.md)** - Product requirements, user stories, success metrics
2. **[ARCHITECTURE.md](./ARCHITECTURE.md)** - Technical architecture and design decisions
3. **[docs/](./docs/)** - User guides and API documentation

---

## 🏗️ Development Methodology

### TDD Approach

Confiture follows **disciplined TDD cycles**:

```
┌─────────────────────────────────────────────────────────┐
│                    TDD CYCLE                            │
│                                                         │
│ ┌─────────┐  ┌─────────┐  ┌─────────────┐  ┌─────────┐ │
│ │   RED   │─▶│ GREEN   │─▶│  REFACTOR   │─▶│   QA    │ │
│ │ Failing │  │ Minimal │  │ Clean &     │  │ Verify  │ │
│ │ Test    │  │ Code    │  │ Optimize    │  │ Quality │ │
│ └─────────┘  └─────────┘  └─────────────┘  └─────────┘ │
└─────────────────────────────────────────────────────────┘
```

### TDD Discipline

**RED**: Write specific failing test
```bash
uv run pytest tests/unit/test_builder.py::test_build_schema_local -v
# Expected: FAILED (not implemented yet)
```

**GREEN**: Minimal implementation to pass
```bash
uv run pytest tests/unit/test_builder.py::test_build_schema_local -v
# Expected: PASSED (minimal working code)
```

**REFACTOR**: Clean up, optimize
```bash
uv run pytest tests/unit/test_builder.py -v
# All tests still pass after refactoring
```

**QA**: Full validation
```bash
uv run pytest --cov=confiture --cov-report=term-missing
uv run ruff check .
uv run ty check python/confiture/
```

---

## 🛠️ Technology Stack

### Core Dependencies

```toml
# pyproject.toml dependencies
[project.dependencies]
python = ">=3.11"
typer = ">=0.12"          # CLI framework
pydantic = ">=2.5"        # Configuration validation
pyyaml = ">=6.0"          # YAML parsing
psycopg = {version = ">=3.1", extras = ["binary", "pool"]}  # PostgreSQL driver
rich = ">=13.7"           # Terminal formatting
sqlglot = ">=28.0"        # SQL dialect-aware parsing (transpilation)
pglast = ">=6.0"          # PostgreSQL's own C parser (libpg_query) — the one parser

[project.optional-dependencies]
ast = []                  # empty alias: an older `fraiseql-confiture[ast]` still resolves

dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=4.1",
    "pytest-json-report>=1.5",
    "ruff>=0.6",
    "ty>=0.0.7",           # Astral's type checker (replaces mypy)
    "maturin>=1.7",
]
```

### Architecture: one model

Confiture parses DDL once, reads the live catalog once, types what changed, and exposes
exactly that as the seam its consumers build on. Each "one X" below is a module and a
guard test; the guard fails on a second implementation, and its allow-list — where it
has one — is a table of **reasons**, each naming the different question a module asks.
An allow-list entry that matches nothing fails too, so an entry is an edit, never an
escape. Keep every guard green; when a change makes an entry match nothing, delete it
in the same change.

**One parser: pglast** (PostgreSQL's own C parser, `libpg_query`), a hard dependency.
There is no regex or sqlparse fallback: `tests/unit/test_single_parser.py` fails on a
fallback switch, an availability flag or a probe, and
`tests/unit/docs/test_no_optional_parser.py` fails on any document, help string or
docstring that tells a reader to install a parser confiture depends on. `[ast]` is an
empty alias kept so an older `fraiseql-confiture[ast]` still resolves. A file pglast
rejects is a **finding**, never a clean result: `IDEM_UNPARSEABLE`,
`PFLIGHT_UNPARSEABLE` (forces `window_safe: false`), lint's `UNPARSEABLE`, an
unclassified change-set entry, `DIFFER_400`. `core/parser_info.py` names the parser on
`confiture --version`'s second line and in every JSON payload's `parser` key.

**One lexer** — `core/sql_lexer.py` is the only module that tokenises SQL text
(`split_statements`, `strip_comments`, `tokens`, `code_text`, `directives`,
`blank_copy_blocks`, `copy_blocks`, `transaction_statements`). A regex elsewhere whose
pattern carries a lexical marker (`--`, `/*`, a dollar quote, a `'…'` shape, `stdin`,
`\.`) fails `tests/unit/test_one_sql_lexer.py`; a regex matching a statement's shape
counts against the shrink-only `sql_keyword_regex` budget. Read a `-- confiture:<name>`
directive through `directives()`. A `COPY … FROM stdin` block is **blanked, never
stripped**: the text pglast reads keeps the file's length, lines and offsets, so every
`file:line` after the block stays true. The same blanking makes a file lint could not
parse cost that file rather than the build.

**One PL/pgSQL compiler call** — `core/plpgsql_parse.parse_body()` returns
`Compiled(tree, text, neutralised, repaired)`; `tests/unit/test_plpgsql_parse.py` pins
the two shapes pglast 8 gets wrong. Its catalogue stub refuses any schema-qualified type
outside `pg_catalog`/`public`, so the qualifier is blanked with spaces (offsets kept),
and which one to blank is the compiler's answer — each blank is tested by putting it
back — never a model of PL/pgSQL's grammar. Its serialiser writes a trigger's implicit
`TG_*` datums as `{}}`, so the stray brace is deleted at the position
`json.JSONDecodeError.pos` names, only when the characters there are that defect; a
serialisation that decodes is returned byte for byte. Do not call
`pglast.parse_plpgsql` directly; do not replace the oracle with a grammar; do not
repair the JSON with a global replace.

**`plpgsql_check` is an analysis engine, not a second parser** (`core/linting/bodies.py`,
the `body` rule family). Only a built schema knows that `v_pk` is `UUID`, so the DDL is
materialised into a throwaway database (`ExpectedSchemaDB.from_source()`) and PostgreSQL
is asked; its diagnosis is reported verbatim, message and SQLSTATE. The extension is in
no stock PostgreSQL, so the rule reports `skipped` rather than an empty result when it
cannot run, and the `plpgsql-check` CI leg is where it does.

**One type canonicaliser** — `core/type_lattice.py`: `canonical_type` decides that
`int8` and `bigint` are one type, `same_type` whether two declarations are, and
`core/ddl_walk.type_name` reads a pglast `TypeName` for it (drops the `pg_catalog`
qualifier, keeps the array suffix). `tests/unit/test_one_type_canonicaliser.py`
allow-lists one other table, `ddl_walk`'s spelling table, which writes the upper-case
type a generated migration prints. A type's identity and its spelling are two fields,
deliberately: a signature drops typmods (PostgreSQL ignores them there) and a column
type keeps them, or `varchar(50)` and `varchar(100)` would compare equal.

**One path matcher** — `core/path_globs.py` answers "does this path, relative to its
include directory, match this configured glob", in **gitignore's** dialect: a pattern
with no `/` matches the filename at any depth, one with a `/` is left-anchored, `**`
spans zero or more components, `*` and `?` never cross a separator.
`PurePath.match`/`full_match`/`fnmatch` on a *path* elsewhere fails
`tests/unit/test_one_path_matcher.py`; its allow-list names the modules that match an
*object* name instead (a seed profile's globs are over bare filenames of a flat
listing, on purpose).

**One DDL reader: `core/ddl_walk.py`**, shared by every walker of a DDL tree.
- *ALTER folding.* `column_edit`, `adds_primary_key` and `object_edits` decide what an
  `ALTER`, `DROP` or rename does to the schema a tree declares. Every `AlterTableType`
  member is in `FOLDED`, `MODELLED_ELSEWHERE` or `NOT_AN_EXPECTED_SCHEMA_FACT`, and every
  `Alter…`/`Drop…`/`Rename…Stmt` node in `FOLDED_STATEMENTS`, `MODELLED_STATEMENTS` or
  `NOT_AN_EXPECTED_SCHEMA_STATEMENT` (`tests/unit/test_alter_subtypes_are_exhaustive.py`,
  `tests/unit/test_ddl_statement_kinds_are_exhaustive.py`);
  `tests/unit/test_one_alter_folder.py` fails on a module elsewhere that names an
  `AlterTableType` member. The fold is **order-aware** — `DROP TABLE IF EXISTS x;
  CREATE TABLE x (…);` is everyday DDL, and an order-blind fold deletes a table the tree
  declares.
- *Constraints.* `read_constraint(node, column=None)` returns a
  `schema_model.Constraint` or a `ColumnFact` wherever the grammar puts the node — on a
  column, at table level, in `ALTER TABLE … ADD CONSTRAINT` — and
  `read_column_constraints` folds a column's clauses in order (a trailing
  `DEFERRABLE` qualifies the constraint before it). Every `ConstrType` member is in
  `MODELLED_CONSTRAINTS` or `NOT_MODELLED_CONSTRAINTS`
  (`tests/unit/test_constraint_reader_is_exhaustive.py`). An unnamed constraint is
  identified by what it says, and generated DDL omits its `CONSTRAINT` clause so
  PostgreSQL names it as it would the author's own.
- *Column types.* `Column.type_key` is the identity (typmod kept), `raw_sql_type` the
  spelling generated DDL writes (`written_type`: the canonical name plus the parser's
  typmod, since pglast has already folded `INT` to `int4`), `type_text` the author's
  spelling a finding prints. A type the map does not know is kept exactly as the parser
  holds it, case included.

**One object list** — `core/ddl_objects.py` decides what a statement *defines* for
everything `migrate validate --require-migration` must notice (views, routines,
triggers, extensions, schemas, …), with two renderings: `definition` neutralises
`OR REPLACE`/`IF NOT EXISTS` so a view that gains one is the same view, `create_sql`
re-renders with the clause each kind supports so a generated migration re-applies.
Every `Create…Stmt` in pglast's grammar is in exactly one of `TRACKED_NODES`,
`MODELLED_ELSEWHERE` or `NOT_A_SCHEMA_OBJECT`
(`tests/unit/test_ddl_objects_are_exhaustive.py`). `ObjectRef` is a **bucket**, not an
identity: a routine's key carries its signature bucket and definitions are paired
inside it, so `fn(bigint)` and `fn(int8)` are one routine.

**One object identity** — `(schema, name)`, a missing qualifier folded to
`core/schema_identity.DEFAULT_SCHEMA`. Identity folds; **spelling never does**:
`qualified` prints what the author wrote and never invents `public.`, because a project
whose `search_path` is not `public` would have its generated DDL moved to another
schema. `tests/unit/test_one_object_identity.py` fails on a module that spells its own
`or "public"` or keys a model by a bare `.name`; both allow-lists are empty. Renames are
matched within one schema (moving a table between schemas is `SET SCHEMA`). Two
definitions of one `(schema, name)` are resolved by `duplicates.wins` — `build_001`'s
rule, so the diff reads the tree the build produces — and reported as `DIFFER_402`.

**One schema model** — `core/schema_model.py`: `Table`, `Column`, `Constraint`,
`Index`, `EnumType`, `Sequence`, `Routine`, `View`, `Trigger`, and the `SchemaModel` that
keys them by `ObjectRef`. It imports no parser and no driver (a subprocess test pins
that, which is why `confiture/core/__init__.py` resolves its names lazily).
`inventory.build_model(sql)` reads a DDL tree into it; the differ, drift and prep-seed
level 2 read that model, and the lint rules read the inventory it is built from. `tests/unit/test_one_schema_model.py` fails on a
class elsewhere named like a model type or carrying a model's fields; its allow-list
names the question each remaining class answers. `SchemaModel.to_json()` is the model's
one wire: sorted, byte-stable, published as `schema-model.schema.json`, and the model
goldens in `tests/fixtures/model_goldens/model/` are those bytes
(`tests/unit/test_port_parity_corpus.py`).

**One live reader** — `core/live_catalog.py` is the only module that reads schema facts
from `pg_catalog`, `information_schema` or the catalog views, into the same model
(`read`, plus routines, views and triggers). `tests/unit/test_one_live_reader.py` fails
on a SQL-shaped string naming the catalog anywhere else; its allow-list holds only
modules asking something that is not a schema fact (ownership, ACLs, dependency
graphs, confiture's own ledger, operational state). The parse side and the live side of
one tree are the same model — `tests/integration/test_parse_live_parity.py`, with each
normalisation it needs named and measured in `normalise_for_parity` — so drift
(`core/drift.py`) compares a model to a model, and a database built from its own DDL has
no drift by construction.

**One change union** — `core/schema_change.py`: a closed union of change variants and
the `SchemaDiff` that carries them, `to_wire()` per variant for the JSON. Every variant
declares an up renderer, a down renderer, a destructive verdict, an accompaniment class
and a risk tier from the one `RiskTier` taxonomy
(`tests/unit/test_schema_change_is_exhaustive.py`); `core/differ_sql.py` is the one
renderer, matching per group and closed by `assert_never`, and `core/ddl_clauses.py`
holds the one clause builder per element (`constraint_body`, `column_body`): the text
after `ADD` in an `ALTER` and the element in a `CREATE TABLE` are the same text. Assert
generated SQL by parsing it with pglast, never by matching strings.

**The seam** — `confiture.platform` re-exports what a tool builds on: `parse_schema`,
`introspect`, `diff`, `dependency_order`, `writable_columns`, `column_facts`,
`naming_hints`, `write_copy_seed`, `write_insert_seed`, `apply_seeds`, `validate_seeds`,
`tier_of`, the model types and the change union. A function that needs a database takes
a URL (confiture opens, commits and closes it) or any object meeting the `Connection`
Protocol (the caller owns its transaction). What the seam refuses it refuses in a
`ConfiturError` — `NotInModelError` is also a `KeyError` — never a driver's exception,
and a typo (a missing path, a bare `str` where names are expected) is never an empty
success. `tests/contract/test_platform_surface.py`
pins every name, signature and field; `tests/unit/test_platform_leaks_no_driver_types.py`
fails on a `pglast` or `psycopg` type in any signature; `docs/reference/platform-api.md`
is generated (`scripts/gen_platform_reference.py`). `confiture schema dump-model` writes
the model's wire from DDL or a live database, and
[the port's boundary](docs/architecture/rust-port-boundary.md)
(`scripts/gen_port_boundary.py`) places every `core/` module in the 2027 crate, in
Python glue, or outside the port.

#### Python migrations: the static evaluator

The SQL a `.py` migration hands to `self.execute(...)` / `self.execute_file(...)` is
resolved by `core/idempotency/static_eval/`, not by pattern-matching the call's
argument. It evaluates every form that is a pure function of the file's own text —
literals, names bound exactly once in the scope that reads them, `Path(__file__)`
arithmetic, file reads, whitelisted pure `str` methods, one-line reader helpers — and
refuses everything else with a `Refusal` code, a reason and a `remedy`. Scoping comes
from the stdlib `symtable`, never from an enumerated list of binding forms. **It never
imports, executes, `eval`s or `compile`s** — a guard test pins that.

- **Reach is a pinned table.** `tests/fixtures/idempotency_shapes/` holds one migration
  per argument shape and `tests/unit/idempotency/test_extractor_coverage.py` pins what each resolves to.
  Widening the grammar is an edit to that table; a refactor that narrows it fails the
  row that regressed. `CONFITURE_CORPUS_DIR=<dir of real .py migrations>` enables a
  floor test on a real corpus.
- **Test fixtures for "dynamic SQL" use a loop variable or a parameter.**
  `sql = "…"; self.execute(sql)` resolves; a test built on it proves nothing.

Every file-naming shape (`execute_file`, `read_text`, the runtime's
`Migration.execute_file`, the import checker's IMP010) resolves through
`core/sql_path.py`: project root → the migration's directory → cwd, first existing file
wins; static analyzers additionally confine the winner to the project root. Do not add
a fourth resolver.

#### pglast version matrix

Confiture depends on **`pglast>=6.0`, uncapped**, verified on 6.16, 7.18 and 8.4;
`uv.lock` pins the current major and the required `pglast-matrix` CI leg runs the
AST-backed suites against both ends of the range (`>=6,<7` and `>=8`). That leg runs an
explicit list of test files: a change that moves DDL reading adds its guards there.

**Never compare a parse-node enum against a literal ordinal.** PostgreSQL 18 inserted a
member into `AlterTableType`, so pglast 8 renumbered everything after it: a literal
silently stops matching, the walker drops the operation, and a replica-unsafe migration
reads `window_safe: true`. Resolve by name through the one shared module:

```python
from confiture.core._pglast_enums import member as _pg_member

_AT_DROP_COLUMN = _pg_member("AlterTableType", "AT_DropColumn")
```

Add the member to `REQUIRED_MEMBERS` there — `tests/unit/test_pglast_enum_binding.py`
enumerates from it, and checks inline literals (`if sub_int == 17:`) as well as constant
blocks. **Never add a member that only one supported pglast defines**: if a member is
missing, `enums_are_usable()` raises `CONFIG_011` naming the installed pglast at first
use, so a pglast-8-only member would make confiture refuse to start on 6 and 7.

### Native extension (schema hash only)

Confiture bundles one native function, `confiture._core.hash_files`, behind
`SchemaBuilder.compute_hash()`. It computes byte-for-byte the digest the Python
path computes (a parity test holds it) and is absent on an sdist/editable
install without a Rust toolchain — the Python path then runs and says so once
at INFO. Building the schema is pure Python.

```toml
# Cargo.toml
[dependencies]
pyo3 = { version = "0.23", default-features = false, features = ["macros"] }
sha2 = "0.10"             # Hashing
```

`scripts/cargo-test.sh` runs the crate tests (they link libpython, so the script
puts the interpreter's `LIBDIR` on the loader path; the `extension-module` feature
is on only for maturin); `[lints]` forbid `unsafe` and deny `clippy::all` + `pedantic`.

> ⚠️ **`confiture-core` (this PyO3 crate) is a performance accelerator for the
> Python package, NOT the start of a Rust rewrite.** Confiture's **1.x line is
> Python**; a full **Rust 2.x port** is a separate, planned, scoped milestone for
> **Q3–Q4 2027** (per `fraise-stack/ROADMAP.md`), shaped as a standalone crate
> that `fraisier-core` embeds — not a fold-in. Do not begin divergent Rust
> migration-engine work in this crate or conflate it with the port. Confiture is
> also an **ops-path-only** concern (invoked by fraisier at deploy time via the
> [fraisier adapter contract](./docs/reference/fraisier-adapter-contract.md));
> there is no `fraiseql`-core dependency on it. See ARCHITECTURE.md Decision 8.

---

## 📁 Project Structure

The tree below is generated from the repository by `scripts/gen_tree.py` (`--check` runs in CI;
`--write` refreshes it). A module's comment is the first line of its docstring — write the docstring,
not the tree.

<!-- BEGIN GENERATED: tree -->
```
confiture/
├── python/confiture/
│   ├── __init__.py               # Confiture: PostgreSQL migrations, sweetly done 🍓
│   ├── error_code_table.py       # The error-code catalog as data: one mapping per code, no logic
│   ├── error_codes.py            # Error code registry and definitions for structured error handling
│   ├── exceptions.py             # Confiture exception hierarchy
│   ├── url_redaction.py          # DSN credential helpers (core-side, import-safe)
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── dry_run.py            # Dry-run mode helpers for CLI integration
│   │   ├── dsn.py                # Database-URL resolution for the CLI (#152 precedence contract) and the…
│   │   ├── error_json.py         # Structured error envelope + JSON-aware CLI error boundary (issue #145)
│   │   ├── generate.py           # CLI commands for the `confiture generate` subcommand group
│   │   ├── git_validation.py     # CLI helpers for git-aware schema validation
│   │   ├── helpers.py            # Shared helpers for Confiture CLI commands
│   │   ├── idempotency.py        # ``migrate validate --idempotent`` / ``migrate fix --idempotent``: scopi…
│   │   ├── lint_formatter.py     # Output formatting for linting results
│   │   ├── main.py               # Main CLI entry point for Confiture
│   │   ├── options.py            # Shared CLI option factories and the option aliases more than one comman…
│   │   ├── ownership.py          # ``migrate fix --ownership``: apply the ownership expectation to a live…
│   │   ├── plugins.py            # Commands other distributions add to ``confiture``: the ``confiture.plug…
│   │   ├── prep_seed_formatter.py # Formatter for prep-seed validation reports
│   │   ├── schema_to_schema.py   # ``confiture migrate schema-to-schema`` — Medium 4 (FDW) CLI
│   │   ├── seed.py               # CLI commands for seed data validation
│   │   ├── seed_copy.py          # ``confiture seed convert``: the COPY-format tool
│   │   ├── sync.py               # ``confiture sync`` — Medium 3 (Production Data Sync) CLI
│   │   ├── test_db.py            # ``confiture test-db``: provision isolated template/clone test databases
│   │   ├── commands/             # CLI command modules for Confiture (35 modules)
│   │   └── formatters/           # (7 modules)
│   ├── config/                   # Configuration module for Confiture
│   │   ├── __init__.py           # Configuration module for Confiture
│   │   ├── _env_vars.py          # Shared ``${VAR}`` expansion for Confiture YAML configuration
│   │   └── environment.py        # Configuration models for Confiture
│   ├── core/                     # Core migration execution and schema building components
│   │   ├── __init__.py           # Core migration execution and schema building components
│   │   ├── _pglast_enums.py      # Name-resolved PostgreSQL parse-node enum members (issue #192)
│   │   ├── backfill.py           # The batched backfill between expand and contract: bounded, observable,…
│   │   ├── baseline_detector.py  # Baseline detector for auto-detecting migration level from a live databa…
│   │   ├── bootstrap.py          # ``confiture bootstrap`` planner and executor (issue #137 part 1)
│   │   ├── builder.py            # Schema builder - builds PostgreSQL schemas from DDL files
│   │   ├── checksum.py           # Migration file checksum computation and verification
│   │   ├── connection.py         # Database connection management for CLI commands
│   │   ├── cor_extractor.py      # Extract CREATE OR REPLACE targets from pending migrations
│   │   ├── cte_debugger.py       # CTE step-through debugger: execute each CTE in isolation to find failur…
│   │   ├── data_assertions.py    # A `RAISE EXCEPTION` guarded on data inside a migration, which `migrate…
│   │   ├── ddl_clauses.py        # Where a column and a constraint become DDL text: one clause each, every…
│   │   ├── ddl_objects.py        # The schema objects a DDL tree defines, and what makes two of them the s…
│   │   ├── ddl_walk.py           # Helpers shared by the AST walkers that read DDL, and what a statement m…
│   │   ├── dependent_objects.py  # Live dependent-objects checker for ``migrate preflight``
│   │   ├── desired_state.py      # Where ``migrate diff`` reads its desired state from (issue #196)
│   │   ├── destructive.py        # The destructive gate: who may generate, and who may apply, a migration…
│   │   ├── differ.py             # Schema differ for detecting database schema changes
│   │   ├── differ_sql.py         # Render a schema change as DDL: the up and the down each variant is, in…
│   │   ├── drift.py              # Schema drift detection for Confiture
│   │   ├── dry_run.py            # SAVEPOINT-based dry-run execution with guaranteed rollback
│   │   ├── dry_run_summary.py    # The ``--dry-run`` summary: what confiture knows about the pending migra…
│   │   ├── error_context.py      # Enhanced error context system for user-friendly error messages
│   │   ├── error_handler.py      # CLI error handler for structured error output
│   │   ├── expand_contract.py    # The expand/contract plan: the classifier's online advice as explicit, c…
│   │   ├── expected_db.py        # Build an "expected" schema into a throwaway database for pg-normalised…
│   │   ├── fk_extractor.py       # Two-pass FK extraction for cross-schema build ordering
│   │   ├── function_body_checker.py # Check that function/procedure body changes include an accompanying migr…
│   │   ├── function_body_drift.py # Function body drift detection
│   │   ├── function_body_normalizer.py # Normalise PostgreSQL function bodies for drift comparison
│   │   ├── function_signature_checker.py # Check that function parameter type changes include DROP FUNCTION for ol…
│   │   ├── function_signature_drift.py # Detect stale function overloads by comparing the routines a tree declar…
│   │   ├── git.py                # Git integration for schema validation
│   │   ├── git_accompaniment.py  # Migration accompaniment validation
│   │   ├── git_schema.py         # Schema building and comparison from git refs
│   │   ├── grant_accompaniment.py # Grant accompaniment validation
│   │   ├── import_checker.py     # Import-check validation for Python migration modules
│   │   ├── large_tables.py       # Large table migration patterns
│   │   ├── ledger.py             # Migration ledger existence probe
│   │   ├── live_catalog.py       # The one reader of a live database's schema: ``pg_catalog`` in, the sche…
│   │   ├── lock_profile.py       # What lock a DDL operation takes, and whether it rewrites the heap (issu…
│   │   ├── locking.py            # Distributed locking for migration coordination
│   │   ├── mcp_http.py           # HTTP transport adapter for MCPServer using FastAPI
│   │   ├── mcp_server.py         # MCPServer: exposes Confiture operations and PostgreSQL functions as MCP…
│   │   ├── migration_analyzer.py # Analyze migration SQL for non-transactional statements
│   │   ├── migration_generator.py # Migration file generator from schema diffs
│   │   ├── migration_grant_extractor.py # Static extraction of ``CREATE TABLE`` and ``GRANT`` statements from a
│   │   ├── migration_verifier.py # Migration verification using .verify.sql sidecar files
│   │   ├── migrator.py           # The migrator's public face: :class:`Migrator`, :class:`MigratorSession`…
│   │   ├── model_facts.py        # What the model says about the objects in it, for a caller that writes i…
│   │   ├── ownership_fixer.py    # Auto-fixer for ownership coverage gaps in migration files (issue #124)
│   │   ├── parser_info.py        # What parses the SQL: pglast's version and the PostgreSQL grammar it emb…
│   │   ├── path_globs.py         # The one path matcher: does this path, relative to its include directory…
│   │   ├── pgtap_generator.py    # Generate pgTAP test scaffolds from PostgreSQL functions
│   │   ├── plpgsql_parse.py      # Compiling a PL/pgSQL body with a compiler that has no catalogue (issues…
│   │   ├── preconditions.py      # Migration preconditions for fail-fast validation
│   │   ├── preflight.py          # Pre-flight migration checks
│   │   ├── progress.py           # Progress tracking for long-running operations
│   │   ├── psql_applier.py       # Shared COPY-aware SQL applier backed by ``psql``
│   │   ├── restorer.py           # Three-phase pg_restore orchestrator
│   │   ├── risk_tier.py          # Risk-tier taxonomy for the migration-adapter seam (issue #197)
│   │   ├── schema_analyzer.py    # Schema analysis and validation for dry-run mode
│   │   ├── schema_artifact.py    # Cacheable schema-artifact dumper (Medium 1, CI provisioning)
│   │   ├── schema_change.py      # What changed between two schema trees: one variant per kind, closed, an…
│   │   ├── schema_exporter.py    # The JSON schemas confiture publishes, and the one place they come from
│   │   ├── schema_facts.py       # What a live database can tell preflight that migration files cannot (is…
│   │   ├── schema_identity.py    # Where an unqualified schema object lands: the one default schema
│   │   ├── schema_model.py       # The one model of what a schema declares: tables, types, sequences, rout…
│   │   ├── schema_snapshot.py    # Schema history snapshot writer
│   │   ├── schema_sources.py     # Where a schema is read from: DDL text, files, a project's build, or a l…
│   │   ├── schema_to_schema.py   # Schema-to-Schema Migration using Foreign Data Wrapper (FDW)
│   │   ├── sql_lexer.py          # The one SQL lexer: libpg_query's scanner and parser, nothing hand-writt…
│   │   ├── sql_path.py           # Where does a SQL-file path written in a migration point? One answer
│   │   ├── sql_utils.py          # Shared SQL utility functions
│   │   ├── ssh_tunnel.py         # SSH tunnel context manager for remote database access
│   │   ├── step_runner.py        # Drive an expand/contract plan stage by stage, with a checkpoint after e…
│   │   ├── strategy.py           # Migration strategy header parser
│   │   ├── stub_generator.py     # Generate typed Python wrapper stubs from PostgreSQL functions
│   │   ├── syncer.py             # Production data synchronization
│   │   ├── temp_database.py      # Temporary database lifecycle and pg_dump wrapper
│   │   ├── test_db.py            # Test-database provisioning primitive (CI-path)
│   │   ├── tree_allocator.py     # SQL function tree file allocation
│   │   ├── tree_prefix.py        # What a numbered filename's prefix is, and where the file it names sorts
│   │   ├── tree_renumber.py      # SQL function tree renumber — safe file-move with cross-reference rewrit…
│   │   ├── type_lattice.py       # Is an `ALTER COLUMN … TYPE` widening or narrowing (issue #199)?
│   │   ├── unified_linter.py     # Unified SQL linter orchestrating Squawk, SQLFluff, and other tools
│   │   ├── view_body_drift.py    # View (and materialized-view) body-drift detection
│   │   ├── view_manager.py       # View dependency manager for ALTER COLUMN TYPE migrations
│   │   ├── _migrator/            # (22 modules)
│   │   ├── anonymization/        # PII anonymization framework (library API) (24 modules)
│   │   ├── change_set/           # The preflight change set: what a migration set changes, and how risky i… (5 modules)
│   │   ├── hooks/                # Enhanced Hook System (18 modules)
│   │   ├── idempotency/          # Idempotency validation for SQL migrations (19 modules)
│   │   ├── introspection/        # Introspection layer for PostgreSQL schemas, functions, and dependencies (5 modules)
│   │   ├── linting/              # Rule Library System (37 modules)
│   │   ├── replica/              # Replica-aware forward-compatibility analysis (issue #139) (3 modules)
│   │   ├── scaffold/             # Scaffold package — pluggable SQL function file generation (4 modules)
│   │   ├── seed/                 # Seed data management and optimization (24 modules)
│   │   └── validation/           # Validation orchestration for ``confiture migrate validate`` modes (16 modules)
│   ├── models/                   # Confiture migration models
│   │   ├── __init__.py           # Confiture migration models
│   │   ├── debug_models.py       # Data models for CTE step-through debugging
│   │   ├── error.py              # Error models for structured error handling: the severity every error an…
│   │   ├── function_info.py      # Data models for PostgreSQL function/procedure introspection
│   │   ├── git.py                # Data models for git-based validation reports
│   │   ├── introspection.py      # Data models for schema introspection output
│   │   ├── lint.py               # Linting models for schema validation
│   │   ├── mcp_models.py         # Data models for MCP (Model Context Protocol) server
│   │   ├── migration.py          # Migration base class for database migrations
│   │   ├── pgtap_models.py       # Data models for pgTAP test scaffold generation
│   │   ├── preflight.py          # Models for the preflight dependent-objects check
│   │   ├── results.py            # Command result models for structured output
│   │   ├── schema.py             # A schema change as it crosses a wire: :class:`WireChange`
│   │   ├── sql_file_migration.py # SQL file-based migrations
│   │   ├── stub_models.py        # Data models for Python stub generation from PostgreSQL functions
│   │   ├── unified_lint.py       # Models for unified SQL linting results
│   │   └── warnings.py           # The build-time warning every envelope that carries ``warnings[]`` repor…
│   ├── platform/                 # The seam a tool builds on: one schema model, what changed, and what a w…
│   │   └── __init__.py           # The seam a tool builds on: one schema model, what changed, and what a w…
│   ├── schemas/                  # The JSON schemas confiture publishes: the one source
│   │   └── __init__.py           # The JSON schemas confiture publishes: the one source
│   ├── sql/
│   │   └── __init__.py
│   └── testing/                  # Confiture Migration Testing Framework
│       ├── __init__.py           # Confiture Migration Testing Framework
│       ├── loader.py             # Migration loader utility for testing
│       ├── pytest_plugin.py      # Pytest plugin for confiture migration testing
│       ├── sandbox.py            # Migration testing sandbox
│       ├── worker_db.py          # Per-worker test-database name/URL resolution for pytest-xdist
│       ├── fixtures/             # Test fixtures and utilities for Confiture migration testing (4 modules)
│       ├── frameworks/           # Testing frameworks for Confiture migration validation (3 modules)
│       └── pytest/               # Pytest integration for confiture migration testing (1 module)
│
├── tests/                        # unit (no database), integration, e2e, contract, performance
│   ├── contract/
│   ├── e2e/
│   ├── fixtures/
│   ├── integration/
│   ├── performance/
│   └── unit/
│
├── db/                           # the repo's own schema, migrations and snapshots
│   ├── environments/
│   ├── schema/
│   └── schema_history/
│
├── docs/                         # the mkdocs site: guides, reference, api, features
│   ├── api/
│   ├── architecture/
│   ├── features/
│   ├── guides/
│   ├── operations/
│   ├── reference/
│   ├── release-notes/
│   ├── research/
│   └── security/
│
├── examples/                     # runnable example projects (examples.yml runs them in CI)
├── plugins/                      # distributions that add commands through confiture.plugins (pgGit)
│   └── fraiseql-confiture-pggit/
│
├── scripts/                      # generators (--check in CI) and developer helpers
├── src/                          # the confiture._core extension (file hashing)
├── ci/                           # local Dagger pipeline mirroring quality-gate.yml
│
├── .github/workflows/
│   ├── examples.yml
│   ├── lockfile-bump.yml
│   ├── migration-deployment-gates.yml
│   ├── migration-performance.yml
│   ├── publish.yml
│   ├── python-version-matrix.yml
│   └── quality-gate.yml
│
├── pyproject.toml
├── uv.lock
├── Cargo.toml
├── Cargo.lock
├── mkdocs.yml
├── docker-compose.yml
├── ARCHITECTURE.md
├── PRD.md
├── CLAUDE.md
├── CHANGELOG.md
└── README.md
```
<!-- END GENERATED: tree -->

---

## 🧪 Testing Strategy

### Test Pyramid

```
        ┌─────────────┐
        │     E2E     │  10% - Full workflows
        │   (slow)    │
        ├─────────────┤
        │ Integration │  30% - Database operations
        │  (medium)   │
        ├─────────────┤
        │    Unit     │  60% - Fast, isolated
        │   (fast)    │
        └─────────────┘
```

### Test Categories

**Unit Tests** (60% of tests):
```python
# tests/unit/test_builder.py
def test_find_sql_files():
    """Test file discovery without database"""
    builder = SchemaBuilder(env="test")
    files = builder.find_sql_files()
    assert len(files) > 0
    assert all(f.suffix == ".sql" for f in files)
```

**Integration Tests** (30% of tests):
```python
# tests/integration/test_build_local.py
@pytest.mark.asyncio
async def test_build_creates_database(test_db):
    """Test actual database creation"""
    builder = SchemaBuilder(env="test")
    await builder.build()

    # Verify tables exist
    async with test_db.connection() as conn:
        result = await conn.execute("SELECT COUNT(*) FROM pg_tables WHERE schemaname = 'public'")
        assert result.scalar() > 0
```

**E2E Tests** (10% of tests):
```python
# tests/e2e/test_complete_workflow.py
def test_full_migration_cycle():
    """Test: init -> build -> migrate -> verify"""
    runner = CliRunner()

    # Initialize
    result = runner.invoke(cli, ["init"])
    assert result.exit_code == 0

    # Build
    result = runner.invoke(cli, ["build", "--env", "test"])
    assert result.exit_code == 0

    # Migrate
    result = runner.invoke(cli, ["migrate", "up"])
    assert result.exit_code == 0
```

### Running Tests

```bash
# All tests
uv run pytest

# Unit tests only (fast)
uv run pytest tests/unit/ -v

# Integration tests (requires PostgreSQL)
uv run pytest tests/integration/ -v

# With coverage
uv run pytest --cov=confiture --cov-report=html

# Watch mode (during development)
uv run pytest-watch

# Specific test
uv run pytest tests/unit/test_builder.py::test_find_sql_files -v
```

---

## 🌱 Prep-Seed Validation

Confiture includes a comprehensive **5-level prep-seed validation system** for catching data transformation issues before deployment.

### Overview

The prep-seed pattern transforms UUID-based foreign keys into BIGINT keys using resolution functions. The validation system catches common issues:
- ❌ Seed files targeting wrong schemas (Level 1)
- ❌ Schema mapping mismatches (Level 2)
- ❌ Schema drift in resolution functions (Level 3)
- ❌ Missing tables/columns at runtime (Level 4)
- ❌ NULL FKs and constraint violations after execution (Level 5)

### Quick Usage

```python
from pathlib import Path
from confiture.core.seed.validation.prep_seed.orchestrator import (
    OrchestrationConfig,
    PrepSeedOrchestrator,
)

# Configure validation
config = OrchestrationConfig(
    max_level=5,  # Run all levels
    seeds_dir=Path("db/seeds/prep"),
    schema_dir=Path("db/schema"),
    database_url="postgresql://localhost/test",  # Required for levels 4-5
    level_5_mode="comprehensive",  # Check all constraints
)

# Run validation
orchestrator = PrepSeedOrchestrator(config)
report = orchestrator.run()

# Check results
if report.has_violations:
    for v in report.violations:
        print(f"[{v.severity}] {v.message}")
```

### Validation Levels

| Level | Type | Speed | Use Case | Database |
|-------|------|-------|----------|----------|
| 1 | Seed files | ~1s | Pre-commit | ✗ |
| 2 | Schema consistency | ~2s | Pre-commit | ✗ |
| 3 | Resolution functions | ~3s | Pre-commit | ✗ |
| 4 | Runtime compatibility | ~10s | CI/CD | ✓ |
| 5 | Full execution | ~30s | Integration tests | ✓ |

### Configuration Options

```python
OrchestrationConfig(
    # Required
    max_level: int,              # 1-5: which levels to run
    seeds_dir: Path,             # Location of seed files
    schema_dir: Path,            # Location of schema files

    # Optional
    database_url: str | None = None,      # Required for levels 4-5
    stop_on_critical: bool = True,        # Halt on CRITICAL violations
    show_progress: bool = True,           # Show progress indicators

    # Schema customization
    prep_seed_schema: str = "prep_seed",   # Schema for prep tables
    catalog_schema: str = "catalog",       # Schema for final tables
    tables_to_validate: list[str] | None = None,  # Specific tables
    level_5_mode: str = "standard",       # "standard" or "comprehensive"
)
```

### Example: CI/CD Integration

```bash
#!/bin/bash

# Static validation (no database, ~5s)
python -c "
from pathlib import Path
from confiture.core.seed.validation.prep_seed.orchestrator import (
    OrchestrationConfig,
    PrepSeedOrchestrator,
)

config = OrchestrationConfig(
    max_level=3,
    seeds_dir=Path('db/seeds/prep'),
    schema_dir=Path('db/schema'),
)
orchestrator = PrepSeedOrchestrator(config)
report = orchestrator.run()

if report.has_violations:
    print('❌ Static validation failed')
    exit(1)
"

# Full validation with database (~40s)
python -c "
import os
from pathlib import Path
from confiture.core.seed.validation.prep_seed.orchestrator import (
    OrchestrationConfig,
    PrepSeedOrchestrator,
)

config = OrchestrationConfig(
    max_level=5,
    seeds_dir=Path('db/seeds/prep'),
    schema_dir=Path('db/schema'),
    database_url=os.environ['DATABASE_URL'],
    level_5_mode='comprehensive',
    stop_on_critical=True,
)
orchestrator = PrepSeedOrchestrator(config)
report = orchestrator.run()

# Fail on CRITICAL violations
critical_count = len([v for v in report.violations if v.severity == 'CRITICAL'])
if critical_count > 0:
    print(f'❌ {critical_count} critical violations found')
    exit(1)
"

echo "✅ All seed validation passed"
```

### Testing

Unit tests for the orchestrator:
```bash
uv run pytest tests/unit/seed_validation/prep_seed/test_orchestrator.py -v
```

Integration tests with database:
```bash
uv run pytest tests/integration/test_orchestrator_integration.py -v
```

### See Also

- **[Prep-Seed Validation Guide](./docs/guides/prep-seed-validation.md)** - Comprehensive guide
- **[Example: Prep-Seed Project](./examples/06-prep-seed-validation)** - Working example

---

## 🚀 Development Workflow

### Setting Up

```bash
# Clone repository
git clone https://github.com/evoludigit/confiture.git
cd confiture

# Install uv (if not installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtual environment and install dependencies
uv sync --all-extras

# Install pre-commit hooks
uv run pre-commit install

# Verify installation
uv run confiture --version
```

### Daily Development

```bash
# 1. Create feature branch
git checkout -b feature/schema-diff

# 2. Write failing test (RED)
vim tests/unit/test_differ.py
uv run pytest tests/unit/test_differ.py::test_detect_column_rename -v
# Should FAIL

# 3. Implement minimal code (GREEN)
vim python/confiture/core/differ.py
uv run pytest tests/unit/test_differ.py::test_detect_column_rename -v
# Should PASS

# 4. Refactor (REFACTOR)
vim python/confiture/core/differ.py
uv run pytest tests/unit/test_differ.py -v
# All tests still pass

# 5. Quality checks (QA)
uv run ruff check .
uv run ty check python/confiture/
uv run pytest --cov=confiture

# 6. Commit (pre-commit hooks run automatically)
git add .
git commit -m "feat: detect column rename in schema diff"

# 7. Push and create PR
git push origin feature/schema-diff
```

---

## 🎨 Code Style

### Python Style Guide

Follow **PEP 8** with these additions:

```python
# Good: Descriptive names
def build_schema_from_ddl_files(env: str) -> str:
    """Build schema by concatenating DDL files for given environment."""
    ...

# Bad: Vague names
def build(e: str) -> str:
    ...

# Good: Type hints everywhere
def find_sql_files(self, directory: Path) -> list[Path]:
    return sorted(directory.rglob("*.sql"))

# Bad: No type hints
def find_sql_files(self, directory):
    return sorted(directory.rglob("*.sql"))

# Good: Docstrings (Google style)
def migrate_up(self, target: str | None = None) -> None:
    """Apply pending migrations up to target version.

    Args:
        target: Target migration version. If None, applies all pending.

    Raises:
        MigrationError: If migration fails.

    Example:
        >>> migrator = Migrator(env="production")
        >>> migrator.migrate_up(target="003_add_user_bio")
    """
    ...
```

### Formatting

```bash
# Auto-format with ruff
uv run ruff format .

# Check code
uv run ruff check .

# Type checking (using Astral's ty type checker)
uv run ty check python/confiture/
```

### Adding or changing a CLI option

`docs/reference/cli.md` carries one generated block per command (usage,
arguments, options) between `<!-- BEGIN GENERATED: cli confiture … -->` markers.
After changing a Typer command run `python scripts/gen_cli_reference.py --write`
and keep the hand prose around the block; `--check` (and
`tests/unit/docs/test_doc_sync_cli.py`) fails on a stale block, an undocumented
flag, an example using a flag the command has not got, or a section for a
command that does not exist.

### Adding a `confiture lint` rule

Register it in `python/confiture/core/linting/rule_registry.py` — **do not add a
per-rule CLI flag.** `--select` / `--ignore` / `--list-rules` are driven by that
registry (#150), and the three flags that predate it (`--replica-safe`,
`--check-tenant-isolation`, `--check-security-definer`) survive only as aliases.
A rule that emits violations without a registry entry still reports (unregistered
codes are never filtered out), but it is invisible to `--list-rules` and cannot
be selected or ignored.

Confiture runs `E, W, F, I, B, C4, UP, ARG, SIM`, `RUF`, `ERA`, `PTH`, `PERF`,
`PL` and `C901`, the last two with their design metrics baselined in
`tests/budgets.json`.
Only `FURB` and `TCH` are still off. `[tool.ruff.lint]` in `pyproject.toml` is the
source of truth and documents the rationale, per-rule ignores included.

### Pre-commit Hooks

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
```

Note: Type checking is handled by Astral's `ty` in CI/CD (see quality-gate.yml).
For local type checking, run: `uv run ty check python/confiture/`

---

## 🐛 Debugging

### pytest Debugging

```bash
# Run test with print statements
uv run pytest tests/unit/test_builder.py::test_find_sql_files -v -s

# Drop into debugger on failure
uv run pytest --pdb

# Run specific test with debugging
uv run pytest tests/unit/test_builder.py::test_find_sql_files --pdb -v
```

### Database Debugging

```bash
# Connect to test database
psql postgresql://localhost/confiture_test

# Check applied migrations
SELECT * FROM tb_confiture ORDER BY applied_at DESC;

# Check schema version
SELECT version FROM tb_confiture ORDER BY applied_at DESC LIMIT 1;
```

---

## 📝 Documentation

### Docstring Format (Google Style)

```python
def build_schema(env: str, output_path: Path | None = None) -> str:
    """Build schema by concatenating DDL files for given environment.

    This function reads all SQL files from db/schema/ directory in
    deterministic order and concatenates them into a single schema file.

    Args:
        env: Environment name (e.g., "local", "production").
        output_path: Optional custom output path. If None, uses
            db/generated/schema_{env}.sql.

    Returns:
        Generated schema content as string.

    Raises:
        FileNotFoundError: If schema directory doesn't exist.
        ConfigurationError: If environment config is invalid.

    Example:
        >>> builder = SchemaBuilder(env="local")
        >>> schema = builder.build_schema("local")
        >>> print(len(schema))
        15234

    Note:
        Files are processed in alphabetical order. Use numbered
        directories (00_common/, 10_tables/) to control order.
    """
    ...
```

### README Updates

When adding features, update README.md:

```markdown
## Features

- ✅ Build from DDL (Medium 1)
- ✅ Incremental migrations (Medium 2)
- ✅ Schema diff detection (NEW!)
- ⏳ Production sync (Medium 3) - Coming soon
- ⏳ Zero-downtime migrations (Medium 4) - Coming soon
```

---

## 🔒 Security

### Sensitive Data

**Never commit**:
- Database credentials (use environment variables)
- `.env` files
- Production data dumps
- API keys

**Always**:
- Use `psycopg3` parameterized queries (SQL injection prevention)
- Validate user input (file paths, environment names)
- Anonymize PII in production sync

```python
# Good: Parameterized query
cursor.execute(
    "SELECT * FROM users WHERE email = %s",
    (user_email,)
)

# Bad: String interpolation (SQL injection risk!)
cursor.execute(f"SELECT * FROM users WHERE email = '{user_email}'")
```

---

## 🤝 Contributing

### Branch Naming

```
feature/schema-diff          # New feature
fix/migration-rollback-bug   # Bug fix
docs/zero-downtime-guide     # Documentation
refactor/builder-cleanup     # Refactoring
test/integration-coverage    # Test improvements
```

### Commit Messages

Follow **Conventional Commits**:

```
feat: add schema diff detection
fix: correct column type mapping in differ
docs: update migration strategies guide
test: add integration tests for schema builder
refactor: simplify file discovery logic
perf: optimize hash computation for large files
```

### Pull Request Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [x] New feature
- [ ] Breaking change
- [ ] Documentation

## Checklist
- [x] Tests pass (`uv run pytest`)
- [x] Code formatted (`uv run ruff format`)
- [x] Type checking passes (`uv run ty check python/confiture/`)
- [x] Documentation updated

## Testing
Describe testing performed

## Related Issues
Closes #123
```

---

## 🎯 Current Status

Confiture is **production-ready** (in production since March 2026). The four mediums
(build-from-DDL, incremental migrations, production sync, schema-to-schema via FDW), the
5-level prep-seed validation, schema linting, the library API (`Migrator.from_config()` +
`MigratorSession`), and the introspection layer are all implemented.

For the current version, the full shipped-feature list, and live test counts, see
**[CHANGELOG.md](./CHANGELOG.md)** — the single source of truth for release status.

---

## 🚨 Common Pitfalls

### ❌ Don't: Mix business logic with CLI
```python
# Bad: Business logic in CLI
@app.command()
def build(env: str):
    files = sorted(Path("db/schema").rglob("*.sql"))  # Logic in CLI!
    schema = "".join(f.read_text() for f in files)
```

### ✅ Do: Separate concerns
```python
# Good: CLI calls core logic
@app.command()
def build(env: str):
    builder = SchemaBuilder(env=env)  # Core logic
    builder.build()                    # Delegate
```

This is enforced, not advised: `tests/unit/test_cli_has_no_apply_loop.py` fails on a
migration loop under `cli/`, and `tests/budgets.json` caps every function's length
and complexity per file — the numbers only go down (`scripts/budgets.py --check`).

---

### ❌ Don't: Skip type hints
```python
# Bad
def build_schema(env):
    return schema
```

### ✅ Do: Add complete type hints
```python
# Good
def build_schema(env: str) -> str:
    return schema
```

---

### ❌ Don't: Use bare except
```python
# Bad
try:
    conn.execute(sql)
except:  # What error? Why?
    pass
```

### ✅ Do: Catch specific exceptions
```python
# Good
try:
    conn.execute(sql)
except psycopg.OperationalError as e:
    raise MigrationError(f"Database connection failed: {e}") from e
```

---

## 📊 Implementation Capabilities

- ✅ **CLI**: commands across schema, migrate, admin, seed, generate subgroups; other
  distributions add theirs through the `confiture.plugins` entry point (pgGit's `branch`
  and `coordinate`: `plugins/fraiseql-confiture-pggit/`)
- ✅ **Validation System**: 5-level prep-seed orchestrator with full database support
- ✅ **CI/CD**: Multi-platform wheel building, quality gates (ruff + ty + pytest)
- ✅ **Python Support**: 3.11, 3.12, 3.13 tested
- ✅ **Library API**: `Migrator.from_config()` + `MigratorSession` context manager
- ✅ **Introspection layer**: `FunctionIntrospector`, `TypeMapper`, `DependencyGraph`
- ✅ **Structured error hierarchy**: `ConfiturError` + error codes + exit codes
- ✅ **Structured output**: JSON/CSV/YAML for all major commands

For live test counts and per-release detail, see **[CHANGELOG.md](./CHANGELOG.md)**.

---

## 🆘 Getting Help

### Resources

- **Project Docs**: `docs/`
- **API Reference**: `docs/api/`
- **Examples**: `examples/`

### Questions to Ask

When stuck, ask:
1. "What test should I write first?" (RED)
2. "What's the simplest code to make this pass?" (GREEN)
3. "How can I improve this without breaking tests?" (REFACTOR)
4. "Does this meet quality standards?" (QA)

---

## 🎉 Philosophy

> **"Make it work, make it right, make it fast - in that order."**

1. **Make it work**: Write failing test, minimal implementation
2. **Make it right**: Refactor, clean code, documentation
3. **Make it fast**: Optimize with Rust extension when needed

**Always follow TDD cycles. Always.**

---

**Last Updated**: September 22, 2026
**Version**: 1.17.0

---

*Making jam from strawberries, one commit at a time.* 🍓→🍯
