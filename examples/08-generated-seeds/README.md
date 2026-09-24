# Generated seeds

A seed generator written against `confiture.platform` and nothing else. It is the
shape a tool like fraiseql-semis takes. It reads the schema into confiture's
model, walks the tables parents first, and supplies only the columns a writer may.
Each value respects what the schema promises for its column. The files it writes
load through `confiture seed apply` and pass all five prep-seed validation levels.

```bash
python generate.py                 # writes db/seeds/prep/ (committed; Random(42))
CONFITURE_EXAMPLE_DB_URL=postgresql://localhost/scratch ./run.sh
```

## The schema

The prep-seed pattern, with one foreign key:

```
db/schema/
├── 00_schemas.sql                    # prep_seed, catalog, catalog.product_status
├── 10_prep_seed/
│   ├── 10_tb_vendor.sql              # id UUID
│   └── 20_tb_product.sql             # fk_vendor_id UUID → prep_seed.tb_vendor
├── 20_catalog/
│   ├── 10_tb_vendor.sql              # pk_vendor BIGINT GENERATED ALWAYS AS IDENTITY
│   └── 20_tb_product.sql             # fk_vendor BIGINT → catalog.tb_vendor
└── 30_functions/
    ├── fn_resolve_tb_product.sql     # joins catalog.tb_vendor: runs second
    └── fn_resolve_tb_vendor.sql
```

The parent's name sorts *after* its child's on purpose. Neither loading the
seeds nor resolving them may depend on file names.

## What `generate.py` asks, and of what

| Question | Call | What it answers here |
|----------|------|----------------------|
| What does the schema declare? | `parse_schema(db/schema)` | the one model, read the way `confiture build` reads the tree |
| Which table first? | `dependency_order(model)` | `prep_seed.tb_vendor`, then `prep_seed.tb_product` |
| Which columns do I write? | `writable_columns(model, table)` | everything but identity, generated and serial columns |
| What must a value respect? | `column_facts(model, table, column)` | the enum's labels, the CHECK, the width, the foreign key's table |
| Write it | `write_insert_seed` / `write_copy_seed` | refused at write time for a column the table lacks or PostgreSQL fills |

A foreign key is filled from the ids already written for the table it resolves
to. That is why the order matters, and why `column_facts` returns the resolved
table rather than the name as the DDL wrote it.

## Two formats

`10_vendor.sql` is an `INSERT` and `20_product.sql` is a `COPY`. Both load
through `confiture seed apply`: each file runs in a savepoint of its own, and a
COPY block's rows stream through the driver's COPY protocol. PostgreSQL fills a
generated key under either format, because COPY honours a column's identity and
default for every column its list leaves out.

Prep-seed level 1 reads `INSERT` statements only, so it checks the vendor file
and passes the product file unread (#366). Levels 2–5 read both.

## Ids

The ids here are version-4 UUIDs drawn from the seeded generator. A generator
for a FraiseQL project takes its ids from **fraiseql-uuid**, which owns the
structured pattern convention; confiture keeps no copy of it. Level 1 checks the
generic shape only — eight, four, four, four and twelve hex digits — and so does
PostgreSQL's `uuid` input: neither reads the version or variant nibble, so an id
such as `01234567-5001-0001-0000-000000000042` loads and validates. Whether an id
follows the convention is fraiseql-uuid's question, not this example's.

## File names and seed profiles

The files are named `10_vendor.sql` and `20_product.sql`: `seed apply` loads
every file under a directory, recursively, in path order, and so does level 5. A
`SeedProfile` in an environment YAML selects files with `include` / `exclude`
globs — the gitignore-style path globs `include_dirs` uses, over each file's path
below the seeds directory. A glob with no `/` matches the file name at any depth,
so `include: ["*_product.sql"]` selects `20_product.sql` by its name alone.

## What `run.sh` checks

1. `generate.py` writes exactly the committed files (same seed, same bytes).
2. `confiture seed validate --prep-seed --level 5` finds no violation. It loads
   both files, runs both resolvers parents first, and rolls back.
3. `confiture seed apply` plus the two resolvers leave 4 vendors and 12 products
   in `catalog`, each product on its vendor's BIGINT key, and a quote in a
   seeded name intact.

See [Building on confiture](../../docs/guides/building-on-confiture.md) for the
whole surface.
