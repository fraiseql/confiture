# Local CI — Quality Gate in Dagger

`local_ci.py` reproduces `.github/workflows/quality-gate.yml` (the 5-job Quality
Gate + summary) in local Linux containers via [Dagger](https://dagger.io), so a
branch can be proven green **before** `git push`. It catches the blind spots a
plain local run misses: `ruff format --check`, `cargo fmt`/`clippy`, the Rust
extension build, and pytest under the dedicated **`confiture`** Postgres role.

## Run

```bash
# one leg
dagger run -- uv run --with 'dagger-io==0.21.3' python ci/local_ci.py lint
dagger run -- uv run --with 'dagger-io==0.21.3' python ci/local_ci.py type-check
dagger run -- uv run --with 'dagger-io==0.21.3' python ci/local_ci.py rust-checks
dagger run -- uv run --with 'dagger-io==0.21.3' python ci/local_ci.py security
dagger run -- uv run --with 'dagger-io==0.21.3' python ci/local_ci.py test

# the whole gate
dagger run -- uv run --with 'dagger-io==0.21.3' python ci/local_ci.py all
```

Requires a running container engine (Docker/Podman) and the `dagger` CLI
(`>=0.18`). The first run pulls the Dagger Engine image once; later runs reuse
warm uv + cargo cache volumes.

## Parity notes

- **Pinned tools.** `lint` runs `ruff@0.15.15`; `type-check` runs `ty@0.0.43` —
  the exact versions pinned in the workflow (and the `[dependency-groups]` /
  pre-commit dev pins). Keep `RUFF`/`TY` here in lockstep with those.
- **`type-check` installs deps.** ty's `unresolved-import` rule needs the
  third-party packages present, so the leg `uv sync --locked
  --no-install-project --all-extras` (deps without building the Rust ext — ty
  skips `_core` via `TYPE_CHECKING`) before running ty.
- **The lockfiles are mounted, not excluded.** `uv.lock` and `Cargo.lock` are
  tracked (#191) and every leg here syncs with `--locked`, matching CI. This is
  the reverse of the pre-0.39.0 arrangement, where the gate deliberately dropped
  the local lock so the container would resolve fresh "like GitHub". GitHub no
  longer resolves fresh, so mounting the tracked lock is what keeps the gate
  faithful. If `--locked` fails here, run `uv lock` and commit — do not relax
  the flag.
- **`test` mirrors GitHub exactly.** It sets the `DATABASE_URL` family +
  `POSTGRES_*` but **not** `CONFITURE_*_DB_URL`, so DB-backed integration tests
  skip on the credential-less fallback just as they do on GitHub. One caveat
  Dagger can't fully reproduce: GitHub maps the Postgres service to the runner's
  `localhost:5432`, whereas Dagger binds it at the service alias `db`. A handful
  of suite tests reach a *host-less* (`localhost`) DSN under full-suite
  conditions; they pass where a local Postgres is reachable (dev machines,
  GitHub's mapped service) but not against the `db`-only binding here. That is a
  harness limitation, not a code defect — see the note in `local_ci.py:test()`.
