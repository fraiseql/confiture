# Schema Linting

**Validate schema files against best practices and custom rules**

---

## What is Schema Linting?

Schema linting analyzes your DDL files for common issues, naming violations, and performance problems before you deploy. It's like a spell-checker for SQL schema.

### Key Concept

> **"Catch schema mistakes before they hit production"**

Linting prevents bad designs early, enforces team standards, and improves long-term database health.

---

## When to Use Schema Linting

### ✅ Perfect For

- **Pre-deployment validation** - Catch issues before production
- **Team standards** - Enforce consistent naming conventions
- **Performance** - Detect missing indices, bad design
- **Security** - Find PII without encryption, weak constraints
- **Compliance** - Verify GDPR/HIPAA requirements
- **Code review** - Automated feedback on schema changes
- **CI/CD gates** - Block schema changes that violate rules

### ❌ Not For

- **Runtime data validation** - Use database constraints instead
- **Query optimization** - Use query analyzers instead
- **Backup strategy** - Use backup tools instead
- **Access control** - Use row-level security instead

---

## How Linting Works

### The Linting Pipeline

```
confiture lint
     │
     ├─→ Load schema files
     │
     ├─→ Parse SQL
     │
     ├─→ For each object:
     │   ├─ Apply built-in rules
     │   ├─ Apply custom rules
     │   └─ Collect violations
     │
     ├─→ Report issues
     │
     └─→ Exit with code 0 (pass) or 1 (fail)
```

### Rule Categories

| Category | Purpose | Examples |
|----------|---------|----------|
| **Naming** | Enforce conventions | Table names, column names |
| **Documentation** | Every commentable object carries a `COMMENT` | `doc_001` tables, `doc_002` routines (per overload), `doc_003` views, `doc_004` types and domains — see [lint-rules.md](../reference/lint-rules.md) |
| **Qualification** | A `CREATE` says which schema it lands in | `qual_001` routines (on), `qual_002` relations and types (opt-in) — see [lint-rules.md](../reference/lint-rules.md) |
| **Structure** | Best practices | Primary keys, timestamps |
| **Security** | Prevent vulnerabilities | PII encryption, weak constraints |
| **Performance** | Optimize queries | Missing indices, N+1 patterns |
| **Compliance** | Meet regulations | Data retention, audit trails |

---

## Running the Linter

### Basic Linting

```bash
# Lint all schema files
confiture lint

# Lint specific file
confiture lint db/schema/10_tables/users.sql

# Lint specific directory
confiture lint db/schema/10_tables/
```

**Output**:
```
🔍 Confiture Schema Linter
═════════════════════════════════════════════════════════════

Scanning: db/schema/ (15 files)

✅ PASS: db/schema/00_common/types.sql (5 objects)
⚠️  WARN: db/schema/10_tables/users.sql (3 issues)
❌ FAIL: db/schema/20_indexes/user_indices.sql (1 critical)

═════════════════════════════════════════════════════════════

Issues Found: 4

⚠️  Warnings (3):
  [W001] users.sql:12 - Column 'created_at' missing type hint comment
  [W002] users.sql:23 - Missing NOT NULL on 'email' column
  [W003] users.sql:45 - Table name uses underscore (prefer snake_case)

❌ Critical (1):
  [C001] user_indices.sql:8 - Index on non-existent column 'user_name'

═════════════════════════════════════════════════════════════

Exit code: 1 (failed)
```

---

## Selecting rules — `--list-rules` / `--select` / `--ignore`

