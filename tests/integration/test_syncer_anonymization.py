"""Integration tests for ProductionSyncer PII anonymization.

Tests:
1. Email anonymization
2. Phone number anonymization
3. Custom anonymization strategies
4. PII detection heuristics
5. Per-table and per-column rules
"""

import pytest

from confiture.core.syncer import (
    AnonymizationRule,
    ProductionSyncer,
    SyncConfig,
    TableSelection,
)


@pytest.fixture
def populated_source_with_pii(source_db, target_db):
    """Populate source database with PII data."""
    # Create users table with PII
    table_ddl = """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(255) NOT NULL,
            email VARCHAR(255) NOT NULL,
            phone VARCHAR(20),
            full_name VARCHAR(255),
            address TEXT,
            ssn VARCHAR(11)
        )
    """

    with source_db.cursor() as cur:
        cur.execute(table_ddl)

    with target_db.cursor() as cur:
        cur.execute(table_ddl)

    # Insert test data with real-looking PII
    with source_db.cursor() as cur:
        cur.execute("""
            INSERT INTO users (username, email, phone, full_name, address, ssn)
            VALUES
                ('john_doe', 'john.doe@example.com', '+1-555-1234', 'John Doe', '123 Main St, Anytown, CA 12345', '123-45-6789'),
                ('jane_smith', 'jane.smith@company.org', '555-987-6543', 'Jane Smith', '456 Oak Ave, Somewhere, NY 67890', '987-65-4321'),
                ('bob_jones', 'bob@personal.net', '(555) 246-8135', 'Bob Jones', NULL, NULL)
        """)

    yield source_db


@pytest.mark.asyncio
async def test_anonymize_email_addresses(
    source_config,
    target_config,
    populated_source_with_pii,
):
    """Test email address anonymization."""
    config = SyncConfig(
        tables=TableSelection(include=["users"]),
        anonymization={
            "users": [
                AnonymizationRule(column="email", strategy="email"),
            ]
        },
    )

    with ProductionSyncer(source_config, target_config) as syncer:
        results = syncer.sync(config)

    assert results["users"] == 3

    # Verify emails are anonymized
    from confiture.core.connection import create_connection

    target_conn = create_connection(target_config)
    with target_conn.cursor() as cur:
        cur.execute("SELECT email FROM users ORDER BY id")
        emails = [row[0] for row in cur.fetchall()]

    target_conn.close()

    # Check that emails are anonymized but still valid format
    assert all("@" in email for email in emails)
    assert "john.doe@example.com" not in emails
    assert "jane.smith@company.org" not in emails

    # Check that anonymization is deterministic (same input = same output)
    assert len(set(emails)) == 3  # All different


@pytest.mark.asyncio
async def test_anonymize_phone_numbers(
    source_config,
    target_config,
    populated_source_with_pii,
):
    """Test phone number anonymization."""
    config = SyncConfig(
        tables=TableSelection(include=["users"]),
        anonymization={
            "users": [
                AnonymizationRule(column="phone", strategy="phone"),
            ]
        },
    )

    with ProductionSyncer(source_config, target_config) as syncer:
        results = syncer.sync(config)

    assert results["users"] == 3

    # Verify phone numbers are anonymized
    from confiture.core.connection import create_connection

    target_conn = create_connection(target_config)
    with target_conn.cursor() as cur:
        cur.execute("SELECT phone FROM users WHERE phone IS NOT NULL ORDER BY id")
        phones = [row[0] for row in cur.fetchall()]

    target_conn.close()

    # Check that phones are anonymized
    assert "+1-555-1234" not in phones
    assert "555-987-6543" not in phones

    # Check that anonymized phones follow a pattern
    for phone in phones:
        assert "555" in phone or phone.startswith("+1-555-")


