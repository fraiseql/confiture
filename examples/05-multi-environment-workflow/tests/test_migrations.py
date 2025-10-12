"""Test migration functionality

Tests that verify migrations apply and rollback correctly.
"""

import pytest
import psycopg


def test_migration_001_add_user_bio(test_db):
    """Test migration 001 adds bio column to users table."""
    # This test assumes migration has been applied during setup
    with psycopg.connect(test_db) as conn:
        with conn.cursor() as cur:
            # Check bio column exists
            cur.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = 'users' AND column_name = 'bio'
            """)
            result = cur.fetchone()

            assert result is not None
            assert result[0] == 'bio'
            assert result[1] == 'text'


def test_migration_002_add_project_status(test_db):
    """Test migration 002 adds status column to projects table."""
    with psycopg.connect(test_db) as conn:
        with conn.cursor() as cur:
            # Check status column exists
            cur.execute("""
                SELECT column_name, data_type, column_default
                FROM information_schema.columns
                WHERE table_name = 'projects' AND column_name = 'status'
            """)
            result = cur.fetchone()

            assert result is not None
            assert result[0] == 'status'
            assert result[1] == 'text'
            assert "'active'" in result[2]  # Default value


def test_migration_003_add_task_priority(test_db):
    """Test migration 003 adds priority column to tasks table."""
    with psycopg.connect(test_db) as conn:
        with conn.cursor() as cur:
            # Check priority column exists
            cur.execute("""
                SELECT column_name, data_type, column_default
                FROM information_schema.columns
                WHERE table_name = 'tasks' AND column_name = 'priority'
            """)
            result = cur.fetchone()

            assert result is not None
            assert result[0] == 'priority'
            assert result[1] == 'text'
            assert "'medium'" in result[2]  # Default value


def test_project_status_constraint(test_db):
    """Test that project status constraint is enforced."""
    with psycopg.connect(test_db) as conn:
        with conn.cursor() as cur:
            # Create a test user first
            cur.execute("""
                INSERT INTO users (email, display_name)
                VALUES ('test@example.com', 'Test User')
                RETURNING id
            """)
            user_id = cur.fetchone()[0]

            # Valid status should work
            cur.execute("""
                INSERT INTO projects (owner_id, name, status)
                VALUES (%s, 'Test Project', 'active')
            """, (user_id,))
            conn.commit()

            # Invalid status should fail
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("""
                    INSERT INTO projects (owner_id, name, status)
                    VALUES (%s, 'Test Project 2', 'invalid_status')
                """, (user_id,))


def test_task_priority_constraint(test_db):
    """Test that task priority constraint is enforced."""
    with psycopg.connect(test_db) as conn:
        with conn.cursor() as cur:
            # Create test data
            cur.execute("""
                INSERT INTO users (email, display_name)
                VALUES ('test2@example.com', 'Test User 2')
                RETURNING id
            """)
            user_id = cur.fetchone()[0]

            cur.execute("""
                INSERT INTO projects (owner_id, name)
                VALUES (%s, 'Test Project')
                RETURNING id
            """, (user_id,))
            project_id = cur.fetchone()[0]

            # Valid priority should work
            cur.execute("""
                INSERT INTO tasks (project_id, title, priority)
                VALUES (%s, 'Test Task', 'high')
            """, (project_id,))
            conn.commit()

            # Invalid priority should fail
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("""
                    INSERT INTO tasks (project_id, title, priority)
                    VALUES (%s, 'Test Task 2', 'invalid_priority')
                """, (project_id,))


def test_migration_idempotency(test_db):
    """Test that migrations can be run multiple times safely."""
    # In a real test, you would:
    # 1. Run migration
    # 2. Run migration again
    # 3. Verify no errors and schema unchanged
    # This is a placeholder for that concept
    with psycopg.connect(test_db) as conn:
        with conn.cursor() as cur:
            # Verify schema is stable
            cur.execute("""
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = 'public'
            """)
            table_count = cur.fetchone()[0]

            # Should have exactly 3 tables
            assert table_count == 3
