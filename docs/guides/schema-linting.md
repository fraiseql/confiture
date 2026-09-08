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
pipeline set `--fail-on-error`, no selected rule emitted at `error`, and four
real `build_001` findings sat behind a green tick for months. A run whose gate
cannot fire now says so on the summary:

```
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

Reachability is computed from the registry's declared severities *plus* the
escalations your config makes — `security_lint.severity: error` for `sec_002`,
declared replicas for `replica_001` — so a project that has escalated is told
its gate is armed rather than warned about a problem it does not have. See
[lint-rules.md](../reference/lint-rules.md) for the two escalable rules.

The three ways to make a gate meaningful, in the order to reach for them:

1. **Raise the threshold** to the severity your rules actually emit
   (`--fail-on warning` is the usual answer today).
2. **Select a rule that reaches your threshold**, or escalate one by config.
3. **Adopt with a baseline** — with `--baseline`, *any* new finding fails the
   run whatever its severity, which is the next section.

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

### Option 1: YAML Configuration

```yaml
# db/confiture.yaml

linting:
  rules:
    # Built-in rules
    naming:
      table_case: snake_case
      column_case: snake_case
      function_case: snake_case
      max_name_length: 63

    structure:
      require_primary_key: true
      require_timestamps: true
      timestamp_fields:
        - created_at
        - updated_at

    security:
      warn_plain_text_pii: true
      require_password_hash: true
      require_ssl_connections: false

    performance:
      warn_missing_indices: true
      warn_select_star: true
      max_index_columns: 5

  # Custom rules
  custom:
    - name: "email_constraint"
      description: "Ensure all email columns have uniqueness"
      rule: "email_column:unique"

    - name: "audit_table"
      description: "Ensure audit tables have timestamps"
      rule: "created_at:required"
```

### Option 2: Python Rules

```python
# db/linting/rules.py

from confiture.linting import Rule, RuleContext, Violation

class EmailConstraintRule(Rule):
    """Custom rule: email columns must have uniqueness."""

    name = "email_constraint"
    severity = "warning"
    description = "Ensure email columns have unique constraint"

    def check(self, context: RuleContext) -> list[Violation]:
        """Check for email columns without unique constraint."""
        violations = []

        for table in context.schema.tables:
            for column in table.columns:
                if 'email' in column.name.lower():
                    if not column.has_constraint('unique'):
                        violations.append(
                            Violation(
                                rule=self.name,
                                severity=self.severity,
                                table=table.name,
                                column=column.name,
                                message=f"Email column '{column.name}' must have UNIQUE constraint",
                                fix=f"ALTER TABLE {table.name} ADD CONSTRAINT {table.name}__{column.name}_unique UNIQUE ({column.name})"
                            )
                        )

        return violations
```

---

## Example: Naming Convention Rule

**Situation**: Enforce team naming standards (snake_case, no abbreviations).

```yaml
# db/confiture.yaml

linting:
  rules:
    naming:
      table_case: snake_case           # Users → users ✓
      column_case: snake_case          # UserName → user_name ✓
      index_prefix: idx_               # idx_users_email ✓
      foreign_key_prefix: fk_          # fk_users_id ✓
      max_name_length: 63              # PostgreSQL limit
      abbreviations_forbidden:
        - tbl
        - col
        - usr
        - msg
```

**Linting Output**:
```
⚠️  WARN: users.sql:1 - Table name 'UserTbl' violates convention
  Expected: user
  Found: UserTbl

⚠️  WARN: users.sql:5 - Abbreviation 'usr' forbidden
  Expected: user
  Found: usr_id
```

---

## Example: Security Rule

**Situation**: Ensure PII is encrypted and passwords are hashed.

```python
# db/linting/security_rules.py

from confiture.linting import Rule, RuleContext, Violation

class PIIEncryptionRule(Rule):
    """Ensure PII columns are encrypted."""

    name = "pii_encryption"
    severity = "critical"

    PII_PATTERNS = ['email', 'ssn', 'credit_card', 'phone', 'password']

    def check(self, context: RuleContext) -> list[Violation]:
        violations = []

        for table in context.schema.tables:
            for column in table.columns:
                # Check if column matches PII patterns
                if any(pii in column.name.lower() for pii in self.PII_PATTERNS):
                    # Check if encrypted
                    if not column.has_comment('encrypted') and 'hash' not in column.name:
                        violations.append(
                            Violation(
                                rule=self.name,
                                severity=self.severity,
                                table=table.name,
                                column=column.name,
                                message=f"PII column '{column.name}' must be encrypted or hashed",
                                fix=f"Add comment to {column.name}: -- encrypted"
                            )
                        )

        return violations
