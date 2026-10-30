"""``DatabaseConfig.from_url`` opens the connection the URL names, on a real server (#793)."""

import psycopg

from confiture.config.environment import DatabaseConfig
from confiture.core.connection import create_connection

PROBE = "SELECT current_database(), current_user, current_setting('search_path')"


def test_the_config_connects_where_the_url_does(fresh_database: str) -> None:
    """Every part of the URL reaches the connection, query parameters included.

    Before #793 the parsed parts were rebuilt into a new connection string and
    ``?options=`` was dropped (folded into the database name).
    """
    separator = "&" if "?" in fresh_database else "?"
    url = f"{fresh_database}{separator}options=-c%20search_path%3Dprobe"

    with psycopg.connect(url) as direct:
        expected = direct.execute(PROBE).fetchone()
    with create_connection(DatabaseConfig.from_url(url)) as conn:
        got = conn.execute(PROBE).fetchone()

    assert expected is not None
    assert expected[2] == "probe"
    assert got == expected
