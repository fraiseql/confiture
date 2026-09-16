"""Integration tests for production data syncer."""

from confiture.core.syncer import (
    ProductionSyncer,
    SyncConfig,
    TableSelection,
)


def test_get_all_tables(source_db, target_db, source_config, target_config):
    """Should list all tables in source database."""
    # Create test tables in source
    with source_db.cursor() as cur:
        cur.execute("""
            CREATE TABLE users (id SERIAL PRIMARY KEY, name TEXT);
            CREATE TABLE posts (id SERIAL PRIMARY KEY, title TEXT);
            CREATE TABLE comments (id SERIAL PRIMARY KEY, content TEXT);
        """)

    with ProductionSyncer(source_config, target_config) as syncer:
        tables = syncer.get_all_tables()

        assert "users" in tables
        assert "posts" in tables
        assert "comments" in tables


def test_select_tables_include(source_db, target_db, source_config, target_config):
    """Should select only included tables."""
    # Create test tables
    with source_db.cursor() as cur:
        cur.execute("""
            CREATE TABLE users (id SERIAL PRIMARY KEY, name TEXT);
            CREATE TABLE posts (id SERIAL PRIMARY KEY, title TEXT);
            CREATE TABLE comments (id SERIAL PRIMARY KEY, content TEXT);
        """)

    with ProductionSyncer(source_config, target_config) as syncer:
        selection = TableSelection(include=["users", "posts"])
        tables = syncer.select_tables(selection)

        assert "users" in tables
        assert "posts" in tables
        assert "comments" not in tables


def test_select_tables_exclude(source_db, target_db, source_config, target_config):
    """Should exclude specified tables."""
    # Create test tables
    with source_db.cursor() as cur:
        cur.execute("""
            CREATE TABLE users (id SERIAL PRIMARY KEY, name TEXT);
            CREATE TABLE posts (id SERIAL PRIMARY KEY, title TEXT);
            CREATE TABLE comments (id SERIAL PRIMARY KEY, content TEXT);
        """)

    with ProductionSyncer(source_config, target_config) as syncer:
        selection = TableSelection(exclude=["comments"])
        tables = syncer.select_tables(selection)

        assert "users" in tables
        assert "posts" in tables
        assert "comments" not in tables


def test_sync_single_table(source_db, target_db, source_config, target_config):
    """Should sync data from source to target table."""
    # Create table in both databases
    with source_db.cursor() as cur:
        cur.execute("""
            CREATE TABLE users (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL
            )
        """)

    with target_db.cursor() as cur:
        cur.execute("""
            CREATE TABLE users (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL
            )
        """)

    # Insert test data in source
    with source_db.cursor() as cur:
        cur.execute("""
            INSERT INTO users (name, email) VALUES
            ('Alice', 'alice@example.com'),
            ('Bob', 'bob@example.com'),
            ('Charlie', 'charlie@example.com')
        """)

    # Sync data
    with ProductionSyncer(source_config, target_config) as syncer:
        rows_synced = syncer.sync_table("users")

    assert rows_synced == 3

    # Verify data in target
    with target_db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM users")
        count = cur.fetchone()[0]
        assert count == 3

        cur.execute("SELECT name, email FROM users ORDER BY name")
        rows = cur.fetchall()
        assert len(rows) == 3
        assert rows[0] == ("Alice", "alice@example.com")


def test_sync_large_table(source_db, target_db, source_config, target_config):
    """Should efficiently sync large tables."""
    # Create table
    with source_db.cursor() as cur:
        cur.execute("""
            CREATE TABLE events (
                id SERIAL PRIMARY KEY,
                event_name TEXT NOT NULL,
                event_data JSONB
            )
        """)

    with target_db.cursor() as cur:
        cur.execute("""
            CREATE TABLE events (
                id SERIAL PRIMARY KEY,
                event_name TEXT NOT NULL,
                event_data JSONB
            )
        """)

    # Insert 10,000 rows
    with source_db.cursor() as cur:
        cur.execute("""
            INSERT INTO events (event_name, event_data)
            SELECT
                'event_' || i,
                ('{"data": "value_' || i || '"}')::jsonb
            FROM generate_series(1, 10000) AS i
        """)

    # Sync data
    with ProductionSyncer(source_config, target_config) as syncer:
        rows_synced = syncer.sync_table("events", batch_size=1000)

    assert rows_synced == 10000

    # Verify count in target
    with target_db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM events")
        count = cur.fetchone()[0]
        assert count == 10000


