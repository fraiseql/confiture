"""Unit tests for the test-db provisioner's pure logic (P2).

Identifier validation, SQL composition, and template-status classification are
testable without a database. DB-touching behaviour is integration-tested.
"""

from __future__ import annotations

import logging

import psycopg
import pytest

from confiture.core.test_db import (
    _TABLESPACE_PROBE_SQL,
    TemplateState,
    TestDbProvisioner,
    _acquire_advisory_slot,
    _advisory_key,
    _alter_db_set_sql,
    _classify_template,
    _clone_sql,
    _comment_sql,
    _create_db_sql,
    _create_tablespace_sql,
    _dbs_in_tablespace_sql,
    _drop_tablespace_sql,
    _managed_kind,
    _validate_identifier,
)
from confiture.exceptions import ConfigurationError, SchemaError


class _FakeCursor:
    def __init__(self, row: tuple | None) -> None:
        self._row = row

    def fetchone(self) -> tuple | None:
        return self._row


class _FakeConn:
    """Minimal connection stub for unit-testing query result handling.

    ``execute`` returns a cursor yielding *row*; if *raises* is set, it raises
    that exception instead (to exercise the degrade-on-error paths).
    """

    def __init__(self, row: tuple | None = None, raises: Exception | None = None) -> None:
        self._row = row
        self._raises = raises

    def __enter__(self) -> _FakeConn:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, *args: object, **kwargs: object) -> _FakeCursor:
        if self._raises is not None:
            raise self._raises
        return _FakeCursor(self._row)


class _CloneFakeConn:
    """Shared fake maintenance conn for ``clone()`` control-flow unit tests.

    The same instance is returned for every ``_maintenance_conn()`` call so state
    persists across the multiple connection-opens of successive clone attempts.
    Each ``CREATE DATABASE`` consumes one entry from *create_outcomes* (an
    exception to raise, or ``None`` to succeed) and records whether that CREATE
    carried a ``TABLESPACE`` clause. Every other statement (``terminate_backends``,
    ``COMMENT``, ``ALTER``) is accepted and succeeds.

    The existence-precondition probe in ``clone()`` reads a marker comment via the
    ``shobj_description`` SELECT; *template_exists* drives whether that probe sees a
    row (the template is present) or ``None`` (the template is missing).
    """

    def __init__(
        self, create_outcomes: list[Exception | None], *, template_exists: bool = True
    ) -> None:
        self._outcomes = list(create_outcomes)
        self.create_tablespaces: list[bool] = []
        self._template_exists = template_exists
        # Clone-concurrency slot acquire/release keys (#166); empty unless a
        # max_concurrency cap is in play.
        self.advisory_locks: list[int] = []
        self.advisory_unlocks: list[int] = []

    def __enter__(self) -> _CloneFakeConn:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, query: object, params: object = None, **kwargs: object) -> _FakeCursor:
        text = query.as_string(None) if hasattr(query, "as_string") else str(query)
        if text.startswith("CREATE DATABASE"):
            self.create_tablespaces.append("TABLESPACE" in text)
            outcome = self._outcomes.pop(0) if self._outcomes else None
            if outcome is not None:
                raise outcome
        elif "pg_try_advisory_lock" in text:
            self.advisory_locks.append(params[0])  # type: ignore[index]
            return _FakeCursor((True,))
        elif "pg_advisory_unlock" in text:
            self.advisory_unlocks.append(params[0])  # type: ignore[index]
            return _FakeCursor((True,))
        elif "shobj_description" in text:
            # clone()'s existence precondition (_read_comment).
            row = ("confiture:template:h",) if self._template_exists else None
            return _FakeCursor(row)
        return _FakeCursor(None)


class _Info:
    server_version = 170000  # ≥ 13 → force_drop uses DROP DATABASE … WITH (FORCE)


class _SetupCursor:
    def __init__(self, conn: _SetupFakeConn, text: str) -> None:
        self._conn = conn
        self._text = text

    def fetchone(self) -> tuple | None:
        if "pg_tablespace_location" in self._text:
            return (self._conn.location,) if self._conn.present else None
        if "pg_stat_file" in self._text:
            return (self._conn.usable,)
        return None

    def fetchall(self) -> list[tuple]:
        if "FROM pg_database d JOIN pg_tablespace" in self._text:
            return list(self._conn.dbs)
        return []


