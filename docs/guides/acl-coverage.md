# ACL Coverage

[← Back to Guides](../index.md) · [Drift Detection](git-aware-validation.md) · [Schema Linting](schema-linting.md)

Catch tables that ship without their expected `GRANT`s — both before they merge (static lint) and after they reach a database (runtime drift).

---

## The problem

`ALTER DEFAULT PRIVILEGES FOR ROLE deploy IN SCHEMA tenant GRANT SELECT ON TABLES TO my_app` only applies to tables created **by role `deploy`**. Migrations frequently run as a different role (e.g. `migrator`), so the new table inherits no default ACL and ends up owner-only. Full-rebuild environments mask this because `db/7_grant/*.sql` runs separately; production migrations don't.

Confiture's other checks never noticed this:

- `confiture lint` validated naming, PKs, docs, multi-tenant columns, FK indexes, secrets — not ACL coverage.
- `confiture drift` compared structure (tables, columns, indexes), not ACLs.
- `confiture migrate validate` checked orphaned files / idempotency / DDL accompaniment — not "this `CREATE TABLE` has no matching `GRANT`".

The ACL coverage feature plugs both gaps.

---

## The `acls:` block

You declare expected grants once in the environment YAML. Both the static rule and the runtime check read the same block.

Two shapes are accepted:

```yaml
# db/environments/production.yaml — flat list (back-compat)
acls:
  - schema: tenant
    apply_to: ALL_TABLES
    grants:
      - role: ${APP_ROLE}
        privileges: [SELECT, INSERT, UPDATE, DELETE]
```

```yaml
# Nested shape — recommended from 0.12.0
acls:
  lint_enabled: true                  # opt into the lint rule (default: false)
  expectations:
    - schema: tenant
      apply_to: ALL_TABLES            # or list of relname glob patterns
      ignore: [tb_*_legacy, "*_tmp"]  # optional, evaluated against the bare relname
      grants:
        - role: ${APP_ROLE}           # ${VAR} expansion at config-load time
          privileges: [SELECT, INSERT, UPDATE, DELETE]
        - role: ${ETL_ROLE}
          privileges: [SELECT, INSERT, UPDATE, DELETE]
        - role: ${ADMIN_ROLE}
          privileges: [SELECT]
    - schema: public
      apply_to: ALL_TABLES
      grants:
        - role: ${APP_ROLE}
          privileges: [SELECT, INSERT, UPDATE, DELETE, TRUNCATE]
```

Validation:

- `apply_to` is either `"ALL_TABLES"` or a list of `fnmatch` glob patterns (same semantics as the `confiture build` ignore globs).
- `privileges` must be a subset of `{SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER}`. Casing is normalized to uppercase on load.
- Unknown keys are rejected (`extra="forbid"` on the Pydantic model).
- `${VAR}` expansion happens at config-load time. Only the strict form `${UPPER_NAME}` is supported — `${VAR:-default}`, `${lower}`, and nested forms raise `ConfigurationError` with an actionable diagnostic. Missing variables fail loud — they never fall back to an empty string.

---

## Static check — `confiture lint` / `migrate validate --check-acls`

The static rule parses every `*.up.sql` in `db/migrations/`, finds `CREATE TABLE` statements, and flags any that aren't matched by a `GRANT` covering all expected `(role, privilege)` pairs — either in the same migration file or in the configured global grant sweep directory (`db/7_grant/` by default).

Two ways to run it:

```bash
# Lint flow — opt in via `acls.lint_enabled: true` in the env YAML.
confiture lint

# Explicit, suitable for a CI gate on `migrate validate`.
confiture migrate validate --check-acls --config confiture.yaml
```

`confiture lint` no-ops unless **both** the environment has an `acls:` block AND `acls.lint_enabled: true` is set. Merely defining `acls:` for the drift command no longer auto-fires the lint rule (changed in 0.12.0 — see CHANGELOG). `--check-acls` on `migrate validate` works regardless of `lint_enabled`; the flag itself is the opt-in.

`--check-acl-coverage` is kept as a deprecated alias for `--check-acls` on `migrate validate` — prefer the canonical spelling.

