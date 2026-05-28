# Ownership Coverage

[← Back to Guides](../index.md) · [ACL Coverage](acl-coverage.md) · [Drift Detection](git-aware-validation.md)

Catch tables, sequences, views, and materialized views that ship without the expected owner — both before they merge (static lint, optionally auto-fixed) and after they reach a database (runtime drift).

This is the **ownership axis** of the same drift class covered by [ACL Coverage](acl-coverage.md). The two features are designed as siblings: one canonical config block per axis, parallel CLI flags, parallel checks.

---

## The problem

When `CREATE TABLE` (or `CREATE VIEW`, `CREATE MATERIALIZED VIEW`, `CREATE SEQUENCE`) inside a migration runs as a role **other than** the project's canonical migrator role, the new object is owned by whoever ran the statement — typically `postgres` if a hotfix was applied manually. Subsequent schema-wide grant statements then fail in production with:

```
ERROR:  permission denied for table foo
HINT:   grantor must own the object
```

A single drifted owner can abort an entire `GRANT … ON ALL SEQUENCES` migration, leaving the schema in a half-granted state. This drift is invisible under build-from-DDL (rebuild runs everything as one role) and only surfaces in incrementally-deployed environments.

---

## The `ownership:` block

You declare the expected owner once in the environment YAML. Both the static rule (`own_001`) and the runtime drift detector read the same block.

```yaml
# db/environments/production.yaml
ownership:
  expected_owner: migrator
  apply_to:
    - schema: tenant
      relkinds: [r, S, v, m]      # table, sequence, view, matview
    - schema: public
      relkinds: [r, S]
  ignore:
    - public.legacy_audit_log     # literal qualified name
    - "*.audit_log"               # cross-schema glob
  lint_enabled: true              # opt-in default for own_001 (default: true)
```

Validation:

- `expected_owner` must be a valid Postgres role identifier: `[a-z_][a-z0-9_]*`, or a double-quoted form `"Mixed Case"` for mixed-case roles.
- `relkinds` accepts only `r` (regular table), `S` (sequence), `v` (view), and `m` (materialized view). Default covers all four. Unknown values raise a `ConfigurationError` with the rejected set named.
- `ignore` accepts both literal qualified names (`schema.relname`) and `fnmatch` globs (`*.audit_log`, `tenant.*_legacy`).
- `${VAR}` expansion runs at config-load time on the same terms as `acls:` — strict `${UPPER_NAME}` form only, missing variables fail loud.

Unlike `acls:` (a list of expectations), `ownership:` is a single declaration — there is exactly one canonical owner per environment.

---

## Static check — `migrate validate --check-ownership-coverage`

The static rule parses every `*.up.sql` in `db/migrations/`, finds each `CREATE` in scope, and flags any that aren't paired with `ALTER … OWNER TO <expected_owner>` later in the same file.

```bash
confiture migrate validate --check-ownership-coverage --config confiture.yaml
```

- Exit `0` on success or when the project has no `ownership:` block (opt-in semantics).
- Exit `1` when violations are found.
- Exit `2` on config errors.

Output looks like:

```
❌ Ownership coverage check failed: 2 violation(s)
  ✗ [own_001] tenant.tb_orders: Table 'tenant.tb_orders' was created without
    `ALTER … OWNER TO migrator;` in the same migration.  Without it, schema-wide
    GRANTs from the canonical migrator role will fail with `grantor must own the object`.
  ✗ [own_001] public.s_invoice_id: Sequence 'public.s_invoice_id' was created without …
```

### AST-only by design

`own_001` is AST-only — pairwise `CREATE` ↔ `ALTER … OWNER TO` matching across realistic PostgreSQL SQL (dollar-quoted strings, CHECK-constraint literals, multi-statement `DO $$ … $$` blocks) is too brittle to ship as a regex. When pglast is not installed, the rule emits a single skip notice and returns no violations rather than ship a half-working detector:

```
own_001 requires the [ast] extra: pip install "fraiseql-confiture[ast]"
```

Install the extra to enable the rule:

```bash
pip install "fraiseql-confiture[ast]"
```

### Sibling rule — `own_002` bare `ALTER OWNER`

