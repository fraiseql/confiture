# Lint rules

Every rule `confiture lint` can emit, generated from the rule registry
(`confiture lint --list-rules` prints the same catalogue). Select and ignore
rules by code or by family with `--select` / `--ignore` — see the
[schema linting guide](../guides/schema-linting.md#selecting-rules--list-rules--select--ignore).

<!-- BEGIN GENERATED: lint-rules -->
| Code | Family | Severity | Default | Rule |
|------|--------|----------|:-------:|------|
| `naming_001` | naming | warning | on | Table names should be snake_case |
| `naming_002` | naming | warning | on | Column names should be snake_case |
| `pk_001` | pk | warning | on | Every table should declare a primary key |
| `doc_001` | doc | info | on | Every table should carry a COMMENT |
| `doc_002` | doc | info | on | Every function and procedure should carry a COMMENT (per overload) |
| `doc_003` | doc | info | on | Every view and materialized view should carry a COMMENT |
| `doc_004` | doc | info | on | Every composite type, enum and domain should carry a COMMENT |
| `sec_001` | security | warning | on | Columns that look like secrets should not be plain text |
| `acl_001` | acl | warning | off | Every CREATE TABLE has a matching GRANT |
| `tenant_001` | tenant | warning | off | Function INSERTs carry the FK a tenant-scoped view requires |
| `replica_001` | replica | warning | off | Migrations stay forward-compatible with streaming replicas |
| `sec_002` | security-definer | warning | off | SECURITY DEFINER routines pin search_path (CVE-2018-1058) |
<!-- END GENERATED -->

> The table above is generated from `LINT_RULES`. Regenerate with
> `python -c "from confiture.core.linting.rule_registry import render_rule_table;
> print(render_rule_table())"`; `tests/unit/test_lint_rules_doc.py` fails if it drifts.

## The `doc` family — every commentable object carries a `COMMENT`

All four rules read the pglast-built object inventory, so a schema qualifier
changes nothing: `tenant.tb_user` and `tb_user` report identically. They are
`info` by default and on by default; `--ignore doc` silences the family,
`--select doc_002` runs one rule alone.

| Rule | Objects | What documents them |
|------|---------|---------------------|
| `doc_001` | tables (a `PARTITION OF` child is exempt; its parent is not) | `COMMENT ON TABLE` |
| `doc_002` | functions and procedures, **per overload** | `COMMENT ON FUNCTION f(integer)`, `COMMENT ON PROCEDURE`, `COMMENT ON ROUTINE` |
| `doc_003` | views and materialized views | `COMMENT ON VIEW`, `COMMENT ON MATERIALIZED VIEW` |
| `doc_004` | composite types, enum types and domains | `COMMENT ON TYPE`, `COMMENT ON DOMAIN` |

A function's identity is its name **and** its input parameter types, so a
comment on one overload says nothing about its sibling:

```sql
CREATE FUNCTION app.f(a integer) RETURNS int LANGUAGE sql AS $$ select 1 $$;
CREATE FUNCTION app.f(a text)    RETURNS int LANGUAGE sql AS $$ select 1 $$;
COMMENT ON FUNCTION app.f(integer) IS 'the integer one';
-- doc_002: Function 'app.f(text)' should have a COMMENT describing its purpose
```

`OUT` and `TABLE` parameters are not part of the identity, and type modifiers
are dropped, so `COMMENT ON PROCEDURE app.p(numeric)` documents
`app.p(x numeric(10,2))`.
