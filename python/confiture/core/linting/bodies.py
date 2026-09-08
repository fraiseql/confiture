"""``body_001`` / ``body_002``: what a plpgsql body does, asked of PostgreSQL (#245).

Every other rule in the catalogue answers from the text. This one cannot: that
``v_pk`` is ``UUID`` and ``pk_widget`` is ``BIGINT`` is a fact about resolved
types, and a parser that has not built the schema does not hold it. So the DDL
is materialised into a *throwaway* database — the drift-guard epic's
:class:`~confiture.core.expected_db.ExpectedSchemaDB`, on a writable maintenance
server — and ``plpgsql_check`` is asked what each body would do on its first
call.

That is not a second parser. confiture still reads DDL with pglast; PostgreSQL
is consulted only for what a parser cannot know, and its diagnosis is reported
verbatim, SQLSTATE included, rather than paraphrased.

**The skip is the common path.** ``plpgsql_check`` ships in no stock PostgreSQL
distribution, so a run that reports nothing is far more often a run that could
not look than a body that is clean. Every way this rule fails to run therefore
produces a :class:`~confiture.core.linting.schema_linter.RuleStatus` naming the
code, the state and what to do about it — and the gate reads those, so a
threshold the skipped rule could have reached does not exit 0.
"""

from __future__ import annotations

from typing import Any

import psycopg

#: A body that will raise on its first call.
RULE_ID = "body_001"

#: The analyser's own opinions about a body that works: an unused variable, a
#: shadowed declaration. Separately selectable, because a project can want the
#: first list without the second.
WARNING_RULE_ID = "body_002"

#: The extension that does the analysis. Not in a stock PostgreSQL.
EXTENSION = "plpgsql_check"

#: How long the reachability probe waits. A lint runs in a pre-commit hook; a
#: server that is not there must cost a moment, not a minute. The same number
#: ``build_003``'s live tier uses, for the same reason.
CONNECT_TIMEOUT_S = 3

_UNREACHABLE = (
    "the maintenance server did not answer, so the scratch database could not be built "
    "(pass --server-url to name a writable server other than the environment's own): "
)

_NO_EXTENSION = (
    f"{EXTENSION} is not available on the maintenance server, and no stock PostgreSQL "
    "carries it: install it (Debian/Ubuntu `postgresql-<major>-plpgsql-check`, "
    "or build https://github.com/okbob/plpgsql_check) and re-run"
)


def first_line(exc: BaseException) -> str:
    """A driver's error, trimmed to the sentence a summary line can carry."""
    text = str(exc).strip()
    return text.splitlines()[0] if text else type(exc).__name__


def unavailable(server_url: str) -> str | None:
    """Why the analyser cannot run, or ``None`` when it can.

    Two questions asked before anything is built, in the order that makes each
    answer meaningful: does the server answer, and does it carry the extension.
    They are different sentences because "your server is down" and "your server
    is fine but has no plpgsql_check" are different things to go and do. The
    third way this rule does not run — the scratch build itself failing — can
    only be discovered by attempting it, and is reported by the caller.

    There is deliberately no "nothing is configured" answer: ``database_url`` is
    a required, validated field of every environment config, so a ``confiture
    lint`` that got this far has a server URL.
    """
    try:
        with psycopg.connect(server_url, connect_timeout=CONNECT_TIMEOUT_S) as connection:
            if not _extension_available(connection):
                return _NO_EXTENSION
    except (psycopg.Error, OSError) as exc:
        return _UNREACHABLE + first_line(exc)
    return None


def _extension_available(connection: Any) -> bool:
    """Whether the server could install the extension into a scratch database.

    ``pg_available_extensions`` rather than ``pg_extension``: the scratch
    database is brand new, so what matters is whether the *server* has the files,
    not whether this database has run ``CREATE EXTENSION`` — the precedent is
    ``tests/integration/test_pggit_integration.py``.
    """
    row = connection.execute(
        "SELECT 1 FROM pg_available_extensions WHERE name = %s", (EXTENSION,)
    ).fetchone()
    return row is not None
