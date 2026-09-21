# Bootstrap

[← Back to Guides](../index.md) · [Ownership Coverage](ownership-coverage.md) · [Legacy Bootstrap](legacy-bootstrap.md)

One-shot environment ownership setup: create the migrator role, fix pre-existing wrong-owned objects, and configure default privileges — once, by an operator, with superuser.

---

## The problem

Migrations run as the canonical migrator role (e.g. `migrator`).  When an object was created by some other role — typically `postgres` during a manual hotfix — the next migration that tries to `ALTER … OWNER TO migrator` fails:

```
ERROR:  permission denied
HINT:   must be owner of the table
```

You're stuck in a catch-22:

- The migration runs as `migrator` (correct policy), but
- `ALTER OWNER` on a foreign-owned object requires superuser, so
- The migration fails mid-apply, leaving the schema half-migrated.

The fix is operational, not in-migration: **bootstrap the environment as superuser once, then let migrations behave normally afterwards.** That's what `confiture bootstrap` does.

---

## The command

```bash
confiture bootstrap --env production                # report drift (--mode check)
confiture bootstrap --mode plan --env production    # show the SQL
confiture bootstrap --mode apply --env production   # execute
```

Three modes, chosen with `--mode` (1.16.0; before it, `--check`, `--dry-run` and
`--apply`):

| `--mode` | Side effects | Exit codes |
|------|--------------|------------|
| `check` (default) | Read-only | `0` no drift, `1` drift, `5` config error |
| `plan` | None | `0` (prints SQL) |
| `apply` | Creates role, runs `REASSIGN OWNED`, sets default privileges | `0` success, `5` config or runtime error |

`--format json` reports `"mode": "check"`, `"dry-run"` or `"apply"`: the `plan` mode's
payload keeps the value it carried before the flag was renamed.

All three modes connect with `ownership.bootstrap_connection_url` (see below) — which must be a superuser URL.

---

## Configuration

```yaml
# db/environments/production.yaml
ownership:
  expected_owner: migrator
  apply_to:
    - schema: tenant
    - schema: public
  bootstrap_connection_url: ${BOOTSTRAP_DATABASE_URL}   # superuser URL
  default_privileges:
    tenant:
      app: [SELECT, INSERT, UPDATE, DELETE]
      readonly: [SELECT]
    public:
      app: [SELECT, INSERT, UPDATE, DELETE]
```

### `bootstrap_connection_url` (required for `bootstrap`)

The bootstrap command refuses to run without this field.  Every step (`CREATE ROLE`, `REASSIGN OWNED`, `ALTER DEFAULT PRIVILEGES`) needs superuser; we don't fall back to the env's main URL because we have no safe way to detect whether it has superuser.  Make the intent explicit.

`${VAR}` expansion runs at config-load time on the same terms as `expected_owner`.

### `default_privileges` (optional)

Maps `schema → role → [PRIVILEGE, ...]`.  When present, `bootstrap` emits one `ALTER DEFAULT PRIVILEGES FOR ROLE migrator IN SCHEMA <s> GRANT … ON TABLES TO <role>` per pair.  When absent, the step is skipped with a one-line notice — useful when you manage default privileges through a separate process.

Privilege keywords are validated against the standard set: `SELECT`, `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, `REFERENCES`, `TRIGGER`, `EXECUTE`, `USAGE`.  Unknown tokens raise a `ValidationError` at config-load time.

---

## What `--mode apply` actually runs

```sql
-- Step 1: CREATE ROLE (only if absent from pg_roles)
CREATE ROLE "migrator" WITH LOGIN NOCREATEROLE;

-- Step 2: REASSIGN OWNED (only if postgres-owned objects exist)
REASSIGN OWNED BY postgres TO "migrator";

