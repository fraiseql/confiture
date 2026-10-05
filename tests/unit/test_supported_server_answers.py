"""What confiture answers for each supported server, and with no server at all.

PostgreSQL 16 is the oldest server confiture supports. A row that once depended on
the server's version now has two readings: a server was read (16, 17 or 18 — every
supported server answers the same), or none was (``None``, the filesystem-only
default, which keeps the conservative reading). These answers are what the
preflight payload and the online runner are built from; they are pinned here.
"""

from unittest.mock import MagicMock, patch

import pytest

from confiture.core.change_set import classify_statements
from confiture.core.change_set.models import tier_for_add_column
from confiture.core.expand_contract import plan
from confiture.core.lock_profile import Duration, LockLevel, LockProfile, profile_for_kind
from confiture.core.risk_tier import RiskTier
from confiture.core.schema_facts import SchemaFacts
from confiture.core.temp_database import TempDatabase, force_drop_database
from confiture.sql_text import rendered

SUPPORTED = (16, 17, 18)

_FAST_DEFAULT = LockProfile(
    lock=LockLevel.ACCESS_EXCLUSIVE,
    rewrites_table=False,
    blocks_reads=True,
    blocks_writes=True,
    duration=Duration.METADATA,
    since_version=11,
    note="PostgreSQL 11+ stores the default in the catalog instead of rewriting",
)
_DEFAULT_UNKNOWN_SERVER = LockProfile(
    lock=LockLevel.ACCESS_EXCLUSIVE,
    rewrites_table=True,
    blocks_reads=True,
    blocks_writes=True,
    duration=Duration.MINUTES_PLUS,
    since_version=11,
    note=(
        "rewrites the whole table below PostgreSQL 11; the server version is "
        "unknown here, so the older reading stands"
    ),
)
_NOT_NULL_MAY_SKIP_SCAN = LockProfile(
    lock=LockLevel.ACCESS_EXCLUSIVE,
    rewrites_table=False,
    blocks_reads=True,
    blocks_writes=True,
    duration=Duration.SECONDS,
    since_version=12,
    note=(
        "PostgreSQL 12+ skips the scan when a valid CHECK (col IS NOT NULL) "
        "already exists; without one it still scans"
    ),
)
_NOT_NULL_PROVEN = LockProfile(
    lock=LockLevel.ACCESS_EXCLUSIVE,
    rewrites_table=False,
    blocks_reads=True,
    blocks_writes=True,
    duration=Duration.METADATA,
    since_version=12,
    note="a validated CHECK (col IS NOT NULL) proves it; no scan",
)
_NOT_NULL_SCAN = LockProfile(
    lock=LockLevel.ACCESS_EXCLUSIVE,
    rewrites_table=False,
    blocks_reads=True,
    blocks_writes=True,
    duration=Duration.MINUTES_PLUS,
    since_version=12,
    note="scans every row to prove no NULL is present",
)
_METADATA_ALTER = LockProfile(
    lock=LockLevel.ACCESS_EXCLUSIVE,
    rewrites_table=False,
    blocks_reads=True,
    blocks_writes=True,
    duration=Duration.METADATA,
)

# (kind, facts) → (answer with a server, answer with none)
_VERSION_DEPENDENT = {
    ("add_column", (("has_default", True), ("nullable", False))): (
        _FAST_DEFAULT,
        _DEFAULT_UNKNOWN_SERVER,
    ),
    ("add_column", (("has_default", True), ("nullable", True))): (
        _FAST_DEFAULT,
        _DEFAULT_UNKNOWN_SERVER,
    ),
    ("add_column", (("has_default", False), ("nullable", False))): (
        _METADATA_ALTER,
        _METADATA_ALTER,
    ),
    ("set_not_null", ()): (_NOT_NULL_MAY_SKIP_SCAN, _NOT_NULL_SCAN),
    ("set_not_null", (("proven_by_check", True),)): (_NOT_NULL_PROVEN, _NOT_NULL_SCAN),
}


@pytest.mark.parametrize(("kind", "facts"), list(_VERSION_DEPENDENT))
@pytest.mark.parametrize("server", SUPPORTED)
def test_every_supported_server_takes_the_favourable_reading(
    kind: str, facts: tuple[tuple[str, bool], ...], server: int
) -> None:
    expected, _ = _VERSION_DEPENDENT[kind, facts]
    assert profile_for_kind(kind, server_version=server, **dict(facts)) == expected


@pytest.mark.parametrize(("kind", "facts"), list(_VERSION_DEPENDENT))
def test_no_server_keeps_the_conservative_reading(
    kind: str, facts: tuple[tuple[str, bool], ...]
) -> None:
    _, expected = _VERSION_DEPENDENT[kind, facts]
    assert profile_for_kind(kind, server_version=None, **dict(facts)) == expected


@pytest.mark.parametrize(
    ("server", "expected"),
    [(None, RiskTier.LOCK_RISKY), *((server, RiskTier.ADDITIVE) for server in SUPPORTED)],
)
def test_a_not_null_column_with_a_default_is_additive_once_a_server_is_read(
    server: int | None, expected: RiskTier
) -> None:
    assert tier_for_add_column(nullable=False, has_default=True, server_version=server) is expected
    facts = SchemaFacts(server_version=server) if server else None
    (entry,) = classify_statements(
        "ALTER TABLE t ADD COLUMN c int NOT NULL DEFAULT 0;", facts=facts
    )
    assert entry.tier is expected


@pytest.mark.parametrize("server", [None, *SUPPORTED])
def test_a_not_null_column_without_a_default_is_a_lock_risk_on_every_server(
    server: int | None,
) -> None:
    assert (
        tier_for_add_column(nullable=False, has_default=False, server_version=server)
        is RiskTier.LOCK_RISKY
    )


def test_the_online_plan_is_one_plan_on_every_supported_server() -> None:
    sql = (
        "ALTER TABLE orders ADD COLUMN status text NOT NULL DEFAULT 'new';"
        "ALTER TABLE orders ADD CONSTRAINT orders_total_positive CHECK (total >= 0);"
        "ALTER TABLE orders ALTER COLUMN total TYPE bigint;"
    )
    plans = {
        server: [p.to_dict() for p in plan(sql, server_version=server)] for server in SUPPORTED
    }
    assert plans[16] == plans[17] == plans[18]
    assert plans[16]


@pytest.mark.parametrize("server_version_num", [160004, 170002, 180004])
def test_a_database_is_dropped_with_force(server_version_num: int) -> None:
    conn = MagicMock()
    conn.info.server_version = server_version_num

    force_drop_database(conn, "doomed")

    (call,) = conn.execute.call_args_list
    assert rendered(call.args[0]) == 'DROP DATABASE IF EXISTS "doomed" WITH (FORCE)'


@pytest.mark.parametrize("server_version_num", [160004, 170002, 180004])
@patch("confiture.core.temp_database.psycopg.connect")
def test_a_temporary_database_is_dropped_with_force(
    mock_connect: MagicMock, server_version_num: int
) -> None:
    conn = MagicMock()
    conn.closed = False
    conn.info.server_version = server_version_num
    mock_connect.return_value = conn

    temp = TempDatabase("postgresql://localhost/app")
    temp.__enter__()
    temp.__exit__(None, None, None)

    sent = [rendered(c.args[0]) for c in conn.execute.call_args_list]
    assert [s for s in sent if s.startswith("DROP DATABASE")] == [
        f'DROP DATABASE IF EXISTS "{temp._db_name}" WITH (FORCE)'
    ]
