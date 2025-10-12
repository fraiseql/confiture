"""Test data integrity and constraints

Tests that verify database constraints work correctly.
"""

import psycopg
import pytest


def test_user_email_unique_constraint(test_db):
    """Test that duplicate emails are rejected."""
    with psycopg.connect(test_db) as conn, conn.cursor() as cur:
        # First insert should work
        cur.execute("""
                INSERT INTO users (email, display_name)
                VALUES ('unique@example.com', 'User 1')
            """)
        conn.commit()

        # Duplicate email should fail
        with pytest.raises(psycopg.errors.UniqueViolation):
            cur.execute("""
                    INSERT INTO users (email, display_name)
                    VALUES ('unique@example.com', 'User 2')
                """)


def test_user_email_format_constraint(test_db):
    """Test that email format is validated."""
    with psycopg.connect(test_db) as conn, conn.cursor() as cur:
        # Valid email should work
        cur.execute("""
                INSERT INTO users (email, display_name)
                VALUES ('valid@example.com', 'Valid User')
            """)
        conn.commit()

        # Invalid email should fail
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute("""
                    INSERT INTO users (email, display_name)
                    VALUES ('not-an-email', 'Invalid User')
                """)


def test_project_owner_foreign_key(test_db):
    """Test that projects require valid owner."""
    with psycopg.connect(test_db) as conn, conn.cursor() as cur:
        # Create valid user
        cur.execute("""
                INSERT INTO users (email, display_name)
                VALUES ('owner@example.com', 'Owner')
                RETURNING id
            """)
        user_id = cur.fetchone()[0]

        # Valid owner should work
        cur.execute(
            """
                INSERT INTO projects (owner_id, name)
                VALUES (%s, 'Valid Project')
            """,
            (user_id,),
        )
        conn.commit()

        # Invalid owner should fail
        import uuid

        fake_id = str(uuid.uuid4())
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cur.execute(
                """
                    INSERT INTO projects (owner_id, name)
                    VALUES (%s, 'Invalid Project')
                """,
                (fake_id,),
            )


def test_task_project_foreign_key(test_db):
    """Test that tasks require valid project."""
    with psycopg.connect(test_db) as conn, conn.cursor() as cur:
        # Create user and project
        cur.execute("""
                INSERT INTO users (email, display_name)
                VALUES ('task_user@example.com', 'Task User')
                RETURNING id
            """)
        user_id = cur.fetchone()[0]

        cur.execute(
            """
                INSERT INTO projects (owner_id, name)
                VALUES (%s, 'Task Project')
                RETURNING id
            """,
            (user_id,),
        )
        project_id = cur.fetchone()[0]

        # Valid project should work
        cur.execute(
            """
                INSERT INTO tasks (project_id, title)
                VALUES (%s, 'Valid Task')
            """,
            (project_id,),
        )
        conn.commit()

        # Invalid project should fail
        import uuid

        fake_id = str(uuid.uuid4())
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cur.execute(
                """
                    INSERT INTO tasks (project_id, title)
                    VALUES (%s, 'Invalid Task')
                """,
                (fake_id,),
            )


def test_updated_at_trigger(test_db):
    """Test that updated_at is automatically updated."""
    with psycopg.connect(test_db) as conn, conn.cursor() as cur:
        # Create user
        cur.execute("""
                INSERT INTO users (email, display_name)
                VALUES ('trigger_test@example.com', 'Trigger Test')
                RETURNING id, updated_at
            """)
        user_id, original_updated_at = cur.fetchone()
        conn.commit()

        # Wait a moment
        import time

        time.sleep(0.1)

        # Update user
        cur.execute(
            """
                UPDATE users
                SET display_name = 'Updated Name'
                WHERE id = %s
                RETURNING updated_at
            """,
            (user_id,),
        )
        new_updated_at = cur.fetchone()[0]
        conn.commit()

        # updated_at should have changed
        assert new_updated_at > original_updated_at