The rule operates on **base tables** (`pg_class.relkind = 'r'`) and **partitioned parents** (`relkind = 'p'`). Partition *children* (`relispartition = true`) are excluded because their grants are inherited from the parent — flagging them would be a false positive that multiplies with every new partition. Views, materialized views, and foreign tables remain out of scope (their grant semantics differ).

### Opt-out: the `-- confiture:owner-only` directive

Some tables really should be owner-only — audit ledgers, write-once event logs. Mark them with a magic comment in the contiguous comment block immediately preceding the `CREATE TABLE`:

```sql
-- confiture:owner-only
-- audit ledger, only the owner reads/writes
CREATE TABLE catalog.tb_audit_ledger (
  id bigserial primary key,
  -- ...
);
```

Blank lines and additional `--` comment lines between the directive and the `CREATE TABLE` are fine. Non-comment SQL between them (anything that isn't `--`-prefixed) breaks the association so the directive only opts out the immediately-following table. Inline forms (`CREATE TABLE foo (…); -- confiture:owner-only`) and block-comment forms (`/* confiture:owner-only */`) are **not** recognized — the directive must live on its own `--` line above the statement.

**Use sparingly.** The directive permanently disables coverage for the marked table — prefer adding the grants you actually want over silencing the check. Owner-only is appropriate for write-once audit ledgers and similar tables whose access pattern is "only the owner ever touches it"; it is rarely the right answer for application tables.

### What the violation looks like

```
❌ ACL coverage check failed: 1 violation(s)
  ✗ [acl_001] public.tb_order: Role 'my_app' is missing grant(s) INSERT, SELECT on
   'public.tb_order'. Add a `GRANT INSERT, SELECT ON public.tb_order TO my_app;`
   to 20260522120000_add_orders.up.sql or to the global grant sweep directory.
```

Every violation names `(schema.table, role, missing privileges)` and a paste-ready `GRANT` statement.

### Same-migration drops

A table created and dropped within the same migration doesn't trigger the rule (intermediate scratch tables are fine).

### Parser tiers

The static extractor uses pglast (PostgreSQL's own C parser via `libpg_query`) when available and falls back to sqlparse + regex. Both code paths are exercised by parameterized unit tests against identical fixtures. Install the optional extra to get pglast: `pip install "fraiseql-confiture[ast]"`.

---

## Runtime check — `confiture drift --check-acls`

The runtime check compares live `pg_class.relacl` against the `acls:` block. Use it when a table already shipped without coverage — full-rebuild environments mask the gap, but production never does.

```bash
confiture drift --config confiture.yaml --check-acls
```

`--schema` is optional with `--check-acls`. If you want both structural and ACL drift in one run, pass both flags.

### Exit codes

| Exit code | Meaning | What to do |
|-----------|---------|------------|
| 0 | No drift detected. The live ACLs match the spec. | Nothing — green build. |
| 1 | Drift detected. `MISSING_GRANT` items are CRITICAL by default; `EXTRA_GRANT` items are WARNING and only fail with `--fail-on-warning`. | Add the missing `GRANT` (paste-ready stanza is in the report), or `REVOKE` the unexpected one. |
| 2 | Configuration or connection error: `--check-acls` set without an `acls:` block, an env-var reference in `acls:` could not be expanded (`${MISSING}` or unsupported syntax like `${VAR:-default}`), or the database connection failed. | Read stderr — the diagnostic names the cause. Set the missing variable, fix the YAML, or check connectivity. |

`MISSING_GRANT` items are CRITICAL by default. `EXTRA_GRANT` items are WARNING — drifted grants don't fail the build unless you opt in via `--fail-on-warning`.

### `--warn-only` — progressive rollout

When you're first turning the check on, you may want to surface gaps without blocking deploys:

```bash
confiture drift --config confiture.yaml --check-acls --warn-only
```

`--warn-only` demotes `MISSING_GRANT` to WARNING. Without `--fail-on-warning`, exit code is 0 even when the check finds gaps. Pair it with a Slack notification hook to get visibility without breakage, then drop the flag once your team has caught up.

### Why the two query paths differ

`MISSING` grants are detected via `has_table_privilege()` (which sees PUBLIC, role inheritance, and ownership); `EXTRA` grants via `information_schema.role_table_grants` (which sees only direct grants, the ones you can actually revoke). The asymmetry is intentional — read `python/confiture/core/drift.py` and the `test_public_inheritance_not_reported_as_extra` integration test for the full rationale.

### Missing roles

If a role named in `acls:` doesn't exist in the database (e.g. you renamed it but forgot to update the config), the detector emits a single WARNING per `(table, role)` pair rather than crashing. The check is informational, and a missing role is itself a finding worth surfacing.

---

## Adopting on an existing project

If you have hundreds of tables already in production with no `acls:` block, here is the recipe to backfill safely.

### 1. Generate a starting point from the live ACLs

Run this query against the live database to dump the *current* state as a YAML draft:

```sql
SELECT
  format(
    '  - schema: %I'      || E'\n' ||
    '    apply_to: [%L]'  || E'\n' ||
    '    grants:'         || E'\n' ||
    string_agg(
      format(
        '      - role: %I'         || E'\n' ||
        '        privileges: [%s]',
        grantee,
        string_agg(privilege_type, ', ' ORDER BY privilege_type)
      ),
      E'\n'
    ),
    n.nspname, c.relname
  )
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN information_schema.role_table_grants g
  ON g.table_schema = n.nspname
 AND g.table_name = c.relname
WHERE c.relkind IN ('r', 'p')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND grantee NOT IN ('PUBLIC')
GROUP BY n.nspname, c.relname, grantee;
```

The output is *current state*, not *intent*. Review every line before committing — some of those grants may be wrong and you're about to declare them as the spec.

### 2. Roll out with `--warn-only`

Until you're confident the block matches your intent:

```bash
confiture drift --check-acls --warn-only --config db/environments/production.yaml
```

Missing grants surface as warnings, not errors. Hook the output into Slack / your dashboards. Once a few days pass without surprises, drop the flag.

### 3. Backfill `7_grant/*.sql` from the block

The opposite recipe — start from a committed `acls:` block, generate the `GRANT` statements that would make the database match — is currently a manual translation: for each `(schema, table, role, privileges)`, write the `GRANT <privileges> ON <schema>.<table> TO <role>;`. A `--fix` CLI subcommand is tracked as future work in the Limitations table below.

---

## CI/CD recipe

```yaml
# .github/workflows/quality-gate.yml
- name: ACL coverage (static)
  run: confiture migrate validate --check-acls --config confiture.yaml

- name: ACL drift (live)
  if: github.ref == 'refs/heads/main'
  env:
    APP_ROLE: ${{ secrets.APP_ROLE }}
    ETL_ROLE: ${{ secrets.ETL_ROLE }}
  run: confiture drift --check-acls --config db/environments/production.yaml
```

The static check is a pre-merge gate (no database access required). The runtime check runs after deploy against the real database.

---

## Limitations

| Out of scope (v1) | Tracking |
|---|---|
| Row-level security policies | Defer to follow-up |
| Column-level grants | Defer to follow-up — `AclTableExpectation` is named to leave room for column/sequence variants |
| Sequence / function / schema grants | Defer to follow-up |
| `DEFAULT PRIVILEGES` as a config concept | This feature works around it; making it first-class is a separate decision |
| Auto-fix (`--fix` generating a `GRANT` migration) | Defer to follow-up |
| Partition-specific grants different from parent | Children inherit; per-partition overrides are not v1 scope (parent / children handled in 0.12.0) |

### `search_path` and unqualified table names

A `CREATE TABLE foo` in a migration that runs with `SET search_path = tenant, public;` lands in `tenant`. The static parser sees just `foo` and assumes `public`. **Recommendation: qualify table names explicitly in migrations** (`CREATE TABLE tenant.foo`). Real projects typically already do this; the runtime check is unaffected because it reads the actual `pg_namespace`.

### Dynamic SQL

`EXECUTE format('CREATE TABLE %I (…)', name)` is invisible to any static parser. The extractor detects the pattern and `has_dynamic_sql()` is available to callers; ACL coverage for dynamically-created tables can only come from the runtime check.

---

## Related

- [Drift Detection — `confiture drift`](git-aware-validation.md)
- [Schema Linting — `confiture lint`](schema-linting.md)
- [Migration Hooks — `confiture migrate validate`](hooks.md)
- [Configuration Reference — the `acls:` block](../reference/configuration.md)
- [CLI Reference — `--check-acls`](../reference/cli.md)