class _SetupFakeConn:
    """Stateful fake maintenance conn for ``setup_ram_tablespace`` unit tests.

    Models tablespace presence: a ``CREATE TABLESPACE`` flips *present* on, a
    ``DROP TABLESPACE`` flips it off, so the post-create ``tablespace_usable``
    re-check sees the freshly created tablespace. Dispatches reads by SQL text.
    """

    def __init__(
        self,
        *,
        present: bool,
        dbs: list[tuple[str, str | None]],
        location: str = "/dev/shm/ram_ts",
        usable: bool = True,
    ) -> None:
        self.present = present
        self.dbs = list(dbs)
        self.location = location
        self.usable = usable
        self.executed: list[str] = []
        self.info = _Info()

    def __enter__(self) -> _SetupFakeConn:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, query: object, params: object = None, **kwargs: object) -> _SetupCursor:
        text = query.as_string(None) if hasattr(query, "as_string") else str(query)
        self.executed.append(text)
        if text.startswith("CREATE TABLESPACE"):
            self.present = True
        elif text.startswith("DROP TABLESPACE"):
            self.present = False
        return _SetupCursor(self, text)


# ---------------------------------------------------------------------------
# Identifier validation (injection guard)
# ---------------------------------------------------------------------------


class TestValidateIdentifier:
    @pytest.mark.parametrize("name", ["t", "t_gw0", "confiture_template", "App_DB_1", "_x"])
    def test_accepts_valid(self, name: str) -> None:
        _validate_identifier(name)  # does not raise

    @pytest.mark.parametrize(
        "name",
        [
            "",
            "1abc",  # leading digit
            "a b",  # space
            'a"; DROP DATABASE postgres; --',  # injection attempt
            "a-b",  # hyphen
            "a" * 64,  # too long (>63)
            "naïve",  # non-ascii
        ],
    )
    def test_rejects_invalid(self, name: str) -> None:
        with pytest.raises(ConfigurationError):
            _validate_identifier(name)


# ---------------------------------------------------------------------------
# SQL composition — identifiers are quoted, never interpolated
# ---------------------------------------------------------------------------


class TestSqlComposition:
    def test_clone_sql_quotes_identifiers(self) -> None:
        assert (
            _clone_sql("t_gw0", "tmpl").as_string(None)
            == 'CREATE DATABASE "t_gw0" WITH TEMPLATE "tmpl"'
        )

    def test_create_db_sql(self) -> None:
        assert _create_db_sql("tmpl").as_string(None) == 'CREATE DATABASE "tmpl"'

    def test_clone_sql_without_tablespace_unchanged(self) -> None:
        # The None branch must stay byte-for-byte identical to today's output.
        assert (
            _clone_sql("t_gw0", "tmpl", tablespace=None).as_string(None)
            == 'CREATE DATABASE "t_gw0" WITH TEMPLATE "tmpl"'
        )

    def test_clone_sql_appends_tablespace(self) -> None:
        assert (
            _clone_sql("t_gw0", "tmpl", tablespace="ram_ts").as_string(None)
            == 'CREATE DATABASE "t_gw0" WITH TEMPLATE "tmpl" TABLESPACE "ram_ts"'
        )

    def test_comment_sql_quotes_name_and_literal(self) -> None:
        sql = _comment_sql("tmpl", "confiture:template:deadbeef").as_string(None)
        assert sql == "COMMENT ON DATABASE \"tmpl\" IS 'confiture:template:deadbeef'"

    def test_alter_db_set_sql_quotes_value(self) -> None:
        # The GUC value is rendered as a quoted literal ('off'), never interpolated —
        # PostgreSQL accepts a quoted string for the synchronous_commit enum GUC.
        assert (
            _alter_db_set_sql("c", "synchronous_commit", "off").as_string(None)
            == 'ALTER DATABASE "c" SET "synchronous_commit" TO \'off\''
        )

    def test_create_tablespace_sql_quotes_name_and_location(self) -> None:
        # Name is a quoted identifier; the path is a quoted literal — injection-safe.
        assert (
            _create_tablespace_sql("ram_ts", "/dev/shm/ram_ts").as_string(None)
            == "CREATE TABLESPACE \"ram_ts\" LOCATION '/dev/shm/ram_ts'"
        )

    def test_drop_tablespace_sql_quotes_name(self) -> None:
        assert _drop_tablespace_sql("ram_ts").as_string(None) == 'DROP TABLESPACE "ram_ts"'

    def test_dbs_in_tablespace_sql_shape(self) -> None:
        sql = _dbs_in_tablespace_sql()
        assert "pg_database" in sql
        assert "pg_tablespace" in sql
        assert "shobj_description" in sql
        assert "%s" in sql  # tablespace name bound as a parameter, never interpolated


