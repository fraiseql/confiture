"""Record, or check, what ``migrate diff`` and ``confiture drift`` say about each schema tree.

The goldens under ``tests/fixtures/model_goldens/`` are the evidence that a change
to how confiture *models* a schema preserved what its comparisons report. They are
recorded from the CLI, never from a Python call, so what they pin is the wire
shape a consumer reads: the JSON on stdout, the exit code, and the DDL a
``--generate`` writes.

Each tree is built the way its example builds it (``confiture build --env …
--schema-only``, or the files its ``run.sh`` applies, in that order), then:

- ``diff/<tree>.json`` + ``.up.sql`` / ``.down.sql`` — ``migrate diff --from
  <empty> --to <tree> --format json --generate``: every object the differ reads
  from the tree, and the DDL it renders for each;
- ``diff/<pair>.*`` — the same for a before/after pair an example ships;
- ``drift/<tree>.json`` — ``confiture drift --format json`` against a database
  built from the tree (needs PostgreSQL).

A deliberate change to either output is refreshed with ``--write`` and named, with
its reason, in ``CHANGELOG.md`` under ``## [Unreleased]``.

Usage::

    uv run python scripts/refresh_model_goldens.py --check
    uv run python scripts/refresh_model_goldens.py --write [--only diff|drift]
    uv run python scripts/refresh_model_goldens.py --write --server-url postgresql://…/postgres
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urlunparse

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDENS = REPO_ROOT / "tests" / "fixtures" / "model_goldens"
CONFITURE = str(Path(sys.executable).parent / "confiture")


@dataclass(frozen=True)
class Tree:
    """One schema tree, and how the project it belongs to builds it."""

    name: str
    project_dir: str = "."
    env: str | None = None
    """Built with ``confiture build --env``; ``None`` concatenates ``files``."""
    files: tuple[str, ...] = ()
    preamble: str = ""
    """SQL the example's ``run.sh`` runs before the files (``CREATE SCHEMA …``)."""
    drift: bool = True
    """Whether a database is built from it and ``confiture drift`` recorded."""


_EX03 = "examples/03-zero-downtime-migration/db"
_EX06 = "examples/06-prep-seed-validation/db/schema"

TREES: tuple[Tree, ...] = (
    Tree("db-schema", ".", "local"),
    Tree("01-basic-migration", "examples/01-basic-migration", "local"),
    Tree("02-fraiseql-integration", "examples/02-fraiseql-integration", "local"),
    # Ships no run.sh and no environment: a before/after pair and nothing else.
    Tree(
        "03-zero-downtime-migration.old",
        files=(f"{_EX03}/old_schema/01_users_table.sql",),
        drift=False,
    ),
    Tree(
        "03-zero-downtime-migration.new",
        files=(f"{_EX03}/new_schema/01_users_table.sql",),
        drift=False,
    ),
    Tree(
        "04-production-sync-anonymization",
        "examples/04-production-sync-anonymization",
        "production",
    ),
    Tree("05-multi-environment-workflow", "examples/05-multi-environment-workflow", "ci"),
    # No environment: run.sh creates the two schemas, then applies three files in order.
    Tree(
        "06-prep-seed-validation",
        files=(
            f"{_EX06}/prep_seed/tb_manufacturer.sql",
            f"{_EX06}/catalog/tb_manufacturer.sql",
            f"{_EX06}/functions/fn_resolve_tb_manufacturer.sql",
        ),
        preamble="CREATE SCHEMA prep_seed;\nCREATE SCHEMA catalog;\n",
    ),
    Tree("07-comment-validation", "examples/07-comment-validation", "local"),
    Tree("basic", "examples/basic", "local"),
)

PAIRS: tuple[tuple[str, str, str], ...] = (
    (
        "03-zero-downtime-migration",
        "03-zero-downtime-migration.old",
        "03-zero-downtime-migration.new",
    ),
)

_VERSION = re.compile(r"\b\d{14}(?=_golden\b)|(?<=-- Version: )\d{14}\b")


