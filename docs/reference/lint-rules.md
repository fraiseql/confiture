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
| `build_003` | build | warning | on | A body references an object the build does not create |
| `sec_001` | security | warning | on | Columns that look like secrets should not be plain text |
| `qual_001` | qual | warning | on | Routines are created schema-qualified |
| `qual_002` | qual | warning | off | Relations and types are created schema-qualified |
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
| `tree_005` | tree | warning | off | No two sibling entries share a numeric prefix |
| `tree_006` | tree | warning | off | An entry's prefix extends its parent's |
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

## The `qual` family — a `CREATE` says which schema it lands in

`CREATE FUNCTION fn_slugify(value text) ...` does not say where the function
goes. PostgreSQL resolves the unqualified name through the **applying role's**
`search_path` at apply time, so the same file applied by a deploy role and by a
developer produces the object in two different schemas — and the copy in the
wrong place is found by whatever breaks next, not by the build.

This is the declaration-side twin of `sec_002`, which reports the same
hazard on the *reference* side: an unqualified name inside a `SECURITY DEFINER`
body resolves through the **caller's** path (CVE-2018-1058).

| Rule | Objects | Default |
|------|---------|:-------:|
| `qual_001` | functions, procedures, aggregates | on |
| `qual_002` | tables, views, materialized views, composite and enum types, domains, sequences | off |

Two codes rather than one because the volume differs by an order of magnitude:
a schema has a handful of routines and hundreds of tables. A project adopts
`qual_001` on the day it upgrades and takes `qual_002` on with
`--select default,qual_002` plus a
[baseline](../guides/schema-linting.md#adopting-a-rule-with-a-baseline--baseline--write-baseline)
when it is ready.

```sql
CREATE SCHEMA app;
CREATE OR REPLACE FUNCTION fn_slugify(value TEXT) RETURNS TEXT
LANGUAGE sql IMMUTABLE AS $$ SELECT lower(value) $$;
-- qual_001: Function 'fn_slugify(text)' is created without a schema; which schema
--           it lands in is decided at apply time by the applying role's search_path
--           fix: Write the name as 'app.fn_slugify'
```

The suggested fix names a schema only when the **same file** declares one above
the statement with `CREATE SCHEMA`; otherwise it says `public` and says that
`public` is a guess. A fix that guessed silently would be worse than none.

### What does not silence it

**`SET search_path` does not.** A reader expects the opposite, so it is worth
stating: setting the path in the file is exactly the mechanism that makes the
outcome depend on who applies it — treating it as an exemption would hide the
hazard the rule exists for. A `SET search_path` at the top of a file and a
different one in the session that applies it produce different databases from
the same DDL.

**A directive does.** Write `-- confiture:unqualified-ok` above a statement that
is deliberately schema-agnostic — an extension bootstrap, a template applied into
whichever schema the caller chose:

```sql
-- confiture:unqualified-ok
CREATE TABLE tb_scratch (id int);
```

It attaches to the statement below it (blank lines and other comments in between
do not detach it) and silences that statement only, so a schema-agnostic file
stays quiet without turning the rule off for the whole tree.

A `CREATE TEMPORARY TABLE` is never reported: it lives in `pg_temp` and has no
schema to write.

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
| `build_003` | warning | a routine or view body that names an object **no file in the build creates** |

`build_001` and `build_002` run as lint rules (`confiture lint`,
`--select build`) and from the build
itself: `confiture build --warn-duplicates` reports and builds,
`confiture build --fail-on-duplicates` reports and exits 1 without writing
anything. `build --format json` carries the findings under `duplicates`
(see [`build.schema.json`](json-schemas/build.schema.json)).

```text
⚠️ build_001: Function 'app.f(integer)' is defined 2 times in one build:
   db/schema/010_first.sql (line 1, offset 0); db/schema/020_second.sql (line 1, offset 0)
   — the last definition wins (CREATE OR REPLACE)
```

### `build_003` — the inventory, read backwards

The same inventory that knows an object is created *twice* knows when one is
created *never*. `build_003` takes the objects a body names — relations from a
`FROM` or an `INSERT`, routines from a call — and subtracts the objects the
build creates. What is left is a body referring to something nobody built:

```sql
CREATE OR REPLACE FUNCTION app.fn_report()
RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE r RECORD;
BEGIN
    FOR r IN SELECT id FROM app.tv_summary LOOP   -- no file creates this
        PERFORM app.fn_refresh_summary(r.id);     -- nor this
    END LOOP;
END;
$$;
```

```text
⚠️ build_003: Function 'app.fn_report()' references relation 'app.tv_summary',
   and no file in the build creates it
   db/schema/010_fn.sql:6
```

Extraction is PostgreSQL's own parser end to end. A PL/pgSQL body goes through
`parse_plpgsql`, which hands back every embedded SQL fragment with the line it
is written on; each fragment is re-parsed and walked for `RangeVar` and
`FuncCall`. A `LANGUAGE sql` body, a `BEGIN ATOMIC` body and a view definition
are SQL already and parse directly.

What the rule deliberately does **not** report:

- **A forward reference inside one build.** The inventory is the whole build,
  so a routine reading a table created three files later resolves. Only a name
  absent from the entire build is a finding.
- **A statement built at run time.** `EXECUTE 'SELECT … ' || quote_ident(t)`
  names nothing a parser can resolve, and guessing at the string is exactly the
  regex behaviour this rule exists to replace.
- **`pg_catalog` and `information_schema`.** PostgreSQL ships them.
- **An unqualified name**, unless `lint.search_path` says where to look — and
  an unqualified *routine* call not even then, because `pg_catalog` is on every
  search path and confiture cannot enumerate it. Without that rule, every
  `now()` and `count()` would be a finding.

#### Three tiers answer a reference

| Tier | What answers | When |
|------|--------------|------|
| a | the build inventory | always |
| b | a live database — `to_regclass` for relations, `pg_proc` for routines | when `--env`'s `database_url` accepts a connection, and only for names tier (a) could not answer |
| c | `lint.ignore_objects` in the environment YAML | always |

Tier (b) is what makes the rule usable on a real project: an object created by
a migration, or owned by an extension, is real and is absent from the DDL tree.
One connection, one round trip, every outstanding name at once — and only when
something is outstanding, so a clean tree connects to nothing.

**A run that could not reach a database says so**, on the summary line and in
the JSON payload's `degraded` array:

```text
build_003 ran without the live tier: no database answered, so an object created
by a migration or owned by an extension is reported as missing: connection failed …
```

Read `n unresolved references` from a degraded run as an upper bound, not a
count of bugs.

Tier (c) is for a project with no reachable database. It is `fnmatch` over
`schema.name`:

```yaml
# db/environments/local.yaml
lint:
  ignore_objects:
    - public.gen_random_uuid    # pgcrypto, installed by the platform
    - audit.*                   # a whole schema a sibling service owns
  search_path:                  # optional: where an unqualified relation lives
    - app
    - public
```

#### Adopting it on a schema that already trips it

`build_003` is on by default, and #246's own report is six unresolved objects
in one routine of an existing schema. `--baseline` is the designed path:

```bash
confiture lint --select build_003 --baseline .confiture-lint-baseline.json --write-baseline
```

records what is there today; later runs fail only on names the file does not
know. The identity of a finding is `<referrer> -> <name>`, so fixing one of six
unresolved names in a routine does not retire the other five, and moving the
routine to another file does not churn the baseline.
