# Preflight golden fixtures — the cross-repo pact (#197 / fraisier-core#44)

**These files are product, not test scaffolding.** They are the shared bytes of
the migration risk contract: confiture asserts that it *emits* these shapes,
fraisier asserts that it *parses* them. Changing a fixture changes the contract
in both repositories at once, so a change here needs a matching change in
fraisier-core and a `contract_version` decision.

Upstream copy: `crates/fraisier-adapter-confiture/tests/fixtures/preflight/` in
[fraisier-core](https://github.com/fraiseql/fraisier-core). Specification:
`docs/proposals/migration-risk-contract.md`, same repo. They are vendored here
rather than referenced so confiture's CI, which cannot see the sibling
repository, still fails when the producer drifts from the pact.

| File | Contract state it pins |
|---|---|
| `v0-no-change-set.json` | A pre-contract payload — no `change_set` at all. Confiture ≤ 0.42.0. |
| `v1-empty.json` | Classified, with `changes: []` — *nothing changes*, which is distinct from the file above. |
| `v1-additive.json` | The simplest classified change. |
| `v1-mixed.json` | Three tiers in one set, in migration order. |
| `v1-unknown-tier.json` | A tier string the consumer does not know. **Confiture must never emit this.** |
| `v1-missing-tier.json` | An entry with no `tier` key — confiture's honest "I cannot classify this". |
| `v2-future.json` | A `contract_version` from the future. **Confiture must never emit this.** |
| `malformed.json` | `change_set` as a string. **Confiture must never emit this.** |

## Scenario

The fixtures share one migration set, which
`tests/contract/test_preflight_change_set_contract.py` reconstructs as real
migration files and runs `migrate preflight --format json` over:

- `20260804120000` — add `tb_user.nickname` (additive)
- `20260804120050` — index `tb_order.placed_at` (lock-risky)
- `20260804120100` — drop `tb_user.legacy_flag` (irreversible)
- `20260804120300` — widen `tb_order.total_cents` (no tier — see below)

## What the pact pins, and what it does not

`kind`, `object`, `migration` and `tier` are compared **exactly**. `detail` is
not: the contract defines it as "one human-readable line for the plan render,
never parsed", and confiture synthesises it from the parsed statement rather
than echoing the source text, so it carries no column type (`ADD COLUMN nickname
NULL`, where the fixture reads `ADD COLUMN nickname text NULL`). Echoing source
text would put arbitrary literals — including credentials in statements such as
`CREATE USER … PASSWORD …` — into a field that gets rendered to an operator, and
the contract forbids exactly that. The test asserts `detail` is a non-empty
string and nothing more.