def _run(*argv: str, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run([CONFITURE, *argv], cwd=cwd, capture_output=True, text=True, check=False)


def build(tree: Tree, out: Path) -> Path:
    """Write the SQL *tree* builds to *out*, exactly as its project builds it."""
    if tree.env is None:
        parts = [tree.preamble, *((REPO_ROOT / f).read_text() for f in tree.files)]
        out.write_text("\n".join(parts))
        return out
    result = _run(
        "build",
        "--env",
        tree.env,
        "--project-dir",
        str(REPO_ROOT / tree.project_dir),
        "--schema-only",
        "--output",
        str(out),
    )
    if result.returncode != 0:
        raise RuntimeError(f"build of {tree.name} failed: {result.stderr or result.stdout}")
    return out


def _normalise(text: str, replacements: dict[str, str]) -> str:
    for old, new in replacements.items():
        text = text.replace(old, new)
    return _VERSION.sub("<version>", text)


def _record_diff(before: Path, after: Path, work: Path) -> dict[str, str]:
    """``migrate diff --generate`` from *before* to *after*: {suffix: normalised text}."""
    migrations = work / "migrations"
    migrations.mkdir()
    result = _run(
        "migrate",
        "diff",
        "--from",
        str(before),
        "--to",
        str(after),
        "--format",
        "json",
        "--generate",
        "--name",
        "golden",
        "--migrations-dir",
        str(migrations),
    )
    replacements = {str(before): "<from>", str(after): "<to>", str(work): "<work>"}
    payload = {"exit_code": result.returncode, "stdout": json.loads(result.stdout)}
    recorded = {".json": _normalise(json.dumps(payload, indent=2) + "\n", replacements)}
    for suffix in (".up.sql", ".down.sql"):
        generated = sorted(migrations.glob(f"*{suffix}"))
        if generated:
            recorded[suffix] = _normalise(generated[0].read_text(), replacements)
    return recorded


def diff_goldens() -> dict[str, str]:
    """Every diff golden, keyed by its path relative to ``GOLDENS``."""
    goldens: dict[str, str] = {}
    by_name = {tree.name: tree for tree in TREES}
    with tempfile.TemporaryDirectory(prefix="confiture-goldens-") as tmp:
        root = Path(tmp)
        empty = root / "empty.sql"
        empty.write_text("")
        with ThreadPoolExecutor() as pool:
            paths = pool.map(lambda tree: build(tree, root / f"{tree.name}.sql"), TREES)
            built = dict(zip(by_name, paths, strict=True))
            jobs = [(name, empty, built[name]) for name in by_name]
            jobs += [(pair, built[old], built[new]) for pair, old, new in PAIRS]
            works = [root / f"work-{name}" for name, _, _ in jobs]
            for work in works:
                work.mkdir()
            results = pool.map(lambda job, work: _record_diff(job[1], job[2], work), jobs, works)
            for (name, _, _), recorded_texts in zip(jobs, results, strict=True):
                for suffix, text in recorded_texts.items():
                    goldens[f"diff/{name}{suffix}"] = text
    return goldens


@contextmanager
def scratch_database(server_url: str) -> Iterator[str]:
    """A database created on *server_url*'s server for one recording, then dropped."""
    import psycopg
    from psycopg import sql

    name = f"confiture_golden_{uuid.uuid4().hex[:8]}"
    admin = urlunparse(urlparse(server_url)._replace(path="/postgres"))
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        yield urlunparse(urlparse(server_url)._replace(path=f"/{name}"))
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )


def _record_drift(tree: Tree, schema: Path, database_url: str, work: Path) -> str:
    subprocess.run(
        ["psql", database_url, "-q", "-v", "ON_ERROR_STOP=1", "-f", str(schema)],
        check=True,
        capture_output=True,
    )
    config = work / f"{tree.name}.yaml"
    config.write_text(f"name: golden\ndatabase_url: {database_url}\ninclude_dirs: []\n")
    result = _run("drift", "-c", str(config), "--schema", str(schema), "--format", "json")
    stdout = json.loads(result.stdout)
    stdout["detection_time_ms"] = 0
    database = urlparse(database_url).path.lstrip("/")
    replacements = {str(schema): "<schema>", database: "<database>"}
    payload = {"exit_code": result.returncode, "stdout": stdout}
    return _normalise(json.dumps(payload, indent=2) + "\n", replacements)


def drift_goldens(make_database: Callable[[], AbstractContextManager[str]]) -> dict[str, str]:
    """Every drift golden; *make_database* is a context manager yielding a fresh URL."""
    with tempfile.TemporaryDirectory(prefix="confiture-goldens-") as tmp:
        root = Path(tmp)

        def one(tree: Tree) -> str:
            schema = build(tree, root / f"{tree.name}.sql")
            with make_database() as url:
                return _record_drift(tree, schema, url, root)

        trees = [tree for tree in TREES if tree.drift]
        with ThreadPoolExecutor() as pool:
            texts = pool.map(one, trees)
            return {f"drift/{t.name}.json": text for t, text in zip(trees, texts, strict=True)}


def recorded(kind: str) -> dict[str, str]:
    """The goldens on disk for *kind* (``diff`` or ``drift``)."""
    return {
        str(path.relative_to(GOLDENS)): path.read_text()
        for path in sorted((GOLDENS / kind).glob("*"))
        if path.is_file()
    }


def _collect(only: str | None, server_url: str) -> dict[str, dict[str, str]]:
    kinds: dict[str, dict[str, str]] = {}
    if only in (None, "diff"):
        kinds["diff"] = diff_goldens()
    if only in (None, "drift"):
        kinds["drift"] = drift_goldens(lambda: scratch_database(server_url))
    return kinds


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--only", choices=("diff", "drift"))
    parser.add_argument(
        "--server-url",
        default=os.environ.get("CONFITURE_TEST_DB_URL", "postgresql://localhost/postgres"),
        help="Any database on the server the drift goldens build scratch databases on",
    )
    args = parser.parse_args()

    stale: list[str] = []
    for kind, live in _collect(args.only, args.server_url).items():
        if args.write:
            directory = GOLDENS / kind
            directory.mkdir(parents=True, exist_ok=True)
            for old in directory.glob("*"):
                old.unlink()
            for rel, text in live.items():
                (GOLDENS / rel).write_text(text)
            print(f"wrote {len(live)} {kind} goldens")
        else:
            on_disk = recorded(kind)
            stale.extend(
                k for k in sorted(set(live) | set(on_disk)) if live.get(k) != on_disk.get(k)
            )
    if stale:
        print("model goldens are stale: " + ", ".join(stale), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