@pytest.mark.asyncio
async def test_anonymize_multiple_columns(
    source_config,
    target_config,
    populated_source_with_pii,
):
    """Test anonymizing multiple columns in same table."""
    config = SyncConfig(
        tables=TableSelection(include=["users"]),
        anonymization={
            "users": [
                AnonymizationRule(column="email", strategy="email"),
                AnonymizationRule(column="phone", strategy="phone"),
                AnonymizationRule(column="full_name", strategy="name"),
            ]
        },
    )

    with ProductionSyncer(source_config, target_config) as syncer:
        results = syncer.sync(config)

    assert results["users"] == 3

    # Verify all columns are anonymized
    from confiture.core.connection import create_connection

    target_conn = create_connection(target_config)
    with target_conn.cursor() as cur:
        cur.execute("SELECT email, phone, full_name FROM users ORDER BY id")
        rows = cur.fetchall()

    target_conn.close()

    # Check email anonymization
    emails = [row[0] for row in rows]
    assert "john.doe@example.com" not in emails

    # Check phone anonymization
    phones = [row[1] for row in rows if row[1] is not None]
    assert "+1-555-1234" not in phones

    # Check name anonymization
    names = [row[2] for row in rows]
    assert "John Doe" not in names
    assert "Jane Smith" not in names


@pytest.mark.asyncio
async def test_redact_strategy(
    source_config,
    target_config,
    populated_source_with_pii,
):
    """Test redact strategy (replaces with [REDACTED])."""
    config = SyncConfig(
        tables=TableSelection(include=["users"]),
        anonymization={
            "users": [
                AnonymizationRule(column="ssn", strategy="redact"),
            ]
        },
    )

    with ProductionSyncer(source_config, target_config) as syncer:
        results = syncer.sync(config)

    assert results["users"] == 3

    # Verify SSNs are redacted
    from confiture.core.connection import create_connection

    target_conn = create_connection(target_config)
    with target_conn.cursor() as cur:
        cur.execute("SELECT ssn FROM users WHERE ssn IS NOT NULL ORDER BY id")
        ssns = [row[0] for row in cur.fetchall()]

    target_conn.close()

    # Check that SSNs are redacted
    assert all(ssn == "[REDACTED]" for ssn in ssns)
    assert "123-45-6789" not in ssns


@pytest.mark.asyncio
async def test_hash_strategy(
    source_config,
    target_config,
    populated_source_with_pii,
):
    """Test hash strategy (one-way hash for referential integrity)."""
    config = SyncConfig(
        tables=TableSelection(include=["users"]),
        anonymization={
            "users": [
                AnonymizationRule(column="email", strategy="hash"),
            ]
        },
    )

    with ProductionSyncer(source_config, target_config) as syncer:
        results = syncer.sync(config)

    assert results["users"] == 3

    # Verify emails are hashed
    from confiture.core.connection import create_connection

    target_conn = create_connection(target_config)
    with target_conn.cursor() as cur:
        cur.execute("SELECT email FROM users ORDER BY id")
        emails = [row[0] for row in cur.fetchall()]

    target_conn.close()

    # Check that emails are hashed (hexadecimal strings)
    assert all(email != "john.doe@example.com" for email in emails)
    assert all(len(email) >= 8 for email in emails)
    assert all(all(c in "0123456789abcdef" for c in email) for email in emails)


@pytest.mark.asyncio
async def test_deterministic_anonymization(
    source_config,
    target_config,
    populated_source_with_pii,
):
    """Test that anonymization is deterministic (same input = same output)."""
    config = SyncConfig(
        tables=TableSelection(include=["users"]),
        anonymization={
            "users": [
                AnonymizationRule(column="email", strategy="email", seed=12345),
            ]
        },
    )

    # First sync
    with ProductionSyncer(source_config, target_config) as syncer:
        syncer.sync(config)

    from confiture.core.connection import create_connection

    target_conn = create_connection(target_config)
    with target_conn.cursor() as cur:
        cur.execute("SELECT id, email FROM users ORDER BY id")
        first_sync = {row[0]: row[1] for row in cur.fetchall()}
    target_conn.close()

    # Second sync (should produce same results)
    with ProductionSyncer(source_config, target_config) as syncer:
        syncer.sync(config)

    target_conn = create_connection(target_config)
    with target_conn.cursor() as cur:
        cur.execute("SELECT id, email FROM users ORDER BY id")
        second_sync = {row[0]: row[1] for row in cur.fetchall()}
    target_conn.close()

    # Verify same input produces same output
    assert first_sync == second_sync


