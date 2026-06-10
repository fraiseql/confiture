"""Test-database provisioning primitive (CI-path).

Provisions a template database, hands out lock-free per-worker clones via
``CREATE DATABASE … WITH TEMPLATE``, tears them down, and reports template
staleness by ``db/`` content hash. The CI-callable core that the pytest-xdist
fixtures sit on.

Built on :mod:`confiture.core.temp_database`'s injection-safe CREATE/DROP
helpers. Staleness is recorded as a ``COMMENT ON DATABASE`` on the template (not
an in-template table): comments are read connection-free from the maintenance DB
via ``shobj_description`` — so a status check never connects to the template and
never races a concurrent clone — and are not copied into clones.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse

import psycopg
import psycopg.errors
import psycopg.sql
from psycopg.sql import SQL, Identifier, Literal

from confiture.core.psql_applier import apply_sql_via_psql
from confiture.core.restorer import DatabaseRestorer, RestoreOptions
from confiture.core.seed_applier import apply_seed_files
from confiture.core.temp_database import (
    _maintenance_url,
    _replace_dbname,
    force_drop_database,
    terminate_backends,
)
from confiture.exceptions import ConfigurationError, SchemaError

logger = logging.getLogger(__name__)

# Marker comments stamped on confiture-managed databases (see module docstring).
_TEMPLATE_PREFIX = "confiture:template:"
_CLONE_PREFIX = "confiture:clone:"
_MANAGED_PREFIX = "confiture:"

# PostgreSQL identifier: leading letter/underscore, then letters/digits/underscore,
# 1–63 ASCII chars. Quoting still happens via Identifier; this is defence in depth.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")

# Tablespace LOCATION lookup. No row → the tablespace does not exist; an empty
# string → a built-in tablespace (pg_default/pg_global) living in the data dir.
_TABLESPACE_LOCATION_SQL = (
    "SELECT pg_tablespace_location(oid) FROM pg_tablespace WHERE spcname = %s"
)

# Presence probe for a tablespace LOCATION dir. Two #158 gotchas are baked in:
#   1. Extract a NON-NULL scalar field (``.size``) — ``pg_stat_file(loc)`` as a
#      whole record reads NULL for an existing dir on Linux (its creation-time
#      field is null), so ``record IS NOT NULL`` wrongly returns false.
#   2. ``missing_ok = true`` (the second arg) makes an absent path return NULL
#      instead of raising, so the probe yields a clean False rather than an error.
# This deliberately CANNOT detect a post-reboot-broken tmpfs (the LOCATION dir
# survives; only the inner PG_<version> dir is gone) — that is why clone()'s disk
# fallback, not this probe, is the real safety net.
_TABLESPACE_PROBE_SQL = "SELECT (pg_stat_file(%s, true)).size IS NOT NULL"

# Databases living in a tablespace, with their managed-marker comment. The
# tablespace name is bound as a parameter; nothing is interpolated.
_DBS_IN_TABLESPACE_SQL = (
    "SELECT d.datname, shobj_description(d.oid, 'pg_database') "
    "FROM pg_database d JOIN pg_tablespace t ON d.dattablespace = t.oid "
    "WHERE t.spcname = %s"
)


class TemplateState(str, Enum):
    """Whether a template matches the current ``db/`` hash."""

    CURRENT = "current"
    STALE = "stale"
    ABSENT = "absent"


@dataclass
class TemplateStatus:
    """Result of a template staleness check."""

    name: str
    state: TemplateState
    stored_hash: str | None
    current_hash: str | None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "stored_hash": self.stored_hash,
            "current_hash": self.current_hash,
        }


@dataclass
class CloneResult:
    """Result of a template clone.

    ``tablespace`` is the tablespace the clone actually landed in: the requested
    one on a successful RAM clone, or ``None`` for an on-disk clone — including
    after a tablespace failure fell back to disk. Callers can assert which path ran.
    """

    template: str
    target: str
    target_url: str
    tablespace: str | None = None

    def to_dict(self) -> dict:
        return {
            "template": self.template,
            "target": self.target,
            "target_url": self.target_url,
            "tablespace": self.tablespace,
        }


class _TablespaceUnavailable(Exception):
    """Internal signal: the requested tablespace cannot host the clone → use disk.

    Raised inside the clone retry loop when a tablespace is in play and the create
    fails for a non-retryable reason (a broken/absent tmpfs dir, a denied
    tablespace, etc.). Caught by :meth:`TestDbProvisioner.clone`, which retries the
    clone on disk. Never escapes the module.
    """

    def __init__(self, cause: BaseException) -> None:
        super().__init__(str(cause))
        self.cause = cause


@dataclass
class ManagedDatabase:
    """A confiture-managed database discovered by :meth:`list_databases`."""

    name: str
    kind: str  # "template" | "clone"
    detail: str  # the hash (template) or source template name (clone)

    def to_dict(self) -> dict:
        return {"name": self.name, "kind": self.kind, "detail": self.detail}


@dataclass
class RamSetupResult:
    """Result of :meth:`TestDbProvisioner.setup_ram_tablespace`.

    ``recreated`` is True when an existing tablespace was dropped and rebuilt (the
    post-reboot reset path), False on a clean first creation. ``action_required``
    is True when the LOCATION dir could not be prepared (the CLI lacked OS rights)
    so the caller must run a privileged command and re-run. ``dropped_databases``
    lists the databases removed from the tablespace — surfaced for transparency,
    since dropping them is destructive.
    """

    tablespace: str
    location: str
    owner: str
    recreated: bool
    action_required: bool
    dropped_databases: list[str]

    def to_dict(self) -> dict:
        return {
            "tablespace": self.tablespace,
            "location": self.location,
            "owner": self.owner,
            "recreated": self.recreated,
            "action_required": self.action_required,
            "dropped_databases": self.dropped_databases,
        }


# ---------------------------------------------------------------------------
# Pure helpers (unit-testable without a database)
# ---------------------------------------------------------------------------


def _validate_identifier(name: str) -> None:
    """Raise :class:`ConfigurationError` unless *name* is a safe SQL identifier.

    Args:
        name: Proposed database name.

    Raises:
        ConfigurationError: If the name is not a valid 1–63 char identifier.
    """
    if not _IDENTIFIER_RE.match(name or ""):
        raise ConfigurationError(
            f"Invalid database identifier: {name!r}.",
            error_code="CONFIG_010",
            resolution_hint="Use 1–63 chars: a letter or underscore followed by "
            "letters, digits, or underscores.",
        )


def _clone_sql(target: str, template: str, tablespace: str | None = None) -> psycopg.sql.Composed:
    base = SQL("CREATE DATABASE {} WITH TEMPLATE {}").format(
        Identifier(target), Identifier(template)
    )
    if tablespace is None:
        return base
    return base + SQL(" TABLESPACE {}").format(Identifier(tablespace))


def _create_db_sql(name: str) -> psycopg.sql.Composed:
    return SQL("CREATE DATABASE {}").format(Identifier(name))


def _alter_db_set_sql(name: str, guc: str, value: str) -> psycopg.sql.Composed:
    """Build ``ALTER DATABASE <name> SET <guc> TO <value>`` (a per-database GUC default).

    The value is rendered as a quoted SQL literal (``'off'``), never interpolated —
    same injection-safe discipline as the other ``_*_sql`` builders. PostgreSQL
    accepts a quoted string for enum GUCs such as ``synchronous_commit``.
    """
    return SQL("ALTER DATABASE {} SET {} TO {}").format(
        Identifier(name), Identifier(guc), Literal(value)
    )


def _comment_sql(name: str, value: str) -> psycopg.sql.Composed:
    return SQL("COMMENT ON DATABASE {} IS {}").format(Identifier(name), Literal(value))


def _create_tablespace_sql(name: str, location: str) -> psycopg.sql.Composed:
    return SQL("CREATE TABLESPACE {} LOCATION {}").format(Identifier(name), Literal(location))


def _drop_tablespace_sql(name: str) -> psycopg.sql.Composed:
    return SQL("DROP TABLESPACE {}").format(Identifier(name))


def _dbs_in_tablespace_sql() -> str:
    """Return the parameterised query for databases living in a tablespace."""
    return _DBS_IN_TABLESPACE_SQL


def _advisory_key(name: str) -> int:
    """Derive a process-stable signed 64-bit advisory-lock key from *name*.

    Used to single-flight template provisioning across xdist workers. Python's
    builtin ``hash`` is not stable across processes (PYTHONHASHSEED), so a
    SHA-256 prefix is used instead.
    """
    digest = hashlib.sha256(name.encode("utf-8")).digest()[:8]
    return int.from_bytes(digest, "big", signed=True)


def _managed_kind(comment: str | None) -> str | None:
    """Return ``"template"``/``"clone"`` for a managed comment, else ``None``."""
    if not comment:
        return None
    if comment.startswith(_TEMPLATE_PREFIX):
        return "template"
    if comment.startswith(_CLONE_PREFIX):
        return "clone"
    return None


def _classify_template(
    comment: str | None, current_hash: str | None, exists: bool
) -> TemplateStatus:
    """Classify a template's staleness from its stored comment.

    Args:
        comment: The template database comment, or None.
        current_hash: The freshly computed ``db/`` hash to compare against.
        exists: Whether the database exists at all.

    Returns:
        A :class:`TemplateStatus`. A database that does not exist — or exists but
        carries no confiture template marker — is reported ABSENT (it is not a
        usable template).
    """
    name = ""  # filled in by caller
    if not exists or not comment or not comment.startswith(_TEMPLATE_PREFIX):
        return TemplateStatus(name, TemplateState.ABSENT, None, current_hash)
    stored = comment[len(_TEMPLATE_PREFIX) :]
    state = TemplateState.CURRENT if stored == current_hash else TemplateState.STALE
    return TemplateStatus(name, state, stored, current_hash)


# ---------------------------------------------------------------------------
# Provisioner
# ---------------------------------------------------------------------------


class TestDbProvisioner:
    """Provisions template databases and per-worker clones on one PG server.

    Args:
        server_url: Any connection URL on the target server. The database
            component is ignored for administrative work (the maintenance
            ``postgres`` database is used for CREATE/DROP); it is the base for
            deriving per-database URLs.
    """

    __test__ = False  # not a pytest test class despite the "Test" prefix

    def __init__(self, server_url: str) -> None:
        self.server_url = server_url
        self.maintenance_url = _maintenance_url(server_url)
        parsed = urlparse(server_url)
        self._host = parsed.hostname or "/var/run/postgresql"
        self._port = parsed.port or 5432
        self._user = parsed.username

    # -- connection helpers ------------------------------------------------

    def _maintenance_conn(self) -> psycopg.Connection:
        return psycopg.connect(self.maintenance_url, autocommit=True)

    def _read_comment(self, conn: psycopg.Connection, db_name: str) -> tuple[bool, str | None]:
        """Return ``(exists, comment)`` for *db_name*, read from the maintenance DB."""
        row = conn.execute(
            "SELECT shobj_description(d.oid, 'pg_database') "
            "FROM pg_database d WHERE d.datname = %s",
            (db_name,),
        ).fetchone()
        if row is None:
            return False, None
        return True, row[0]

    def _set_comment(self, conn: psycopg.Connection, db_name: str, value: str) -> None:
        conn.execute(_comment_sql(db_name, value))

    # -- tablespace usability ----------------------------------------------

    def _tablespace_location(self, conn: psycopg.Connection, name: str) -> str | None:
        """Return the LOCATION dir of tablespace *name*, or None if it has no row.

        An empty string is a built-in tablespace (``pg_default``/``pg_global``),
        which lives in the data directory and has no separate LOCATION.
        """
        row = conn.execute(_TABLESPACE_LOCATION_SQL, (name,)).fetchone()
        return row[0] if row else None

    def tablespace_usable(self, name: str) -> bool:
        """Cheap gate: does tablespace *name* exist with a present LOCATION dir?

        This is a **gate, not a guarantee.** It answers "is it worth *attempting* a
        RAM clone in this tablespace?" — nothing more. A tmpfs LOCATION can pass
        this probe yet still fail the actual ``CREATE DATABASE … TABLESPACE`` after a
        reboot (the ``pg_tablespace`` row and the data-dir symlink survive a reboot,
        but the inner ``PG_<version>`` directory is cleared from ``/dev/shm``). That
        post-reboot breakage is impossible to detect cheaply, which is exactly why
        :meth:`clone`'s on-disk fallback — not this probe — is the real safety net.

        Returns False (never raises) for an absent tablespace, an absent LOCATION
        dir, or any error reading it (e.g. ``pg_stat_file`` denied for lack of
        ``pg_read_server_files``/superuser): when we cannot verify, the safe answer
        is "don't attempt RAM," and the on-disk clone path is always correct.

        A built-in tablespace (empty LOCATION) is always usable.
        """
        if not name:
            return False
        try:
            with self._maintenance_conn() as conn:
                location = self._tablespace_location(conn, name)
                if location is None:
                    return False  # no such tablespace
                if location == "":
                    return True  # built-in (pg_default/pg_global) — always usable
                row = conn.execute(_TABLESPACE_PROBE_SQL, (location,)).fetchone()
                return bool(row and row[0])
        except psycopg.Error:
            return False

    def _dbs_in_tablespace(
        self, conn: psycopg.Connection, name: str
    ) -> list[tuple[str, str | None]]:
        """Return ``(datname, comment)`` for every database living in tablespace *name*."""
        rows = conn.execute(_dbs_in_tablespace_sql(), (name,)).fetchall()
        return [(r[0], r[1]) for r in rows]

    def setup_ram_tablespace(
        self,
        name: str,
        location: str,
        *,
        owner: str,
        force: bool = False,
        dir_prepared: bool = True,
    ) -> RamSetupResult:
        """(Re)create tmpfs tablespace *name* at *location* — an idempotent reset.

        This owns the post-reboot DROP+re-CREATE dance: ``/dev/shm`` is cleared on
        boot, so the ``pg_tablespace`` row and the data-dir symlink survive but the
        inner ``PG_<version>`` directory is gone. Recreating that dir is not enough —
        the catalog still points at a tablespace PostgreSQL believes is initialised.
        The fix is to **drop the tablespace (after dropping the databases inside it)
        and re-create it**, which re-runs PostgreSQL's tablespace initialisation.

        By default only confiture-managed databases in the tablespace are dropped;
        a non-managed database blocks with a ``CONFIG_010`` error unless *force*
        (the same marker discipline as :meth:`provision_template`/:meth:`drop`). The
        OS-side dir preparation (create + chown to the PG server user) is the
        caller's job — when it could not be done (*dir_prepared* is False, e.g. the
        client lacks chown rights), nothing is dropped or created and the result
        flags ``action_required`` so the caller can print the privileged command.

        Args:
            name: Tablespace name to (re)create.
            location: The tmpfs LOCATION directory.
            owner: OS user that owns *location* (recorded on the result).
            force: Drop even non-managed databases living in the tablespace.
            dir_prepared: Whether *location* is ready (exists, empty, PG-owned).

        Returns:
            A :class:`RamSetupResult`.

        Raises:
            ConfigurationError: Invalid name, or a non-managed database present
                without *force*.
            SchemaError: The tablespace was created but is not usable afterwards.
        """
        _validate_identifier(name)

        if not dir_prepared:
            # We cannot finish the create, so we must not start: leave the catalog
            # untouched and signal that a privileged OS step is required.
            return RamSetupResult(
                tablespace=name,
                location=location,
                owner=owner,
                recreated=False,
                action_required=True,
                dropped_databases=[],
            )

        with self._maintenance_conn() as conn:
            existing = self._tablespace_location(conn, name) is not None
            dbs = self._dbs_in_tablespace(conn, name)
            unmanaged = sorted(d for d, comment in dbs if _managed_kind(comment) is None)
            if unmanaged and not force:
                raise ConfigurationError(
                    f"Tablespace {name!r} holds non-confiture-managed database(s): "
                    f"{', '.join(unmanaged)}. Refusing to drop them.",
                    error_code="CONFIG_010",
                    resolution_hint="Move or drop them yourself, or pass --force to "
                    "drop everything living in the tablespace.",
                )

            dropped: list[str] = []
            for db_name, _comment in dbs:
                force_drop_database(conn, db_name)
                dropped.append(db_name)
            if existing:
                conn.execute(_drop_tablespace_sql(name))
            conn.execute(_create_tablespace_sql(name, location))

        if not self.tablespace_usable(name):
            raise SchemaError(
                f"Created tablespace {name!r} but it is not usable at {location!r}.",
                error_code="SCHEMA_001",
                resolution_hint="Check that the LOCATION dir exists, is empty, and is "
                "owned by the PostgreSQL server OS user.",
            )

        return RamSetupResult(
            tablespace=name,
            location=location,
            owner=owner,
            recreated=existing,
            action_required=False,
            dropped_databases=dropped,
        )

    # -- staleness ---------------------------------------------------------

    def template_status(self, template: str, current_hash: str | None) -> TemplateStatus:
        """Report whether *template* matches *current_hash* (connection-free read)."""
        _validate_identifier(template)
        with self._maintenance_conn() as conn:
            exists, comment = self._read_comment(conn, template)
        status = _classify_template(comment, current_hash, exists)
        status.name = template
        return status

    # -- provisioning ------------------------------------------------------

    def provision_template(
        self,
        template: str,
        *,
        schema_hash: str,
        schema_sql: str | None = None,
        seed_files: list[Path] | None = None,
        from_artifact: Path | None = None,
        restorer: DatabaseRestorer | None = None,
        force: bool = False,
    ) -> TemplateStatus:
        """(Re)build *template* from DDL or a P1 artifact and stamp its hash.

        Args:
            template: Template database name.
            schema_hash: ``db/`` content hash to record on the template.
            schema_sql: Schema DDL to apply (DDL path).
            seed_files: Optional seed files to apply after the schema (DDL path).
            from_artifact: Path to a P1 ``-Fc``/``-Fd`` dump to restore instead
                of applying DDL.
            restorer: Injectable restorer (testing).
            force: Permit clobbering a same-named database that is not
                confiture-managed.

        Returns:
            A :class:`TemplateStatus` with ``state == CURRENT``.

        Raises:
            ConfigurationError: On invalid input or a refused clobber.
            SchemaError / RestoreError: On a failed build or restore.
        """
        _validate_identifier(template)
        if (schema_sql is None) == (from_artifact is None):
            raise ConfigurationError(
                "provision_template requires exactly one of schema_sql or from_artifact.",
                error_code="CONFIG_010",
            )

        with self._maintenance_conn() as conn:
            exists, comment = self._read_comment(conn, template)
            if exists and not force and _managed_kind(comment) is None:
                raise ConfigurationError(
                    f"Refusing to replace database {template!r}: it exists and is not "
                    "confiture-managed.",
                    error_code="CONFIG_010",
                    resolution_hint="Choose a different --template name, or pass --force.",
                )
            force_drop_database(conn, template)
            conn.execute(_create_db_sql(template))

        template_url = _replace_dbname(self.server_url, template)

        if from_artifact is not None:
            self._restore_into(template, from_artifact, restorer)
        else:
            apply_sql_via_psql(template_url, schema_sql)
            if seed_files:
                apply_seed_files(template_url, seed_files)

        with self._maintenance_conn() as conn:
            self._set_comment(conn, template, _TEMPLATE_PREFIX + schema_hash)

        return TemplateStatus(template, TemplateState.CURRENT, schema_hash, schema_hash)

    def ensure_template(
        self,
        template: str,
        *,
        schema_hash: str,
        schema_sql: str | None = None,
        seed_files: list[Path] | None = None,
        from_artifact: Path | None = None,
        restorer: DatabaseRestorer | None = None,
    ) -> TemplateStatus:
        """Provision *template* only if stale, single-flight across processes.

        A session-level PostgreSQL advisory lock keyed on the template name
        serialises concurrent callers (e.g. xdist workers all entering the
        session template fixture): the first to acquire the lock builds, and the
        rest observe ``CURRENT`` and return without rebuilding.

        Args mirror :meth:`provision_template`.

        Returns:
            The resulting :class:`TemplateStatus` (always ``CURRENT`` on success).
        """
        _validate_identifier(template)
        lock_key = _advisory_key(template)
        with self._maintenance_conn() as conn:
            conn.execute("SELECT pg_advisory_lock(%s)", (lock_key,))
            try:
                status = self.template_status(template, schema_hash)
                if status.state is TemplateState.CURRENT:
                    return status
                return self.provision_template(
                    template,
                    schema_hash=schema_hash,
                    schema_sql=schema_sql,
                    seed_files=seed_files,
                    from_artifact=from_artifact,
                    restorer=restorer,
                )
            finally:
                conn.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))

    def _restore_into(self, target: str, artifact: Path, restorer: DatabaseRestorer | None) -> None:
        restorer = restorer or DatabaseRestorer()
        result = restorer.restore(
            RestoreOptions(
                backup_path=Path(artifact),
                target_db=target,
                host=self._host,
                port=self._port,
                username=self._user,
                jobs=4,
                parallel_restore=True,
                no_owner=True,
                no_acl=True,
            )
        )
        if not result.success:
            raise SchemaError(
                f"Restoring artifact into template {target!r} failed: "
                + "; ".join(result.errors[:3]),
                error_code="SCHEMA_001",
                resolution_hint="Check that the artifact is a valid -Fc/-Fd dump.",
            )

    # -- cloning -----------------------------------------------------------

    def _require_template_exists(self, template: str) -> None:
        """Fail fast with an actionable error if *template* is absent.

        ``CREATE DATABASE … WITH TEMPLATE <missing>`` otherwise surfaces a raw
        psycopg ``template database "<name>" does not exist`` — and because the
        clone runs from the session provisioning fixture, that cryptic message
        repeats once per collected test (one CI job saw 1120 identical errors)
        while pointing at neither the cause nor the fix. The probe reuses the same
        connection-free ``shobj_description`` read that backs
        :meth:`template_status`, so the precondition is cheap.

        Raises:
            SchemaError: If no database named *template* exists.
        """
        with self._maintenance_conn() as conn:
            exists, _comment = self._read_comment(conn, template)
        if not exists:
            raise SchemaError(
                f"Cannot clone: template database {template!r} does not exist.",
                error_code="SCHEMA_001",
                resolution_hint="Provision it first "
                "(TestDbProvisioner.provision_template() / ensure_template()), or "
                "bypass the clone by pointing the worker DB at an already-applied "
                "database.",
            )

    def clone(
        self,
        template: str,
        target: str,
        *,
        retries: int = 5,
        backoff: float = 0.25,
        sync_commit_off: bool = True,
        tablespace: str | None = None,
    ) -> CloneResult:
        """Clone *template* into *target* via ``CREATE DATABASE … WITH TEMPLATE``.

        Stray sessions on the template are terminated first; if a concurrent
        clone is mid-copy (``source database … is being accessed``) the call
        retries with a short backoff.

        Args:
            template: Source template database.
            target: Clone database name to create.
            retries: Bounded retries on "source is being accessed".
            backoff: Seconds to wait between retries (grows linearly).
            sync_commit_off: When true (default), set ``synchronous_commit = off``
                as a per-database default on the fresh clone. This is a per-database
                GUC — it affects only sessions connecting to *target*, never other
                databases on a shared cluster — so it is safe where a cluster-wide
                ``fsync=off`` is not. Ephemeral test clones do not need durable
                commits; this drops the per-commit fsync wait that dominates under
                parallel test runs on an ``fsync=on`` cluster. Applied regardless of
                which tablespace path (RAM or disk-fallback) ultimately wins.
            tablespace: When set, create the clone in this tablespace
                (``CREATE DATABASE … TABLESPACE <ram>``) — e.g. a tmpfs tablespace
                for fast RAM-backed clones. On *any* tablespace-related failure (a
                broken/absent tmpfs dir, a denied tablespace), the clone falls back
                **once** to a plain on-disk clone with a fresh retry budget, logs a
                WARNING, and records ``tablespace=None`` on the result. When
                ``None`` (default), behaviour is byte-for-byte unchanged.

        Returns:
            A :class:`CloneResult`; ``result.tablespace`` is the tablespace the
            clone actually landed in (``None`` for on-disk, including a fallback).

        Raises:
            ConfigurationError: On invalid identifiers.
            SchemaError: If cloning fails after all retries.
        """
        _validate_identifier(template)
        _validate_identifier(target)
        if tablespace is not None:
            _validate_identifier(tablespace)

        self._require_template_exists(template)

        try:
            return self._clone_with_retries(
                template,
                target,
                tablespace=tablespace,
                retries=retries,
                backoff=backoff,
                sync_commit_off=sync_commit_off,
            )
        except _TablespaceUnavailable as exc:
            # The tmpfs probe is only a cheap gate; a post-reboot tablespace passes
            # it yet fails the actual CREATE. This on-disk fallback is the real
            # safety net. One shot, with a *fresh* retry budget — a tablespace
            # failure must never exhaust the ObjectInUse backoff before disk runs.
            logger.warning(
                "Clone into tablespace %r failed (%s); falling back to an on-disk "
                "clone of %r → %r.",
                tablespace,
                exc.cause,
                template,
                target,
            )
            return self._clone_with_retries(
                template,
                target,
                tablespace=None,
                retries=retries,
                backoff=backoff,
                sync_commit_off=sync_commit_off,
            )

    def _clone_with_retries(
        self,
        template: str,
        target: str,
        *,
        tablespace: str | None,
        retries: int,
        backoff: float,
        sync_commit_off: bool,
    ) -> CloneResult:
        """Run the bounded ``ObjectInUse`` retry loop for one tablespace choice.

        ``ObjectInUse`` retries on the same tablespace (a busy template is unrelated
        to where the clone lands). ``DuplicateDatabase`` raises ``SCHEMA_001``. When
        a *tablespace* is in play, any other failure signals
        :class:`_TablespaceUnavailable` so :meth:`clone` can retry on disk; on the
        disk path (``tablespace is None``) such errors propagate unchanged.
        """
        last_err: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                with self._maintenance_conn() as conn:
                    terminate_backends(conn, template)
                    conn.execute(_clone_sql(target, template, tablespace))
                    self._set_comment(conn, target, _CLONE_PREFIX + template)
                    if sync_commit_off:
                        conn.execute(_alter_db_set_sql(target, "synchronous_commit", "off"))
                return CloneResult(
                    template=template,
                    target=target,
                    target_url=_replace_dbname(self.server_url, target),
                    tablespace=tablespace,
                )
            except psycopg.errors.ObjectInUse as e:
                last_err = e
                if attempt < retries:
                    time.sleep(backoff * attempt)
            except psycopg.errors.DuplicateDatabase as e:
                raise SchemaError(
                    f"Clone target {target!r} already exists.",
                    error_code="SCHEMA_001",
                    resolution_hint="Drop it first or choose a different target name.",
                ) from e
            except psycopg.Error as e:
                if tablespace is not None:
                    raise _TablespaceUnavailable(e) from e
                raise

        raise SchemaError(
            f"Could not clone {template!r} into {target!r} after {retries} attempts: {last_err}",
            error_code="SCHEMA_001",
            resolution_hint="The template was continuously in use; reduce clone concurrency.",
        )

    # -- teardown ----------------------------------------------------------

    def drop(self, target: str, *, force: bool = False) -> bool:
        """Drop a confiture-managed clone or template.

        Args:
            target: Database to drop.
            force: Drop even if *target* carries no confiture marker.

        Returns:
            True if a database was dropped, False if it did not exist.

        Raises:
            ConfigurationError: If *target* is not confiture-managed and not
                ``force`` (guards against fat-fingering a real database).
        """
        _validate_identifier(target)
        with self._maintenance_conn() as conn:
            exists, comment = self._read_comment(conn, target)
            if not exists:
                return False
            if not force and _managed_kind(comment) is None:
                raise ConfigurationError(
                    f"Refusing to drop {target!r}: not a confiture-managed template/clone.",
                    error_code="CONFIG_010",
                    resolution_hint="Pass --force to override (use with care).",
                )
            force_drop_database(conn, target)
        return True

    # -- discovery / cleanup ----------------------------------------------

    def list_databases(self) -> list[ManagedDatabase]:
        """Enumerate all confiture-managed databases on the server."""
        out: list[ManagedDatabase] = []
        with self._maintenance_conn() as conn:
            rows = conn.execute(
                "SELECT d.datname, shobj_description(d.oid, 'pg_database') "
                "FROM pg_database d WHERE NOT d.datistemplate"
            ).fetchall()
        for name, comment in rows:
            kind = _managed_kind(comment)
            if kind is None:
                continue
            prefix = _TEMPLATE_PREFIX if kind == "template" else _CLONE_PREFIX
            out.append(ManagedDatabase(name=name, kind=kind, detail=comment[len(prefix) :]))
        return out

    def prune(self, template: str) -> list[str]:
        """Drop every clone of *template*. Returns the dropped names.

        Use to reap clones leaked by crashed workers.
        """
        _validate_identifier(template)
        dropped: list[str] = []
        for db in self.list_databases():
            if db.kind == "clone" and db.detail == template and self.drop(db.name):
                dropped.append(db.name)
        return dropped