# ---------------------------------------------------------------------------
# Template-status classification (pure)
# ---------------------------------------------------------------------------


class TestClassifyTemplate:
    def test_absent_when_db_missing(self) -> None:
        st = _classify_template(comment=None, current_hash="h1", exists=False)
        assert st.state is TemplateState.ABSENT

    def test_current_when_hash_matches(self) -> None:
        st = _classify_template(comment="confiture:template:h1", current_hash="h1", exists=True)
        assert st.state is TemplateState.CURRENT
        assert st.stored_hash == "h1"

    def test_stale_when_hash_differs(self) -> None:
        st = _classify_template(comment="confiture:template:OLD", current_hash="NEW", exists=True)
        assert st.state is TemplateState.STALE
        assert st.stored_hash == "OLD"

    def test_absent_when_db_exists_but_unmanaged(self) -> None:
        st = _classify_template(comment=None, current_hash="h1", exists=True)
        assert st.state is TemplateState.ABSENT


class TestManagedKind:
    def test_template(self) -> None:
        assert _managed_kind("confiture:template:abc") == "template"

    def test_clone(self) -> None:
        assert _managed_kind("confiture:clone:tmpl") == "clone"

    def test_unmanaged(self) -> None:
        assert _managed_kind(None) is None
        assert _managed_kind("some user comment") is None


# ---------------------------------------------------------------------------
# Provisioner wiring (maintenance URL derivation)
# ---------------------------------------------------------------------------


class TestProvisionerInit:
    def test_derives_maintenance_url(self) -> None:
        prov = TestDbProvisioner("postgresql://localhost/myapp")
        assert prov.maintenance_url == "postgresql://localhost/postgres"


# ---------------------------------------------------------------------------
# Tablespace usability probe (the pg_stat_file gotcha) — pure/mocked
# ---------------------------------------------------------------------------


def _prov() -> TestDbProvisioner:
    return TestDbProvisioner("postgresql://localhost/x")


class TestTablespaceProbeSql:
    def test_probe_uses_missing_ok_and_size_field(self) -> None:
        # Guards the exact #158 gotcha against regression: the probe must extract a
        # NON-NULL scalar field (.size) — `record IS NOT NULL` reads false for an
        # existing dir on Linux — and pass missing_ok (`, true`) so an absent path
        # returns NULL rather than raising.
        assert "pg_stat_file(" in _TABLESPACE_PROBE_SQL
        assert ", true)" in _TABLESPACE_PROBE_SQL
        assert ".size IS NOT NULL" in _TABLESPACE_PROBE_SQL


class TestTablespaceLocation:
    def test_none_when_no_row(self) -> None:
        # No pg_tablespace row → tablespace does not exist.
        assert _prov()._tablespace_location(_FakeConn(row=None), "nope") is None

    def test_empty_string_for_builtin(self) -> None:
        # pg_default / pg_global report an empty LOCATION (they live in the data dir).
        assert _prov()._tablespace_location(_FakeConn(row=("",)), "pg_default") == ""

    def test_returns_location_dir(self) -> None:
        assert _prov()._tablespace_location(_FakeConn(row=("/dev/shm/x",)), "x") == "/dev/shm/x"


class TestTablespaceUsableDegrade:
    def test_false_on_denied_probe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # If the probe is denied for lack of privilege, the safe answer is "don't
        # attempt RAM" — return False, never raise. The disk path is always correct.
        prov = _prov()
        boom = psycopg.errors.InsufficientPrivilege("permission denied for function pg_stat_file")
        monkeypatch.setattr(prov, "_maintenance_conn", lambda: _FakeConn(raises=boom))
        assert prov.tablespace_usable("any_tbl") is False

    def test_true_for_builtin_without_probing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # An empty LOCATION (built-in tablespace) is always usable; no fs probe needed.
        prov = _prov()
        monkeypatch.setattr(prov, "_maintenance_conn", lambda: _FakeConn(row=("",)))
        assert prov.tablespace_usable("pg_default") is True

    def test_false_when_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        prov = _prov()
        monkeypatch.setattr(prov, "_maintenance_conn", lambda: _FakeConn(row=None))
        assert prov.tablespace_usable("nope") is False


