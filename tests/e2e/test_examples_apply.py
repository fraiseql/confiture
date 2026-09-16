"""Every example environment that declares a schema builds one PostgreSQL accepts.

``tests/unit/docs/test_example_configs.py`` proves an example's environment file
loads through the ``Environment`` model. That is a statement about the YAML, not
about the DDL it points at: ``examples/02-fraiseql-integration`` *built* for
months while the schema it produced could not be applied to a database at all.

So this asks the other half of the question — does the built schema survive
``psql -v ON_ERROR_STOP=1``. Two details matter, both learned from the way the
02 breakage hid:

- The **apply** is the assertion, never the build. ``confiture build`` is a
  concatenation; it does not parse for syntax, so a file full of invalid DDL
  builds happily and fails on the first statement PostgreSQL reads.
- ``ON_ERROR_STOP=1`` reports the **first** error and stops. 02 had six real
  errors from two root causes, and the 60 cascade failures behind them were
  invisible until the first was fixed. A green run here means the whole file
  applied, not that its first statement did.

Environments that declare ``include_dirs: []`` are excluded by construction:
they are sync endpoints (``examples/04-production-sync-anonymization`` names
both of its own that way in a comment) and build no schema. That is a statement
the example makes on purpose, not a gap — the test asserts they say it clearly
rather than asserting they build.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

import psycopg
import pytest

from confiture.config.environment import Environment
from confiture.core.builder import SchemaBuilder
from confiture.core.psql_applier import apply_sql_via_psql

REPO_ROOT = Path(__file__).resolve().parents[2]
PLACEHOLDER_DSN = "postgresql://user:secret@db.example.internal:5432/app"

# A floor, so a listing that silently returns nothing cannot pass vacuously.
MIN_ENVIRONMENTS = 12


def _tracked(*patterns: str) -> list[Path]:
    """Tracked files matching the git pathspecs, relative to the repo root."""
    out = subprocess.run(
        ["git", "ls-files", "--", *patterns],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(REPO_ROOT / line for line in out.splitlines() if line)


def _environment_files() -> list[Path]:
    return _tracked("examples/*/db/environments/*.yaml")


def _load(env_file: Path, monkeypatch: pytest.MonkeyPatch) -> Environment:
    """Load *env_file* through the real model, with ``${VAR}`` placeholders bound."""
    import re

    for var in set(re.findall(r"\$\{([A-Z_][A-Z0-9_]*)(?::-[^}]*)?\}", env_file.read_text())):
        monkeypatch.setenv(var, PLACEHOLDER_DSN if "URL" in var or "DSN" in var else "x")
    return Environment.load(env_file.stem, project_dir=env_file.parents[2])


def test_every_example_schema_applies(
    fresh_database_factory: Callable[[str], str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each example environment with ``include_dirs`` builds DDL that applies cleanly."""
    env_files = _environment_files()
    assert len(env_files) >= MIN_ENVIRONMENTS, "the examples lost their environment files"

    applied = 0
    failures: list[str] = []
    for env_file in env_files:
        env = _load(env_file, monkeypatch)
        if not env.include_dirs:
            continue  # a sync endpoint; it builds no schema on purpose
        where = env_file.relative_to(REPO_ROOT)
        try:
            schema = SchemaBuilder(env=env).build()
        except Exception as exc:  # noqa: BLE001 - the report names the example
            failures.append(f"{where}: build failed: {exc}")
            continue
        url = fresh_database_factory("confiture_ex")
        try:
            apply_sql_via_psql(url, schema)
        except Exception as exc:  # noqa: BLE001 - the report names the example
            failures.append(f"{where}: apply failed: {exc}")
            continue
        applied += 1

    assert applied > 0, "no example environment declared a schema to build"
    assert failures == [], "example schemas PostgreSQL rejects:\n" + "\n".join(failures)


def test_every_example_schema_is_tracked(monkeypatch: pytest.MonkeyPatch) -> None:
    """The DDL an example builds from is in the repository, not just on one laptop.

    ``examples/02-fraiseql-integration`` gitignored the only file that defined its
    tables (``db/schema/10_tables/generated.sql``, treated as a codegen artifact).
    Locally the example built and — once its DDL was valid — applied. On a clean
    checkout ``confiture build`` found two files instead of three, emitted a schema
    of indexes referencing tables that were never created, and reported success.

    A build that succeeds on nothing is the failure mode this catches, so the
    assertion is on *tracked* files: whatever the working tree happens to hold is
    not what a reader clones.
    """
    tracked = {p for p in _tracked("examples/**/*.sql")}
    failures: list[str] = []
    for env_file in _environment_files():
        env = _load(env_file, monkeypatch)
        if not env.include_dirs:
            continue
        project = env_file.parents[2]
        found = [
            sql
            for include in env.include_dirs
            for sql in (project / str(getattr(include, "path", include))).rglob("*.sql")
        ]
        untracked = [p for p in found if p not in tracked]
        if not found:
            failures.append(f"{env_file.relative_to(REPO_ROOT)}: include_dirs match no SQL file")
        elif untracked:
            names = ", ".join(str(p.relative_to(REPO_ROOT)) for p in sorted(untracked))
            failures.append(
                f"{env_file.relative_to(REPO_ROOT)}: builds from untracked SQL "
                f"(absent on a clean checkout): {names}"
            )
    assert failures == [], "example schemas that do not survive a clone:\n" + "\n".join(failures)


def test_schemaless_environments_say_why(monkeypatch: pytest.MonkeyPatch) -> None:
    """An environment that builds nothing states that in the file, so it reads as a choice.

    Without this, ``include_dirs: []`` is indistinguishable from a forgotten key,
    and ``SCHEMA_001 No include_dirs specified`` gets filed as a bug against an
    example that is working exactly as intended.
    """
    failures: list[str] = []
    for env_file in _environment_files():
        env = _load(env_file, monkeypatch)
        if env.include_dirs:
            continue
        text = env_file.read_text().lower()
        if "builds no schema" not in text:
            failures.append(
                f"{env_file.relative_to(REPO_ROOT)}: empty include_dirs with no stated reason "
                "(say 'builds no schema' in a comment)"
            )
    assert failures == [], "\n".join(failures)
