# Zero-downtime migrations: expand, backfill, contract

Some schema changes cannot be applied in one statement without holding the
table: a column that must be `NOT NULL` on a table that already has rows, a
constraint that must be checked against every row, a type change that rewrites
the heap. PostgreSQL takes `ACCESS EXCLUSIVE` for the statement, and every
reader and writer queues behind it for as long as it runs.

`migrate preflight` has always *said* so — its replica classifier advises
"add the column nullable → backfill → `SET NOT NULL` in a later release". Since
1.3.0 confiture *drives* it: `migrate up --online` applies such a migration as
staged phases, each a metadata change or a bounded batch, with a checkpoint
after every stage.

## The three patterns

| You write | Expand | Backfill | Contract |
|---|---|---|---|
| `ALTER TABLE t ADD COLUMN c text NOT NULL DEFAULT 'x'` | add `c` nullable with the default; `ADD CONSTRAINT t_c_not_null CHECK (c IS NOT NULL) NOT VALID` | fill the `NULL`s in batches | `VALIDATE CONSTRAINT` (no exclusive lock); `SET NOT NULL` (metadata-only once the check is validated, PostgreSQL ≥ 12); drop the check |
| `ALTER TABLE t ADD CONSTRAINT k CHECK (…)` / `FOREIGN KEY (…)` | the same constraint `NOT VALID` | — | `VALIDATE CONSTRAINT` |
| `ALTER TABLE t ALTER COLUMN c TYPE bigint` | add `c__new`; a trigger dual-writes `c` into it | copy `c` into `c__new` in batches | drop the trigger; rename `c` → `c__old`, `c__new` → `c`; drop `c__old` (**destructive**: needs `--allow-destructive`) |

A migration runs online as a whole or not at all: a file that mixes a staged
change with a plain statement applies the classic way, and `migrate preflight`
says which it is:

```json
{"version": "20260101000000", "online_available": true,
 "online_stages": [{"pattern": "replace_column", "table": "orders", "stage": "expand", "exclusive_hold": "metadata", "destructive": false}, …]}
```

`exclusive_hold` is the longest `ACCESS EXCLUSIVE` hold the stage takes,
from the same lock-profile table preflight costs every change with.

## Running it

```bash
confiture migrate up --online                     # staged where possible, classic otherwise
confiture migrate up --online --max-lock-ms 200   # yield between batches while others wait
confiture migrate steps                           # the checkpoints
confiture migrate steps --resume 20260101000000   # continue after a crash
```

The backfill commits every `migration.backfill.batch_size` rows (default
5 000), records the next block after each commit, and reports a
`backfill_progress` event per batch. With `migration.backfill.max_lock_ms`
(or `--max-lock-ms`) it pauses between batches while another session waits for
a lock on the table.

## Checkpoints

Every stage is recorded in `<tracking_table>_steps` — `tb_confiture_steps` by
default, created beside the ledger — as it starts and as it finishes, with the
backfill's cursor and rows done. A process that dies between stages, or in the
middle of a backfill, leaves the rows behind; `migrate steps --resume` continues
from the first stage that is not done, and from the backfill's block. The
migration reaches the ledger only when its last contract stage has finished:
until then it is pending, and `migrate status` says so.

## What stays the same

`window_safe` in `migrate preflight` is forward-compatibility for a two-version
window, and nothing here changes it: an online run makes a change *apply*
without a long lock, it does not make the change compatible with an old
release still writing to the table. The type-change pattern keeps the old
column's values, not its indexes, defaults or constraints — review the plan
before the contract stage drops it.

See also: [Replica-safe migrations](replica-safe-migrations.md) for the
classifier's verdicts, [Desired-state ingest](desired-state.md) for where the
migration comes from.
