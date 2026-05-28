# Function Uniqueness

[← Back to Guides](../index.md) · [Ownership Coverage](ownership-coverage.md) · [Schema Linting](schema-linting.md)

Catch `CREATE FUNCTION` / `CREATE PROCEDURE` definitions that appear in more than one DDL file — before `confiture build` silently picks the last-loaded copy.

---

## The problem

`confiture build` concatenates every `.sql` file in your schema directory in deterministic file-order, then feeds the result to PostgreSQL.  If two files define the same callable:

```
db/schema/0397_maintenance/03970_sync_tv_dimensions.sql
db/schema/0397_maintenance/039700_sync_tv_dimensions.sql
```

both with:

```sql
CREATE OR REPLACE FUNCTION stat_etl.sync_tv_dimensions()
RETURNS integer AS $$ … $$ LANGUAGE plpgsql;
```

PostgreSQL accepts both (each `CREATE OR REPLACE` succeeds), but only the **last-loaded** copy survives.  No warning, no failure, no signal at runtime — just whichever copy lexicographic file order produces.

Nobody knows which is authoritative.  Git history shows two parallel evolutions.  Bugs that look fixed in one file resurface because the other shadows it.

---

## The `function_coverage:` block

You opt the rule in by declaring a `function_coverage:` block in your environment YAML:

```yaml
# db/environments/production.yaml
function_coverage:
  enabled: true
  apply_to:               # fnmatch-style schema-name patterns
    - "*"                 # every schema
  ignore:                 # object-path globs (schema.name)
    - "public.legacy_*"
```

Validation:

- `enabled` (default `false`) — master switch.  When `false` the rule is a no-op.
- `apply_to` (default `["*"]`) — list of `fnmatch` patterns matched against the *schema name*.  `["public", "stat_etl"]` covers only those two schemas; `["*"]` covers all.
- `ignore` (default `[]`) — list of `fnmatch` patterns matched against the *qualified callable name* (`schema.name`).  Useful when a duplicate is intentional and needs to stay (very rare — prefer the inline directive instead).

The block is **opt-in by default** to avoid surprising existing projects that already ship known duplicates.  Documented upgrade path: enable, run, fix or opt out per call site, then leave on.

---

## Static check — `migrate validate --check-function-uniqueness`

The static rule parses every `*.sql` file in the configured DDL directories, extracts each `CREATE FUNCTION` / `CREATE PROCEDURE`, and flags any fully-qualified signature defined in more than one file.

```bash
confiture migrate validate \
  --check-function-uniqueness \
  --config confiture.yaml \
  --ddl-dir db/schema
```

- Exit `0` on success or when the project has no `function_coverage:` block (opt-in semantics).
- Exit `1` when violations are found.
- Exit `2` on config errors.

`--ddl-dir` is repeatable; default is `db/schema`.

Output looks like:

```
❌ Function uniqueness check failed: 1 violation(s)
  ✗ [func_001] stat_etl.sync_tv_dimensions: Function 'stat_etl.sync_tv_dimensions()'
    is defined in 2 files: 03970_sync_tv_dimensions.sql, 039700_sync_tv_dimensions.sql.
    `confiture build` will silently keep whichever copy is loaded last; the
    earlier definitions are dropped. Resolve by removing the duplicate or
    marking one with `-- confiture:func-allow-duplicate`.
```

---

## Kind-aware key

The duplicate-detection key is `(kind, schema, name, parameter_types_tuple)` where `kind ∈ {"function", "procedure"}`.  Three corollaries:

1. **Functions and procedures don't collide.**  `CREATE FUNCTION public.foo()` and `CREATE PROCEDURE public.foo()` live in separate PostgreSQL namespaces, so they're distinct.
2. **Overloads are distinct.**  `foo(integer)` and `foo(text)` are different signatures — neither is a duplicate of the other.
3. **OUT parameters don't participate.**  Per PostgreSQL overload-resolution rules, only `IN` / `INOUT` / `VARIADIC` parameters count toward the signature.  `foo(IN x int)` and `foo(IN x int, OUT y text)` are the same signature — and one of them will shadow the other at build time.

---

## Opt-out directive

Put `-- confiture:func-allow-duplicate` on the line directly above a `CREATE FUNCTION` (or `CREATE PROCEDURE`) to exclude that one statement from the duplicate-detection map:

```sql
-- confiture:func-allow-duplicate
CREATE OR REPLACE FUNCTION public.foo()
RETURNS void AS $$ … $$ LANGUAGE plpgsql;
```

The directive attaches to the *next* non-blank non-comment line.  Use it sparingly — every annotated duplicate is a future bug magnet.

---

## AST-only by design

`func_001` is AST-only via [pglast](https://github.com/lelit/pglast).  When pglast is not installed, the rule emits one skip notice to stderr and returns no violations:

```
func_001 requires the [ast] extra: pip install "fraiseql-confiture[ast]"
```

Install the extra to enable the rule:

```bash
pip install "fraiseql-confiture[ast]"
```

The rule is intentionally false-negative-safe: it would rather skip than ship a half-working regex detector that lets duplicates through silently.

---

## CI/CD recipe

Run the check as a pre-merge gate alongside ownership / ACL coverage:

```yaml
# .github/workflows/db.yml (excerpt)
- name: Function uniqueness
  run: |
    confiture migrate validate \
      --check-function-uniqueness \
      --config db/environments/preflight.yaml \
      --ddl-dir db/schema \
      --format json --output func-uniqueness.json

- uses: actions/upload-artifact@v4
  with:
    name: func-uniqueness-report
    path: func-uniqueness.json
```

Exit code `1` fails the gate; exit code `0` lets it through.

---

## See Also

- [Schema Linting](schema-linting.md) — the umbrella surface
- [Ownership Coverage](ownership-coverage.md) — the sibling axis (one canonical owner per env)
- [ACL Coverage](acl-coverage.md) — the other sibling axis (`GRANT` sweep)
- [CLI Reference](../reference/cli.md)
