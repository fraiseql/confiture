# Example 9: A multi-tenant schema

A small schema shaped the way the `tenant` lint family asks: every relation carries
`tenant_id` or is declared global, foreign keys cannot cross tenants, and keys lead
with the discriminator. `db/project.yaml` declares the project tenant-scoped, so a
plain `confiture lint` runs all five rules, and they all pass.

The design, and how to move an existing schema to it, is in
[the multi-tenant schemas guide](../../docs/guides/multi-tenant-schemas.md).

## What it shows

| File | What it shows |
|---|---|
| `db/project.yaml` | the `tenancy:` block: discriminator, root, global schemas |
| `10_management/10_tb_organization.sql` | the root: the table of tenants |
| `20_catalog/` | global reference data: companies, products, standard units |
| `30_app/10_tb_custom_unit.sql` | a tenant's own units, beside the standard ones |
| `30_app/20_tb_provider.sql` | a counterparty: the tenant's relation with a global company |
| `30_app/30_tb_order.sql` | composite keys and foreign keys, and `CREATE STATISTICS` |
| `30_app/40_fn_create_order.sql` | a routine whose `INSERT` supplies `tenant_id` |
| `30_app/50_v_order.sql` | a view publishing `tenant_id` as a plain column |
| `30_app/60_v_unit.sql` | the hybrid read view: standard rows for every tenant, plus a tenant's own |

## Run it

```bash
confiture lint --project-dir . --fail-on info
```

`run.sh` lints the tree, builds it into a scratch database, and shows what the
design buys at run time: two tenants each place an order `PO-1`, and a line of
tenant B's that names tenant A's order is refused by the composite foreign key.

```bash
CONFITURE_EXAMPLE_DB_URL=postgresql://localhost/confiture_examples ./run.sh
```

It creates and drops one database, `confiture_ex09_multi_tenant`, on that server.

## Try breaking it

Each of these edits makes one rule report:

- drop `tenant_id` from the `INSERT` in `fn_create_order` (`tenant_001`);
- remove `REFERENCES management.tb_organization (id)` from a `tenant_id` column
  (`tenant_002`);
- remove `o.tenant_id` from `app.v_order` (`tenant_003`);
- write `FOREIGN KEY (fk_provider) REFERENCES app.tb_provider (id)` on `tb_order`
  (`tenant_004`);
- write `UNIQUE (reference)` on `tb_order` (`tenant_005`).
