# Security-Definer Search-Path Lint (sec_002)

**Rule ID:** `sec_002`
**Severity:** warning (configurable to error)
**Requires:** `[ast]` extra for static scan (`pip install "fraiseql-confiture[ast]"`)

---

## Why this rule exists

A `SECURITY DEFINER` function runs with the privileges of the function *owner*, not
the calling user.  If `search_path` is not pinned the caller can prefix their own
schema onto `search_path` and shadow standard objects — causing the function to
execute attacker-supplied code under owner privileges.  This is **CVE-2018-1058**,
a well-known PostgreSQL privilege-escalation vector.

The rule checks that every `SECURITY DEFINER` function or procedure either:

1. Sets a fixed `search_path` in its definition:
   ```sql
   SECURITY DEFINER SET search_path = pg_catalog, public
   ```
2. Sets it to empty (maximum isolation):
   ```sql
   SECURITY DEFINER SET search_path = ''
   ```
3. Uses `FROM CURRENT` (captures the caller's path at *definition* time, not call time):
   ```sql
   SECURITY DEFINER SET search_path FROM CURRENT
   ```

---

## Quick start

### Static scan (no database required)

```bash
confiture migrate validate \
  --check-security-definer \
  --ddl-dir db/schema \
  --config db/environments/local.yaml
```

Requires pglast (`pip install "fraiseql-confiture[ast]"`).  Without pglast the
scan emits a notice and exits 0.

### Live catalog scan

Authoritative when `ALTER FUNCTION … SET search_path` was applied in a separate
file from the original `CREATE`:

```bash
confiture migrate validate \
  --check-security-definer \
  --against-db \
  --schemas public,auth \
  --config db/environments/production.yaml
```

### Emit a remediation script

```bash
confiture migrate validate \
  --check-security-definer \
  --ddl-dir db/schema \
  --config db/environments/local.yaml \
  --emit-remediation /tmp/fix_secdef.sql
```

The generated file contains one `ALTER FUNCTION … SET search_path = …` statement
per flagged callable.  Review and apply it with `psql`:

```bash
psql "$DATABASE_URL" -f /tmp/fix_secdef.sql
```

---

## Configuration

Add a `security_lint:` block to your environment config:

```yaml
# db/environments/production.yaml
name: production
database_url: ${DATABASE_URL}

security_lint:
  enabled: true
  severity: error       # "warning" (default) or "error"
  apply_to:             # fnmatch patterns for schemas (default: ["*"])
    - "public"
    - "auth"
    - "api_*"
  ignore:               # fnmatch patterns for qualified names (default: [])
    - "public.legacy_*"
```

| Field | Default | Description |
|-------|---------|-------------|
| `enabled` | `false` | Must be `true` to activate the rule |
| `severity` | `"warning"` | `"warning"` = advisory (exit 0); `"error"` = CI gate (exit 1 on findings) |
| `apply_to` | `["*"]` | Schema patterns to include |
| `ignore` | `[]` | Qualified `schema.name` patterns to exclude |

---

## Suppressing individual violations

When a function deliberately omits a pinned `search_path` (rare), add the
directive comment immediately before the function definition in the DDL file:

```sql
-- confiture:secdef-allow-unpinned
CREATE FUNCTION public.legacy_compat()
    RETURNS void LANGUAGE plpgsql SECURITY DEFINER
    AS $$ BEGIN END $$;
```

The directive suppresses only the immediately following function or procedure.

> **Note:** This suppression applies to the static scan only. The live scan
> reads `pg_proc.proconfig` and has no way to see source comments.

---

## Exit codes

| Condition | Exit code |
|-----------|-----------|
| No violations, or all violations are warnings | `0` |
| At least one ERROR-severity violation | `1` |

---

## Integration with `confiture lint`

```bash
confiture lint \
  --env local \
  --check-security-definer
```

This runs the static scan against the files returned by
`SchemaBuilder(env).find_sql_files()`.

---

## Static vs live — choosing the right path

| | Static (`--ddl-dir`) | Live (`--against-db`) |
|--|--|--|
| Database required | No | Yes |
| `pglast` required | Yes | No |
| Catches `ALTER … SET search_path` applied post-CREATE | No (false positive) | Yes |
| Works in pre-commit / air-gapped CI | Yes | No |
| Covers undeployed DDL changes | Yes | No |

For a **build-from-DDL** workflow the static scan is authoritative.  For a
**migrate** workflow where `SET search_path` may live in a separate migration
file, use `--against-db`.

---

## See also

- [PostgreSQL docs: Writing SECURITY DEFINER Functions Safely](https://www.postgresql.org/docs/current/sql-createfunction.html#SQL-CREATEFUNCTION-SECURITY)
- [CVE-2018-1058](https://nvd.nist.gov/vuln/detail/CVE-2018-1058)
- `docs/guides/function-uniqueness.md` — related function-signature lint (`func_001`)
- `docs/guides/migrate-validate.md` — all `migrate validate` options
