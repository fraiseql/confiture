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

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import psycopg
import psycopg.sql

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


@dataclass(frozen=True)
class Diagnosis:
    """One thing ``plpgsql_check`` said about one routine.

    ``identity`` is ``schema.name(input types)`` as PostgreSQL spells it, built
    from ``pg_proc`` rather than from ``regprocedure`` — the latter drops the
    schema for anything on the current ``search_path``, and a finding that says
    ``fn_widget_pk(text)`` without saying where does not name an object.

    ``body_line`` is counted in the *body's* own frame, the way
    ``parse_plpgsql`` counts: line 1 is whatever follows the opening delimiter.
    A diagnosis about the routine as a whole — "control reached end of function
    without RETURN" — carries no line at all.
    """

    schema: str
    name: str
    arity: int
    identity: str
    body_line: int | None
    level: str
    sqlstate: str
    message: str

    @property
    def raises(self) -> bool:
        """Whether this is a body that will fail, rather than an opinion about one.

        ``plpgsql_check`` reports both through one table, and its own ``level``
        does not separate them: the issue's headline case — a ``UUID`` variable
        fed from a ``BIGINT`` column — comes back at ``warning`` and carries
        SQLSTATE ``42804``, while "unused variable" comes back at ``warning``
        and carries ``00000``. The SQLSTATE is what tells them apart: a
        condition PostgreSQL would actually raise, or the analyser's own view of
        a body that works.
        """
        return self.sqlstate != _NO_CONDITION


#: SQLSTATE ``successful_completion``: what ``plpgsql_check`` puts on a remark
#: that is not a diagnosis of anything PostgreSQL would raise.
_NO_CONDITION = "00000"

#: Every PL/pgSQL routine the DDL created, and what the analyser says about it.
#:
#: A trigger function cannot be checked without the relation it fires on —
#: asking for one without it raises ``missing trigger relation``, which in a
#: single query would take the whole analysis down — so the relation comes from
#: ``pg_trigger``, and a trigger function nothing fires is left alone.
#: ``format_type`` over ``proargtypes`` spells the input types the way the
#: catalog does; ``pg_depend`` keeps an extension's own routines out.
#:
#: ``{check}`` is the analyser, schema-qualified: the connection's
#: ``search_path`` is set to the one the application uses, which need not
#: contain the schema the extension was installed into.
_ANALYSIS = """
WITH routines AS (
    SELECT p.oid,
           n.nspname AS schema,
           p.proname AS name,
           p.pronargs AS arity,
           n.nspname || '.' || p.proname || '(' || COALESCE(
               (SELECT string_agg(format_type(t, NULL), ',' ORDER BY o)
                  FROM unnest(p.proargtypes::oid[]) WITH ORDINALITY AS a(t, o)),
               '') || ')' AS identity,
           p.prorettype = 'pg_catalog.trigger'::regtype AS is_trigger,
           (SELECT t.tgrelid
              FROM pg_trigger t
             WHERE t.tgfoid = p.oid AND NOT t.tgisinternal
             LIMIT 1) AS relid
      FROM pg_proc p
      JOIN pg_namespace n ON n.oid = p.pronamespace
      JOIN pg_language l ON l.oid = p.prolang
     WHERE l.lanname = 'plpgsql'
       AND n.nspname NOT IN ('pg_catalog', 'information_schema')
       AND NOT EXISTS (
           SELECT 1 FROM pg_depend d WHERE d.objid = p.oid AND d.deptype = 'e')
)
SELECT r.schema, r.name, r.arity, r.identity,
       c.lineno, c.level, c.sqlstate, c.message
  FROM routines r
  CROSS JOIN LATERAL {check}(
           funcoid := r.oid,
           relid := COALESCE(r.relid, 0),
           fatal_errors := false,
           other_warnings := true,
           extra_warnings := false,
           performance_warnings := false,
           security_warnings := false) c
 WHERE NOT r.is_trigger OR r.relid IS NOT NULL
 ORDER BY r.schema, r.name, r.arity, c.lineno NULLS LAST
"""


def diagnose(
    server_url: str, schema_sql: str, *, search_path: Sequence[str] = ()
) -> list[Diagnosis]:
    """What ``plpgsql_check`` says about every routine in *schema_sql*.

    The DDL is built into a throwaway database on *server_url* and the database
    is dropped again — :class:`~confiture.core.expected_db.ExpectedSchemaDB` owns
    that lifecycle, and has since the drift-guard epic. Nothing here opens the
    server's own database.

    *search_path* is the environment's ``lint.search_path``. An unqualified name
    in a body resolves through ``search_path`` at run time, so the analyser has
    to be asked the same question the application will ask; left empty, the
    scratch database's default applies.
    """
    # Reason: import cycle (expected_db reaches the migrator, which reaches the linter)
    from confiture.core.expected_db import ExpectedSchemaDB

    with ExpectedSchemaDB(server_url).from_source(schema_sql=schema_sql) as connection:
        analyser = _install(connection)
        if search_path:
            connection.execute(
                psycopg.sql.SQL("SET search_path = {}").format(
                    psycopg.sql.SQL(", ").join(psycopg.sql.Identifier(s) for s in search_path)
                )
            )
        return [
            Diagnosis(
                schema=schema,
                name=name,
                arity=arity,
                identity=identity,
                body_line=lineno,
                level=level,
                sqlstate=sqlstate,
                message=message,
            )
            for schema, name, arity, identity, lineno, level, sqlstate, message in (
                connection.execute(psycopg.sql.SQL(_ANALYSIS).format(check=analyser)).fetchall()
            )
        ]


def _install(connection: Any) -> psycopg.sql.Identifier:
    """Create the extension in the scratch database; return its analyser, qualified.

    An extension lands in whichever schema is first on the ``search_path`` when
    it is created — usually ``public``, which the project's own
    ``lint.search_path`` need not contain. Naming the function by its schema is
    what keeps the two independent.
    """
    connection.execute(
        psycopg.sql.SQL("CREATE EXTENSION IF NOT EXISTS {}").format(
            psycopg.sql.Identifier(EXTENSION)
        )
    )
    schema = connection.execute(
        "SELECT n.nspname FROM pg_extension e"
        " JOIN pg_namespace n ON n.oid = e.extnamespace"
        " WHERE e.extname = %s",
        (EXTENSION,),
    ).fetchone()[0]
    return psycopg.sql.Identifier(schema, "plpgsql_check_function_tb")
