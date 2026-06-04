# fraisier migration-adapter contract

`fraisier-adapter-confiture` is the FraiseQL stack's **native, in-process
migration adapter** (fraisier-core PRD §6.3) — the privileged path the Rust
deploy engine uses to run schema migrations, distinct from the generic IPC
subprocess adapters. It drives Confiture by spawning the `confiture migrate`
CLI. This document is the **formal contract** between the two: the subcommands,
flags, JSON shapes, and exit codes the adapter depends on.

Because the adapter lives in a separate repository, Confiture CI cannot see it
directly. The contract is therefore enforced from Confiture's side by
[`tests/contract/test_fraisier_adapter_surface.py`](../../tests/contract/test_fraisier_adapter_surface.py),
which mirrors the adapter's argument construction and report parsing. A drift in
any subcommand's flags, JSON shape, or exit code fails Confiture's own CI.

## Minimum version

The adapter requires **Confiture ≥ 0.20.0** — the release that introduced
`migrate current`, `migrate down-to`, and the `--no-config` env-only DSN mode the
adapter relies on. See the [compatibility policy](#compatibility-policy) below.

## Invocation shape

Every call the adapter makes follows the same shape:

```
confiture migrate <subcommand> [<args>] --no-config --format json --output <file> [--migrations-dir <dir>]
```

- **`--no-config`** — config-file discovery is suppressed; the environment is the
  *sole* DSN source, so a stray `db/environments/*.yaml` in the deploy workdir can
  never shadow the operator's DSN.
- **DSN via `CONFITURE_DATABASE_URL`** — the secret is injected as an environment
  variable on the child process, **never** in argv (so it cannot leak into a
  process listing, log, or panic message).
- **`--format json` + `--output <file>`** — Confiture writes clean JSON to the
  file while human progress goes to stdout, so the adapter never has to
  disentangle the two. The adapter reads the file first and falls back to stdout.
- **`--migrations-dir`** — passed to every subcommand **except `current`**, which
  reads only the tracking table and has no migration-file inputs (and rejects the
  flag).

## Subcommand surface

| Adapter method     | Confiture command                          | JSON schema |
|--------------------|--------------------------------------------|-------------|
| `current_revision` | `migrate current`                          | [migrate-current](json-schemas/migrate-current.schema.json) |
| `up`               | `migrate up [--target <rev>]`              | [migrate-up](json-schemas/migrate-up.schema.json) |
| `down_to`          | `migrate down-to <rev>`                    | [migrate-down-to](json-schemas/migrate-down-to.schema.json) |
| `verify`           | `migrate verify`                           | [migrate-verify](json-schemas/migrate-verify.schema.json) |
| `preflight`        | `migrate preflight`                        | [migrate-preflight](json-schemas/migrate-preflight.schema.json) |
| `describe`         | `confiture --version` (synthesised)        | — (last whitespace token is the version) |

The adapter-consumed fields per command:

- **current** — `revision` (the head, `null` when none applied).
- **up** — `applied[].version` (the new head).
- **down-to** — `from`, `to`, `rolled_back[]`.
- **verify** — `failed_count` (ok ⇔ `0`) and each `results[].{version, name, status, error}`.
- **preflight** — `ok`, `summary`, each `issues[].{severity, code, message, migration}`.

## Exit codes

The adapter branches on Confiture's [exit-code convention](exit-codes.md). The
codes it specifically recognises:

| Exit | Adapter handling |
|------|------------------|
| `0` | success |
| `2` (`PRECON_1001`) | from `current`: a reachable-but-uninitialised DB → "no current revision" (not an error) |
| `2`, `5` | `InvalidConfig` (configuration problem) |
| `6` (`LOCK_1300`) | migration lock held by another process — **retriable** |
| everything else | execution failure |

The full universe of codes is `0..8`; the contract test asserts every observed
exit code falls within it, and that `PRECON_1001`/`CONFIG_010`/`LOCK_1300` keep
the integer values the adapter hardcodes.

## Compatibility policy

The exit-code convention and the JSON shapes above are a **stability contract**
(see [exit-codes.md](exit-codes.md#stability-contract)). Going forward:

- The adapter's minimum is **Confiture ≥ 0.20.0**. Any change that would break
  a subcommand's flags, JSON shape, or exit code for the adapter is a
  **breaking change** requiring a major version bump and a CHANGELOG old→new
  note — and should update the contract test in the same commit.
- New fields may be added to a JSON shape additively; the published schemas pin
  the adapter-consumed fields so a removal or rename is caught in CI.
