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
| `tree_007` | tree | warning | off | An entry numbered like its siblings, or none of them numbered |
| `tree_008` | tree | info | off | No status word in a file or directory name the build reads |
| `body_001` | body | warning | off | A plpgsql body resolves against the schema it is built into |
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
is written on; each fragment is re-parsed and walked for `RangeVar` and
`FuncCall`. A `LANGUAGE sql` body, a `BEGIN ATOMIC` body and a view definition
are SQL already and parse directly.

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

Two shapes are still refused, and both are **named** rather than passed off as
clean (see `degraded`, below):

- an array whose element type the stub cannot resolve — `app.type_input[]`, and
  equally `public.type_input[]` and a bare `type_input[]`, since naming the
  array type means resolving the element and telling `type_input[]` from
  `text[]` needs the catalogue that is not there;
- a `RETURNS TRIGGER` body, whose implicit `TG_` datums `libpg_query`
  serialises as malformed JSON.

Both are pglast 8's alone: pglast 6.16 and 7.18 read all of it.

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

## The `tree` family — the arrangement that decides the build order

confiture builds a schema by concatenating a directory tree in path order, and
that order decides which definition of an object wins and which objects exist
when a later file references one. The whole family is **opt-in**
(`--select tree`, or one code at a time), because a tree that has never been
checked will light up; `--baseline` is the designed way to adopt it.

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

| Code | What it reports | Severity |
|------|-----------------|----------|
| `body_001` | a diagnosis carrying a real SQLSTATE: the body raises on its first call | `warning` |
| `body_002` | the analyser's own opinion about a body that works — an unused variable, a shadowed declaration | `info` |

Both are opt-in and separately selectable, so a project can adopt the failures
without the style opinions:

```bash
confiture lint --select body_001 --server-url postgresql://localhost/postgres
```

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