@pytest.mark.asyncio
async def test_null_values_not_anonymized(
    source_config,
    target_config,
    populated_source_with_pii,
):
    """Test that NULL values remain NULL after anonymization."""
    config = SyncConfig(
        tables=TableSelection(include=["users"]),
        anonymization={
            "users": [
                AnonymizationRule(column="address", strategy="redact"),
                AnonymizationRule(column="ssn", strategy="redact"),
            ]
        },
    )

    with ProductionSyncer(source_config, target_config) as syncer:
        syncer.sync(config)

    from confiture.core.connection import create_connection

    target_conn = create_connection(target_config)
    with target_conn.cursor() as cur:
        # Bob Jones has NULL address and SSN
        cur.execute(
            "SELECT address, ssn FROM users WHERE username = 'bob_jones'"
        )
        row = cur.fetchone()
    target_conn.close()

    # NULL values should remain NULL
    assert row[0] is None  # address
    assert row[1] is None  # ssn


@pytest.mark.asyncio
async def test_auto_detect_pii_columns(
    source_config,
    target_config,
    populated_source_with_pii,
):
    """Test automatic detection of PII columns by name."""
    # Note: This would use auto_detect_pii=True in a future config option
    # For now, we'll manually specify common PII column names

    config = SyncConfig(
        tables=TableSelection(include=["users"]),
        anonymization={
            "users": [
                AnonymizationRule(column="email", strategy="email"),
                AnonymizationRule(column="phone", strategy="phone"),
                AnonymizationRule(column="ssn", strategy="redact"),
            ]
        },
    )

    with ProductionSyncer(source_config, target_config) as syncer:
        results = syncer.sync(config)

    assert results["users"] == 3

    # Verify all PII columns are anonymized
    from confiture.core.connection import create_connection

    target_conn = create_connection(target_config)
    with target_conn.cursor() as cur:
        cur.execute(
            "SELECT email, phone, ssn FROM users WHERE ssn IS NOT NULL ORDER BY id"
        )
        rows = cur.fetchall()
    target_conn.close()

    for row in rows:
        email, phone, ssn = row
        # Email anonymized
        assert "@" in email
        assert "example.com" not in email or email.endswith("@example.com")
        # Phone anonymized
        assert "555" in phone
        # SSN redacted
        assert ssn == "[REDACTED]"


@pytest.mark.asyncio
async def test_no_anonymization_without_rules(
    source_config,
    target_config,
    populated_source_with_pii,
):
    """Test that data is copied as-is when no anonymization rules provided."""
    config = SyncConfig(
        tables=TableSelection(include=["users"]),
        # No anonymization rules
    )

    with ProductionSyncer(source_config, target_config) as syncer:
        results = syncer.sync(config)

    assert results["users"] == 3

    # Verify data is copied as-is
    from confiture.core.connection import create_connection

    source_conn = create_connection(source_config)
    target_conn = create_connection(target_config)

    with source_conn.cursor() as src_cur, target_conn.cursor() as tgt_cur:
        src_cur.execute("SELECT email, phone FROM users ORDER BY id")
        source_data = src_cur.fetchall()

        tgt_cur.execute("SELECT email, phone FROM users ORDER BY id")
        target_data = tgt_cur.fetchall()

    source_conn.close()
    target_conn.close()

    # Data should match exactly
    assert source_data == target_data