`own_001` catches *new* `CREATE` without a paired `ALTER OWNER`.  Its sibling `own_002` catches the opposite shape: an `ALTER … OWNER TO <expected_owner>` on an object the migration did **not** itself create.  This is the catch-22 from [issue #137](https://github.com/fraiseql/confiture/issues/137) — a migration tries to "repair" pre-existing wrong ownership, but it runs as the non-owning migrator role and fails at apply time.

Three severity tiers per occurrence:

| Shape | Severity | Recommended fix |
|-------|----------|-----------------|
| Bare `ALTER OWNER`, no guard | **ERROR** | Run [`confiture bootstrap`](bootstrap.md) once, or wrap in `IF EXISTS` and mark `requires_superuser = True`. |
| `IF EXISTS` guard, no `requires_superuser = True` | **WARNING** | Add `requires_superuser = True` to the companion `.py` so the migration runs via [`apply-as`](superuser-migrations.md). |
| `IF EXISTS` guard AND `requires_superuser = True` | silent | Intended pattern — no action needed. |

Companion detection: the rule looks for a sibling `.py` file with the same stem (`20260528170300_fix.up.sql` → `20260528170300_fix.py`) and greps for `requires_superuser\s*=\s*True`.  Pure-SQL migrations with no companion default to "not superuser."

`own_002` is registered alongside `own_001` under `--check-ownership-coverage`; the two run in lockstep.

### Opt-out: the `-- confiture:owner-skip` directive

For genuinely extension-owned objects, mark the `CREATE` with a directive comment on its own line:

```sql
-- confiture:owner-skip   (intentional: extension manages this table)
CREATE TABLE extensions.dblink_meta (id int);
```

### Skipping a whole file: `-- confiture:run-as <role>`

When a migration is known to run as a specific role, declare it once at the top:

```sql
-- confiture:run-as migrator
CREATE TABLE tenant.tb_orders (id int);
-- no ALTER OWNER needed; the migration declared its role
```

**Trust boundary.** The `-- confiture:run-as` directive is **declarative only**. The lint rule trusts the comment; nothing at lint time verifies the migration actually runs as that role in production. If a developer writes `-- confiture:run-as migrator` but the migration is then applied by `postgres` in staging, the lint will pass but the runtime drift detector (`confiture drift --check-ownership`, below) will catch it. The static rule is the PR-time gate; the runtime check is the production-time gate — they are designed to be complementary.

---

## Runtime check — `confiture drift --check-ownership`

Compare `pg_class.relowner` in a live database against the configured expectation. Reports one `WRONG_OWNER` drift item per relation whose actual owner differs from `expected_owner`.

```bash
confiture drift --check-ownership --config confiture.yaml
```

Composable with the structural and ACL drift checks in a single invocation:

```bash
confiture drift \
  --check-ownership \
  --check-acls \
  --schema db/generated/schema.sql \
  --config confiture.yaml
```

JSON output for CI pipelines:

```bash
confiture drift --check-ownership --format json --config confiture.yaml
```

```json
{
  "expected_schema_source": "ownership",
  "has_drift": true,
  "tables_checked": 12,
  "drift_items": [
    {
      "type": "wrong_owner",
      "severity": "critical",
      "object": "tenant.tb_orders",
      "expected": "migrator",
      "actual": "postgres",
      "message": "Relation 'tenant.tb_orders' is owned by 'postgres' but expected owner is 'migrator'"
    }
  ]
}
```

### Partition handling

Partition children are **individually checked**. PostgreSQL allows each partition to have a distinct owner (uncommon but legal), and a drifted child is exactly the kind of mistake this detector exists to catch. If you split partitions across roles intentionally, list each drifted child in `ignore`.

---

## Auto-fix — `migrate fix --ownership`

Once the lint rule flags a missing `ALTER … OWNER TO`, the auto-fixer can insert it directly into the migration file:

```bash
# Preview
confiture migrate fix --ownership --dry-run --config confiture.yaml

# Apply
confiture migrate fix --ownership --config confiture.yaml
```

The fixer inserts each `ALTER … OWNER TO` on the line immediately following the offending `CREATE`'s terminating semicolon. Re-running the fixer on an already-fixed file is a no-op.

### Checksum-drift guard

Confiture records checksums of every applied migration in the local tracking table. Rewriting an already-applied file silently breaks `migrate verify`, so the fixer **refuses** to rewrite files whose version is recorded:

```
Refused 1 file(s) (already applied — pass --force to rewrite anyway):
  ✗ 20260527090000_add_foo.up.sql: already applied locally
```

Pass `--force` to override — typically only safe in a development environment where you can re-apply the migration cleanly afterwards. The guard runs against the local database only; verify against other environments separately before rewriting.

### Combined with `--idempotent`

A single invocation can apply both fix classes; idempotency fixes run first, then ownership fixes:

```bash
confiture migrate fix --idempotent --ownership --config confiture.yaml
```

---

## Combined with ACL coverage

The ownership and ACL features sit on parallel axes — most projects want both.

CI step covering everything at once:

```bash
confiture migrate validate \
  --check-acl-coverage \
  --check-ownership-coverage \
  --config db/environments/production.yaml
```

Live drift in one query:

```bash
confiture drift \
  --check-acls \
  --check-ownership \
  --config db/environments/production.yaml
```

---

## Edge cases

- **Extension-installed objects.** Use the `-- confiture:owner-skip` directive on the `CREATE` statement.
- **Migrations that run as the expected role.** Use the `-- confiture:run-as <role>` front-matter directive — remember the trust boundary documented above.
- **Partitioned tables.** `ALTER TABLE OWNER TO` does **not** cascade to partition children in older PostgreSQL versions. The drift detector flags each child individually; the auto-fixer emits `ALTER` for whatever appears as a `CREATE` in the migration.
- **`ALTER OWNER TO` prerequisites.** The grantor must be a member of the target role. If your migrator role is freshly provisioned, ensure `GRANT migrator TO <session_role>` runs before the migration.
- **Side effects on `SECURITY DEFINER`.** Changing ownership on a table referenced by functions/views with `SECURITY DEFINER` can shift the effective privileges those routines run with. Review carefully when auto-fixing in environments with `SECURITY DEFINER` callers.

---

## Related

- [ACL Coverage](acl-coverage.md) — the sister feature on the grants axis.
- [Function Uniqueness](function-uniqueness.md) — the sister feature on the duplicate-DDL axis (`func_001`).
- [Bootstrap](bootstrap.md) — operator-explicit setup that prevents the wrong-owner drift in the first place (`confiture bootstrap`).
- [Drift Detection](git-aware-validation.md) — full drift command reference.
- Issue history: #66 (grant-sweep accompaniment), #120 (ACL coverage), #124 (ownership — this guide), #137 (bootstrap & superuser migrations).