*New in 0.42.0 (#150).*

Every rule has a **code** (`naming_001`) and belongs to a **family** (`naming`).
Start from the catalogue:

```bash
confiture lint --list-rules              # table: code, family, severity, default/opt-in
confiture lint --list-rules --format json
```

| Rule | Family | Default | Notes |
|------|--------|---------|-------|
| `naming_001` | `naming` | on | Table names snake_case |
| `naming_002` | `naming` | on | Column names snake_case |
| `pk_001` | `pk` | on | Table has a primary key |
| `doc_001` | `doc` | on | Table has a COMMENT |
| `sec_001` | `security` | on | Secret-looking columns |
| `qual_001` | `qual` | on | Routine created without a schema |
| `qual_002` | `qual` | opt-in | Relation or type created without a schema |
| `acl_001` | `acl` | opt-in | Needs `acls.lint_enabled: true` |
| `tenant_001` | `tenant` | opt-in | Multi-tenant FK isolation |
| `replica_001` | `replica` | opt-in | Replica forward-compatibility |
| `func_001` | `func` | opt-in | Needs `function_coverage.enabled: true` |
| `own_001`, `own_002` | `own` | opt-in | Need an `ownership:` block |
| `tree_001`–`tree_008` | `tree` | opt-in | DDL file-tree numbering and naming |
| `sec_002` | `security-definer` | opt-in | Needs `security_lint.enabled: true` |

The table above is a summary; [lint-rules.md](../reference/lint-rules.md) is
generated from the registry and lists every rule.

`sec_001` and `sec_002` share a code prefix but are different rules in different
families — the flag that shipped `sec_002` named `security-definer`, and that is
the selector.

### The `qual` family

An unqualified `CREATE` does not say where the object goes: the applying role's
`search_path` decides at apply time, so the same file applied by two roles
produces the object in two schemas. `qual_001` (routines) is on by default;
`qual_002` (relations and types) is opt-in because the volume in an existing
project is far higher — `--select default,qual_002`, with a `--baseline` while
the backlog drains.

`-- confiture:unqualified-ok` above a statement opts that statement out. A
`SET search_path` in the file deliberately does **not**: it is the mechanism
that makes the outcome role-dependent. See
[lint-rules.md](../reference/lint-rules.md#the-qual-family-a-create-says-which-schema-it-lands-in).

### `build_003` — references resolve against the build

The inventory that tells `build_001` an object is defined *twice* can tell you
when one is created *never*. `build_003` subtracts what the build creates from
what a routine or view body names; what is left is a body referring to
something nobody built — the failure that had one routine in a large schema
never completing a call.

It resolves in three tiers: the build inventory, then a live database when
`--env`'s connection is reachable (an object created by a migration or owned by
an extension is real and absent from the tree), then `lint.ignore_objects` for
a project with neither. A run where no database answered prints
`build_003 ran without the live tier: …` and carries the same sentence in the
JSON `degraded` array — read its count as an upper bound.

An unqualified name is not judged unless `lint.search_path` names the schemas
to look in, and an unqualified routine call is not judged even then: `now()` is
`pg_catalog`'s and no configuration makes that enumerable.

A routine whose signature or declarations name a schema-qualified type — the
shape of every mutation in a FraiseQL schema — is read like any other since
1.7.0, and a trigger function's body since 1.8.0. A body confiture still could
not read is **named** in `degraded`, not counted as clean; the one shape that
reaches it is described in
[lint-rules.md](../reference/lint-rules.md#build_003-the-inventory-read-backwards).

`--baseline` is the adoption path for an existing schema; see
[lint-rules.md](../reference/lint-rules.md#build_003-the-inventory-read-backwards).

### The file-tree family

`--select tree` runs the eight rules that read the *shape* of `db/schema/`
rather than the SQL in it. The arrangement decides which definition of an object
wins and which objects exist when a later file references one, so it is worth
checking:

| Code | Reports |
|------|---------|
| `tree_001` | two **files** in one directory share a prefix (**error**) |
| `tree_002` | a numbered file carries no verb after its prefix |
| `tree_003` | a gap in a directory's prefix sequence |
| `tree_004` | an override with no counterpart (needs `--overrides-dir`) |
| `tree_005` | two sibling **entries** share a prefix, one of them a directory |
| `tree_006` | an entry's prefix does not extend its parent's |
| `tree_007` | an entry carries no prefix while its siblings do |
| `tree_008` | a name carries a status word (`lint.status_words`) |

They read the files **the environment builds** — `exclude_dirs` and the
per-directory `exclude` globs apply — so a file the build never reads never
produces a finding about its numbering. None of them opens a file: these are
findings about names.

A tree that has never been checked will light up, which is why the family is
opt-in and why `--baseline` exists:

```bash
confiture lint --select tree --baseline .confiture-lint-baseline.json --write-baseline
```

`tree_006` reads the convention out of the tree rather than assuming one — see
[lint-rules.md](../reference/lint-rules.md#the-tree-family-the-arrangement-that-decides-the-build-order)
for what fires and what does not.

Before 1.4.0 the first four emitted `GEN001`–`GEN004` and were reachable only from
`confiture lint-unified --check tree`, outside the registry and therefore outside
`--select`, `--ignore` and `--baseline`. The old codes remain accepted
*selectors* for one minor; the codes the rules emit are the new ones.

Select and skip by code or family:

```bash
confiture lint --select pk,naming          # only those families
confiture lint --select naming_001         # one rule
confiture lint --ignore doc                # the defaults, minus doc_001
confiture lint --select default,replica    # the defaults plus a family
```

- **No `--select`** runs the default set — unchanged from earlier releases.
- **`default`** is a selector meaning "every rule marked on", so opt-in families
  can be *added* rather than replacing the defaults.
- **`--ignore` wins over `--select`.** `--select naming --ignore naming_001` runs
  `naming_002` only.
- An unknown code or family **fails** with exit 5 and lists the valid set, rather
  than quietly selecting nothing.
- Selecting a rule is necessary but not always sufficient: `acl_001` and
  `sec_002` also need their configuration block (see the table).

### The `body` family — a scratch database, and what PostgreSQL says about it

`--select body` runs the two rules that cannot answer from the files. Whether
`v_pk UUID` can receive `pk_widget BIGINT` is a fact about resolved types, and
only a built schema holds it — so these rules **build the DDL into a throwaway
database** and run
[`plpgsql_check`](https://github.com/okbob/plpgsql_check) over every PL/pgSQL
routine in it:

```bash
confiture lint --select body_001 --server-url postgresql://localhost/postgres
```

| Code | Reports | Severity |
|------|---------|----------|
| `body_001` | a diagnosis with a real SQLSTATE — the body raises on its first call | `warning` |
| `body_002` | the analyser's opinion about a body that works: an unused variable, a shadowed declaration | `info` |

Both are opt-in and separately selectable, so the failures can be adopted
without the style notes.

**Where it builds.** `--server-url` names a writable maintenance server. Only
its *server* is used: a database is created beside the configured one and
dropped again, and the environment's own database is never opened. Without the
flag the environment's `database_url` supplies the server, so pass
`--server-url` when `--env` names something you would rather not create a
database on.

**Why a run may report nothing.** `plpgsql_check` ships with no PostgreSQL
distribution — it is `postgresql-<major>-plpgsql-check` on Debian and Ubuntu,
and a source build elsewhere. Not running is therefore the common case, and it
is stated rather than reported as clean:

```
body_001 did not run: plpgsql_check is not available on the maintenance server, and no
stock PostgreSQL carries it: install it (Debian/Ubuntu `postgresql-<major>-plpgsql-check`,
or build https://github.com/okbob/plpgsql_check) and re-run
```

The same entry is in the `skipped` array of `--format json`, and **`--fail-on`
does not read a skip as a pass**: `--select body_001 --fail-on warning` over a
skip exits 1, because the run has not established that there are no warnings.

**Unqualified names.** If the environment declares `lint.search_path`, the
scratch connection is set to it before the analysis — an unqualified name in a
body resolves through `search_path`, and the analyser has to be asked the
question the application will ask.

See [lint-rules.md](../reference/lint-rules.md#the-body-family-a-routines-body-resolves-checked-by-postgresql).

### The `doc` family reports a distribution, not just a count

A documentation counter changes behaviour once a project starts driving it to
zero, and what it rewards is whatever satisfies it. `doc_001`–`doc_004` are
satisfied by any `COMMENT`, so a schema whose every object carries a one-line
restatement of its own name reports **no findings at all** and reads as 100 %
documented — the same as one where somebody read every consumer of every object
and wrote a paragraph (#250).

Every run that includes the family prints one line saying which of the two it
has, above the findings and before the "no violations" line:

```
doc: 412 documented, 0 undocumented, median comment 9 chars (p10 7, p90 14)
```

`--format json` carries the same figures per rule under `documentation`. Nothing
here is a finding: it does not move the exit code and there is nothing to
select, ignore or baseline. It is there so that "documentation: 100 %" is a
statement a reader can check.

One rule *does* judge a comment, and only in the narrowest mechanical band:

```bash
confiture lint --select default,doc_005
```

`doc_005` reports a comment whose every meaningful word is already a word of the
object's own name — `'Deletes a widget'` on `delete_widget`. It is `info` and
opt-in because it is a heuristic: a correct comment that happens to restate the
name is a false positive, and the answer to one is a baseline, not a reworded
comment. See
[lint-rules.md](../reference/lint-rules.md#doc_005-a-comment-that-says-only-what-the-name-says).

### The three per-rule flags are now aliases

`--replica-safe`, `--check-tenant-isolation` and `--check-security-definer` still
work and mean exactly what they always did — the defaults plus that one family:

| Flag | Equivalent |
|------|-----------|
| `--replica-safe` | `--select default,replica` |
| `--check-tenant-isolation` | `--select default,tenant` |
| `--check-security-definer` | `--select default,security-definer` |

They are deprecated in the help text with no removal scheduled. New rules
register in `confiture/core/linting/rule_registry.py` instead of adding a flag.

Violation output now carries the code: the text table gained a **Code** column
and JSON violations a `rule_id` field, so a finding maps back to the selector
that turns it off.

---

## A file confiture cannot parse costs that file, loudly

Every rule that reads DDL reads it through pglast. A file pglast rejects used to
cost the **whole build**: the inventory came back empty, nine rules read nothing,
and the run reported an `info` notice and exit 0. A green tick that means
"examined nothing" is worse than a red one.

Since 1.9.0 a rejected file costs one file, and says so in three places at once:

```console
$ confiture lint --env local
naming_001 ran on less than the whole schema: 1 file was not read, so nothing it
defines or references is checked (db/schema/030_broken.sql)
...
UNPARSEABLE  error  db/schema/030_broken.sql:1
$ echo $?
1
```

* **The finding.** One `UNPARSEABLE` per rejected file — not per rule that
  happened to open it — naming the file and the line pglast stopped at. It is a
  registered rule at **`error`**, so the default `--fail-on error` gate fails on
  it, the way `migrate diff` and `migrate preflight` already treat a file they
  cannot read. `--ignore UNPARSEABLE` is the escape hatch for a project with a
  deliberately non-SQL file under `db/schema/`.
* **The `degraded` array.** Every rule that lost the file is named there with
  what it lost. A `--baseline` silences the *finding*, as a baseline does; it
  does not touch `degraded`, so the blindness stays visible even in an adopted
  project.
* **The counts.** `tables_checked` and `columns_checked` count what was in the
  files that parsed, and the JSON schema says so.

### `COPY … FROM stdin` is not a parse failure

A seed file is the common shape, and it is not broken SQL: `COPY … FROM stdin`
followed by tab-separated rows and a `\.` terminator is psql *client protocol*,
which no SQL parser accepts. Adding `db/seed` to `include_dirs` used to take the
whole lint down with it.

Confiture now blanks each `COPY` block — replacing its characters with spaces and
keeping its newlines — before parsing, so the surrounding statements parse and
every finding after the block still reports the line its author wrote. Nothing
needs configuring, and nothing needs excluding:

```yaml
# db/environments/local.yaml
include_dirs:
  - db/schema
  - db/seed        # a COPY block here no longer blinds the lint
```

The blanked text is what the *parser* sees. The rules that want the real build —
the `body` family, which materialises it into a throwaway database, and
`tenant_001`, which scans it as text — still get every seed row.

---

## Making lint block — `--fail-on`

A lint whose findings never fail a pipeline is a lint nobody fixes. One flag
decides:

```bash
confiture lint --fail-on error     # the default: only errors fail
confiture lint --fail-on warning   # warnings too (`--fail-on-warning` is an alias)
confiture lint --fail-on info      # every finding fails
confiture lint --fail-on never     # report everything, never fail
```

`--fail-on-error` and `--fail-on-warning` are aliases for the first two, kept
because pipelines already pass them. Passing an alias *and* `--fail-on` states
the gate twice and exits 2; an unrecognised severity is `CONFIG_010` (exit 5).

**A threshold nothing can reach is reported, not obeyed quietly.** This is the
trap [#247](https://github.com/fraiseql/confiture/issues/247) was filed for: a
pipeline set `--fail-on-error`, no rule that ran by default emitted at `error`,
and four real `build_001` findings sat behind a green tick for months. Two
things answer it. `build_001` is now an **error**, so the default selection
reaches the default threshold and that particular pipeline goes red; and a run
whose gate genuinely cannot fire — a narrower `--select`, say — says so on the
summary instead of passing quietly:

```
$ confiture lint --select doc,naming --fail-on error
no selected rule emits at 'error'; this gate cannot fail — see --fail-on and --baseline
```

and `--format json` carries the same answer:

```json
"gate": {
  "threshold": "error",
  "reachable": false,
  "reason": "no selected rule emits at 'error'; this gate cannot fail — see --fail-on and --baseline",
  "max_selectable_severity": "warning"
}
```

A default run answers `"reachable": true` and `"max_selectable_severity":
"error"`, because `build_001` is in the default set.

Reachability is computed from the registry's declared severities *plus* the
escalations your config makes — `security_lint.severity: error` for `sec_002`,
declared replicas for `replica_001` — so a project that has escalated is told
its gate is armed rather than warned about a problem it does not have. See
[lint-rules.md](../reference/lint-rules.md) for the two escalable rules.

The three ways to make a gate meaningful, in the order to reach for them:

1. **Lower the threshold** to the severity your rules actually emit
   (`--fail-on warning` catches everything above `info`).
2. **Select a rule that reaches your threshold**, or escalate one by config.
3. **Adopt with a baseline** — with `--baseline`, *any* new finding fails the
   run whatever its severity, which is the next section.

Going the other way, a default run that has just gone red on a `build_001`
backlog declines it with `--baseline` (the ratchet), `--ignore build_001` (off
for this run) or `--fail-on never` (report, never fail). Not with `--fail-on
warning`: `warning` is a *lower* threshold than `error`, so an error still
trips it.

## Adopting a rule with a baseline — `--baseline` / `--write-baseline`

Turning on a rule against a schema that already trips it a hundred times is a
flag day nobody schedules. A **baseline** records the identity of every finding
the schema has today, and later runs fail only on findings the file does not
know:

```bash
# Once: record what exists today (the conventional name, commit it)
confiture lint --baseline .confiture-lint-baseline.json --write-baseline

# Every run afterwards: exit 0 unless something new appears, print only the new
confiture lint --baseline .confiture-lint-baseline.json
```

An identity is `rule_id:kind:qualified_name` (plus `@file` for file-scoped rules
such as `build_001`) — never a line number, so moving code around changes
nothing, while renaming an undocumented table is one identity out and one in,
and fails. When a finding disappears the file is rewritten without it, so the
ratchet only tightens; `--write-baseline` resets it deliberately. With a
baseline, **any** new finding fails the run (exit 1), whatever its severity —
that is the point of adopting a rule this way. `--format json` adds
`baseline: {new, fixed, known}` and lists only the new findings under
`violations.items`. A missing or malformed baseline file is `CONFIG_012`
(exit 5).

## Configuring Rules

Rules are a fixed catalogue, not a plug-in point. `--list-rules` prints all of
them with their code, family, severity and whatever configuration each one
additionally needs:

```bash
confiture lint --list-rules
```

### Choosing which ones run

```bash
# One rule, or a whole family
confiture lint --select pk_001
confiture lint --select pk,naming

# The usual set plus one opt-in family
confiture lint --select default,replica

# Everything except the documentation family
confiture lint --ignore doc
```

`--ignore` wins over `--select`, and an unknown selector exits 5.

### Configuration the rules read

`confiture lint` takes its settings from the environment's config file, under
keys that belong to the rule families rather than to the linter:

```yaml
# db/environments/local.yaml

lint:
  ignore_objects: []      # objects no rule reports on
  search_path: []         # schemas to resolve unqualified names against
  status_words:           # words doc_00x treats as an unfinished comment
    - TODO
    - FIXME
    - WIP
    - DRAFT
```

Some rules need more before they can report anything, and `--list-rules` says
which: `tree_004` needs `--overrides-dir`, and the `body` family needs a
writable server for its scratch database (`--server-url`, defaulting to the
environment's own `database_url`).

See [Configuration Reference](../reference/configuration.md) for every field.

### Adopting a rule against an existing backlog

A rule that fires 400 times on a mature schema is a rule nobody turns on.
`--write-baseline` records what exists today so that only *new* violations fail
— see [Adopting a rule with a baseline](#adopting-a-rule-with-a-baseline----baseline----write-baseline).

### Adding a rule

There is no user-supplied rule: no `linting:` configuration key, no rules file
to load, and no registration hook. A new rule is a change to confiture —
register it in `python/confiture/core/linting/rule_registry.py`, which is what
drives `--select`, `--ignore` and `--list-rules`.

---

## CI/CD Integration

### GitHub Actions Example

```yaml
# .github/workflows/schema-lint.yml

name: Schema Lint

on:
  pull_request:
    paths:
      - 'db/schema/**'

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install Confiture
        run: pip install fraiseql-confiture

      - name: Lint schema
        run: confiture lint --fail-on warning

      - name: Comment on PR
        if: failure()
        uses: actions/github-script@v6
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
          script: |
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: '❌ Schema lint failed. Run `confiture lint` locally to see issues.'
            })
```

---

## Best Practices

### 1. Enforce Linting in CI/CD

**Good**:
```bash
# Block on everything the rules can emit
confiture lint --fail-on warning

# Adopt against an existing backlog: fail only on what is new
confiture lint --baseline .confiture-lint-baseline.json
```

**Bad**:
```bash
# The default threshold no rule reaches: a green tick that means nothing.
# The run tells you so — read the notice rather than the exit code.
confiture lint --fail-on error
```

## Troubleshooting

### ❌ Error: "Rule not found"

**Cause**: `--select` or `--ignore` names a rule or family that does not exist.
An unknown selector exits 5 rather than silently matching nothing.

**Solution**: Check the catalogue:

```bash
# List all available rules, with the configuration each one needs
confiture lint --list-rules

# Select by code or by family; an unknown selector exits 5
confiture lint --select pk_001
confiture lint --select pk,naming
```

---

### ❌ Error: "Too many false positives"

**Cause**: Rule too strict for codebase.

**Solution**: Adjust rule severity or exceptions:

```yaml
linting:
  rules:
    naming:
      table_case: snake_case
      # But allow legacy tables
      exclude_tables:
        - UserTbl  # Existing legacy table
        - MsgQueue

  # Or disable rule
  exclude_rules:
    - "naming"  # Skip naming checks
```

---

## See Also

- [Advanced Patterns](./advanced-patterns.md) - Complex validation workflows
- [Migration Decision Tree](./migration-decision-tree.md) - Best practices
- [Troubleshooting](../troubleshooting.md) - Common issues
- [CLI Reference](../reference/cli.md) - Lint command documentation

---

## 🎯 Next Steps

**Ready to lint your schema?**
- ✅ You now understand: the rule catalogue, selection, baselines, CI/CD integration

**What to do next:**

1. **[Advanced Patterns](./advanced-patterns.md)** - Complex validation workflows
2. **[CLI Reference](../reference/cli.md)** - Full lint command documentation
3. **[Examples](https://github.com/fraiseql/confiture/tree/main/examples)** - Production linting examples

**Got questions?**
- **[FAQ](../glossary.md)** - Glossary and definitions
- **[Troubleshooting](../troubleshooting.md)** - Common issues

---

*Part of Confiture documentation* 🍓

*Making migrations sweet and simple*
