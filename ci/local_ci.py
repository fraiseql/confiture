#!/usr/bin/env python3
"""Run Confiture's GitHub "Quality Gate" locally, in Dagger containers.

Reproduces ``.github/workflows/quality-gate.yml`` (5 jobs + summary) on the same
kind of Linux containers GitHub uses, so an unpushed bundle can be proven green
before ``git push``. See ``ci/README.md``.

Usage (driven through a Dagger session so the SDK reuses the local engine)::

    dagger run -- uv run --with 'dagger-io==0.21.3' python ci/local_ci.py all
    dagger run -- uv run --with 'dagger-io==0.21.3' python ci/local_ci.py lint
    dagger run -- uv run --with 'dagger-io==0.21.3' python ci/local_ci.py test

Jobs: ``lint``, ``type-check``, ``rust-checks``, ``security``, ``test``, ``all``.
"""

from __future__ import annotations

import sys
import time

import anyio
import dagger
from dagger import dag

# --- parity constants (mirror quality-gate.yml) ------------------------------

PY_VERSION = "3.11"
UV_IMAGE = f"ghcr.io/astral-sh/uv:python{PY_VERSION}-bookworm-slim"
RUST_IMAGE = "rust:1-bookworm"
POSTGRES_IMAGE = "postgres:15"

# Pinned tool versions — must match the pins in quality-gate.yml (and uv.lock)
# so this local gate reproduces CI exactly rather than chasing whatever Astral
# shipped today.
RUFF = "ruff@0.15.15"
TY = "ty@0.0.43"

PG_USER = "confiture"
PG_PASSWORD = "confiture"
PG_MAIN_DB = "confiture_test"
EXTRA_DBS = ("confiture_source_test", "confiture_target_test")

# Keep the mounted source lean and deterministic: no host build artifacts, no
# host venv, no VCS metadata. Everything the jobs need is rebuilt in-container.
SOURCE_EXCLUDE = [
    ".git",
    ".venv",
    "venv",
    "target",
    "**/__pycache__",
    "**/*.pyc",
    ".dagger",
    ".phases",
    "htmlcov",
    ".pytest_cache",
    ".ruff_cache",
]


def _source() -> dagger.Directory:
    return dag.host().directory(".", exclude=SOURCE_EXCLUDE)


def _uv_base() -> dagger.Container:
    """uv + Python 3.11 image with the repo mounted and uv's cache warmed."""
    return (
        dag.container()
        .from_(UV_IMAGE)
        .with_mounted_cache("/root/.cache/uv", dag.cache_volume("confiture-uv"))
        .with_env_variable("UV_LINK_MODE", "copy")
        .with_mounted_directory("/src", _source())
        .with_workdir("/src")
    )


# --- the five quality-gate legs ----------------------------------------------


def lint() -> dagger.Container:
    """quality-gate `lint`: ruff check + ruff format --check (the format-check blind spot)."""
    return (
        _uv_base()
        .with_exec(["uvx", RUFF, "check", "."])
        .with_exec(["uvx", RUFF, "format", "--check", "."])
    )


def type_check() -> dagger.Container:
    """quality-gate `type-check`: ty against the project WITH its deps present.

    ty's `unresolved-import` rule (pre-1.0 default) needs the third-party deps
    installed, else every `import psycopg`/`pytest`/... is a hard error. We sync
    the dependency tree WITHOUT building the project (so no Rust toolchain is
    needed — ty skips the `_core` import via `TYPE_CHECKING`), then run pinned ty.
    """
    return (
        _uv_base()
        .with_exec(["uv", "venv", "--python", PY_VERSION])
        .with_exec(["uv", "sync", "--no-install-project", "--all-extras"])
        .with_exec(["uv", "pip", "install", TY.replace("@", "==")])
        # --no-sync: don't let `uv run` rebuild the project (which needs Rust).
        .with_exec(["uv", "run", "--no-sync", "ty", "check", "python/confiture/"])
    )


def security() -> dagger.Container:
    """quality-gate `security`: bandit at High/High (Trivy is advisory → skipped)."""
    return _uv_base().with_exec(
        [
            "uvx",
            "bandit",
            "-r",
            "python/confiture/",
            "--severity-level",
            "high",
            "--confidence-level",
            "high",
        ]
    )


def rust_checks() -> dagger.Container:
    """quality-gate `rust-checks`: cargo fmt --check + clippy -D warnings (never run on this branch)."""
    return (
        dag.container()
        .from_(RUST_IMAGE)
        .with_mounted_cache(
            "/usr/local/cargo/registry", dag.cache_volume("confiture-cargo-registry")
        )
        .with_exec(["rustup", "component", "add", "rustfmt", "clippy"])
        .with_mounted_directory("/src", _source())
        .with_workdir("/src")
        .with_exec(["cargo", "fmt", "--check"])
        .with_exec(["cargo", "clippy", "--all-targets", "--", "-D", "warnings"])
    )


