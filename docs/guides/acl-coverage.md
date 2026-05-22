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

```yaml
# db/environments/production.yaml
acls:
  - schema: tenant
    apply_to: ALL_TABLES              # or list of relname glob patterns
    ignore: [tb_*_legacy, "*_tmp"]    # optional, evaluated against the bare relname
    grants:
      - role: ${APP_ROLE}             # ${VAR} expansion at config-load time
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
- `${VAR}` expansion happens at config-load time. Missing variables raise `ConfigurationError` — they never fall back to an empty string.

---

## Static check — `confiture lint` / `migrate validate --check-acl-coverage`

The static rule parses every `*.up.sql` in `db/migrations/`, finds `CREATE TABLE` statements, and flags any that aren't matched by a `GRANT` covering all expected `(role, privilege)` pairs — either in the same migration file or in the configured global grant sweep directory (`db/7_grant/` by default).

Two ways to run it:

```bash
# Built into the default lint flow when the env has an acls: block.
confiture lint

# Explicit, suitable for a CI gate on `migrate validate`.
confiture migrate validate --check-acl-coverage --config confiture.yaml
```

`confiture lint` no-ops when the environment has no `acls:` block, so adopting the feature doesn't disrupt existing projects.

The rule operates on **base tables only** (`pg_class.relkind = 'r'`). Views, materialized views, and foreign tables are out of scope for v1 (their grant semantics differ from base tables).

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

Blank lines and additional `--` comment lines between the directive and the `CREATE TABLE` are fine. Non-comment SQL between them (anything that isn't `--`-prefixed) breaks the association so the directive only opts out the immediately-following table.

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

| Code | Meaning |
|------|---------|
| 0 | No drift detected |
| 1 | Drift detected — `MISSING_GRANT` (CRITICAL) or warnings with `--fail-on-warning` |
| 2 | Connection or configuration error (`acls:` block missing when `--check-acls` is set, malformed config, no `${VAR}`) |

`MISSING_GRANT` items are CRITICAL by default. `EXTRA_GRANT` items are WARNING — drifted grants don't fail the build unless you opt in via `--fail-on-warning`.

### `--warn-only` — progressive rollout

When you're first turning the check on, you may want to surface gaps without blocking deploys:

```bash
confiture drift --config confiture.yaml --check-acls --warn-only
```

`--warn-only` demotes `MISSING_GRANT` to WARNING. Without `--fail-on-warning`, exit code is 0 even when the check finds gaps. Pair it with a Slack notification hook to get visibility without breakage, then drop the flag once your team has caught up.

### Why the two query paths differ

The runtime detector uses **two distinct queries** that look superficially similar but answer different questions:

- `MISSING_GRANT` uses `has_table_privilege(role, table::regclass, priv)`. This is a hypothesis-check: it answers "does this role hold this privilege?" and transparently sees grants inherited through `PUBLIC`, role-membership chains, and ownership. The right primitive when you want to know whether a role *effectively* has the privilege.

- `EXTRA_GRANT` uses `information_schema.role_table_grants`. This enumerates *directly granted* privileges on the table. Privileges held only through `PUBLIC` or via ownership are deliberately not in this view — they would otherwise surface as "extras" you can't revoke (you didn't grant them).

That asymmetry is intentional and integration-tested (`test_public_inheritance_not_reported_as_extra`).

### Missing roles

If a role named in `acls:` doesn't exist in the database (e.g. you renamed it but forgot to update the config), the detector emits a single WARNING per `(table, role)` pair rather than crashing. The check is informational, and a missing role is itself a finding worth surfacing.

---

## CI/CD recipe

```yaml
# .github/workflows/quality-gate.yml
- name: ACL coverage (static)
  run: confiture migrate validate --check-acl-coverage --config confiture.yaml

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
| Column-level grants | Defer to follow-up |
| Sequence / function / schema grants | Defer to follow-up |
| `DEFAULT PRIVILEGES` as a config concept | This feature works around it; making it first-class is a separate decision |
| Auto-fix (`--fix` generating a `GRANT` migration) | Defer to follow-up |
| Per-partition inheritance for partitioned tables | Each partition treated as an independent table |

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
- [CLI Reference — `--check-acls`, `--check-acl-coverage`](../reference/cli.md)
