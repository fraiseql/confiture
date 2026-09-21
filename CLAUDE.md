# Confiture Development Guide

**Project**: Confiture - PostgreSQL Migrations, Sweetly Done 🍓
**Version**: 1.14.0
**Last Updated**: September 20, 2026
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

[project.optional-dependencies]
ast = [
    "pglast>=6.0",         # PostgreSQL's own C parser (libpg_query) — no token limits
]

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

### SQL Parsing Architecture

**One parser: pglast** (PostgreSQL's own C parser via `libpg_query`), a hard
dependency since 0.50.0 (D13). There is no regex or sqlparse fallback and no
switch to one — `tests/unit/test_single_parser.py` fails on any `FORCE_REGEX`
env var, `_HAS_PGLAST` flag or `is_pglast_available` probe. Every DDL question
has one answer, and a file pglast rejects is a **finding**, never a clean result:
`IDEM_UNPARSEABLE` (idempotency, counted as unanalyzed), `PFLIGHT_UNPARSEABLE`
(preflight, forces `window_safe: false`), lint's `UNPARSEABLE` notice, one
unclassified change-set entry, `DIFFER_400` from `migrate diff`.

The prose is guarded too, since 1.10.1: `tests/unit/docs/test_no_optional_parser.py`
fails on any document, help string or docstring that tells a reader to install a
parser confiture already depends on, or that describes a fallback. It found **19**
sites that had drifted since D13 — four guides selling the extra, five CLI `--help`
strings (published twice, since `docs/reference/cli.md` is generated from them), and
six docstrings promising a skip notice no code can emit. It reads `pyproject.toml`
and applies only while pglast is a dependency, and it scans **whole documents**: a
promise about installation lives in a paragraph, not in a code block, which is where
the guard's own first draft could not see it.

`[ast]` is an **empty alias** (`ast = []`), kept so an older
`fraiseql-confiture[ast]` still resolves. Installing it changes nothing.

The consumers, all on `pglast.parser.parse_sql`:

- **`detect_non_idempotent_patterns`** (`core/idempotency/patterns.py`, visitors
  in `ast_detector.py`) — the `migrate validate --idempotent` gate. The validator
  hands pglast the raw file; statement locations index that exact text.
- **`OperationClassifier`** (`core/replica/classifier.py`) and
  **`build_change_set`** (`core/change_set.py`) — replica forward-compatibility
  and risk tiers, sharing `core/ddl_walk.py` for what "nullable", "has a default"
  and "the type as written" mean.
- **`SchemaDiffer`** (`core/differ.py`) — `CREATE TABLE`, index, enum, sequence
  and constraint passes, all through pglast, all keyed by `(schema, name)` with
  an unqualified name folded to `schema_identity.DEFAULT_SCHEMA` (#313).
- **`SchemaLinter`** (`core/linting/schema_linter.py`) — the default rules read
  `core/linting/inventory.py`, a pglast-built object inventory, so a schema
  qualifier changes nothing (#216).

`confiture --version` names the parser on its second line and every JSON payload
carries `parser: {"pglast": "8.4", "pg_major": 18}` (`core/parser_info.py`).

**`plpgsql_check` is not a second parser** (`core/linting/bodies.py`, the `body`
family, #245). A parser cannot know that `pk_widget` is `BIGINT` and `v_pk` is
`UUID`; only a built schema knows that, so the DDL is materialised into a
throwaway database (`ExpectedSchemaDB.from_source()`) and PostgreSQL is asked.
It is an *analysis engine consulted about resolved types*, never a fallback for
reading DDL: confiture still parses every statement with pglast, and the
extension's diagnosis is reported verbatim — message and SQLSTATE — because
confiture has nothing to add to it. The extension is in no stock PostgreSQL, so
the rule reports a `skipped` status rather than an empty result when it cannot
run, and one required CI leg (`plpgsql-check`) is the only place it does.

**One place compiles a PL/pgSQL body** (`core/plpgsql_parse.py`, #270 and #272).
`pglast.parse_plpgsql` is the wrong shape twice, on **pglast 8 only** both
times — 6.16 and 7.18 have neither — and both ended in the same place, a routine
`build_003` never looked at. `parse_body()` answers for both and returns
`Compiled(tree, text, neutralised, repaired)`.

*The compiler* is PostgreSQL's own with the catalogue stubbed out, and that
stub's `LookupExplicitNamespace` resolves `pg_catalog` and `public` and refuses
everything else — so `app.mutation_response` as a parameter, a return type, a
`SETOF`, a `RETURNS TABLE` column or a `DECLARE` took the whole routine down
before a line of its body was read. That was 233 of 297 routines on a
FraiseQL-shaped schema, silently. Nothing downstream reads a type — the caller
wants linenos and `PLpgSQL_expr` query strings — so the qualifier is **blanked
with spaces**, keeping every offset and line number. Which one to blank is the
compiler's answer, never a model of PL/pgSQL's declaration grammar: a guess
narrows the search and each blank in it is then tested by *putting it back*,
because a qualifier the compiler accepts is a reference and `app.tv_summary`
blanked to `tv_summary` is a name `build_003` declines to judge.

*The serialiser* writes a trigger function's implicit `TG_*` datums as `{}}`,
one closing brace too many each, so `json.loads` never reached the tree and
**every** `RETURNS TRIGGER` and `RETURNS event_trigger` body was unread whatever
it held — 5 of the 8 plpgsql routines in this repo's own corpora. The stray
brace is deleted at the position `json.JSONDecodeError.pos` names, and only when
the characters there are that defect: `{"PLpgSQL_stmt_return":{}}` is a
legitimate `{}}` in very nearly every body, so `raw.replace("{}}", "{}")`
corrupts an ordinary `RETURNS void` function. A serialisation that decodes is
returned byte-for-byte (`repaired == 0`); one broken some other way raises, so
the routine stays named in `degraded`. Each repaired datum decodes to `{}` —
**a datum index is not a fact that tree holds**, and the three majors do not
agree on that array anyway.

Do not call `pglast.parse_plpgsql` directly; do not replace the oracle with a
grammar; do not repair the JSON with a global replace.

**One lexer too.** `core/sql_lexer.py` is the only module that tokenises SQL text
(`split_statements`, `strip_comments`, `tokens`, `code_text`, `comments`,
`directives`, `blank_copy_blocks`). A regex outside it whose pattern carries a
lexical marker — `--`, `/*`, a dollar quote, a `'…'` shape, `stdin`, `\.` — fails
`tests/unit/test_one_sql_lexer.py` (allow-list entries state why the text is not
SQL); a regex that matches a statement's shape (`^CREATE\s+TABLE`) counts against
the shrink-only `sql_keyword_regex` dimension of `tests/budgets.json`. Read a
`-- confiture:<name>` directive through `sql_lexer.directives()`, never with a
line walker of your own.

A `COPY … FROM stdin` block is **blanked, never stripped** (since 1.9.0, #274).
`blank_copy_blocks` replaces the block's characters with spaces and leaves its
newlines alone, so the text pglast reads is the same length, the same line count
and the same offsets as the text on disk. `strip_copy_blocks` is retired, not
kept alongside: deleting a block moves every finding after it, and `confiture
lint` reports `file:line` on all of them. The same technique — #270's — blanks a
whole file the lint could not parse, which is what makes a rejected file cost
that file rather than the build.

`_lex` reads the file once however many blocks are in it (since 1.9.1, #278).
After a block whose data it cannot resume across, the rescan grows a window from
the resume point until a complete `COPY … FROM stdin;` is inside it, rather than
handing `pglast.parser.scan` the rest of the file — the scanner reads its whole
buffer however early its error is, so that cost O(n × total) for n blocks. A
window is trusted for exactly the one block it was grown to hold: its tokens stop
at the window, not at the end of the file, so resuming inside one drops
everything past it. Note that `\.` does **not** make the scanner error
(`scan("\\.\n")` is `ASCII_92`, `ASCII_46`); an unterminated quote does, which
is why a corpus whose data rows lex cleanly never reaches the rescan at all and
proves nothing about it.

**One type canonicaliser too** (since 1.9.0, #275). `core/type_lattice.py` holds
the only alias table: `canonical_type` decides that `int8` and `bigint` are one
type, and `core/ddl_walk.type_name` is its reader for a pglast `TypeName` — it
drops the `pg_catalog` qualifier the parser adds, keeps the array suffix, and
leaves the internal spelling for the lattice to alias. There were **six** such
tables resolving in **three** directions; `tests/unit/test_one_type_canonicaliser.py`
deleted the two under `core/linting/` and allow-lists the remaining **two** with
the reason each is a different question (`core/ddl_walk.py` writes upper-case column
types into a migration, `core/function_signature_parser.py` resolves the
*opposite* way for what `--check-signatures` prints). The third,
`core/drift.py`'s `_types_compatible`, is gone since 1.11.0: `same_type` in the
lattice answers it, carrying the schema wildcard `inventory.types_match` applies
to a routine's arguments, because `format_type` omits a schema that
`search_path` makes visible (#302). An allow-list entry that no longer matches
anything fails, as in the one-lexer guard — which is what forced that second
edit.

A type's *identity* and its *spelling* are two fields, deliberately:
`SchemaObject.signature` is the arguments as the author wrote them, because it is
what a finding prints, and `signature_key` is `canonical_type(type_name(arg))` per
argument, because it is what decides whether two routines are the same routine.
`object_key` is a **bucket**, not an identity — a dict key cannot express "a type
schema written on one side and left off the other still matches" — so group
through `inventory.group_by_signature`, never through the key alone.

**One path matcher too** (since 1.5.0, #256). `core/path_globs.py` answers "does
this path, relative to its include directory, match this configured glob" and
nothing else does. The dialect is **gitignore's**, named as such so a reader has
a reference implementation to compare against: a pattern with no `/` matches the
*filename* at any depth, a pattern with a `/` is matched **left-anchored**
against the whole relative path, `**` spans **zero or more** components, and `*`
/ `?` never cross a separator. `PurePath.match`, `PurePath.full_match` or
`fnmatch` called on a *path* anywhere else fails
`tests/unit/test_one_path_matcher.py`; its allow-list entries state, per module,
which *object* name (`schema.relname`, a bare filename from a flat listing) that
module matches instead. That is the point of the allow-list: `SeedProfile`
spells its keys `include` / `exclude` exactly as `DirectoryConfig` does, but they
are `fnmatch` globs over a bare filename, on purpose — seed discovery is a flat
listing where a path never appears and `**` has nothing to span. `recursive`
bounds the walk and the patterns filter what it found; nothing rewrites a
pattern between what the YAML says and what the matcher sees.

**One ALTER folder too** (since 1.11.0, #301). `core/ddl_walk.py` decides what a
DDL statement does to the schema a tree declares, and two readers apply the
verdict to object models that share nothing — the lint inventory (`confiture
drift`'s expected side) and `SchemaDiffer` (`migrate diff`'s). `column_edit`
answers for one `AlterTableCmd`, `adds_primary_key` for the table-level flag, and
`object_edits` for the statement kinds that are not `AlterTableStmt` at all:
`DROP TABLE`, `ALTER TABLE … RENAME COLUMN`, `… RENAME TO` and `… SET SCHEMA` are
a `DropStmt`, two `RenameStmt` and an `AlterObjectSchemaStmt`, and no reader saw
any of them. Before it, the differ folded 3 of 66 `AlterTableType` members and
the inventory 2, so a column the tree itself dropped was reported as **critical**
drift against a database applied verbatim from that tree.

Two guards, both enumerating pglast's own grammar rather than a hand list: every
`AlterTableType` member (66) is in `FOLDED`, `MODELLED_ELSEWHERE` or
`NOT_AN_EXPECTED_SCHEMA_FACT`, and every `Alter…`/`Drop…`/`Rename…Stmt` node (41)
in `FOLDED_STATEMENTS`, `MODELLED_STATEMENTS` or
`NOT_AN_EXPECTED_SCHEMA_STATEMENT` — the declining tables being tables of
**reasons**. `tests/unit/test_one_alter_folder.py` fails on any module outside
`ddl_walk` that names an `AlterTableType` member or compares a `subtype` against
a bare ordinal; its four allow-list entries each state the different question that
module asks (replica observability, risk tier, an `IF NOT EXISTS` guard, the
object a finding names).

The fold is **order-aware**, and that is not a detail:
`DROP TABLE IF EXISTS x; CREATE TABLE x (…);` is everyday DDL and both readers
collect every `CREATE` before folding anything, so an order-blind fold deletes a
table the tree really declares. Each compares the statement's offset against the
object's. One reader folds less than the other on purpose: `objects_in` applies a
`DROP` and **not** a rename, because its two renderings are of the creating
statement and rewriting `CREATE VIEW v` as `CREATE VIEW v2` is SQL generation, not
parsing.

**One object list too** (since 1.10.0, #288). `core/ddl_objects.py` decides what
a DDL statement *defines*, for everything `migrate validate --require-migration`
has to notice. Before it, `SchemaDiffer` modelled tables, enum types and
sequences, so a view, a routine, a trigger, an extension or a schema added to the
tree and not to a migration passed the gate with a green tick — **sixteen**
statement kinds, `ALTER TABLE … ADD COLUMN` among them.

Identity is **the lint inventory's answer**, not a second one:
`inventory.object_from_statement` already decides what a statement defines, how a
schema qualifier is read, and which overload a routine is. What `ddl_objects`
adds is the half the inventory does not hold — the definition — in **two**
renderings, both `RawStream`'s and neither string surgery on its output:
`definition` neutralises `OR REPLACE` / `IF NOT EXISTS`, so a view that gains one
is the same view; `create_sql` re-renders *with* the clause each kind supports,
because a migration generated from the neutralised form carries a bare
`CREATE VIEW` that fails on its second apply.

`ObjectRef` is a **bucket**, as `object_key` is: a dict key cannot express "a type
schema written on one side and left off the other still matches", so the key
carries `signature_bucket` and `pair_definitions` matches inside it. Keying on the
full signature reported `DROP fn(bigint)` + `ADD fn(int8)` for one routine
respelled — an instruction to drop a function and take its dependents with it —
and `display`, which carries the signature *as written*, re-made the same mistake
one field along until it became `field(compare=False)`.

Every `Create…Stmt` in pglast's grammar must be in exactly one of `TRACKED_NODES`,
`MODELLED_ELSEWHERE` or `NOT_A_SCHEMA_OBJECT` — the last a table of **reasons** —
or `tests/unit/test_ddl_objects_are_exhaustive.py` fails; so does a node claimed
twice, and so does a declined node pglast no longer defines. That guard is the
point of the module. The sixteen invisible kinds were not sixteen oversights but
one: nothing said which statements the differ answered for, so a kind never
considered looked exactly like a kind deliberately skipped.

A schema pglast rejects now **fails** that gate rather than skipping it
(`is_valid: false`, `was_skipped` in the envelope). The old exit 0 was justified
by the sqlparse token limit, which D13 made unreachable.

**One object identity too** (since 1.13.0, #313). What makes two relations the
same relation is `(schema, name)` with a missing qualifier folded to
`core/schema_identity.py`'s `DEFAULT_SCHEMA` — the middle term of
`inventory.object_key`, which `ddl_objects.ObjectRef` and `drift.py` already
applied. `SchemaDiffer` was the **last reader of a DDL tree here with no schema
in its identity**: `Table(name=stmt.relation.relname)` threw `schemaname` away at
parse time, so inside one `compare()` call `a.v` and `b.v` were two views —
`ParsedSchema.objects` is #288's `ObjectRef` — and `a.t` and `b.t` were one
table. The same run answered the same question two ways.

It was silent *and* destructive. Silent: on a 707-file schema with `tenant.` /
`etl_ingest.` twins, **4 of 433 tables** were permanently invisible to
`migrate validate --require-migration`. Destructive: swapping two files' build
order — a rename, a renumber, **no schema change at all** — made the differ
compare `tenant.t` against `etl.t` and `migrate diff --generate` write
`ALTER TABLE t DROP COLUMN IF EXISTS b`. It also corrupted the parse itself:
`ALTER TABLE etl.t ADD COLUMN` and `CREATE INDEX … ON etl.t` landed on
`tenant.t`; `DROP TABLE etl.t` and `ALTER TABLE etl.t RENAME TO` hit **both**
tables. And it shipped in this repository's own `examples/06-prep-seed-validation`
— the prep-seed pattern *is* two schemas holding the same table names.

Identity folds; **spelling never does**. `Table.qualified` /
`EnumType.qualified` / `Sequence.qualified` print what the author wrote and
never invent a `public.`, because a project whose `search_path` is not `public`
would have its generated DDL rewritten into another schema. That is
`ObjectRef`'s own split between the key and `display`, and `SchemaObject`'s
between `signature` and `signature_key` (#275).

Renames are matched **within one schema**, and that is grammar rather than a
threshold: `ALTER TABLE a.t RENAME TO a.t2` is a syntax error (moving a table
between schemas is `SET SCHEMA`), and `_similarity_score` scores
`tenant.tb_meter`/`etl.tb_meter` at 0.6 — exactly what it scores the real rename
`tenant.tb_a`/`tenant.tb_b`. No threshold separates those.

A **collapse is a finding**: two definitions of one `(schema, name)` in one tree
are resolved by `duplicates.wins` — `build_001`'s own rule — so the diff reads
the tree the build produces (a later `IF NOT EXISTS` is a no-op, so the *first*
definition is what the database has), and `DIFFER_402` says so in
`migrate diff --format json`'s `warnings[]` and in the accompaniment report.
Warned, not failed: a duplicate is `confiture lint`'s problem and
`build --fail-on-duplicates`' problem, both of which already exist and are
opt-in.

`tests/unit/test_one_object_identity.py` fails on a module that spells its own
`or "public"` beside a schema (nine sites in four modules did) or that keys one
of the schema-object models by a bare `.name` in a comprehension; both
allow-lists are empty, and an entry matching nothing fails as in the one-lexer
guard. The check is pinned against `3b12dcce`'s three maps verbatim — a guard
never seen red is a guard that does not run. `DEFAULT_SCHEMA` moved out of
`core/linting/inventory.py` into its own import-safe module for a measured
reason: two of those four sites needed the fold and not a parser, so they wrote
the word instead.

**One constraint reader too** (since 1.14.0, #315 and #316). PostgreSQL's
grammar puts a `Constraint` node in three places — on a column, at table level
inside `CREATE TABLE`, and in `ALTER TABLE … ADD CONSTRAINT` — and
`core/differ.py` had three readers of it. The column loop read **none**, so
`pid INT REFERENCES b.parent(id)` parsed to zero foreign keys; the other two
disagreed about what a CHECK expression is, one rendering it and one storing
`type(raw_expr).__name__`, which generated
`ALTER TABLE t ADD CONSTRAINT ck CHECK (A_Expr) ()`. Across this repository's own
schema and its eight example schemas, **13 of 17 foreign keys** and 16 of 23
unique constraints were invisible.

The one reader lives in `core/ddl_walk.py` and **returns** what a node declares:
`read_constraint(node, column=None)` gives a `schema_model.Constraint` (primary
key, UNIQUE, CHECK, foreign key — with its deferrability) or a `ColumnFact`
(`NOT NULL`, default, identity, generated expression), and
`read_column_constraints(coldef)` folds a column's clauses in order, because on a
column `DEFERRABLE INITIALLY DEFERRED` arrives as sibling nodes after the
constraint it qualifies. Where the constraint was written decides only which
columns it covers; whoever assembles the table applies a primary key to the
columns it covers. The differ and the lint inventory both read through it. Every
`ConstrType` member is in `MODELLED_CONSTRAINTS` or `NOT_MODELLED_CONSTRAINTS`,
the second a table of **reasons**; a generated column's `raw_expr` is not a
CHECK, which is exactly why the reader dispatches on the kind and never on that
field. `tests/unit/test_constraint_reader_is_exhaustive.py` enumerates pglast's
own enum and fails on a member in neither table, in both, or on a modelled kind
missing from `_pglast_enums.REQUIRED_MEMBERS`. A *declined* member the installed
pglast lacks is tolerated and named: confiture supports pglast 6 through 8 and
PostgreSQL 18 added the `ENFORCED` pair — which is also why that pair stays
declined, since `REQUIRED_MEMBERS` is version-fatal.

An **unnamed** constraint is identified by what it says, never by `""` — two
unnamed foreign keys on one table were one — and generated DDL omits the
`CONSTRAINT` clause rather than inventing `child_pid_fkey`. PostgreSQL then
generates the same name it would have generated for the author's own DDL, which
an integration test pins, because that is what makes omitting it safe rather than
lossy. `NOT VALID` + `VALIDATE CONSTRAINT` needs the name, so an unnamed foreign
key is added in one statement carrying the module's `-- review:` idiom.

`_constraint_body` is the one clause builder: the text after `ADD` in an `ALTER`
and the element in a `CREATE TABLE` are the same text. Writing it twice is how
the reader came to disagree with itself. `differ_sql.column_body` is its sibling
for a column — `CREATE TABLE`, `ADD COLUMN` and a dropped column's declaration —
and writes an identity and a generated expression as the schema declared them.

**A column's type has a spelling too** (since 1.14.0). `Column.type` is the
canonical `ColumnType` — the identity — and `Column.raw_sql_type` is **the type
as generated DDL should write it, recorded for every column**
(`ddl_walk.written_type`, one rule for every model of a column). It used to be
filled only when the type map missed, which is what dropped
`VARCHAR(50)`'s length on the floor: the length lives in the spelling, and a
modelled type had no spelling to keep it in. A schema saying `VARCHAR(50)`
generated an unbounded `VARCHAR`, and `VARCHAR(50)` → `VARCHAR(100)` reported
**nothing at all**.

The name comes from the canonical type and the typmod from the parser, and that
split is deliberate: pglast has already folded the author's keywords into
PostgreSQL's internal spellings — `INT` arrives as `int4`, `DOUBLE PRECISION` as
`float8` — so "as the author wrote it" is not recoverable here and writing the
parser's string back is valid DDL nobody wants to read. A type the map does not
know is left exactly as the parser holds it, case included, because `"MyType"`
is not `mytype`. A type with no typmod therefore generates the text it always
generated.

Whether two columns declare the same type is `type_lattice.same_type`, never a
comparison of the spellings: that is the one canonicaliser (#275), and its own
docstring states this case — *a signature drops typmods, because PostgreSQL
ignores them there, and a **column** type must keep them or `varchar(50)` and
`varchar(100)` compare equal*. One rule, two questions.

**One schema model too.** `core/schema_model.py` defines `Table`, `Column`,
`Constraint`, `Index`, `EnumType`, `Sequence` and the `SchemaModel` that keys them
by `ObjectRef`; it imports no parser and no driver (a subprocess test pins that,
which is why `confiture/core/__init__.py` resolves its names lazily).
`inventory.build_model(sql)` reads a DDL tree into it — the lint inventory is the
one DDL reader that answers in it — and its output for every example tree is
pinned in `tests/fixtures/model_goldens/model/`. A column carries its type twice
(`type_key` the identity, typmod kept; `raw_sql_type` the spelling) plus
`type_text`, the author's spelling a finding prints.
`tests/unit/test_one_schema_model.py` fails on a class elsewhere that is named
like a model type or carries the fields of one; its allow-list names the question
each existing one answers, and an entry that matches nothing fails.

Prep-seed level 2 reads the qualifier too (1.14.0, #317): `SchemaTables` keys
`(schema, name)` and routes on `Table.schema`, not on
`"prep_seed" in str(sql_file)`. A tree declaring nothing in the configured
prep-seed schema is a **finding**, not a silent empty pass — the heuristic routed
unqualified DDL somewhere and a qualifier cannot.

#### Python migrations: the static evaluator (since 0.46.0, #213)

The SQL a `.py` migration hands to `self.execute(...)` / `self.execute_file(...)`
is resolved by `core/idempotency/static_eval.py`, not by pattern-matching the
call's argument. It evaluates every form that is a pure function of the file's
own text — literals, names bound exactly once in the scope that reads them
(module constants, single-assignment locals, `self.<attr>` class attributes),
`Path(__file__)` arithmetic, file reads, pure `str` methods by whitelist, and
one-line reader helpers — and refuses everything else with a `Refusal` code, a
reason and a `remedy`. Scoping comes from the stdlib `symtable` (the compiler's
own analysis), never from an enumerated list of binding forms. **It never
imports, executes, `eval`s or `compile`s** — a guard test pins that.

Two invariants to keep:

- **Reach is a pinned table.** `tests/fixtures/idempotency_shapes/` holds one
  migration per argument shape and `test_extractor_coverage.py` pins what each
  resolves to. Widening the grammar is an edit to that table; narrowing it, by
  any refactor, fails the row that regressed. `CONFITURE_CORPUS_DIR=<dir of
  real .py migrations>` enables a floor test on a real corpus.
- **Test fixtures for "dynamic SQL" use a loop variable or a parameter.**
  `sql = "…"; self.execute(sql)` resolves now; a test built on it proves nothing.

Every file-naming shape (`execute_file`, `read_text`, the runtime's
`Migration.execute_file`, the import checker's IMP010) resolves through
`core/sql_path.py`: project root → the migration's directory → cwd, first
existing file wins; static analyzers additionally confine the winner to the
project root. Do not add a fourth resolver.

#### pglast version matrix (since 0.39.0, #192)

Confiture depends on **`pglast>=6.0`, uncapped** — a hard dependency since
0.50.0 (D13), not an extra. `[ast]` survives as an empty alias so an older
`fraiseql-confiture[ast]` still resolves; installing it changes nothing.
Verified green on 6.16,
7.18 and 8.4; `uv.lock` pins the current major, and a required
`pglast-matrix` CI leg runs the AST-backed suites against both ends of the
range (`>=6,<7` and `>=8`).

**Never compare a parse-node enum against a literal ordinal.** PostgreSQL 18
inserted a member into `AlterTableType`, so pglast 8 renumbered everything at
index ≥ 13 down by one — `_AT_DROP_COLUMN = 14` silently stopped matching and
the `elif` chains fell through, *dropping* the operation. Because `window_safe`
is computed from the presence of `PFLIGHT_REPLICA_*` findings, that turned
replica-unsafe migrations into `window_safe: true`.

Resolve by name through the single shared module instead:

```python
from confiture.core._pglast_enums import member as _pg_member

_AT_DROP_COLUMN = _pg_member("AlterTableType", "AT_DropColumn")
```

Add the member to `REQUIRED_MEMBERS` in that module — the guard test
(`tests/unit/test_pglast_enum_binding.py`) enumerates from it, so a new constant
joins the guard automatically. If pglast ever drops a member confiture walks,
`enums_are_usable()` raises `CONFIG_011` naming the installed pglast, at first
use, rather than under-reporting silently.

Note that a literal can hide *inline* (`if sub_int == 17:`), not just in a
constant block — that form is how `core/idempotency/_captures.py` survived the
first sweep. The guard checks both shapes.

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
│   │   ├── branch.py             # CLI commands for pgGit branch operations
│   │   ├── coordinate.py         # Multi-agent coordination CLI commands for pgGit
│   │   ├── dry_run.py            # Dry-run mode helpers for CLI integration
│   │   ├── dry_run_summary.py    # The ``--dry-run`` summary: what confiture knows about the pending migra…
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
│   │   ├── prep_seed_formatter.py # Formatter for prep-seed validation reports
│   │   ├── schema_to_schema.py   # ``confiture migrate schema-to-schema`` — Medium 4 (FDW) CLI (issue ARCH…
│   │   ├── seed.py               # CLI commands for seed data validation
│   │   ├── sync.py               # ``confiture sync`` — Medium 3 (Production Data Sync) CLI
│   │   ├── test_db.py            # ``confiture test-db``: provision isolated template/clone test databases
│   │   ├── commands/             # CLI command modules for Confiture (31 modules)
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
│   │   ├── blue_green.py         # Blue-green migration orchestration
│   │   ├── bootstrap.py          # ``confiture bootstrap`` planner and executor (issue #137 part 1)
│   │   ├── builder.py            # Schema builder - builds PostgreSQL schemas from DDL files
│   │   ├── checksum.py           # Migration file checksum computation and verification
│   │   ├── connection.py         # Database connection management for CLI commands
│   │   ├── cor_extractor.py      # Extract CREATE OR REPLACE targets from pending migrations
│   │   ├── cte_debugger.py       # CTE step-through debugger: execute each CTE in isolation to find failur…
│   │   ├── data_assertions.py    # A `RAISE EXCEPTION` guarded on data inside a migration, which `migrate…
│   │   ├── ddl_objects.py        # The schema objects a DDL tree defines, and what makes two of them the s…
│   │   ├── ddl_walk.py           # Helpers shared by the AST walkers that read DDL, and what a statement m…
│   │   ├── dependent_objects.py  # Live dependent-objects checker for ``migrate preflight``
│   │   ├── desired_state.py      # Where ``migrate diff`` reads its desired state from (issue #196)
│   │   ├── destructive.py        # The destructive gate: who may generate, and who may apply, a migration…
│   │   ├── differ.py             # Schema differ for detecting database schema changes
│   │   ├── differ_sql.py         # Generate DDL SQL from SchemaChange objects
│   │   ├── drift.py              # Schema drift detection for Confiture
│   │   ├── dry_run.py            # SAVEPOINT-based dry-run execution with guaranteed rollback
│   │   ├── error_context.py      # Enhanced error context system for user-friendly error messages
│   │   ├── error_handler.py      # CLI error handler for structured error output
│   │   ├── expand_contract.py    # The expand/contract plan: the classifier's online advice as explicit, c…
│   │   ├── expected_db.py        # Build an "expected" schema into a throwaway database for pg-normalised…
│   │   ├── fk_extractor.py       # Two-pass FK extraction for cross-schema build ordering
│   │   ├── function_body_checker.py # Check that function/procedure body changes include an accompanying migr…
│   │   ├── function_body_drift.py # Function body drift detection
│   │   ├── function_body_normalizer.py # Normalise PostgreSQL function bodies for drift comparison
│   │   ├── function_signature_checker.py # Check that function parameter type changes include DROP FUNCTION for ol…
│   │   ├── function_signature_drift.py # Detect stale function overloads by comparing source signatures against…
│   │   ├── function_signature_parser.py # Parse PostgreSQL function/procedure signatures from SQL text
│   │   ├── git.py                # Git integration for schema validation
│   │   ├── git_accompaniment.py  # Migration accompaniment validation
│   │   ├── git_schema.py         # Schema building and comparison from git refs
│   │   ├── grant_accompaniment.py # Grant accompaniment validation
│   │   ├── import_checker.py     # Import-check validation for Python migration modules
│   │   ├── large_tables.py       # Large table migration patterns
│   │   ├── ledger.py             # Migration ledger existence probe
│   │   ├── live_function_catalog.py # Adapter that converts FunctionIntrospector results to FunctionSignature…
│   │   ├── live_objects.py       # The views, matviews, triggers and routines a live database holds (issue…
│   │   ├── live_view_catalog.py  # Query live view (and materialized-view) definitions from a database
│   │   ├── lock_profile.py       # What lock a DDL operation takes, and whether it rewrites the heap (issu…
│   │   ├── locking.py            # Distributed locking for migration coordination
│   │   ├── mcp_http.py           # HTTP transport adapter for MCPServer using FastAPI
│   │   ├── mcp_server.py         # MCPServer: exposes Confiture operations and PostgreSQL functions as MCP…
│   │   ├── migration_analyzer.py # Analyze migration SQL for non-transactional statements
│   │   ├── migration_generator.py # Migration file generator from schema diffs
│   │   ├── migration_grant_extractor.py # Static extraction of ``CREATE TABLE`` and ``GRANT`` statements from a
│   │   ├── migration_verifier.py # Migration verification using .verify.sql sidecar files
│   │   ├── migrator.py           # Migration executor — public re-exports
│   │   ├── ownership_fixer.py    # Auto-fixer for ownership coverage gaps in migration files (issue #124)
│   │   ├── parser_info.py        # What parses the SQL: pglast's version and the PostgreSQL grammar it emb…
│   │   ├── path_globs.py         # The one path matcher: does this path, relative to its include directory…
│   │   ├── pg_version.py         # PostgreSQL version detection and feature flags
│   │   ├── pgtap_generator.py    # Generate pgTAP test scaffolds from PostgreSQL functions
│   │   ├── plpgsql_parse.py      # Compiling a PL/pgSQL body with a compiler that has no catalogue (issues…
│   │   ├── preconditions.py      # Migration preconditions for fail-fast validation
│   │   ├── preflight.py          # Pre-flight migration checks
│   │   ├── progress.py           # Progress tracking for long-running operations
│   │   ├── psql_applier.py       # Shared COPY-aware SQL applier backed by ``psql``
│   │   ├── restorer.py           # Three-phase pg_restore orchestrator
│   │   ├── risk_tier.py          # Risk-tier taxonomy for the migration-adapter seam (issue #197)
│   │   ├── rollback_generator.py # Auto-generate rollback SQL for simple operations
│   │   ├── schema_analyzer.py    # Schema analysis and validation for dry-run mode
│   │   ├── schema_artifact.py    # Cacheable schema-artifact dumper (Medium 1, CI provisioning)
│   │   ├── schema_exporter.py    # The JSON schemas confiture publishes, and the one place they come from
│   │   ├── schema_facts.py       # What a live database can tell preflight that migration files cannot (is…
│   │   ├── schema_identity.py    # Where an unqualified schema object lands: the one default schema
│   │   ├── schema_model.py       # The one model of what a schema declares: tables, columns, constraints,…
│   │   ├── schema_snapshot.py    # Schema history snapshot writer
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
│   │   ├── _migrator/            # (19 modules)
│   │   ├── anonymization/        # PII anonymization framework (library API) (24 modules)
│   │   ├── change_set/           # The preflight change set: what a migration set changes, and how risky i… (4 modules)
│   │   ├── hooks/                # Enhanced Hook System (18 modules)
│   │   ├── idempotency/          # Idempotency validation for SQL migrations (17 modules)
│   │   ├── introspection/        # Introspection layer for PostgreSQL schemas, functions, and dependencies (6 modules)
│   │   ├── linting/              # Rule Library System (36 modules)
│   │   ├── replica/              # Replica-aware forward-compatibility analysis (issue #139) (3 modules)
│   │   ├── scaffold/             # Scaffold package — pluggable SQL function file generation (3 modules)
│   │   ├── seed/                 # Seed data management and optimization (24 modules)
│   │   └── validation/           # Validation orchestration for ``confiture migrate validate`` modes (15 modules)
│   ├── integrations/
│   │   ├── __init__.py
│   │   └── pggit/                # pgGit integration module for Confiture (9 modules)
│   ├── models/                   # Confiture migration models
│   │   ├── __init__.py           # Confiture migration models
│   │   ├── debug_models.py       # Data models for CTE step-through debugging
│   │   ├── error.py              # Error models for structured error handling
│   │   ├── function_info.py      # Data models for PostgreSQL function/procedure introspection
│   │   ├── git.py                # Data models for git-based validation reports
│   │   ├── introspection.py      # Data models for schema introspection output
│   │   ├── lint.py               # Linting models for schema validation
│   │   ├── mcp_models.py         # Data models for MCP (Model Context Protocol) server
│   │   ├── migration.py          # Migration base class for database migrations
│   │   ├── pgtap_models.py       # Data models for pgTAP test scaffold generation
│   │   ├── preflight.py          # Models for the preflight dependent-objects check
│   │   ├── results.py            # Command result models for structured output
│   │   ├── schema.py             # Data models for schema representation
│   │   ├── sql_file_migration.py # SQL file-based migrations
│   │   ├── stub_models.py        # Data models for Python stub generation from PostgreSQL functions
│   │   ├── unified_lint.py       # Models for unified SQL linting results
│   │   └── warnings.py           # The build-time warning every envelope that carries ``warnings[]`` repor…
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
│   ├── performance/
│   ├── reference/
│   ├── release-notes/
│   ├── research/
│   └── security/
│
├── examples/                     # runnable example projects (examples.yml runs them in CI)
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

Confiture runs `E, W, F, I, B, C4, UP, ARG, SIM` plus the heavier families the
top-notch plan turned on in Phase 11 — `RUF`, `ERA`, `PTH`, `PERF`, `PL` and
`C901`, the last two with their design metrics baselined in `tests/budgets.json`.
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
- [x] PHASES.md updated (if applicable)

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

- ✅ **CLI**: commands across schema, migrate, admin, seed, branch, coordinate, generate subgroups
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

**Last Updated**: September 20, 2026
**Version**: 1.14.0

---

*Making jam from strawberries, one commit at a time.* 🍓→🍯
