"""Small helpers shared across test layers."""

from __future__ import annotations

import os
import re

import psycopg

from confiture.core.schema_model import Routine
from confiture.core.type_lattice import signature_from_type_names

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

#: The extension the ``body`` lint family needs. No stock PostgreSQL carries it.
PLPGSQL_CHECK = "plpgsql_check"

_PLPGSQL_CHECK_URL: list[str | None] = []


def strip_ansi(text: str) -> str:
    """Remove ANSI colour codes (Rich forces them when ``GITHUB_ACTIONS`` is set)."""
    return _ANSI_RE.sub("", text)


def plpgsql_check_url() -> str | None:
    """A reachable server whose PostgreSQL carries ``plpgsql_check``, or ``None``.

    The ``body`` family needs one, and only the dedicated CI leg has it: CI's
    ``postgres:15``, the compose stack's ``postgres:16-alpine`` and a stock
    local install all lack the extension, so every other run of these tests
    exercises the skip path instead. ``CONFITURE_TEST_DB_URL`` is the one place
    a server URL comes from (TST-02); an unset variable means "no server was
    asked for", which is not a failure.

    Probed once per session — the answer cannot change mid-run, and a server
    that is not there must not be dialled once per test.
    """
    if not _PLPGSQL_CHECK_URL:
        _PLPGSQL_CHECK_URL.append(_probe(os.getenv("CONFITURE_TEST_DB_URL")))
    return _PLPGSQL_CHECK_URL[0]


def _probe(url: str | None) -> str | None:
    if not url:
        return None
    try:
        with psycopg.connect(url, connect_timeout=5) as connection:
            available = connection.execute(
                "SELECT 1 FROM pg_available_extensions WHERE name = %s", (PLPGSQL_CHECK,)
            ).fetchone()
    except (psycopg.Error, OSError):
        return None
    return url if available else None


def routine(name: str, *types: str, schema: str = "public", body: str | None = None) -> Routine:
    """A ``schema_model.Routine`` with its arguments spelled as a catalogue spells them.

    The detectors read routines from the model on both sides; a test that states a
    routine's arguments as text is stating them the way ``format_type`` would.
    """
    return Routine(
        name=name,
        schema=schema,
        signature=", ".join(types),
        signature_key=signature_from_type_names(types),
        body=body,
    )


def routines(bodies: dict[str, str | None]) -> list[Routine]:
    """``{"schema.name(type,…)": body}`` as routines — the shape body-drift tests state."""
    found: list[Routine] = []
    for key, body in bodies.items():
        qualified, _, arguments = key.partition("(")
        schema, _, name = qualified.rpartition(".")
        types = [t for t in arguments.rstrip(")").split(",") if t]
        found.append(routine(name, *types, schema=schema or "public", body=body))
    return found
