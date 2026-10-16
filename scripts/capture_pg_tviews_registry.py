"""Capture what ``tviews.registry`` holds for each tree under ``tests/fixtures/pg_tviews_registry/``.

Each ``<case>.sql`` is applied to a database of its own, on a server whose
pg_tviews offers the contract confiture reads, and ``<case>.json`` beside it records
every registry row as ``to_jsonb(r)`` writes it, with the release and contract that
wrote it. The unit tests of the registry reader read these files: a row is what a
server answered, never one composed by hand.

Usage::

    uv run python scripts/capture_pg_tviews_registry.py \\
        --server-url postgresql://postgres@localhost:5432/postgres --commit <pg_tviews sha>
"""

import argparse
import json
from pathlib import Path

import psycopg

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "pg_tviews_registry"

_REGISTRY = "SELECT to_jsonb(r) FROM tviews.registry r ORDER BY r.schema, r.name"


def _database_url(server_url: str, name: str) -> str:
    return psycopg.conninfo.make_conninfo(server_url, dbname=name)


def capture(server_url: str, case: Path, commit: str) -> dict[str, object]:
    """The registry rows *case* leaves on a fresh database of *server_url*."""
    name = f"confiture_capture_{case.stem}"
    with psycopg.connect(server_url, autocommit=True) as admin:
        admin.execute(t"DROP DATABASE IF EXISTS {name:i} WITH (FORCE)")
        admin.execute(t"CREATE DATABASE {name:i}")
    try:
        with psycopg.connect(_database_url(server_url, name), autocommit=True) as conn:
            # Its own round trip: in one batch with the CREATE EXTENSION, pg_tviews'
            # hook is not loaded yet and a `CREATE TABLE tv_x AS` stays a plain table.
            conn.execute("CREATE EXTENSION pg_tviews")
            conn.execute(case.read_text())
            release = conn.execute(
                "SELECT extversion FROM pg_extension WHERE extname = 'pg_tviews'"
            ).fetchone()
            contract = conn.execute("SELECT tviews.contract_version()").fetchone()
            rows = [row[0] for row in conn.execute(_REGISTRY).fetchall()]
    finally:
        with psycopg.connect(server_url, autocommit=True) as admin:
            admin.execute(t"DROP DATABASE IF EXISTS {name:i} WITH (FORCE)")
    return {
        "captured_from": {
            "pg_tviews": release[0] if release else None,
            "commit": commit,
            "contract": contract[0] if contract else None,
        },
        "registry": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--commit", required=True, help="the pg_tviews commit the server runs")
    args = parser.parse_args()
    for case in sorted(FIXTURES.glob("*.sql")):
        captured = capture(args.server_url, case, args.commit)
        case.with_suffix(".json").write_text(json.dumps(captured, indent=2, sort_keys=True) + "\n")
        print(case.with_suffix(".json").name)


if __name__ == "__main__":
    main()
