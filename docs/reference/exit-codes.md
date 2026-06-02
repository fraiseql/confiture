# Exit-code convention

Confiture's process exit codes are a **stability contract**. Tooling that wraps
Confiture — CI gates, deploy adapters, monitoring — branches on them, so they
are documented here and frozen going forward (see [Stability
contract](#stability-contract)).

Every `confiture` command exits with one of the integer codes below. The
authoritative source is the hand-authored `CANONICAL_EXIT_CODES` table in
[`python/confiture/core/error_codes.py`](../../python/confiture/core/error_codes.py);
the runtime reads it through `ConfiturError.exit_code`. You can print this
reference from the CLI with `confiture --exit-codes`.

> Symbolic error codes (`CONFIG_006`, `PRECON_1001`, …) are documented in
> [error-reference.md](../error-reference.md) and surfaced in `--format json`
> output. This document maps each symbolic code to its **integer exit code**.

## Canonical table

<!-- BEGIN GENERATED: confiture --exit-codes -->
| Exit | Meaning |
|------|---------|
| 0 | Success (including success-with-signal: already applied, nothing pending, advisories) |
| 1 | Generic failure (SQL/hook execution, ambiguous-change advisory, status: pending) |
| 2 | Tracking table absent — confiture not initialized on this database yet |
| 3 | Database connection failed — host/auth/network unreachable |
| 4 | Schema / DDL / build error |
| 5 | Configuration invalid, or validation / sync / lint / precondition failure |
| 6 | Lock or connection-pool contention — another writer holds the lock |
| 7 | Git / pgGit / grant-accompaniment error |
| 8 | Irreversible rollback, or inconsistent state after rollback |

### Symbolic codes per exit code

- **0** — Success (including success-with-signal: already applied, nothing pending, advisories)
  - LINT_1501, MIGR_101, MIGR_105
- **1** — Generic failure (SQL/hook execution, ambiguous-change advisory, status: pending)
  - DIFFER_402, HOOK_1100, HOOK_1101, SQL_001, SQL_700, SQL_701, SQL_702, SQL_703
- **2** — Tracking table absent — confiture not initialized on this database yet
  - PRECON_1001
- **3** — Database connection failed — host/auth/network unreachable
  - CONFIG_006, GEN_001, MIGR_001, MIGR_004, MIGR_010, MIGR_011, MIGR_100, MIGR_102, MIGR_103, MIGR_104, MIGR_106, MIGR_107
- **4** — Schema / DDL / build error
  - REBUILD_001, SCHEMA_001, SCHEMA_200, SCHEMA_201, SCHEMA_202, SCHEMA_203, SCHEMA_204
- **5** — Configuration invalid, or validation / sync / lint / precondition failure
  - ANON_1400, ANON_1401, CONFIG_001, CONFIG_002, CONFIG_003, CONFIG_004, CONFIG_005, CONFIG_007, CONFIG_010, DIFFER_400, DIFFER_401, DIFF_001, LINT_1500, PRECON_1000, RESTORE_001, SEED_001, SYNC_001, SYNC_300, SYNC_301, SYNC_302, SYNC_303, VALID_001, VALID_500, VALID_501, VALID_502, VERIFY_001
- **6** — Lock or connection-pool contention — another writer holds the lock
  - LOCK_1300, LOCK_1301, POOL_1200, POOL_1201
- **7** — Git / pgGit / grant-accompaniment error
  - GIT_001, GIT_002, GIT_800, GIT_801, GIT_802, GRANT_001, PGGIT_900, PGGIT_901
- **8** — Irreversible rollback, or inconsistent state after rollback
  - ROLLBACK_001, ROLLBACK_600, ROLLBACK_601, ROLLBACK_602
<!-- END GENERATED -->

> The block above is generated from `CANONICAL_EXIT_CODES` /
> `EXIT_CODE_MEANINGS`. Regenerate with `confiture --exit-codes` after adding a
> code; the convention test (`tests/unit/test_exit_code_convention.py`) fails if
> the registry and the hand-authored table disagree.

## Per-code carve-outs

A few codes deliberately differ from their family's default number. During any
call-site audit these are **intentional** — do not "align" them to the family
number:

| Code | Exit | Family default | Why it differs |
|------|------|----------------|----------------|
| `MIGR_101` (already applied) | 0 | 3 | success-with-signal, not an error |
| `MIGR_105` (no pending migrations) | 0 | 3 | success-with-signal, not an error |
| `LINT_1501` (lint advisory) | 0 | 5 | informational, non-blocking |
| `DIFFER_402` (ambiguous change) | 1 | 5 | generic advisory, not a hard diff error |
| `PRECON_1001` (tracking table absent) | 2 | 5 | the fresh-DB "not initialized yet" signal |
| `CONFIG_006` (connection failed) | 3 | 5 | host/auth/network, distinct from config-invalid |

`migrate status` additionally uses **1** for the established "pending migrations
exist" signal and **2** for "tracking table absent" — both are
success-with-signal exit codes specific to that command, not errors.

## How the convention was decided (issue #146)

Confiture 0.18.0 shipped **three incompatible** exit-code conventions: the CLI's
de-facto literals, the `ErrorCodeRegistry`'s family mapping, and the convention
proposed by issue #146. The decision (owner-accepted, 2026-05-31):

> Keep the **`ErrorCodeRegistry` as the canonical home** for exit codes — it is
> the one wired to the structured exception hierarchy and to
> `ConfiturError.exit_code` — but **renumber three families** so the registry
> *emits* the wrapper-facing convention: no-table = 2, connection failed = 3,
> config invalid = 5. The lock family stays 6.

Rationale: low numbers go to the most common operational failures (a fresh DB
with no tracking table; an unreachable database), and the structured exception
hierarchy stays the single source of truth. This was a **deliberate,
documented breaking change** to `.exit_code` output, made before the downstream
adapter shipped (so the breaking-change window was open).

## Reconciliation appendix — what changed vs 0.18.0

Only these codes' integer values changed. Wrappers that branched on the old
numbers must update:

| Symbolic code | Meaning | Old exit (≤0.18.0) | New exit |
|---------------|---------|:------------------:|:--------:|
| `PRECON_1001` | Database not initialized (tracking table absent) | 5 | **2** |
| `CONFIG_001` | Missing required config field | 2 | **5** |
| `CONFIG_002` | Invalid YAML syntax | 2 | **5** |
| `CONFIG_003` | Invalid database URL format | 2 | **5** |
| `CONFIG_004` | Environment config not found | 2 | **5** |
| `CONFIG_005` | Invalid include/exclude pattern | 2 | **5** |
| `CONFIG_006` | Database connection failed | 2 | **3** |
| `CONFIG_010` | Database URL not set in environment | 2 | **5** |

Migration guidance for wrapper authors:

- If you branched on **exit 2 = config error**, it is now **5**.
- **Exit 2** now means **tracking table absent** (fresh DB, no current revision).
- **Exit 3** now distinguishes a **connection failure** from a config error.

Codes that already matched the convention and did **not** change: `MIGR_106`
(duplicate version) = 3, `ROLLBACK_600` (irreversible) = 8, the entire lock/pool
family = 6.

## Stability contract

Going forward, the exit-code convention is **frozen**:

- **Additive only** — new symbolic codes may map to an existing integer; new
  integers may be introduced for genuinely new failure classes.
- **Meaning never changes** — the integer→meaning mapping above is stable. A
  code never silently changes which integer it exits with.
- **Breaking changes require a major version bump** and a prominent
  CHANGELOG old→new table.

The one sanctioned break before this contract took effect was the #146
renumbering documented in the reconciliation appendix above.

## See also

- [Symbolic error-code reference](../error-reference.md)
- [JSON output schemas](json-schemas.md)
