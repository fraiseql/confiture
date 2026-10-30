"""``DatabaseConfig.from_url`` reads a URL the way libpq does (#793).

libpq's own parser (``psycopg.conninfo.conninfo_to_dict``) is the reference: every
row is checked against what it resolves, and a key the URL leaves out stays
``None`` so libpq fills it at connect time, as it would for the URL itself.
"""

import pytest
from psycopg.conninfo import conninfo_to_dict

from confiture.config.environment import DatabaseConfig
from confiture.core.connection import dsn_from_config

#: URL → (host, port, database, user, password, parameters).
URLS = {
    "postgresql:///postgres?host=/var/run/postgresql": (
        "/var/run/postgresql",
        None,
        "postgres",
        None,
        None,
        {},
    ),
    "postgresql:///app": (None, None, "app", None, None, {}),
    "postgresql://u@/app?host=/tmp": ("/tmp", None, "app", "u", None, {}),
    "postgresql://user@host/app": ("host", None, "app", "user", None, {}),
    "postgresql://u:p%40ss@h/app": ("h", None, "app", "u", "p@ss", {}),
    "postgres://app:secret@db.internal:6543/prod": (
        "db.internal",
        6543,
        "prod",
        "app",
        "secret",
        {},
    ),
    "postgresql://h1:5432,h2:5433/db?target_session_attrs=read-write": (
        "h1,h2",
        "5432,5433",
        "db",
        None,
        None,
        {"target_session_attrs": "read-write"},
    ),
    "postgresql://[::1]:5433/db": ("::1", 5433, "db", None, None, {}),
    "postgresql://h/app?sslmode=verify-full&options=-c%20search_path%3Dapp": (
        "h",
        None,
        "app",
        None,
        None,
        {"sslmode": "verify-full", "options": "-c search_path=app"},
    ),
    "postgresql://": (None, None, None, None, None, {}),
}


@pytest.mark.parametrize(("url", "expected"), URLS.items())
def test_each_part_is_what_libpq_reads(url: str, expected: tuple) -> None:
    config = DatabaseConfig.from_url(url)

    assert (
        config.host,
        config.port,
        config.database,
        config.user,
        config.password,
        config.parameters,
    ) == expected


@pytest.mark.parametrize("url", URLS)
def test_the_conninfo_is_the_urls(url: str) -> None:
    assert conninfo_to_dict(DatabaseConfig.from_url(url).conninfo()) == conninfo_to_dict(url)


@pytest.mark.parametrize("url", URLS)
def test_a_connection_from_the_config_is_the_urls(url: str) -> None:
    """``create_connection(config)`` opens what ``psycopg.connect(url)`` would."""
    dsn = dsn_from_config(DatabaseConfig.from_url(url))

    assert conninfo_to_dict(dsn) == conninfo_to_dict(url)


def test_a_direct_config_keeps_its_defaults() -> None:
    config = DatabaseConfig()

    assert conninfo_to_dict(dsn_from_config(config)) == {
        "host": "localhost",
        "port": "5432",
        "dbname": "postgres",
        "user": "postgres",
        "password": "",
    }


@pytest.mark.parametrize(
    "url",
    [
        "mysql://u:hunter2@h/db",
        "host=h password=hunter2",
        "postgresql://u:hunter2@h/db?sslmode",
        "postgresql://u:hunter2@h/db?nonsense=1",
    ],
)
def test_one_libpq_refuses_is_refused_without_its_password(url: str) -> None:
    with pytest.raises(ValueError, match="Invalid PostgreSQL URL") as raised:
        DatabaseConfig.from_url(url)

    assert "hunter2" not in str(raised.value)


def test_a_sync_label_names_a_part_libpq_fills_as_its_default() -> None:
    from confiture.core.syncer import ProductionSyncer

    syncer = ProductionSyncer(
        DatabaseConfig.from_url("postgresql:///app?host=/tmp"),
        DatabaseConfig(host="h", port=6543, database="t"),
    )

    assert (syncer.source.label, syncer.target.label) == ("/tmp:default/app", "h:6543/t")