-- Step 3: ALTER DEFAULT PRIVILEGES (one per schema/role pair)
ALTER DEFAULT PRIVILEGES FOR ROLE "migrator"
  IN SCHEMA "tenant"
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "app";
-- … more ALTER DEFAULT PRIVILEGES statements …
```

The entire plan runs inside a single transaction.  On any failure, the executor rolls back and raises `BootstrapError`.

---

## The `--all-schemas` safety gate

`REASSIGN OWNED BY postgres TO migrator` is **database-wide** — PostgreSQL provides no per-schema variant.  When `postgres` owns objects in schemas outside `ownership.apply_to`, `bootstrap` refuses to run unless the operator passes `--all-schemas` explicitly:

```
❌ `REASSIGN OWNED BY postgres TO migrator` would also flip ownership in
schemas not covered by `ownership.apply_to`: ['analytics', 'reporting'].
Re-run with `--all-schemas` to authorize, or extend `ownership.apply_to`
to cover them.

💡 Either add the affected schemas to ownership.apply_to in the env YAML,
or pass --all-schemas explicitly. PostgreSQL's REASSIGN OWNED is
database-wide; there is no per-schema variant.
```

This is conservative — most operators will want the cross-check.  If you've reviewed the affected schemas and decided the flip is fine, `--all-schemas` waves the safety off for that one invocation.

---

## Idempotency

Every step is a no-op on already-correct state:

- `CREATE ROLE` only runs when `pg_roles` lacks the role.
- `REASSIGN OWNED` only runs when `pg_class` has postgres-owned objects.
- `ALTER DEFAULT PRIVILEGES` is itself idempotent at the SQL level (re-granting an existing privilege does nothing).

`bootstrap` (`--mode check`) after a successful `bootstrap --mode apply` exits `0`.  Re-running `--mode apply` is safe; the second run produces an empty plan for the role and reassign steps.

---

## Operational caveats

### `AccessExclusiveLock`

`REASSIGN OWNED` takes `AccessExclusiveLock` on every affected object.  Inside the wrapping transaction this is fine, but during the lock window other sessions block on every touched table.  **Run during a maintenance window.**

### Extensions

Extension-installed objects are also owned by `postgres`.  Use `ownership.ignore` to exclude them explicitly:

```yaml
ownership:
  ignore:
    - "public.pg_stat_statements*"
    - "public.uuid_*"
```

The `ignore` block is the same one `own_001` and the drift detector read; you only declare it once.

### Recovery from partial failure

The plan is transactional, so partial failure rolls back cleanly.  After a failure:

1. Read the error message — it names the step that failed.
2. Fix the underlying issue (permissions, network, role membership).
3. Re-run `confiture bootstrap` (`--mode check`) to see what remains.
4. Re-run `confiture bootstrap --mode apply` once the check shows a non-empty plan.

The `BootstrapError` exit code is `5` (configuration-class error); inspect stderr for the detailed message and the resolution hint.

---

## CI/CD recipe

`bootstrap` is **not** a deploy-time command.  Run it as a one-shot when provisioning a new environment, or as a periodic check-only gate:

```yaml
# .github/workflows/db-check.yml (excerpt)
- name: Bootstrap drift check
  env:
    BOOTSTRAP_DATABASE_URL: ${{ secrets.PROD_SUPERUSER_DATABASE_URL }}
  run: |
    confiture bootstrap \
      --mode check \
      --env production \
      --format json > bootstrap.json
- uses: actions/upload-artifact@v4
  with:
    name: bootstrap-check
    path: bootstrap.json
```

`--mode check` exits `1` on drift, which fails the gate.  Periodic check runs against production catch the case where someone manually `CREATE TABLE`d as `postgres` and forgot to flip ownership.

---

## See Also

- [Ownership Coverage](ownership-coverage.md) — the static + drift surfaces that complement `bootstrap` at PR-time and deploy-time
- [Legacy Bootstrap](legacy-bootstrap.md) — pre-0.17.0 manual workflows
- [CLI Reference](../reference/cli.md)
