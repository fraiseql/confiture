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

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import psycopg
import psycopg.sql

from confiture.core.linting import references
from confiture.core.linting.schema_linter import LintViolation, RuleSeverity

#: A body that will raise on its first call.
RULE_ID = "body_001"

#: The analyser's own opinions about a body that works: an unused variable, a
#: shadowed declaration. Separately selectable, because a project can want the
#: first list without the second.
WARNING_RULE_ID = "body_002"

#: The extension that does the analysis. Not in a stock PostgreSQL.
EXTENSION = "plpgsql_check"

#: The schema key a routine created without a qualifier is filed under: the
#: file cannot say which schema it lands in, and the catalog can.
_ANY_SCHEMA = "*"

#: How long the reachability probe waits. A lint runs in a pre-commit hook; a
#: server that is not there must cost a moment, not a minute. The same number
#: ``build_003``'s live tier uses, for the same reason.
CONNECT_TIMEOUT_S = 3

_UNREACHABLE = (
    "the maintenance server did not answer, so the scratch database could not be built "
    "(pass --server-url to name a writable server other than the environment's own): "
)

#: The third way the rule does not run, and the only one that can only be found
#: by trying: the server is there, the extension is there, and the DDL does not
#: apply — a build that fails here is a build that would fail anywhere.
BUILD_FAILED = (
    "the scratch database could not be built from the DDL, so the bodies were never analysed: "
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
class Location:
    """Where a routine is written: its file, its ``CREATE``, and its body's first line."""

    file: str | None
    line: int
    body_line: int | None

    def at(self, body_line: int | None) -> int:
        """The file line a body-relative diagnosis belongs on.

        A diagnosis about the routine as a whole carries no line, and one whose
        body could not be located in the file falls back to the ``CREATE`` —
        the statement's own line is a coarser answer than the body's and a much
        better one than a line several short of it.
        """
        if body_line is None or self.body_line is None:
            return self.line
        return references.file_line(body_line, self.body_line)


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
    kind: str
    identity: str
    body_line: int | None
    level: str
    sqlstate: str
    message: str
    hint: str | None

    @property
    def key(self) -> tuple[str, str, int]:
        """What joins a catalog routine to the ``CREATE`` that made it."""
        return (self.schema, self.name, self.arity)

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
           CASE p.prokind WHEN 'p' THEN 'procedure' ELSE 'function' END AS kind,
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
SELECT r.schema, r.name, r.arity, r.kind, r.identity,
       c.lineno, c.level, c.sqlstate, c.message, c.hint
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
                kind=kind,
                identity=identity,
                body_line=lineno,
                level=level,
                sqlstate=sqlstate,
                message=message,
                hint=hint,
            )
            for schema, name, arity, kind, identity, lineno, level, sqlstate, message, hint in (
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


def locations(sources: Iterable[tuple[str | None, str]]) -> dict[tuple[str, str, int], Location]:
    """Where each routine is written, keyed the way a diagnosis is keyed.

    ``sources`` is ``(project-relative file label, text)`` per DDL file. The key
    is ``(schema, name, input-argument count)``: PostgreSQL spells an argument's
    type its own way (``character varying`` for a ``varchar`` in the DDL), so
    the count is what the two sides can agree on without normalising type names.
    A schema-less ``CREATE`` lands in whatever the build's search path put first,
    which the catalog knows and the file does not, so it is keyed under every
    schema no other definition of that name claims.

    Two overloads of one name with the same arity cannot be told apart this way,
    and neither gets a location rather than one of them getting the wrong file.
    """
    found: dict[tuple[str, str, int], Location] = {}
    ambiguous: set[tuple[str, str, int]] = set()
    unqualified: list[tuple[tuple[str, str, int], Location]] = []
    for label, text in sources:
        for placed in references.body_locations(text):
            obj = placed.obj
            here = Location(file=label, line=obj.statement_line, body_line=placed.first_line)
            key = (obj.folded_schema or "", obj.folded_name, _arity(obj.signature))
            if obj.folded_schema is None:
                unqualified.append((key, here))
            elif key in found:
                ambiguous.add(key)
            else:
                found[key] = here
    for (_schema, name, arity), here in unqualified:
        _add_unqualified(found, ambiguous, name, arity, here)
    for key in ambiguous:
        found.pop(key, None)
    return found


def _add_unqualified(
    found: dict[tuple[str, str, int], Location],
    ambiguous: set[tuple[str, str, int]],
    name: str,
    arity: int,
    here: Location,
) -> None:
    """A routine created without a schema qualifier answers for every schema.

    Which one it lands in is a property of the build's search path, not of the
    file — so the location is offered under any schema, and withdrawn where a
    qualified definition of the same name already claims one.
    """
    key = (_ANY_SCHEMA, name, arity)
    if key in found:
        ambiguous.add(key)
    else:
        found[key] = here


def locate(where: Mapping[tuple[str, str, int], Location], diagnosis: Diagnosis) -> Location | None:
    """The DDL location of the routine a diagnosis is about, if it can be told."""
    return where.get(diagnosis.key) or where.get((_ANY_SCHEMA, diagnosis.name, diagnosis.arity))


def _arity(signature: str | None) -> int:
    """How many input arguments a ``CREATE``'s parameter list declares.

    The inventory's signature is the input types as written with their typmods
    dropped (``numeric``, never ``numeric(10,2)``), so no entry can contain a
    comma and counting them is exact.
    """
    return 0 if not signature else signature.count(",") + 1


def findings(
    diagnoses: Iterable[Diagnosis], where: Mapping[tuple[str, str, int], Location]
) -> list[LintViolation]:
    """One finding per diagnosis, at the file line the routine's body puts it on."""
    return [_finding(diagnosis, locate(where, diagnosis)) for diagnosis in diagnoses]


def _finding(diagnosis: Diagnosis, at: Location | None) -> LintViolation:
    raising = diagnosis.raises
    return LintViolation(
        rule_id=RULE_ID if raising else WARNING_RULE_ID,
        rule_name="Unresolved Body" if raising else "Body Warning",
        severity=RuleSeverity.WARNING if raising else RuleSeverity.INFO,
        object_type=diagnosis.kind,
        object_name=diagnosis.identity,
        message=_message(diagnosis),
        file_path=None if at is None else at.file,
        line_number=None if at is None else at.at(diagnosis.body_line),
        suggested_fix=diagnosis.hint,
    )


def _message(diagnosis: Diagnosis) -> str:
    """PostgreSQL's diagnosis, attributed and quoted — never paraphrased.

    The SQLSTATE rides along for the findings that have a real one: it is what
    a reader looks up, and what tells a type mismatch from a missing relation
    without reading the prose.
    """
    state = f" (SQLSTATE {diagnosis.sqlstate})" if diagnosis.raises else ""
    return f"{EXTENSION} on '{diagnosis.identity}': {diagnosis.message}{state}"
