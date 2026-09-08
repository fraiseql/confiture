# Lint rules

Every rule `confiture lint` can emit, generated from the rule registry
(`confiture lint --list-rules` prints the same catalogue). Select and ignore
rules by code or by family with `--select` / `--ignore` — see the
[schema linting guide](../guides/schema-linting.md#selecting-rules--list-rules--select--ignore).
Adopt a rule on a schema that already trips it with a
[baseline](../guides/schema-linting.md#adopting-a-rule-with-a-baseline--baseline--write-baseline).

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
| `build_001` | build | warning | on | An object is defined more than once in one build |
| `build_002` | build | info | on | A routine's overloads are split across files |
| `sec_001` | security | warning | on | Columns that look like secrets should not be plain text |
| `acl_001` | acl | error | off | Every CREATE TABLE has a matching GRANT |
| `tenant_001` | tenant | warning | off | Function INSERTs carry the FK a tenant-scoped view requires |
| `replica_001` | replica | warning | off | Migrations stay forward-compatible with streaming replicas |
| `func_001` | func | error | off | Every function and procedure signature is defined exactly once |
| `own_001` | own | error | off | Every created relation is paired with an ALTER … OWNER TO |
| `own_002` | own | error | off | No bare ALTER … OWNER TO on an object the migration did not create (guarded: warning) |
| `tree_001` | tree | error | off | No two files in one directory share a numeric prefix |
| `tree_002` | tree | warning | off | A numbered file carries a verb after its prefix |
| `tree_003` | tree | warning | off | Prefixes within one directory are contiguous |
| `tree_004` | tree | warning | off | Every file in the overrides mirror has a counterpart in the tree |
| `sec_002` | security-definer | warning | off | SECURITY DEFINER routines pin search_path (CVE-2018-1058) |
<!-- END GENERATED -->

The **Severity** column is the severity a rule emits by default. Two rules are
escalated by configuration, and `--list-rules --format json` names both the
severity they reach and what raises it (`escalates_to`, `escalated_by`):

| Rule | Reaches | When |
|------|---------|------|
| `sec_002` | `error` | `security_lint.severity: error` |
| `replica_001` | `error` | `infrastructure.replicas` declared, without `migration.allow_unsafe_under_replication` |

`confiture lint --fail-on <severity>` reads both, so it can tell a project whose
gate cannot fire from one whose gate is armed — see
[making lint block](cli.md#making-lint-block-fail-on).

One rule grades its findings rather than its configuration: `own_002` emits
`warning` for an `ALTER … OWNER TO` wrapped in an `IF EXISTS` guard and `error`
for a bare one. The catalogue declares the `error`, because that is what the gate
needs in order to answer whether `--fail-on error` can fire.

Rules whose subject is a file rather than a database object — `tree_001` through
`tree_004`, `own_001`, `own_002`, and the four that read a tree of migrations —
carry the file in their `--baseline` identity, so baselining one directory does
not silence the rest of the tree.

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

## The `build` family — one object, one definition

`confiture build` concatenates the schema files in order, so a second
definition of the same object is never what the author meant: a second
`CREATE OR REPLACE` silently replaces the first, a second `CREATE TABLE IF NOT
EXISTS` is a no-op, and a second plain `CREATE` fails the build at that
statement. The identity of an object is its kind, schema (`public` when
unqualified), name and — for routines — input parameter types.

| Rule | Severity | Reports |
|------|----------|---------|
| `build_001` | warning | an object defined more than once across the build's files, with every definition's file, offset and line, and which one wins (`last`, `first` or `conflict`) |
| `build_002` | info | a routine whose overloads are split across files — legal, but how the first mistake starts |

Both run as lint rules (`confiture lint`, `--select build`) and from the build
itself: `confiture build --warn-duplicates` reports and builds,
`confiture build --fail-on-duplicates` reports and exits 1 without writing
anything. `build --format json` carries the findings under `duplicates`
(see [`build.schema.json`](json-schemas/build.schema.json)).

```text
⚠️ build_001: Function 'app.f(integer)' is defined 2 times in one build:
   db/schema/010_first.sql (line 1, offset 0); db/schema/020_second.sql (line 1, offset 0)
   — the last definition wins (CREATE OR REPLACE)
```