def _postgres() -> dagger.Service:
    return (
        dag.container()
        .from_(POSTGRES_IMAGE)
        .with_env_variable("POSTGRES_USER", PG_USER)
        .with_env_variable("POSTGRES_PASSWORD", PG_PASSWORD)
        .with_env_variable("POSTGRES_DB", PG_MAIN_DB)
        .with_exposed_port(5432)
        .as_service(use_entrypoint=True)
    )


def test() -> dagger.Container:
    """quality-gate `test`: full pytest under the `confiture` role with the Rust ext built.

    Rust+Python+uv share one base (maturin is the build backend, so even
    ``uv pip install .`` needs the toolchain). Sets BOTH the CI env-var name-set
    (``DATABASE_URL`` family) and the conftest name-set (``CONFITURE_*_DB_URL``)
    so the integration tests actually drive the service as the ``confiture`` role.
    """
    dsn = f"postgresql://{PG_USER}:{PG_PASSWORD}@db:5432"
    db = _postgres()

    # createdb (not hand-quoted SQL) sidesteps nested-quoting landmines; the
    # main DB already exists via POSTGRES_DB, so only the two extras are created.
    create_extra_dbs = (
        f"set -e; export PGPASSWORD={PG_PASSWORD}; "
        f"for i in $(seq 1 60); do pg_isready -h db -U {PG_USER} -d postgres && break; "
        "echo waiting-for-postgres...; sleep 2; done; "
        f"for d in {' '.join(EXTRA_DBS)}; do "
        f'createdb -h db -U {PG_USER} "$d" || echo "$d already exists"; done'
    )

    return (
        dag.container()
        .from_(RUST_IMAGE)
        .with_mounted_cache("/root/.cache/uv", dag.cache_volume("confiture-uv"))
        .with_mounted_cache(
            "/usr/local/cargo/registry", dag.cache_volume("confiture-cargo-registry")
        )
        .with_env_variable("UV_LINK_MODE", "copy")
        # toolchain: python + dev headers + psql client; uv via the standalone installer
        .with_exec(
            [
                "bash",
                "-lc",
                "apt-get update && apt-get install -y --no-install-recommends "
                "python3 python3-dev python3-venv postgresql-client socat curl ca-certificates "
                "&& curl -LsSf https://astral.sh/uv/install.sh | sh",
            ]
        )
        .with_env_variable(
            "PATH", "/root/.local/bin:/usr/local/cargo/bin:/usr/local/bin:/usr/bin:/bin"
        )
        .with_mounted_directory("/src", _source())
        .with_workdir("/src")
        .with_service_binding("db", db)
        # build env: venv + deps (incl. extras) + Rust extension (maturin develop)
        .with_exec(["uv", "venv", "--python", PY_VERSION])
        .with_exec(["uv", "tool", "install", "maturin"])
        .with_exec(["uv", "pip", "install", ".[dev,notifications,ast]"])
        .with_exec(["uv", "run", "maturin", "develop", "--uv"])
        # sanity: Rust extension actually loaded (mirrors CI's HAS_RUST verify step)
        .with_exec(
            [
                "uv",
                "run",
                "python",
                "-c",
                "from confiture.core.builder import HAS_RUST; "
                "print(f'HAS_RUST={HAS_RUST}'); assert HAS_RUST, 'Rust ext not loaded'",
            ]
        )
        .with_exec(["bash", "-lc", create_extra_dbs])
        # env parity: CI's DATABASE_URL family + POSTGRES_* ...
        .with_env_variable("DATABASE_URL", f"{dsn}/{PG_MAIN_DB}")
        .with_env_variable("SOURCE_DB_URL", f"{dsn}/{EXTRA_DBS[0]}")
        .with_env_variable("TARGET_DB_URL", f"{dsn}/{EXTRA_DBS[1]}")
        .with_env_variable("POSTGRES_HOST", "db")
        .with_env_variable("POSTGRES_PORT", "5432")
        .with_env_variable("POSTGRES_USER", PG_USER)
        .with_env_variable("POSTGRES_PASSWORD", PG_PASSWORD)
        .with_env_variable("POSTGRES_DB", PG_MAIN_DB)
        # NOTE: GitHub CI does NOT set conftest's own CONFITURE_*_DB_URL name-set,
        # so its DB-backed integration tests SKIP on the credential-less fallback
        # (`postgresql://localhost/...`). We mirror that exactly here to prove the
        # push goes green. Setting CONFITURE_*_DB_URL=<the `db` service> instead
        # makes those tests actually RUN under the `confiture` role — a stricter
        # exercise that surfaced a separate, latent gap (CI never runs its own
        # integration tests, and they fail/pollute when forced to run). Tracked as
        # a follow-up, NOT a push blocker.
        #
        # GitHub maps the Postgres service to the runner's localhost:5432; Dagger
        # binds it at the alias `db`. A few tests use a host-less / hardcoded
        # `localhost` DSN (e.g. e2e migrate-up with a `host: localhost` config), so
        # we forward localhost:5432 -> db with socat to reproduce GitHub faithfully.
        .with_exec(
            [
                "bash",
                "-lc",
                "socat TCP-LISTEN:5432,fork,reuseaddr TCP:db:5432 & "
                "for i in $(seq 1 30); do pg_isready -h localhost -U "
                + PG_USER
                + " && break; sleep 0.5; done; "
                "uv run pytest tests/ -q -ra --tb=short",
            ]
        )
    )


