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

from confiture.core.restorer import DatabaseRestorer, RestoreOptions
from confiture.core.seed_applier import apply_seed_files
from confiture.core.temp_database import (
    _maintenance_url,
    _replace_dbname,
    force_drop_database,
    terminate_backends,
)
from confiture.exceptions import ConfigurationError, SchemaError

# Marker comments stamped on confiture-managed databases (see module docstring).
_TEMPLATE_PREFIX = "confiture:template:"
_CLONE_PREFIX = "confiture:clone:"
_MANAGED_PREFIX = "confiture:"

# PostgreSQL identifier: leading letter/underscore, then letters/digits/underscore,
# 1–63 ASCII chars. Quoting still happens via Identifier; this is defence in depth.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


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
    """Result of a template clone."""

    template: str
    target: str
    target_url: str

    def to_dict(self) -> dict:
        return {"template": self.template, "target": self.target, "target_url": self.target_url}


@dataclass
class ManagedDatabase:
    """A confiture-managed database discovered by :meth:`list_databases`."""

    name: str
    kind: str  # "template" | "clone"
    detail: str  # the hash (template) or source template name (clone)

    def to_dict(self) -> dict:
        return {"name": self.name, "kind": self.kind, "detail": self.detail}


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


def _clone_sql(target: str, template: str) -> psycopg.sql.Composed:
    return SQL("CREATE DATABASE {} WITH TEMPLATE {}").format(
        Identifier(target), Identifier(template)
    )


def _create_db_sql(name: str) -> psycopg.sql.Composed:
    return SQL("CREATE DATABASE {}").format(Identifier(name))


def _comment_sql(name: str, value: str) -> psycopg.sql.Composed:
    return SQL("COMMENT ON DATABASE {} IS {}").format(Identifier(name), Literal(value))


def _managed_kind(comment: str | None) -> str | None:
    """Return ``"template"``/``"clone"`` for a managed comment, else ``None``."""
    if not comment:
        return None
    if comment.startswith(_TEMPLATE_PREFIX):
        return "template"
    if comment.startswith(_CLONE_PREFIX):
        return "clone"
    return None


def _classify_template(comment: str | None, current_hash: str | None, exists: bool) -> TemplateStatus:
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
            with psycopg.connect(template_url, autocommit=True) as c:
                c.execute(schema_sql, prepare=False)  # type: ignore[arg-type]
            if seed_files:
                apply_seed_files(template_url, seed_files)

        with self._maintenance_conn() as conn:
            self._set_comment(conn, template, _TEMPLATE_PREFIX + schema_hash)

        return TemplateStatus(template, TemplateState.CURRENT, schema_hash, schema_hash)

    def _restore_into(
        self, target: str, artifact: Path, restorer: DatabaseRestorer | None
    ) -> None:
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

    def clone(
        self, template: str, target: str, *, retries: int = 5, backoff: float = 0.25
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

        Returns:
            A :class:`CloneResult` with the clone's connection URL.

        Raises:
            ConfigurationError: On invalid identifiers.
            SchemaError: If cloning fails after all retries.
        """
        _validate_identifier(template)
        _validate_identifier(target)

        last_err: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                with self._maintenance_conn() as conn:
                    terminate_backends(conn, template)
                    conn.execute(_clone_sql(target, template))
                    self._set_comment(conn, target, _CLONE_PREFIX + template)
                return CloneResult(
                    template=template,
                    target=target,
                    target_url=_replace_dbname(self.server_url, target),
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

        raise SchemaError(
            f"Could not clone {template!r} into {target!r} after {retries} attempts: "
            f"{last_err}",
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