def test_sync_multiple_tables(source_db, target_db, source_config, target_config):
    """Should sync multiple tables at once."""
    # Create tables
    with source_db.cursor() as cur:
        cur.execute("""
            CREATE TABLE users (id SERIAL PRIMARY KEY, name TEXT);
            CREATE TABLE posts (id SERIAL PRIMARY KEY, title TEXT);
        """)

    with target_db.cursor() as cur:
        cur.execute("""
            CREATE TABLE users (id SERIAL PRIMARY KEY, name TEXT);
            CREATE TABLE posts (id SERIAL PRIMARY KEY, title TEXT);
        """)

    # Insert data
    with source_db.cursor() as cur:
        cur.execute("""
            INSERT INTO users (name) VALUES ('Alice'), ('Bob');
            INSERT INTO posts (title) VALUES ('Post 1'), ('Post 2'), ('Post 3');
        """)

    # Sync with config
    with ProductionSyncer(source_config, target_config) as syncer:
        config = SyncConfig(
            tables=TableSelection(include=["users", "posts"]),
            batch_size=10000,
        )
        results = syncer.sync(config)

    assert results["users"] == 2
    assert results["posts"] == 3

    # Verify data
    with target_db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM users")
        assert cur.fetchone()[0] == 2

        cur.execute("SELECT COUNT(*) FROM posts")
        assert cur.fetchone()[0] == 3


def test_sync_truncates_target(source_db, target_db, source_config, target_config):
    """Should truncate target table before syncing."""
    # Create table
    with source_db.cursor() as cur:
        cur.execute("""
            CREATE TABLE users (id SERIAL PRIMARY KEY, name TEXT)
        """)

    with target_db.cursor() as cur:
        cur.execute("""
            CREATE TABLE users (id SERIAL PRIMARY KEY, name TEXT)
        """)

    # Insert old data in target
    with target_db.cursor() as cur:
        cur.execute("""
            INSERT INTO users (name) VALUES ('OldUser1'), ('OldUser2')
        """)

    # Insert new data in source
    with source_db.cursor() as cur:
        cur.execute("""
            INSERT INTO users (name) VALUES ('NewUser')
        """)

    # Sync should replace old data
    with ProductionSyncer(source_config, target_config) as syncer:
        rows_synced = syncer.sync_table("users")

    assert rows_synced == 1

    # Verify only new data exists
    with target_db.cursor() as cur:
        cur.execute("SELECT name FROM users")
        rows = cur.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "NewUser"


def test_sync_verifies_row_count(source_db, target_db, source_config, target_config):
    """Should verify row count after sync."""
    # Create table
    with source_db.cursor() as cur:
        cur.execute("""
            CREATE TABLE users (id SERIAL PRIMARY KEY, name TEXT)
        """)

    with target_db.cursor() as cur:
        cur.execute("""
            CREATE TABLE users (id SERIAL PRIMARY KEY, name TEXT)
        """)

    # Insert data
    with source_db.cursor() as cur:
        cur.execute("""
            INSERT INTO users (name) VALUES ('Alice'), ('Bob'), ('Charlie')
        """)

    # Sync and verify count is returned
    with ProductionSyncer(source_config, target_config) as syncer:
        rows_synced = syncer.sync_table("users")

    assert rows_synced == 3


def test_sync_keeps_rows_of_tables_that_reference_each_other(
    source_db, target_db, source_config, target_config
):
    """A child table copied before its parent still holds its rows afterwards.

    Each target table used to be truncated with CASCADE immediately before being
    copied, and tables are copied in the order ``select_tables`` returns them —
    alphabetical. ``posts`` sorts before ``users``, so ``posts`` was copied, and
    then ``TRUNCATE users CASCADE`` emptied it again. The sync reported both
    tables at their full row counts and exited 0, because the count it reports is
    what it inserted, not what the target holds at the end.

    On a nine-table schema this emptied five of eight tables. The failure needs
    only a foreign key to reproduce, which is why no existing test saw it: the
    multi-table cases all sync tables that do not reference one another.
    """
    ddl = """
        CREATE TABLE users (id INT PRIMARY KEY, name TEXT);
        CREATE TABLE posts (id INT PRIMARY KEY, user_id INT REFERENCES users(id), title TEXT);
    """
    for db in (source_db, target_db):
        with db.cursor() as cur:
            cur.execute(ddl)

    with source_db.cursor() as cur:
        cur.execute("""
            INSERT INTO users (id, name) VALUES (1, 'Alice'), (2, 'Bob');
            INSERT INTO posts (id, user_id, title) VALUES (1, 1, 'A'), (2, 1, 'B'), (3, 2, 'C');
        """)

    with ProductionSyncer(source_config, target_config) as syncer:
        results = syncer.sync(config=SyncConfig(tables=TableSelection(include=["users", "posts"])))

    assert results == {"posts": 3, "users": 2}

    # The assertion that matters: what the target actually holds once the whole
    # sync has finished, not what each table reported on its way past.
    with target_db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM posts")
        assert cur.fetchone()[0] == 3, "posts was emptied by a later table's TRUNCATE CASCADE"
        cur.execute("SELECT COUNT(*) FROM users")
        assert cur.fetchone()[0] == 2