def test_task_completed_at_trigger(test_db):
    """Test that completed_at is set when task marked done."""
    with psycopg.connect(test_db) as conn, conn.cursor() as cur:
        # Create user and project
        cur.execute("""
                INSERT INTO users (email, display_name)
                VALUES ('complete_test@example.com', 'Complete Test')
                RETURNING id
            """)
        user_id = cur.fetchone()[0]

        cur.execute(
            """
                INSERT INTO projects (owner_id, name)
                VALUES (%s, 'Complete Project')
                RETURNING id
            """,
            (user_id,),
        )
        project_id = cur.fetchone()[0]

        # Create task
        cur.execute(
            """
                INSERT INTO tasks (project_id, title, status)
                VALUES (%s, 'Test Task', 'todo')
                RETURNING id, completed_at
            """,
            (project_id,),
        )
        task_id, completed_at = cur.fetchone()
        conn.commit()

        # completed_at should be NULL initially
        assert completed_at is None

        # Mark as done
        cur.execute(
            """
                UPDATE tasks
                SET status = 'done'
                WHERE id = %s
                RETURNING completed_at
            """,
            (task_id,),
        )
        new_completed_at = cur.fetchone()[0]
        conn.commit()

        # completed_at should now be set
        assert new_completed_at is not None


def test_cascade_delete_user_projects(test_db):
    """Test that deleting user cascades to projects."""
    with psycopg.connect(test_db) as conn, conn.cursor() as cur:
        # Create user with project
        cur.execute("""
                INSERT INTO users (email, display_name)
                VALUES ('cascade_test@example.com', 'Cascade Test')
                RETURNING id
            """)
        user_id = cur.fetchone()[0]

        cur.execute(
            """
                INSERT INTO projects (owner_id, name)
                VALUES (%s, 'Will Be Deleted')
                RETURNING id
            """,
            (user_id,),
        )
        project_id = cur.fetchone()[0]
        conn.commit()

        # Delete user
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()

        # Project should be deleted too
        cur.execute("SELECT COUNT(*) FROM projects WHERE id = %s", (project_id,))
        count = cur.fetchone()[0]
        assert count == 0


def test_analytics_views_work(test_db):
    """Test that analytics views return valid data."""
    with psycopg.connect(test_db) as conn, conn.cursor() as cur:
        # Create test data
        cur.execute("""
                INSERT INTO users (email, display_name)
                VALUES ('view_test@example.com', 'View Test')
                RETURNING id
            """)
        user_id = cur.fetchone()[0]

        cur.execute(
            """
                INSERT INTO projects (owner_id, name)
                VALUES (%s, 'View Project')
                RETURNING id
            """,
            (user_id,),
        )
        project_id = cur.fetchone()[0]

        cur.execute(
            """
                INSERT INTO tasks (project_id, title, status)
                VALUES
                    (%s, 'Task 1', 'todo'),
                    (%s, 'Task 2', 'done')
            """,
            (project_id, project_id),
        )
        conn.commit()

        # Test user_project_summary view
        cur.execute(
            """
                SELECT total_projects, total_tasks, completed_tasks
                FROM user_project_summary
                WHERE user_id = %s
            """,
            (user_id,),
        )
        result = cur.fetchone()

        assert result is not None
        assert result[0] == 1  # total_projects
        assert result[1] == 2  # total_tasks
        assert result[2] == 1  # completed_tasks

        # Test project_task_stats view
        cur.execute(
            """
                SELECT total_tasks, todo_tasks, done_tasks
                FROM project_task_stats
                WHERE project_id = %s
            """,
            (project_id,),
        )
        result = cur.fetchone()

        assert result is not None
        assert result[0] == 2  # total_tasks
        assert result[1] == 1  # todo_tasks
        assert result[2] == 1  # done_tasks


# Pytest fixtures
@pytest.fixture
def test_db():
    """Provide test database connection string."""
    import os

    host = os.getenv("PGHOST", "localhost")
    port = os.getenv("PGPORT", "5432")
    database = os.getenv("PGDATABASE", "confiture_ci")
    user = os.getenv("PGUSER", "postgres")
    password = os.getenv("PGPASSWORD", "postgres")

    return f"postgresql://{user}:{password}@{host}:{port}/{database}"