def _diag(pytest_args: list[str]) -> dagger.Container:
    """Diagnostic: run pytest (args) in a postgres-FREE, Rust-FREE container.

    Mirrors the test leg's CI env (minus the DB service) so DB-touching tests
    fail-fast instead of skipping — used to bisect test-isolation pollution.
    Runs against source via pythonpath (no project build, so no Rust needed).
    """
    dsn = f"postgresql://{PG_USER}:{PG_PASSWORD}@db:5432"
    return (
        _uv_base()
        .with_exec(["uv", "venv", "--python", PY_VERSION])
        .with_exec(["uv", "sync", "--no-install-project", "--all-extras"])
        .with_env_variable("DATABASE_URL", f"{dsn}/{PG_MAIN_DB}")
        .with_env_variable("SOURCE_DB_URL", f"{dsn}/{EXTRA_DBS[0]}")
        .with_env_variable("TARGET_DB_URL", f"{dsn}/{EXTRA_DBS[1]}")
        .with_env_variable("POSTGRES_HOST", "db")
        .with_env_variable("POSTGRES_PORT", "5432")
        .with_env_variable("POSTGRES_USER", PG_USER)
        .with_env_variable("POSTGRES_PASSWORD", PG_PASSWORD)
        .with_env_variable("POSTGRES_DB", PG_MAIN_DB)
        .with_exec(["uv", "run", "--no-sync", "pytest", *pytest_args])
    )


JOBS: dict[str, object] = {
    "lint": lint,
    "type-check": type_check,
    "rust-checks": rust_checks,
    "security": security,
    "test": test,
}


async def _run_one(name: str) -> tuple[str, bool, str]:
    builder = JOBS[name]
    try:
        out = await builder().stdout()  # type: ignore[operator]
        return name, True, out
    except dagger.ExecError as exc:
        detail = (exc.stdout or "") + "\n" + (exc.stderr or "")
        return name, False, detail.strip()
    except dagger.QueryError as exc:  # engine/service-level failure
        return name, False, f"[dagger error] {exc}"


async def _main() -> int:
    requested = sys.argv[1] if len(sys.argv) > 1 else "all"
    if requested == "diag":
        import pathlib

        pytest_args = sys.argv[2:] or ["tests/", "-q"]
        async with dagger.connection(dagger.Config(log_output=sys.stderr)):
            try:
                out = await _diag(pytest_args).stdout()
                ok = True
            except dagger.ExecError as exc:
                out = (exc.stdout or "") + "\n" + (exc.stderr or "")
                ok = False
        pathlib.Path("/tmp/ci-diag.log").write_text(out)
        print("\n".join(out.splitlines()[-60:]))
        print("\nDIAG:", "PASS" if ok else "FAIL", "  args:", " ".join(pytest_args))
        return 0 if ok else 1
    if requested == "all":
        names = list(JOBS)
    elif requested in JOBS:
        names = [requested]
    else:
        print(f"unknown job '{requested}'; choose from: {', '.join(JOBS)}, all")
        return 2

    start = time.monotonic()
    async with dagger.connection(dagger.Config(log_output=sys.stderr)):
        if len(names) == 1:
            results = [await _run_one(names[0])]
        else:
            results = [None] * len(names)

            async def _slot(i: int, n: str) -> None:
                results[i] = await _run_one(n)

            async with anyio.create_task_group() as tg:
                for i, n in enumerate(names):
                    tg.start_soon(_slot, i, n)

    print("\n" + "=" * 64)
    print("  Confiture Quality Gate (local · Dagger)")
    print("=" * 64)
    all_ok = True
    for name, ok, out in results:  # type: ignore[misc]
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")
        if not ok:
            all_ok = False
            import pathlib

            pathlib.Path(f"/tmp/ci-{name}.log").write_text(out)  # full capture
            tail = "\n".join(out.splitlines()[-120:])
            print("  " + "-" * 60)
            print("\n".join("    " + line for line in tail.splitlines()))
            print("  " + "-" * 60)
    print("-" * 64)
    print(f"  {'✅ GATE OPEN' if all_ok else '❌ GATE BLOCKED'}  ({time.monotonic() - start:.0f}s)")
    print("=" * 64)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(anyio.run(_main))
