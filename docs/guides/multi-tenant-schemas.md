# Multi-tenant schemas

A multi-tenant schema keeps many tenants' rows in one set of tables, and every row
belongs to exactly one tenant or to none. This guide describes the shape confiture's
`tenant` lint family checks: what a project declares, what each rule asks and why,
and how to move an existing schema to it.

[`examples/09-multi-tenant-schema`](https://github.com/fraiseql/confiture/tree/main/examples/09-multi-tenant-schema)
is a small project in this shape that passes all five rules; its `run.sh` builds it
and shows PostgreSQL refusing a row that crosses tenants. The rules themselves are
catalogued in [lint-rules.md](../reference/lint-rules.md#tenant_001-an-insert-into-a-tenant-table-supplies-the-discriminator).

## Tenancy is a column, not an inference

Every tenant-scoped relation carries the tenant id in a column of its own, the
**discriminator** (`tenant_id` by default), `NOT NULL`, referencing the table of
tenants. A relation that does not carry it is **global** — shared by every tenant —
and says so. Nothing is inferred.

The alternative is to let a row's tenant follow from its foreign keys: an order
line belongs to an order, the order to a provider, the provider to a tenant. That
chain holds only while every link is present and every link leads to a tenant
table, and nothing enforces either. Each read has to join the whole chain to know
whose row it is; no index can lead with a value the row does not hold; and a
foreign key from one link to the next can point at another tenant's row without
PostgreSQL noticing.

With the column, a relation's scope is a fact about that relation alone. Each rule
reads one object, a filter on `tenant_id` is a filter on a column every relation
has, every index can lead with it, and a composite foreign key lets PostgreSQL
itself refuse a reference into another tenant's rows.

## Declaring it: `db/project.yaml`

Tenancy is a fact about the schema, the same in every environment, so it is
declared once, in `db/project.yaml`
([reference](../reference/configuration.md#dbprojectyaml)):

```yaml
# db/project.yaml
tenancy:
  discriminator: tenant_id              # the column every tenant row carries
  root: management.tb_organization      # the table of tenants
  global_schemas: [catalog]             # every relation here is shared
```

- **`discriminator`**: the column name; `tenant_id` when omitted.
- **`root`**: the table of tenants, schema-qualified. Its key is the tenant id.
- **`global_schemas`**: schemas holding shared reference data.

The block is the switch. Without it confiture assumes nothing about tenants and no
tenant rule runs; selecting one (`--select tenant`) reports it *skipped*, with the
reason, never an empty pass. With it, all five rules run in every `confiture lint`,
with no `--select`; `--ignore` still narrows them, and `confiture lint --list-rules`
prints each rule's state and why. An environment file carrying a `tenancy:` block
is refused and pointed at `db/project.yaml`.

## Three scopes, and declaring global

Every table is one of:

| Scope | Because | Examples |
|---|---|---|
| **tenant** | it carries the discriminator | orders, invoices, a tenant's settings |
| **global** | its schema is in `global_schemas`, or it is declared | currencies, a product catalogue |
| **root** | it is `tenancy.root` | the table of tenants |

A table that is none of these is **undecided**, and that is a finding: the decision
nobody made. The root carries no discriminator; one of its own columns *is* the
tenant id — the column the discriminators reference, usually its primary key.

A table outside the global schemas is declared global by a directive on the line
above its `CREATE`, with a reason:

```sql
-- confiture:tenant-global ISO 4217 codes, the same for every tenant
CREATE TABLE app.tb_currency (
    code  text PRIMARY KEY,
    label text NOT NULL
);
```

The directive also applies to `CREATE [MATERIALIZED] VIEW` and to
`CREATE UNIQUE INDEX` (see `tenant_005`). A declaration is honest or it is a
finding: a directive without a reason, a table declared global that carries the
discriminator anyway, a directive on a view that reads no tenant relation, or on a
unique index that already leads with the discriminator. A view that reads only
global relations is global without a declaration.

## The rules

All five report at `warning`. Each finding names the object, and the file and
line it is written at.

### `tenant_001` — an INSERT supplies the discriminator

Every `INSERT` in a function or procedure body into a tenant table names the
discriminator among the columns it writes, or the column has a default. Without
it the row is refused by `NOT NULL` at run time, in whichever code path reaches
that `INSERT` first.

```sql
CREATE FUNCTION app.fn_create_order(p_tenant_id uuid, p_provider uuid, p_reference text)
RETURNS uuid
LANGUAGE plpgsql
AS $$
DECLARE
    v_id uuid := gen_random_uuid();
BEGIN
    INSERT INTO app.tb_order (tenant_id, id, fk_provider, reference)
    VALUES (p_tenant_id, v_id, p_provider, p_reference);
    RETURN v_id;
END;
$$;
```

A default that reads the session's tenant is a legitimate design, and the rule
does not ask for the column then:

```sql
CREATE TABLE app.tb_note (
    tenant_id uuid NOT NULL DEFAULT current_setting('app.tenant_id')::uuid
        REFERENCES management.tb_organization (id),
    id        uuid NOT NULL,
    body      text NOT NULL,
    PRIMARY KEY (tenant_id, id)
);
```

A body the rule cannot read — one the PL/pgSQL compiler refuses, a string
`EXECUTE` builds at run time — is reported in the rule's `degraded` status, never
passed; `--require-complete` fails on it.

### `tenant_002` — every table carries it, or is declared global

A tenant table carries the discriminator `NOT NULL` and references the root with
it. The reference is what makes the column a tenant id rather than a value that
happens to be named like one; `NOT NULL` is what makes every row someone's.

```sql
CREATE TABLE app.tb_provider (
    tenant_id  uuid NOT NULL REFERENCES management.tb_organization (id),
    id         uuid NOT NULL,
    fk_company uuid NOT NULL REFERENCES catalog.tb_company (id),
    PRIMARY KEY (tenant_id, id)
);
```

It reports a table that is neither tenant nor global, a nullable discriminator,
a discriminator that does not reference the root, and a declaration that cannot
hold. A column a later `ALTER TABLE` adds counts; a partition is judged with its
parent.

### `tenant_003` — a view publishes it, traced as a plain column

Every view and materialized view that reads a tenant relation — a tenant table,
the root, or another view that is tenant data, directly or through a routine it
calls — outputs a column named for the discriminator that is, **as a plain
column**, the discriminator of a relation it reads.

```sql
CREATE VIEW app.v_order AS
SELECT o.tenant_id,
       o.id,
       o.reference,
       c.legal_name AS provider_name
FROM app.tb_order o
JOIN app.tb_provider p ON p.tenant_id = o.tenant_id AND p.id = o.fk_provider
JOIN catalog.tb_company c ON c.id = p.fk_company;
```

A reader scopes a view by filtering on that column, and only a plain column
carries the guarantee the table gave it. `o.tenant_id::text`, a `COALESCE`, an
aggregate over it, a `NULL` in one branch of a `UNION`, or a `tenant_id` read from
a global table does not. The column is traced through the parse tree — aliases,
`JOIN … USING`, subqueries, CTEs, `*`, and each branch of a set operation — never
matched by name in the text. What the tracer cannot follow (a set-returning
function in `FROM`, a relation the model lacks) is a finding with its reason.

### `tenant_004` — a foreign key cannot cross tenants

A foreign key between two tenant tables carries the discriminator on both sides,
at the same position:

```sql
CREATE TABLE app.tb_order_line (
    tenant_id uuid NOT NULL REFERENCES management.tb_organization (id),
    id        uuid NOT NULL,
    fk_order  uuid NOT NULL,
    quantity  integer NOT NULL,
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, fk_order) REFERENCES app.tb_order (tenant_id, id)
);
```

Written as `FOREIGN KEY (fk_order) REFERENCES app.tb_order (id)`, the key accepts a
line of tenant B's naming tenant A's order: the order exists, so PostgreSQL has no
reason to object. Written with the discriminator, the referenced row must belong
to the same tenant, and PostgreSQL refuses anything else. The composite key needs
a target unique on `(tenant_id, id)`, which a primary key that leads with the
discriminator already is.

The other directions:

| From → to | Verdict |
|---|---|
| tenant → global | fine: every tenant may point at shared data |
| global → tenant or root | a finding: a shared row cannot point at one tenant's row |
| tenant → root | only the discriminator references the root |

**Only the discriminator references the root.** A second column referencing the
table of tenants is one of two things, and there is no directive to excuse either.

If it is the row's own tenant written again — a `bigint` twin of a `uuid`
discriminator, say — it duplicates the discriminator and nothing keeps the two
equal; a row whose two columns name two tenants is visible to the wrong one. Drop
it.

If it is another organisation — a provider, a partner, a customer — it is a
**counterparty**, and a pointer into another tenant's space is how one tenant's
rows come to reveal another's. Model it as a relation of the tenant's own over a
global directory of companies:

```sql
CREATE TABLE catalog.tb_company (
    id         uuid PRIMARY KEY,
    legal_name text NOT NULL,
    vat_id     text UNIQUE
);

CREATE TABLE app.tb_provider (
    tenant_id  uuid NOT NULL REFERENCES management.tb_organization (id),
    id         uuid NOT NULL,
    fk_company uuid NOT NULL REFERENCES catalog.tb_company (id),
    terms      text,
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, fk_company)
);

CREATE TABLE app.tb_order (
    tenant_id   uuid NOT NULL REFERENCES management.tb_organization (id),
    id          uuid NOT NULL,
    fk_provider uuid NOT NULL,
    reference   text NOT NULL,
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, reference),
    FOREIGN KEY (tenant_id, fk_provider) REFERENCES app.tb_provider (tenant_id, id)
);
```

A company's identity is stored once; each tenant keeps its own terms with it; and
an order can only name a provider of its own tenant. When the company is itself a
tenant, nothing changes: the relation is still the ordering tenant's row.

**A record two tenants must both see** — a contract between a customer and a
provider that are both tenants — is two records, one per tenant. A row belongs to
exactly one tenant: that is what the discriminator means, and what an application's
tenant filter relies on. So each party owns its own copy, the copies are tied by a
correlation key that is not a foreign key, and one routine writes them together:

```sql
CREATE TABLE app.tb_contract (
    tenant_id uuid NOT NULL REFERENCES management.tb_organization (id),
    id        uuid NOT NULL,
    agreement uuid NOT NULL,  -- the same value in each party's copy; not a foreign key
    title     text NOT NULL,
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, agreement)
);

CREATE FUNCTION app.fn_sign_contract(p_customer uuid, p_provider uuid, p_title text)
RETURNS uuid LANGUAGE plpgsql AS $$
DECLARE
    v_agreement uuid := gen_random_uuid();
BEGIN
    INSERT INTO app.tb_contract (tenant_id, id, agreement, title)
    VALUES (p_customer, gen_random_uuid(), v_agreement, p_title),
           (p_provider, gen_random_uuid(), v_agreement, p_title);
    RETURN v_agreement;
END;
$$;
```

Each copy is filtered, keyed and referenced like any tenant row, and no row points
into another tenant's space. The correlation key reveals nothing on its own; the
terms both parties must agree on are written only through the routine that writes
both copies. Declaring the contract global instead would be wrong twice over: it is
not reference data, and a global relation has no tenant to filter on, so any view
over it would show every tenant's contracts.

### `tenant_005` — keys lead with it

A tenant table's primary key, each `UNIQUE` constraint and each unique index has
the discriminator as its first key.

`UNIQUE (email)` on a tenant table is two defects. Tenant A's row blocks tenant B's
insert of the same address, which is a correctness bug. And the error B receives —
`duplicate key value violates unique constraint`, with `Key (email)=(…) already
exists` in its detail — tells B that the address exists in some other tenant: an
existence oracle across tenants, answerable by anyone who can attempt an insert.
`UNIQUE (tenant_id, email)` is neither. `UNIQUE (email, tenant_id)` prevents the
collision but does not lead with the discriminator, and is reported too: it cannot
serve a scoped lookup by its leading column, and it is not the `(tenant_id, …)`
target a composite foreign key names.

A primary key `(tenant_id, id)` is also the target every composite foreign key to
the table needs, so it serves `tenant_004` with no second index. Non-unique indexes
are not judged: a sweep across tenants by `created_at`, or a lookup by `id` alone,
legitimately wants one.

A uniqueness that is platform-wide on purpose — one login per address across the
platform — is written as its own `CREATE UNIQUE INDEX`, under the directive, so the
exception is visible in review:

```sql
-- confiture:tenant-global one login per address across the platform
CREATE UNIQUE INDEX ux_user_email ON app.tb_user (lower(email));
```

An inline `UNIQUE` in `CREATE TABLE` cannot carry the directive.

## Standard rows plus a tenant's own

Some reference data has a standard set every tenant shares and a tenant's own
additions: units of measure, document templates, tax categories. A table holding
both would need a `NULL` discriminator for the standard rows, which `tenant_002`
refuses and which a reader's `WHERE tenant_id = $1` would filter away.

It is two tables and one read view. The standard rows live in a global table, a
tenant's own in a tenant table, and the view's global branch fans the standard rows
out to every tenant by joining the root:

```sql
CREATE TABLE catalog.tb_unit (
    id    uuid PRIMARY KEY,
    code  text NOT NULL UNIQUE,
    label text NOT NULL
);

CREATE TABLE app.tb_custom_unit (
    tenant_id uuid NOT NULL REFERENCES management.tb_organization (id),
    id        uuid NOT NULL,
    code      text NOT NULL,
    label     text NOT NULL,
    PRIMARY KEY (tenant_id, id),
    UNIQUE (tenant_id, code)
);

CREATE VIEW app.v_unit AS
SELECT o.id AS tenant_id, u.id, u.code, u.label, false AS is_custom
FROM catalog.tb_unit u
CROSS JOIN management.tb_organization o
UNION ALL
SELECT c.tenant_id, c.id, c.code, c.label, true
FROM app.tb_custom_unit c;
```

`o.id AS tenant_id` publishes the root's tenant id under the discriminator's name,
so `tenant_003` traces both branches. A filter on `tenant_id` is pushed into each
branch of the `UNION ALL`: in the first it becomes a primary-key lookup on the
root, so one tenant's read costs the standard rows once, not once per tenant.

## Moving an existing schema

The steps below take a schema whose tenant is implied by foreign keys to the shape
above. `db/schema/` is edited to the target shape; each step is also a migration
for the databases that already exist. On large tables, write each step the way the
[zero-downtime guide](zero-downtime.md) describes: expand, backfill in batches,
contract.

### 1. Declare the project and its global schemas

Write `db/project.yaml` with the discriminator, the root and the schemas that hold
shared reference data. Run `confiture lint`: `tenant_002` now lists every table
whose scope is undecided, which is the worklist. Declare the global tables that
live outside the global schemas with the directive, each with its reason.

### 2. Add the column, backfill it, make it `NOT NULL`, reference the root

Add the column nullable, so the change is cheap and existing writers keep working:

```sql
ALTER TABLE app.tb_order ADD COLUMN tenant_id uuid;
```

Backfill it once from the chain the tenant used to be inferred from:

```sql
UPDATE app.tb_order o
SET tenant_id = p.tenant_id
FROM app.tb_provider p
WHERE p.id = o.fk_provider
  AND o.tenant_id IS NULL;
```

Then make it `NOT NULL` and reference the root. A `CHECK … NOT VALID` followed by
`VALIDATE` scans the table without blocking writes, and from PostgreSQL 12 on a
validated `CHECK (tenant_id IS NOT NULL)` lets `SET NOT NULL` skip its own scan.
The foreign key is added the same way:

```sql
ALTER TABLE app.tb_order
    ADD CONSTRAINT tb_order_tenant_id_not_null CHECK (tenant_id IS NOT NULL) NOT VALID;
ALTER TABLE app.tb_order VALIDATE CONSTRAINT tb_order_tenant_id_not_null;
ALTER TABLE app.tb_order ALTER COLUMN tenant_id SET NOT NULL;
ALTER TABLE app.tb_order DROP CONSTRAINT tb_order_tenant_id_not_null;

ALTER TABLE app.tb_order
    ADD CONSTRAINT tb_order_tenant_id_fkey
    FOREIGN KEY (tenant_id) REFERENCES management.tb_organization (id) NOT VALID;
ALTER TABLE app.tb_order VALIDATE CONSTRAINT tb_order_tenant_id_fkey;
```

Every writer must supply the column before `SET NOT NULL`; `tenant_001` lists the
routines whose `INSERT` does not.

### 3. Drop duplicate tenant columns

A table that already carried a second reference to the root holds the same fact
twice. Say the root keeps a surrogate `pk_organization bigint` beside its `id uuid`,
and an invoice carried `fk_organization` before it gained `tenant_id`. Check that
the two agree — the query counts the rows where they do not — then drop the old
column:

```sql
SELECT count(*)
FROM app.tb_invoice i
JOIN management.tb_organization o ON o.pk_organization = i.fk_organization
WHERE o.id <> i.tenant_id;

ALTER TABLE app.tb_invoice DROP COLUMN fk_organization;
```

A second reference that names a counterparty is remodelled instead, as a tenant
relation over a global directory of companies (see `tenant_004`).

### 4. Rebuild the keys to lead with `tenant_id`

Build the composite unique index first, without blocking writes
(`CREATE INDEX CONCURRENTLY` runs outside a transaction block):

```sql
CREATE UNIQUE INDEX CONCURRENTLY tb_order_tenant_id_id_key
    ON app.tb_order (tenant_id, id);
```

It is the target the composite foreign keys of the next step reference. Once they
are in place and no foreign key depends on the old primary key, swap it:

```sql
ALTER TABLE app.tb_order
    DROP CONSTRAINT tb_order_pkey,
    ADD CONSTRAINT tb_order_pkey PRIMARY KEY USING INDEX tb_order_tenant_id_id_key;
```

Every other unique key is rebuilt the same way: `UNIQUE (reference)` becomes
`UNIQUE (tenant_id, reference)`. A lookup by `id` alone keeps a plain, non-unique
index on `(id)` if it needs one.

### 5. Make the foreign keys composite

Add the composite key beside the old one, validate it, then drop the old one:

```sql
ALTER TABLE app.tb_order_line
    ADD CONSTRAINT tb_order_line_order_fkey
    FOREIGN KEY (tenant_id, fk_order) REFERENCES app.tb_order (tenant_id, id) NOT VALID;
ALTER TABLE app.tb_order_line VALIDATE CONSTRAINT tb_order_line_order_fkey;
ALTER TABLE app.tb_order_line DROP CONSTRAINT tb_order_line_fk_order_fkey;
```

`VALIDATE` is where a row already pointing at another tenant's row surfaces: it
fails, naming the key, and that row is data to repair before the constraint can
hold.

### 6. Publish `tenant_id` from the views

`CREATE OR REPLACE VIEW` can add columns only at the end of the list, so appending
`tenant_id` keeps the change in place; putting it first means dropping and
recreating the view and whatever depends on it.

```sql
CREATE OR REPLACE VIEW app.v_order AS
SELECT o.id,
       o.reference,
       o.tenant_id
FROM app.tb_order o;
```

### 7. Adopt with a baseline

A schema this size is rarely moved in one change. Record today's findings once,
and from then on only a new one fails:

```bash
confiture lint --baseline .confiture-lint-baseline.json --write-baseline
confiture lint --baseline .confiture-lint-baseline.json
```

The baseline file is the migration's remaining worklist; it shrinks as findings
are fixed and never grows on its own
([baselines](schema-linting.md#adopting-a-rule-with-a-baseline-baseline-write-baseline)).
A project that moves tables and views first and keys later can instead defer the
key rules explicitly, with `--ignore tenant_004,tenant_005`, until step 4 begins.

## Planner statistics for `(tenant_id, …)` pairs

A composite key makes the planner see two columns where there used to be one. For
a filter on both — `WHERE tenant_id = $1 AND fk_order = $2` — PostgreSQL multiplies
the two columns' selectivities as though they were independent. They are not:
`fk_order` alone determines `tenant_id`, so the estimate comes out too low. Extended
statistics tell it so:

```sql
CREATE STATISTICS app.st_order_line_tenant_order (dependencies)
    ON tenant_id, fk_order FROM app.tb_order_line;
ANALYZE app.tb_order_line;
```

Functional-dependency statistics apply to equality conditions against constants
(and `IN` lists), which is the shape of a scoped lookup. They do not change the
estimate of a join clause. For a join on both columns — `l.tenant_id = o.tenant_id
AND l.fk_order = o.id` — PostgreSQL uses the composite foreign key itself: when a
join's clauses match all columns of a foreign key, the planner estimates the join
from the key. That is one more reason to write the foreign keys composite.
Measure with `EXPLAIN ANALYZE` before and after; add statistics where the estimates
were wrong, not everywhere.

## The schema and the request

Two different things keep one tenant's data from another's, and they belong to
different owners.

**The shape of the schema is confiture's concern.** Every row has a tenant, every
read view publishes it as a plain column, no key can reach across tenants, and no
key collides across them. The five rules check that shape statically, from the DDL,
before any database exists.

**Scoping each request is the application's concern.** Something has to decide
which tenant a request acts for and restrict every read and write to it — a
`WHERE tenant_id = $1` added to every query, a row-level security policy that
reads a session setting, or both:

```sql
ALTER TABLE app.tb_order ENABLE ROW LEVEL SECURITY;

CREATE POLICY tb_order_tenant ON app.tb_order
    USING (tenant_id = current_setting('app.tenant_id')::uuid);
```

confiture does not check that layer, and cannot: it depends on how the application
connects and who it connects as. What the schema's shape gives it is a column to
filter on in every relation it reads, an index that leads with that column, and a
database that refuses a cross-tenant reference even when a filter is forgotten.
Two PostgreSQL facts matter at this boundary. A table's owner bypasses its
row-level security unless the table is altered with `FORCE ROW LEVEL SECURITY`.
And a view reads its tables with its owner's privileges, so the policies that
apply are the owner's, unless the view is created `WITH (security_invoker = true)`
(PostgreSQL 15 and later).

## See also

- [Lint rules](../reference/lint-rules.md#tenant_004-a-foreign-key-cannot-cross-tenants):
  every finding each rule emits.
- [Schema linting](schema-linting.md): `--select`, `--ignore`, `--fail-on`,
  baselines.
- [Configuration](../reference/configuration.md#dbprojectyaml): `db/project.yaml`.
- [Zero-downtime migrations](zero-downtime.md): expand, backfill, contract.