```

**Configuration**:
```yaml
linting:
  security:
    require_encryption:
      - email
      - ssn
      - credit_card
      - phone
    require_hash:
      - password
    forbidden_plain_text:
      - api_key
      - secret
      - token
```

---

## Example: Performance Rule

**Situation**: Detect missing indices and optimize queries.

```python
# db/linting/performance_rules.py

from confiture.linting import Rule, RuleContext, Violation

class MissingIndexRule(Rule):
    """Detect columns that should have indices."""

    name = "missing_indices"
    severity = "warning"

    # Columns commonly queried
    COMMONLY_QUERIED = [
        'id', 'user_id', 'email', 'created_at',
        'status', 'type', 'category'
    ]

    def check(self, context: RuleContext) -> list[Violation]:
        violations = []

        for table in context.schema.tables:
            for column in table.columns:
                # Check if commonly queried
                if column.name in self.COMMONLY_QUERIED:
                    # Check if indexed
                    if not column.has_index():
                        violations.append(
                            Violation(
                                rule=self.name,
                                severity=self.severity,
                                table=table.name,
                                column=column.name,
                                message=f"Column '{column.name}' should probably have an index",
                                fix=(
                                    f"CREATE INDEX idx_{table.name}_{column.name} "
                                    f"ON {table.name}({column.name});"
                                )
                            )
                        )

        return violations
```

---

## Example: Compliance Rule

**Situation**: Ensure GDPR compliance (data retention, audit trails).

```python
# db/linting/compliance_rules.py

from confiture.linting import Rule, RuleContext, Violation

class GDPRComplianceRule(Rule):
    """Ensure GDPR compliance requirements."""

    name = "gdpr_compliance"
    severity = "critical"

    def check(self, context: RuleContext) -> list[Violation]:
        violations = []

        for table in context.schema.tables:
            # Check for required audit columns
            has_created_at = any(c.name == 'created_at' for c in table.columns)
            has_updated_at = any(c.name == 'updated_at' for c in table.columns)

            if not has_created_at:
                violations.append(
                    Violation(
                        rule=self.name,
                        severity="critical",
                        table=table.name,
                        message="Table must have 'created_at' column for GDPR audit trail",
                        fix=f"ALTER TABLE {table.name} ADD COLUMN created_at TIMESTAMPTZ DEFAULT NOW();"
                    )
                )

            if not has_updated_at:
                violations.append(
                    Violation(
                        rule=self.name,
                        severity="critical",
                        table=table.name,
                        message="Table must have 'updated_at' column for tracking changes",
                        fix=f"ALTER TABLE {table.name} ADD COLUMN updated_at TIMESTAMPTZ DEFAULT NOW();"
                    )
                )

            # Check for PII columns without encryption
            for column in table.columns:
                if 'email' in column.name.lower() and 'encrypted' not in column.name:
                    if not column.has_comment('encrypted'):
                        violations.append(
                            Violation(
                                rule=self.name,
                                severity="critical",
                                table=table.name,
                                column=column.name,
                                message="PII must be encrypted for GDPR compliance"
                            )
                        )

        return violations
```

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

### 2. Document Custom Rules

**Good**:
```python
class CustomRule(Rule):
    """
    Custom rule: All tables must have owner.

    This ensures we can contact the team responsible
    for each table for schema changes.

    Example fix:
        COMMENT ON TABLE users IS 'owner: platform-team';
    """
```

**Bad**:
```python
class CustomRule(Rule):
    """Check something"""
    pass
```

### 3. Include Auto-Fixes

**Good**:
```python
violations.append(
    Violation(
        rule="naming",
        message="Table name should be snake_case",
        fix="Rename to lowercase"  # Clear fix
    )
)
```

**Bad**:
```python
violations.append(
    Violation(
        rule="naming",
        message="Bad table name"  # Vague
        # No fix suggestion
    )
)
```

---

## Troubleshooting

### ❌ Error: "Rule not found"

**Cause**: Custom rule not loaded or wrong name.

**Solution**: Check configuration:

```bash
# List all available rules
confiture lint --list-rules

# Load custom rules explicitly
confiture lint --rules db/linting/rules.py
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
- ✅ You now understand: Linting rules, custom rules, CI/CD integration

**What to do next:**

1. **[Advanced Patterns](./advanced-patterns.md)** - Custom validation rules
2. **[CLI Reference](../reference/cli.md)** - Full lint command documentation
3. **[Examples](https://github.com/fraiseql/confiture/tree/main/examples)** - Production linting examples

**Got questions?**
- **[FAQ](../glossary.md)** - Glossary and definitions
- **[Troubleshooting](../troubleshooting.md)** - Common issues

---

*Part of Confiture documentation* 🍓

*Making migrations sweet and simple*
