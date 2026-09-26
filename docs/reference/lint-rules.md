# Lint rules

Every rule `confiture lint` can emit, generated from the rule registry
(`confiture lint --list-rules` prints the same catalogue). Select and ignore
rules by code or by family with `--select` / `--ignore` — see the
[schema linting guide](../guides/schema-linting.md#selecting-rules-list-rules-select-ignore).
Adopt a rule on a schema that already trips it with a
[baseline](../guides/schema-linting.md#adopting-a-rule-with-a-baseline-baseline-write-baseline).

<!-- BEGIN GENERATED: lint-rules -->
| Code | Family | Severity | Default | Rule |
|------|--------|----------|:-------:|------|
| `UNPARSEABLE` | parse | error | on | Every file in the build parses |
| `naming_001` | naming | warning | on | Table names should be snake_case |
| `naming_002` | naming | warning | on | Column names should be snake_case |
| `pk_001` | pk | warning | on | Every table should declare a primary key |
| `doc_001` | doc | info | on | Every table should carry a COMMENT |
| `doc_002` | doc | info | on | Every function and procedure should carry a COMMENT (per overload) |
| `doc_003` | doc | info | on | Every view and materialized view should carry a COMMENT |
| `doc_004` | doc | info | on | Every composite type, enum and domain should carry a COMMENT |
| `doc_005` | doc | info | off | A COMMENT says something the object's own name does not |
| `build_001` | build | error | on | An object is defined more than once in one build |
| `build_002` | build | info | on | A routine's overloads are split across files |
| `build_003` | build | warning | on | A body references an object the build does not create |
| `build_004` | build | error | on | A statement needs, when it runs, an object the build creates later |
| `sec_001` | security | warning | on | Columns that look like secrets should not be plain text |
| `sec_003` | security | warning | on | No credential is written as a literal in the tree (a seed row, a role password) |
| `qual_001` | qual | warning | on | Routines are created schema-qualified |
| `qual_002` | qual | warning | off | Relations and types are created schema-qualified |
| `acl_001` | acl | error | off | Every CREATE TABLE has a matching GRANT |
| `tenant_001` | tenant | warning | with `tenancy:` | An INSERT into a tenant table supplies the discriminator |
| `tenant_002` | tenant | warning | with `tenancy:` | A table carries the tenant discriminator NOT NULL, or is declared global |
| `tenant_003` | tenant | warning | with `tenancy:` | A view reading tenant data publishes the discriminator as a plain column, or is declared global |
| `tenant_004` | tenant | warning | with `tenancy:` | A foreign key between tenant tables carries the discriminator on both sides |
| `tenant_005` | tenant | warning | with `tenancy:` | A tenant table's primary key and unique keys lead with the discriminator |
| `replica_001` | replica | warning | off | Migrations stay forward-compatible with streaming replicas |
| `func_001` | func | error | off | Every function and procedure signature is defined exactly once |
| `own_001` | own | error | off | Every created relation is paired with an ALTER … OWNER TO |
| `own_002` | own | error | off | No bare ALTER … OWNER TO on an object the migration did not create (guarded: warning) |
| `tree_001` | tree | error | on | No two files in one directory share a numeric prefix |
| `tree_002` | tree | warning | off | A numbered file carries a verb after its prefix |
| `tree_003` | tree | warning | off | Prefixes within one directory are contiguous |
| `tree_004` | tree | warning | off | Every file in the overrides mirror has a counterpart in the tree |
| `tree_005` | tree | warning | off | No two sibling entries share a numeric prefix |
| `tree_006` | tree | warning | off | An entry's prefix extends its parent's |
| `tree_007` | tree | warning | off | An entry numbered like its siblings, or none of them numbered |
| `tree_008` | tree | info | off | No status word in a file or directory name the build reads |
| `body_001` | body | warning | off | A plpgsql body resolves against the schema it is built into |
| `body_003` | body | warning | off | Analysis artefact: a body names a TEMP table only a running body creates |
| `body_004` | body | warning | off | Analysis artefact: plpgsql_check cannot follow a RECORD variable's assignment |
| `body_005` | body | warning | off | Analysis artefact: a body calls dblink, which the analysed database lacks |
| `body_002` | body | info | off | A plpgsql body carries no unused variable or shadowed declaration |
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
`tree_008`, `own_001`, `own_002`, and the four that read a tree of migrations —
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

A `COMMENT ON … IS NULL` *removes* a comment, and an empty one says nothing;
neither documents the object, and both report.

### The distribution — what the counter cannot say

The four rules count comments. A project that drives that count to zero is
rewarded by whatever satisfies it, and a hundred one-line restatements of the
signature read as "documentation: 100 %" exactly as a hundred paragraphs do — a
schema where one documentation pass wrote about 1 100 characters per object
looks identical, afterwards, to one that wrote nine (#250).

So every run that includes the family reports the distribution beside the count.
On the summary line, above the findings and before the "no violations" line,
because the case this exists for has no findings:

```
doc: 412 documented, 0 undocumented, median comment 9 chars (p10 7, p90 14)
```

and in `--format json`, as a `documentation` block with a row per rule:

```json
{
  "documentation": {
    "documented": 412,
    "undocumented": 0,
    "comment_length": {"p10": 7, "p50": 9, "p90": 14},
    "rules": [
      {"code": "doc_001", "documented": 96, "undocumented": 0,
       "comment_length": {"p10": 8, "p50": 11, "p90": 19}},
      {"code": "doc_003", "documented": 0, "undocumented": 0, "comment_length": null}
    ]
  }
}
```

Percentiles are **nearest rank**, so every number reported is a length some
comment actually has rather than an average of two neighbours, and a length is
the comment text with surrounding whitespace stripped. Every `doc` code gets a
row whether or not the schema holds any of its objects, so a consumer reads a
fixed shape. The block is **absent**, not zeroed, when the family did not run
(`--ignore doc`): unmeasured and none are different answers.

This is a measurement, not a rule — it emits no finding, moves no exit code, and
there is nothing to select or baseline.

### `doc_005` — a comment that says only what the name says

`info`, **opt-in** (`--select default,doc_005`). One finding per comment where
every meaningful word is already a word of the object's own name:

```sql
COMMENT ON FUNCTION app.delete_widget(uuid, uuid, boolean, uuid) IS
'Deletes a widget';
-- doc_005: Function 'app.delete_widget(...)' has a COMMENT that says only what
-- its name already says: 'Deletes a widget'
```

The comparison is string-only and deliberately narrow. The name is split on `_`;
the comment is lowercased, split on non-word characters, and stripped of
articles and prepositions (`a`, `the`, `of`, `to`, …), which is what makes
`'Deletes a widget'` and `'Deletes widget'` the same finding. Both sides are
reduced to a crude stem, so an inflected verb still matches the name's own word
— `'Creating widgets'` against `create_widget`. Only the *local* name is
compared: a schema qualifier and a signature are not things a comment restates.

It stays quiet when:

- the comment carries any word the name does not — `'Soft-deletes a widget and
  cascades to its variants, returning the affected count'` against
  `delete_widget` reports nothing, because of `soft`;
- the name is one word, so there is nothing to restate and nothing to be right
  about;
- there is no comment at all, which is `doc_001`–`doc_004`'s finding.

**The length bound the issue also proposes is not implemented.** "Shorter than
40 characters on an object with more than one parameter" would be wrong more
often than right: a short accurate comment is common, and punishing it teaches
padding.

**This rule is a heuristic and it is wrong sometimes.** A comment that is
*correct* and happens to restate the name is a false positive — some objects
really do only do what their name says. That is why it is `info`, why it is
opt-in, and why the answer to one is
[a baseline](../guides/schema-linting.md#adopting-a-rule-with-a-baseline-baseline-write-baseline)
rather than rewording a comment that was fine.

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
[baseline](../guides/schema-linting.md#adopting-a-rule-with-a-baseline-baseline-write-baseline)
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
| `build_001` | error | an object defined more than once across the build's files, with every definition's file, offset and line, and which one wins (`last`, `first` or `conflict`) |
| `build_002` | info | a routine whose overloads are split across files — legal, but how the first mistake starts |
| `build_003` | warning | a routine or view body that names an object **no file in the build creates** |
| `build_004` | error | a statement that needs, when it runs, an object the build **creates later** |

`build_001` and `build_002` run as lint rules (`confiture lint`,
`--select build`) and from the build
itself: `confiture build --warn-duplicates` reports and builds,
`confiture build --fail-on-duplicates` reports and exits 1 without writing
anything. `build --format json` carries the findings under `duplicates`
(see [`build.schema.json`](json-schemas/build.schema.json)); the build's own
flags decide its exit code, so promoting the lint rule left them alone.

```text
⚠️ build_001: Function 'app.f(integer)' is defined 2 times in one build:
   db/schema/010_first.sql (line 1, offset 0); db/schema/020_second.sql (line 1, offset 0)
   — the last definition wins (CREATE OR REPLACE)
```

### Why `build_001` is an error

It is the one rule a default `confiture lint` can fail on, and the reason is
that its finding is not a matter of taste: two definitions of one object mean
the build's outcome depends on the order the files are concatenated in, and no
reader of either file can see that order. Which definition survives is decided
somewhere else entirely — a `CREATE OR REPLACE` takes the last, an `IF NOT
EXISTS` takes the first, and a plain `CREATE` fails the build outright.

Three ways to decline it on a schema that already trips it, in the order you
should reach for them:

| | What it does |
|---|---|
| `--baseline lint-baseline.json --write-baseline` | records today's duplicates and fails only on the next one — the ratchet |
| `--ignore build_001` (or `--ignore build`) | turns the rule off for this run |
| `--fail-on never` | reports every finding and never sets the exit code |

`--fail-on warning` is **not** among them: `warning` is a *lower* threshold than
`error`, so an error still trips it.

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
is written on and the statement it belongs to; each fragment is parsed the way
that statement writes it — a query as a query, a condition or a `RETURN` value
as an expression, `v := app.fn_x(p)` by its right-hand side — and walked for
`RangeVar` and `FuncCall`. A `LANGUAGE sql` body, a `BEGIN ATOMIC` body and a
view definition are SQL already and parse directly.

Only the string an `EXECUTE` runs is out of reach, and it is declined out loud
as dynamic; its `USING` parameters, and the body of a `FOR … IN EXECUTE` loop,
are read like any other statement. A statement the reader could not parse is
reported as a `degraded` entry naming the routine, the file and the line — the
rest of the body is read, and the rule does not pretend it read that one.

#### A schema-qualified type is not a reason to skip a routine

`libpg_query`'s PL/pgSQL compiler is PostgreSQL's own with the catalogue
stubbed out, and on pglast 8 that stub resolves `pg_catalog` and `public` and
nothing else. A type written `app.mutation_response` therefore made it refuse
the **whole routine** before reading a line of the body — in a parameter, a
return type, a `SETOF`, a `RETURNS TABLE` column or a `DECLARE`. Since 1.7.0
(#270) confiture blanks that qualifier before handing the statement over, with
spaces, so every line number is still the file's:

```sql
CREATE OR REPLACE FUNCTION app.m_submit(pk uuid, input_data app.type_input)
RETURNS app.mutation_response LANGUAGE plpgsql AS $$
DECLARE
    v_res app.mutation_response;                  -- three type qualifiers,
BEGIN                                             -- none of them a reference
    SELECT * INTO v_res FROM app.tv_summary;      -- reported, qualified
    RETURN v_res;
END;
$$;
```

Which qualifier is a type is the compiler's answer, not a guess: one it refuses
is blanked, one it accepts is put back. A reference is never rewritten, because
`app.tv_summary` reduced to `tv_summary` would be a name the rule declines to
judge — the same silent miss, one step along.

One shape is still refused, and it is **named** rather than passed off as clean
(see `degraded`, below): an array whose element type the stub cannot resolve —
`app.type_input[]`, and equally `public.type_input[]` and a bare `type_input[]`,
since naming the array type means resolving the element, and telling
`type_input[]` from `text[]` needs the catalogue that is not there. It is
pglast 8's alone: pglast 6.16 and 7.18 read it.

#### A trigger function's body is read like any other

`RETURNS TRIGGER` and `RETURNS event_trigger` bodies were unread until 1.8.0 —
all of them, whatever they contained ([#272]). `libpg_query` writes the implicit
`TG_*` datums it synthesises for them as `{}}`, one closing brace too many each,
so its output was not valid JSON and the tree never arrived. That was 5 of the 8
plpgsql routines confiture's own examples ship, and triggers are where a schema
keeps its audit writes, its denormalisation maintenance and its cross-table
invariants: bodies that reference plenty, and rarely covered by a call path a
test exercises.

Confiture deletes those braces before decoding, at the position the JSON decoder
stops at and only when the characters there are that defect. A serialisation
that decodes is never edited — the same three characters spell the implicit
`RETURN` at the end of very nearly every body, so a global replace would break
the routines that were never broken. Also pglast 8's alone.

[#272]: https://github.com/fraiseql/confiture/issues/272

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

### `build_004` — the inventory, read in build order

`build_003` asks whether the build creates what a body names at all;
`build_004` asks whether it creates it **before** the statement that needs it
(#383). Some statements are resolved when they run, so the object has to exist
by then; others are resolved when they are first used:

| Resolved when the statement runs | Resolved when first used |
|---|---|
| a view or materialized view's query; `CREATE TABLE … AS` | a `LANGUAGE plpgsql` body |
| a `LANGUAGE sql` body, while `check_function_bodies` is on (the default) | a `LANGUAGE sql` body after `SET check_function_bodies = off` |
| a `LANGUAGE sql … BEGIN ATOMIC` body, always | |
| a column `DEFAULT`, a `CHECK`, a generated column, an index expression | |
| a trigger's `EXECUTE FUNCTION`; the table an index, trigger or `ALTER TABLE` is on | |
| a `REFERENCES`, an `INHERITS` | a `REFERENCES` in a `CREATE TABLE` when `build.two_pass` moves it to the end |

So the same helper fails the build written `LANGUAGE sql` in a directory that
loads before its table, and builds written `LANGUAGE plpgsql`:

```text
❌ build_004: Function 'public.first_continent()' needs relation 'catalog.tb_continent'
   when it is created, but the build first creates it later, at
   db/schema/0_schema/01_write_side/010211_tb_continent.sql:4. A LANGUAGE sql body is
   resolved when the function is created, while check_function_bodies is on; a
   LANGUAGE plpgsql body is resolved when it first runs.
```

The order is the one `confiture build` emits: its files in build order
(`build --list-files`), each read top to bottom, and the first `CREATE` of an
object is the one that counts — a later `OR REPLACE` does not make it exist
sooner. An object no file creates is `build_003`'s, not this rule's. A statement
naming what it creates itself (a table's foreign key to itself, a recursive
`LANGUAGE sql` function) is not a finding: PostgreSQL accepts both.

It is an **error**, on by default, with no directive to silence it: every row
of the table above was applied to an empty PostgreSQL in both orders
(`tests/integration/test_forward_reference_oracle.py`), and the rule reports
exactly the orders PostgreSQL refuses, so a finding is a build that fails.
The fix is to move one of the two statements. Not yet read: a column or
parameter typed with a domain, enum or composite type created later — the rule
reads relations and routines, as `build_003` does.

## The `tree` family — the arrangement that decides the build order

confiture builds a schema by concatenating a directory tree in path order, and
that order decides which definition of an object wins and which objects exist
when a later file references one. The family is **opt-in** (`--select tree`,
or one code at a time), because a tree that has never been checked will light
up; `--baseline` is the designed way to adopt it — except `tree_001`.

### Why `tree_001` is on by default, at `error`

Two files in one directory that share a numeric prefix load in the order the
rest of their names decides, and nobody reads `10_views.sql` against
`10_views_safe.sql` as a load order. Adding a third file can reorder the other
two silently; that is `build_001`'s duplicate, or `build_004`'s forward
reference, waiting to happen. So `tree_001` is not a naming preference, as the
rest of the family is: it is the one arrangement that makes the build order an
accident, and a default `confiture lint` fails on it (#384). It was an `error`
nobody saw unless they asked for it, which read as an oversight.

To keep today's behaviour on a tree that trips it, pass `--ignore tree_001`, or
record the collisions with `--baseline lint.json --write-baseline` and fail only
on the next one.

None of these rules opens a file. They are findings about names, and each one
carries the path — and line 1 when the entry is a file, since a name has no
line of its own.

| Code | Reports |
|------|---------|
| `tree_001` | two **files** in one directory share a numeric prefix |
| `tree_002` | a numbered file carries no verb after its prefix (`00001.sql`) |
| `tree_003` | prefixes within one directory are not contiguous |
| `tree_004` | a file in the overrides mirror has no counterpart in the tree |
| `tree_005` | two sibling **entries** share a prefix, at least one a directory |
| `tree_006` | an entry's prefix does not extend its parent's |
| `tree_007` | an entry carries no prefix while its siblings do |
| `tree_008` | a name carries a status word |

### What they read

The files the environment builds, resolved through the same `SchemaBuilder`
`confiture build` uses. A directory kept out by `exclude_dirs` or by a
per-directory `exclude` glob contributes no entry, so a numbering that decides
nothing is judged by nothing. `tree_004` is the exception: its subject is the
overrides mirror, which the build never reads, and it needs `--overrides-dir`.

### `tree_005` — a collision, and the order it produces

```
db/schema/03_functions/034_dim/0248_configurator/
db/schema/03_functions/034_dim/0248_flag/
```

Two entries sharing a prefix are ordered by what follows it, which nobody reads
as significant — and adding a file to one of them silently reorders the other.
`tree_001` compares the *files* inside one directory and is an `error`;
`tree_005` is about the entries it does not compare, so a colliding pair of
directories is reported once, by one rule. The message names the resulting
build order, because confiture is the only component that computes it.

### `tree_006` — the convention is read from the tree, not assumed

Two numbering conventions are both idiomatic, and confiture cannot pick one for
a project:

```
01_core/010_users/0101_user.sql     # a child's prefix continues its parent's
10_tables/01_users.sql              # each directory numbers its own contents
```

`tree_006` fires only where the tree itself demonstrates the first — where a
directory's own prefix extends *its* parent's. `034_dim` continuing `03_f…` is
the tree saying which convention it keeps, so `034_dim/0341_geo/03452_odd` is a
finding and `10_tables/01_users.sql` is not.

Under the default alphabetical sort this is not cosmetic: `0341_geo` sorts
before `034_dim` (`1` < `_`), so a prefix of the wrong length moves its whole
subtree.

### `tree_008` — a name that says the work is not finished

`..._update_TODO.sql` is in the build and applied on every deploy. Whether that
is confiture's business is arguable, so the rule is `info`, opt-in, and its
vocabulary is configurable:

```yaml
# db/environments/local.yaml
lint:
  status_words: [TODO, FIXME, WIP, DRAFT, SPIKE]
```

The words are matched case-insensitively against the underscore-separated parts
of a file or directory name. The default is the four above.

### Adopting the family on an existing tree

```bash
confiture lint --select tree --baseline .confiture-lint-baseline.json --write-baseline
```

A tree finding's object *is* a path, so its identity carries the file and a
baseline written today stays valid: fixing one collision does not retire the
other thirty-five, and a collision added tomorrow is new.

## `sec_003` — no credential written as a literal in the tree

`sec_001` reads column *names*: a column named for a secret should not hold one
in plain text. `sec_003` reads the *values*. A password committed in a seed file
is in git history, in every developer's database and in every environment the seed
is applied to — and it is there before any build that would ship it has run, so
the rule reads the **source tree**, every file under the environment's
`include_dirs`, not a built bundle.

It reports, at `warning` and on by default:

- a literal written into a column `sec_001` names for a secret (`password`,
  `token`, `secret`, `api_key`, `credit_card`, `ssn`) — by `INSERT … VALUES`, every
  row of it, or by `COPY … FROM stdin`, every row decoded;
- a literal in a column named for a key (`signing_key`) when it looks like one:
  16 characters or more, high-entropy, not a UUID — so `sort_key = 'by_name'` is
  not reported;
- `CREATE ROLE` / `ALTER ROLE … PASSWORD '<literal>'`.

It does not report a password hash (bcrypt, argon2, `SCRAM-SHA-256$…`, `md5…`,
crypt, PBKDF2, LDAP `{SSHA}`) — the point is plaintext — nor an obvious
placeholder: an empty string, one repeated character (`xxxx`, `****`), a template
(`<redacted>`, `{{ DB_PASSWORD }}`, `${PASSWORD}`), or `changeme` and its kin. A
comment is not a statement, so a documented example is never read.

**A finding never repeats the secret.** It gives the kind and the length, and names
the row by its first other column — `app.tb_user.password[id=3]` — so a `--baseline`
can hold an accepted finding without the value reaching a CI log. A tree that has
never been checked adopts the rule the usual way: `--baseline` records today's
findings, and only a new one fails.

## `tenant_001` — an INSERT into a tenant table supplies the discriminator

On when `db/project.yaml` declares `tenancy:`, like the rest of the family. Every
`INSERT` in a function or procedure body — PL/pgSQL, `LANGUAGE sql`, `BEGIN ATOMIC`
— into a **tenant table** (the scope `tenant_002` decides: it carries the
discriminator) names the discriminator among the columns it writes, or the column
has a default. A default is a legitimate design:

```sql
CREATE TABLE app.tb_order (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL DEFAULT current_setting('app.tenant_id')::uuid
        REFERENCES management.tb_organization (id)
);
-- clean: the session's tenant fills tenant_id
INSERT INTO app.tb_order (id) VALUES (gen_random_uuid());
```

Without one, the row is refused by `NOT NULL`, or belongs to no tenant.
`INSERT … VALUES` and `INSERT … SELECT` are judged by their column list; an `INSERT`
with no column list writes the table's first columns in the order the model holds
them (`ALTER TABLE … ADD COLUMN` appends), as many as its `VALUES` row or its query
outputs — a `SELECT *` over a table or view the model holds is counted through the
column tracer `tenant_003` uses. `DEFAULT VALUES` writes none. A data-modifying
CTE's `INSERT` is judged like any other; an `INSERT` into a global, root or undecided
table is not judged, and neither is one outside a routine (a seed row).

What the fragment reader cannot read is a finding saying the `INSERT` in it is not
judged, never a pass: a body the PL/pgSQL compiler refuses, a statement pglast
rejects, a string `EXECUTE` builds at run time (as `build_003` declares it), and an
`INSERT` without a column list whose query's outputs cannot be counted (a
set-returning function in `FROM`). A finding names the routine and the table
(`app.fn_create_order -> app.tb_order`), which is what a `--baseline` records.

This code once meant something else — an `INSERT` missing the foreign key a
tenant-scoped view joined on, inferred from the view's text; the CHANGELOG records
the change.

## `tenant_002` — every table carries the tenant discriminator, or is declared global

On when `db/project.yaml` declares `tenancy:` (and off otherwise: confiture assumes
nothing about tenants until the project says it is tenant-scoped). Tenancy is a
column, never an inference: a table is **tenant-scoped** because it carries
`tenancy.discriminator` (`tenant_id` by default) `NOT NULL`, referencing
`tenancy.root` — the table of tenants — when one is configured. It is **global**
because its schema is listed in `tenancy.global_schemas`, or because a
`-- confiture:tenant-global <reason>` line sits above its `CREATE TABLE`. The root
table itself is neither: one of its columns *is* the tenant id.

That column is the one the discriminator's foreign keys reference — a root may keep
a surrogate primary key beside the tenant id it publishes as a `UNIQUE` column, and
`tenant_id uuid NOT NULL REFERENCES management.tb_organization (tenant_uuid)` says
which one a tenant row carries. While no discriminator references the root yet, it
is the root's single-column primary key. When the discriminators reference
different columns of the root, the tenant id is undecided and is not guessed.
`tenant_002` decides every table's scope once, and the root's tenant id with it;
`tenant_003`, `tenant_004` and `tenant_005` read that one answer. A table defined
twice is judged once, by its first definition.

It reports, at `warning`:

- a table that is neither tenant-scoped nor declared global — the decision nobody
  made;
- a nullable discriminator, at the column;
- a discriminator that does not reference the root;
- a declaration that cannot hold: `tenant-global` without a reason, or a table
  declared global that carries the discriminator anyway;
- on the root, discriminators that reference different columns of it: which one is
  the tenant id is then undecided, and the rules that need it do not judge.

A column added by a later `ALTER TABLE` counts (the model folds it), and a
partition is judged with its parent, not on its own. `--select tenant_002` on a
project with no `tenancy:` block reports the rule *skipped*, with the reason — never
an empty pass.

## `tenant_003` — a view publishes the discriminator, or is declared global

On when `db/project.yaml` declares `tenancy:`, like `tenant_002`. Every view and
materialized view that **reads a tenant relation** — a table carrying the
discriminator, the root, or a view that is itself tenant data, directly or through
a routine it calls — must output a column named `tenancy.discriminator` that is,
**as a plain column**, the discriminator of a tenant relation it reads (or the
root's tenant id, published under the discriminator's name). A view that reads
only global relations is global without a declaration.

The column is traced through the view's parse tree, never its text: `FROM`
aliases, `JOIN … USING`/`NATURAL` merged columns, subqueries in `FROM`, CTEs
(recursive ones included), `*` and `t.*`, and set operations, where the column at
the same position must trace in every branch. So this publishes, branch by branch —
standard rows fanned out to every tenant, beside a tenant's own:

```sql
CREATE VIEW app.v_paper_format AS
SELECT o.id AS tenant_id, f.* FROM catalog.tb_paper_format f
  CROSS JOIN management.tb_organization o
UNION ALL
SELECT c.tenant_id, c.id, c.label FROM app.tb_custom_paper_format c;
```

and none of these does: `coalesce(o.tenant_id, …)`, `o.tenant_id::text`, an
aggregate over it, a `NULL` in one branch of a `UNION`, a `tenant_id` read from a
global table, or a `count(*)` across tenants with no `tenant_id` beside it.

It reports, at `warning`:

- a view reading tenant data that publishes no discriminator, or one that is not a
  plain column of a tenant relation's discriminator — naming what it reads;
- a column the tracer could not follow — a set-returning function in `FROM`, a
  relation the model lacks, a routine the view calls whose body could not be read —
  with the reason: an unread view is a finding, never a clean pass;
- a declaration that cannot hold: `tenant-global` without a reason, a view declared
  global that publishes the discriminator anyway, or a directive on a view that
  reads no tenant relation (stale).

A view is declared global as a table is: its schema in `tenancy.global_schemas`, or
a `-- confiture:tenant-global <reason>` line above its `CREATE [MATERIALIZED] VIEW`.
Views over views are judged inner view first, whatever order the files list them
in.

## `tenant_004` — a foreign key cannot cross tenants

On when `db/project.yaml` declares `tenancy:`, like the rest of the family. It reads
the scope `tenant_002` decides for every table — **tenant** (it carries the
discriminator), **global** (its schema is in `tenancy.global_schemas`, or a
`-- confiture:tenant-global <reason>` line declares it), the **root** (`tenancy.root`)
or **undecided** — and judges each foreign key by the scopes of its two ends:

| From → to | Verdict |
|---|---|
| tenant → tenant | the key carries the discriminator on both sides, at the same position |
| tenant → root | only the discriminator references the root, at its tenant id (that is `tenant_002`'s reference) |
| global → tenant or root | a finding: a row shared by every tenant cannot point at one tenant's row |
| tenant → global | fine |
| to or from an undecided table | not judged; that table has its `tenant_002` finding |

A key between two tenant tables that leaves the discriminator out can point at
another tenant's row, and PostgreSQL will not stop it. Written with it, PostgreSQL
does:

```sql
-- reported: fk_order can name tenant B's order from tenant A's line
FOREIGN KEY (fk_order) REFERENCES app.tb_order (id)
-- clean
FOREIGN KEY (tenant_id, fk_order) REFERENCES app.tb_order (tenant_id, id)
```

The hint writes the composite form, and names the `PRIMARY KEY (tenant_id, id)` or
`UNIQUE (tenant_id, id)` the target then needs when it has neither — a primary key
that leads with the discriminator (`tenant_005`) *is* that target. A foreign key
that names no columns references the target's primary key and is judged as such.
Foreign keys added by a later `ALTER TABLE … ADD CONSTRAINT` count. The root's
tenant id plays the discriminator's part: the discriminator referencing it is clean,
any other column referencing the root — its surrogate key included — names a tenant
that is not the row's own, and a foreign key *from* the root to a tenant table is
judged the same way; one between two rows of the root is not judged. While the
root's tenant id is undecided (the discriminators reference different columns of
it), a foreign key to or from the root is not judged.

## `tenant_005` — a tenant table's keys lead with the discriminator

On when `db/project.yaml` declares `tenancy:`. On every tenant table (the root is
not one), the primary key, each `UNIQUE` constraint and each unique index must have
the discriminator as their **first** key. `UNIQUE (email)` lets one tenant's row
block another tenant's insert, and the violation tells the second tenant the value
exists elsewhere; `UNIQUE (email, tenant_id)` still does not lead with it and is
reported too. A unique index on an expression, or a partial one, is judged by its
first key the same way. Non-unique indexes are not judged: a cross-tenant sweep by
`created_at`, or a lookup by `id` alone, legitimately wants one.

A uniqueness that is platform-wide on purpose is written as its own
`CREATE UNIQUE INDEX`, under the directive, so the exception is visible in review:

```sql
-- confiture:tenant-global one login per address across the platform
CREATE UNIQUE INDEX ux_user_email ON app.tb_user (lower(email));
```

The directive is honest or it is a finding: without a reason, and on a unique
index that already leads with the discriminator (stale). An inline `UNIQUE` in
`CREATE TABLE` cannot carry it. An index finding points at its `CREATE UNIQUE
INDEX`, in whichever file it is written.

Every rule of the family reports itself *skipped*, with the reason, when selected
in a project with no `tenancy:` block. A schema that predates
them can adopt the family with `--ignore tenant_003,tenant_004,tenant_005` until its
views and keys are rebuilt.

## The `body` family — a routine's body resolves, checked by PostgreSQL

Every other rule on this page answers from the text. `body_001` cannot: that
`v_pk` is `UUID` and `pk_widget` is `BIGINT` is a fact about *resolved types*,
and a parser that has not built the schema does not hold it. PostgreSQL stores
a PL/pgSQL body without resolving anything in it, so this compiles, deploys and
lints clean, and raises the first time anyone calls it:

```sql
CREATE FUNCTION app.fn_widget_pk(p_name TEXT) RETURNS uuid
LANGUAGE plpgsql AS $$
DECLARE
    v_pk UUID;
BEGIN
    SELECT pk_widget INTO v_pk FROM app.tb_widget WHERE name = p_name;
    RETURN v_pk;
END;
$$;
```

The family builds the DDL into a **throwaway database** on a writable
maintenance server and runs
[`plpgsql_check`](https://github.com/okbob/plpgsql_check) over every PL/pgSQL
routine in it. PostgreSQL's own diagnosis is reported verbatim — message,
SQLSTATE and all — because confiture has nothing to add to it.

This is not a second parser. confiture still reads DDL with pglast; PostgreSQL
is consulted only for what a parser cannot know.

| Code | What it reports | Severity | JSON `class` |
|------|-----------------|----------|--------------|
| `body_001` | a diagnosis carrying a real SQLSTATE: the body raises on its first call | `warning` | `real` |
| `body_003` | an artefact: `42P01` on an unqualified relation some analysed body creates `TEMP` — it exists only while that body runs | `warning` | `temp_table` |
| `body_004` | an artefact: `55000`, `record "…" is not assigned yet` — the analyser cannot follow a RECORD's assignment | `warning` | `record` |
| `body_005` | an artefact: `42883` on a `dblink` routine — the extension is absent from the scratch database | `warning` | `dblink` |
| `body_002` | the analyser's own opinion about a body that works — an unused variable, a shadowed declaration | `info` | — |

Every code is opt-in and separately selectable, so a project can adopt the failures
without the artefacts or the style opinions:

```bash
confiture lint --select body_001 --server-url postgresql://localhost/postgres
```

### A finding says what it is

Most of what `plpgsql_check` reports on a real tree is an artefact of analysing a
body statically — on one FraiseQL project, 132 of 177 findings (#354). A TEMP table
a running body creates is invisible to an analyser by construction, and the same
body reports it forever. Each such class is read from the diagnosis, never guessed,
and reported under a code of its own, with the class in the JSON's `class`.

That is what keeps a baseline honest: its entries are keyed per routine, so a
routine baselined for an artefact under `body_001` would absorb every later real
error on it. Under their own codes they cannot. A baseline taken before 1.16
carries artefacts under `body_001`; they move to `body_003`–`body_005` once.

A `real` finding is a lead, not a verdict: confirming it still means calling the
routine in a rolled-back transaction.

### The extension is not in a stock PostgreSQL

`plpgsql_check` ships with no PostgreSQL distribution. On Debian and Ubuntu it
is `postgresql-<major>-plpgsql-check` from the PGDG repository; elsewhere it is
built from [source](https://github.com/okbob/plpgsql_check). It only has to be
*available* on the maintenance server — confiture runs `CREATE EXTENSION` in
the scratch database it makes and drops.

Because absence is the common case, a run that cannot do the analysis says so
instead of reporting an empty list:

```
body_001 did not run: plpgsql_check is not available on the maintenance server, and no
stock PostgreSQL carries it: install it (Debian/Ubuntu `postgresql-<major>-plpgsql-check`,
or build https://github.com/okbob/plpgsql_check) and re-run
```

The same entry appears in the `skipped` array of `--format json`, and
**`--fail-on` does not read a skip as a pass**: a run that asked for `body_001`
at `--fail-on warning` and could not run it exits 1, because it has not
established that there are no warnings. A threshold the skipped rule could not
have reached anyway — `--fail-on error` against a `warning` rule — is
unaffected, and `--fail-on never` still never fails.

### Where it builds

`--server-url` names the maintenance server. Only its *server* is used: a
throwaway database is created beside the configured one and dropped again, and
the environment's own database is never opened. Without the flag the
environment's `database_url` supplies the server — so pass `--server-url` when
`--env` names something you would rather not create a database on.

If the environment declares `lint.search_path`, the scratch connection is set to
it before the analysis, because an unqualified name in a body resolves through
`search_path` and the analyser must be asked the same question the application
will ask.