# ---------------------------------------------------------------------------
# RAM clone + one-shot disk fallback (control flow, deterministic via fakes)
# ---------------------------------------------------------------------------


class TestCloneTablespaceFallback:
    def test_falls_back_to_disk_on_tablespace_error(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        # A broken/absent tmpfs surfaces as SQLSTATE class 58 (UndefinedFile). The
        # clone must retry ONCE on disk and record tablespace=None, with a warning.
        prov = _prov()
        fake = _CloneFakeConn([psycopg.errors.UndefinedFile("could not create directory"), None])
        monkeypatch.setattr(prov, "_maintenance_conn", lambda: fake)
        with caplog.at_level(logging.WARNING):
            result = prov.clone("tmpl", "c0", tablespace="ram_ts", retries=3, backoff=0)
        assert result.tablespace is None
        assert fake.create_tablespaces == [True, False]  # RAM attempt, then disk
        assert any("falling back to an on-disk clone" in r.message for r in caplog.records)

    def test_object_in_use_retries_stay_on_tablespace(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # ObjectInUse is template contention, unrelated to the tablespace: it must
        # keep retrying WITH the tablespace, never fall back to disk.
        prov = _prov()
        oiu = psycopg.errors.ObjectInUse("source database is being accessed by other users")
        fake = _CloneFakeConn([oiu, oiu, None])
        monkeypatch.setattr(prov, "_maintenance_conn", lambda: fake)
        result = prov.clone("tmpl", "c0", tablespace="ram_ts", retries=5, backoff=0)
        assert result.tablespace == "ram_ts"
        assert fake.create_tablespaces == [True, True, True]

    def test_object_in_use_exhausted_raises_not_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A continuously-busy template exhausts retries and raises SCHEMA_001 — disk
        # would hit the same contention, so it must NOT silently fall back.
        prov = _prov()
        oiu = psycopg.errors.ObjectInUse("source database is being accessed by other users")
        fake = _CloneFakeConn([oiu, oiu])
        monkeypatch.setattr(prov, "_maintenance_conn", lambda: fake)
        with pytest.raises(SchemaError, match="after 2 attempts"):
            prov.clone("tmpl", "c0", tablespace="ram_ts", retries=2, backoff=0)
        assert fake.create_tablespaces == [True, True]  # never tried disk

    def test_duplicate_database_still_raises_schema_001(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prov = _prov()
        fake = _CloneFakeConn([psycopg.errors.DuplicateDatabase("already exists")])
        monkeypatch.setattr(prov, "_maintenance_conn", lambda: fake)
        with pytest.raises(SchemaError, match="already exists"):
            prov.clone("tmpl", "c0", tablespace="ram_ts", retries=3, backoff=0)

    def test_disk_clone_unaffected_when_tablespace_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # tablespace=None never enters the fallback path: byte-for-byte unchanged.
        prov = _prov()
        fake = _CloneFakeConn([None])
        monkeypatch.setattr(prov, "_maintenance_conn", lambda: fake)
        result = prov.clone("tmpl", "c0", retries=3, backoff=0)
        assert result.tablespace is None
        assert fake.create_tablespaces == [False]


# ---------------------------------------------------------------------------
# Missing-template precondition (#160): fail once, actionably, before cloning
# ---------------------------------------------------------------------------


class TestCloneMissingTemplate:
    def test_raises_actionable_error_when_template_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # An absent template must fail the cheap precondition BEFORE any CREATE
        # DATABASE is attempted — never the raw psycopg "template database does not
        # exist" once per collected test (#160).
        prov = _prov()
        fake = _CloneFakeConn([], template_exists=False)
        monkeypatch.setattr(prov, "_maintenance_conn", lambda: fake)
        with pytest.raises(SchemaError, match="does not exist"):
            prov.clone("missing_tmpl", "c0", retries=3, backoff=0)
        assert fake.create_tablespaces == []  # failed fast, no clone attempted

    def test_error_names_template_and_points_at_provisioning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prov = _prov()
        fake = _CloneFakeConn([], template_exists=False)
        monkeypatch.setattr(prov, "_maintenance_conn", lambda: fake)
        with pytest.raises(SchemaError) as exc_info:
            prov.clone("missing_tmpl", "c0", retries=3, backoff=0)
        err = exc_info.value
        assert "missing_tmpl" in str(err)
        assert err.error_code == "SCHEMA_001"
        assert "provision" in (err.resolution_hint or "").lower()

    def test_present_template_clones_normally(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The precondition is transparent on the happy path: a present template
        # clones exactly as before.
        prov = _prov()
        fake = _CloneFakeConn([None], template_exists=True)
        monkeypatch.setattr(prov, "_maintenance_conn", lambda: fake)
        result = prov.clone("tmpl", "c0", retries=3, backoff=0)
        assert result.target == "c0"
        assert fake.create_tablespaces == [False]


# ---------------------------------------------------------------------------
# Bounded clone concurrency (#166) — advisory-slot acquire, fsync probe, gating
# ---------------------------------------------------------------------------


class _SlotFakeConn:
    """Fake maintenance conn driving ``_acquire_advisory_slot``.

    Each ``pg_try_advisory_lock`` consumes one boolean from *try_results* (default
    True once exhausted); acquired/released keys are recorded for assertions.
    """

    def __init__(self, try_results: list[bool]) -> None:
        self._results = list(try_results)
        self.acquired: list[int] = []
        self.released: list[int] = []

    def __enter__(self) -> _SlotFakeConn:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, query: object, params: object = None, **kwargs: object) -> _FakeCursor:
        text = str(query)
        if "pg_try_advisory_lock" in text:
            got = self._results.pop(0) if self._results else True
            if got:
                self.acquired.append(params[0])  # type: ignore[index]
            return _FakeCursor((got,))
        if "pg_advisory_unlock" in text:
            self.released.append(params[0])  # type: ignore[index]
            return _FakeCursor((True,))
        return _FakeCursor(None)


class TestAcquireAdvisorySlot:
    def test_returns_first_free_slot(self) -> None:
        conn = _SlotFakeConn([True])
        assert _acquire_advisory_slot(conn, [10, 20, 30], poll=0) == 10
        assert conn.acquired == [10]

    def test_skips_busy_slots(self) -> None:
        # First slot held, second free → second is taken (no extra acquire recorded).
        conn = _SlotFakeConn([False, True])
        assert _acquire_advisory_slot(conn, [10, 20], poll=0) == 20
        assert conn.acquired == [20]

    def test_spins_until_a_slot_frees(self) -> None:
        # All slots busy for two scans, then one frees: the scan loops, never raises.
        conn = _SlotFakeConn([False, False, True])
        assert _acquire_advisory_slot(conn, [10], poll=0) == 10
        assert conn.acquired == [10]


class TestClusterFsyncOn:
    def test_true_when_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        prov = _prov()
        monkeypatch.setattr(prov, "_maintenance_conn", lambda: _FakeConn(row=("on",)))
        assert prov.cluster_fsync_on() is True

    def test_false_when_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        prov = _prov()
        monkeypatch.setattr(prov, "_maintenance_conn", lambda: _FakeConn(row=("off",)))
        assert prov.cluster_fsync_on() is False

    def test_normalises_case_and_whitespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        prov = _prov()
        monkeypatch.setattr(prov, "_maintenance_conn", lambda: _FakeConn(row=(" On ",)))
        assert prov.cluster_fsync_on() is True

    def test_degrades_to_throttle_on_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # If fsync can't be read, throttle (True) — always correct, just slower.
        prov = _prov()
        boom = psycopg.OperationalError("connection refused")
        monkeypatch.setattr(prov, "_maintenance_conn", lambda: _FakeConn(raises=boom))
        assert prov.cluster_fsync_on() is True


class TestCloneMaxConcurrency:
    def test_no_cap_takes_no_slot(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # max_concurrency=None (default) is byte-for-byte unchanged: no advisory lock.
        prov = _prov()
        fake = _CloneFakeConn([None])
        monkeypatch.setattr(prov, "_maintenance_conn", lambda: fake)
        prov.clone("tmpl", "c0", retries=3, backoff=0)
        assert fake.advisory_locks == []
        assert fake.advisory_unlocks == []

    def test_cap_below_one_is_unbounded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        prov = _prov()
        fake = _CloneFakeConn([None])
        monkeypatch.setattr(prov, "_maintenance_conn", lambda: fake)
        prov.clone("tmpl", "c0", retries=3, backoff=0, max_concurrency=0)
        assert fake.advisory_locks == []

    def test_cap_acquires_and_releases_one_slot(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A cap takes the first slot (index 0), holds it across the clone, releases it.
        prov = _prov()
        fake = _CloneFakeConn([None])
        monkeypatch.setattr(prov, "_maintenance_conn", lambda: fake)
        prov.clone("tmpl", "c0", retries=3, backoff=0, max_concurrency=2)
        slot0 = _advisory_key("clone:tmpl:0")
        assert fake.advisory_locks == [slot0]
        assert fake.advisory_unlocks == [slot0]

    def test_slot_released_even_when_clone_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The slot must be released on the failure path too (finally), or workers wedge.
        prov = _prov()
        fake = _CloneFakeConn([psycopg.errors.DuplicateDatabase("already exists")])
        monkeypatch.setattr(prov, "_maintenance_conn", lambda: fake)
        with pytest.raises(SchemaError):
            prov.clone("tmpl", "c0", retries=3, backoff=0, max_concurrency=2)
        assert fake.advisory_unlocks == [_advisory_key("clone:tmpl:0")]


# ---------------------------------------------------------------------------
# ram-setup orchestration (managed-only guard, drop+create) — mocked conn
# ---------------------------------------------------------------------------


class TestSetupRamTablespace:
    def test_rejects_invalid_tablespace_name(self) -> None:
        with pytest.raises(ConfigurationError):
            _prov().setup_ram_tablespace("bad name", "/dev/shm/x", owner="postgres")

    def test_dir_not_prepared_signals_action_required(self) -> None:
        # Guided mode: nothing dropped or created, just the action-required signal.
        result = _prov().setup_ram_tablespace(
            "ram_ts", "/dev/shm/ram_ts", owner="postgres", dir_prepared=False
        )
        assert result.action_required is True
        assert result.recreated is False
        assert result.dropped_databases == []

    def test_refuses_unmanaged_db_without_force(self, monkeypatch: pytest.MonkeyPatch) -> None:
        prov = _prov()
        fake = _SetupFakeConn(present=True, dbs=[("appdb", None)])
        monkeypatch.setattr(prov, "_maintenance_conn", lambda: fake)
        with pytest.raises(ConfigurationError, match="non-confiture-managed"):
            prov.setup_ram_tablespace("ram_ts", "/dev/shm/ram_ts", owner="postgres")
        # Nothing destructive ran before the guard fired.
        assert not any(
            t.startswith(("DROP TABLESPACE", "CREATE TABLESPACE")) for t in fake.executed
        )

    def test_force_drops_unmanaged_and_recreates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        prov = _prov()
        fake = _SetupFakeConn(
            present=True,
            dbs=[("appdb", None), ("ram_ts_db_gw0", "confiture:clone:tmpl")],
        )
        monkeypatch.setattr(prov, "_maintenance_conn", lambda: fake)
        result = prov.setup_ram_tablespace(
            "ram_ts", "/dev/shm/ram_ts", owner="postgres", force=True
        )
        assert result.recreated is True
        assert result.action_required is False
        assert set(result.dropped_databases) == {"appdb", "ram_ts_db_gw0"}
        assert any(t.startswith("DROP TABLESPACE") for t in fake.executed)
        assert any(t.startswith("CREATE TABLESPACE") for t in fake.executed)

    def test_managed_clones_dropped_without_force(self, monkeypatch: pytest.MonkeyPatch) -> None:
        prov = _prov()
        fake = _SetupFakeConn(present=True, dbs=[("ram_ts_db_gw0", "confiture:clone:tmpl")])
        monkeypatch.setattr(prov, "_maintenance_conn", lambda: fake)
        result = prov.setup_ram_tablespace("ram_ts", "/dev/shm/ram_ts", owner="postgres")
        assert result.dropped_databases == ["ram_ts_db_gw0"]
        assert result.recreated is True

    def test_fresh_create_when_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        prov = _prov()
        fake = _SetupFakeConn(present=False, dbs=[])
        monkeypatch.setattr(prov, "_maintenance_conn", lambda: fake)
        result = prov.setup_ram_tablespace("ram_ts", "/dev/shm/ram_ts", owner="postgres")
        assert result.recreated is False  # nothing pre-existed
        assert result.dropped_databases == []
        assert any(t.startswith("CREATE TABLESPACE") for t in fake.executed)
        assert not any(t.startswith("DROP TABLESPACE") for t in fake.executed)

    def test_raises_when_created_tablespace_not_usable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prov = _prov()
        fake = _SetupFakeConn(present=False, dbs=[], usable=False)
        monkeypatch.setattr(prov, "_maintenance_conn", lambda: fake)
        with pytest.raises(SchemaError, match="not usable"):
            prov.setup_ram_tablespace("ram_ts", "/dev/shm/ram_ts", owner="postgres")
