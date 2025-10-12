"""Test schema building from DDL files

Tests that verify the schema can be built correctly from DDL files.
"""

import psycopg


def test_schema_build_creates_tables(test_db):
    """Test that schema build creates all expected tables."""
    with psycopg.connect(test_db) as conn, conn.cursor() as cur:
        # Check tables exist
        cur.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name
            """)
        tables = {row[0] for row in cur.fetchall()}

        assert "users" in tables
        assert "projects" in tables
        assert "tasks" in tables


def test_schema_build_creates_indexes(test_db):
    """Test that schema build creates all performance indexes."""
    with psycopg.connect(test_db) as conn, conn.cursor() as cur:
        # Check indexes exist
        cur.execute("""
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public'
                ORDER BY indexname
            """)
        indexes = {row[0] for row in cur.fetchall()}

        # Users indexes
        assert "idx_users_email" in indexes
        assert "idx_users_created_at" in indexes

        # Projects indexes
        assert "idx_projects_owner_id" in indexes
        assert "idx_projects_status" in indexes

        # Tasks indexes
        assert "idx_tasks_project_id" in indexes
        assert "idx_tasks_assigned_to" in indexes


def test_schema_build_creates_views(test_db):
    """Test that schema build creates all analytics views."""
    with psycopg.connect(test_db) as conn, conn.cursor() as cur:
        # Check views exist
        cur.execute("""
                SELECT table_name
                FROM information_schema.views
                WHERE table_schema = 'public'
                ORDER BY table_name
            """)
        views = {row[0] for row in cur.fetchall()}

        assert "user_project_summary" in views
        assert "project_task_stats" in views
        assert "active_user_dashboard" in views


def test_schema_build_creates_triggers(test_db):
    """Test that schema build creates all triggers."""
    with psycopg.connect(test_db) as conn, conn.cursor() as cur:
        # Check triggers exist
        cur.execute("""
                SELECT trigger_name
                FROM information_schema.triggers
                WHERE trigger_schema = 'public'
                ORDER BY trigger_name
            """)
        triggers = {row[0] for row in cur.fetchall()}

        assert "update_users_updated_at" in triggers
        assert "update_projects_updated_at" in triggers
        assert "update_tasks_updated_at" in triggers


def test_users_table_structure(test_db):
    """Test users table has correct columns and constraints."""
    with psycopg.connect(test_db) as conn, conn.cursor() as cur:
        # Check columns
        cur.execute("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = 'users'
                ORDER BY ordinal_position
            """)
        columns = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

        assert "id" in columns
        assert "email" in columns
        assert "display_name" in columns
        assert "bio" in columns
        assert "created_at" in columns
        assert "updated_at" in columns

        # Check NOT NULL constraints
        assert columns["email"][1] == "NO"  # NOT NULL
        assert columns["display_name"][1] == "NO"  # NOT NULL


def test_projects_table_structure(test_db):
    """Test projects table has correct columns and constraints."""
    with psycopg.connect(test_db) as conn, conn.cursor() as cur:
        # Check columns
        cur.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = 'projects'
                ORDER BY ordinal_position
            """)
        columns = {row[0]: row[1] for row in cur.fetchall()}

        assert "id" in columns
        assert "owner_id" in columns
        assert "name" in columns
        assert "description" in columns
        assert "status" in columns
        assert "created_at" in columns
        assert "updated_at" in columns


def test_tasks_table_structure(test_db):
    """Test tasks table has correct columns and constraints."""
    with psycopg.connect(test_db) as conn, conn.cursor() as cur:
        # Check columns
        cur.execute("""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = 'tasks'
                ORDER BY ordinal_position
            """)
        columns = {row[0]: row[1] for row in cur.fetchall()}

        assert "id" in columns
        assert "project_id" in columns
        assert "assigned_to" in columns
        assert "title" in columns
        assert "description" in columns
        assert "priority" in columns
        assert "status" in columns
        assert "due_date" in columns
        assert "completed_at" in columns
        assert "created_at" in columns
        assert "updated_at" in columns


def test_foreign_key_relationships(test_db):
    """Test that foreign key relationships are created correctly."""
    with psycopg.connect(test_db) as conn, conn.cursor() as cur:
        # Check foreign keys
        cur.execute("""
                SELECT
                    tc.table_name,
                    kcu.column_name,
                    ccu.table_name AS foreign_table_name,
                    ccu.column_name AS foreign_column_name
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_name = kcu.constraint_name
                  AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage AS ccu
                  ON ccu.constraint_name = tc.constraint_name
                  AND ccu.table_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_schema = 'public'
            """)
        foreign_keys = cur.fetchall()

        # Projects.owner_id -> Users.id
        assert any(
            fk[0] == "projects" and fk[1] == "owner_id" and fk[2] == "users" for fk in foreign_keys
        )

        # Tasks.project_id -> Projects.id
        assert any(
            fk[0] == "tasks" and fk[1] == "project_id" and fk[2] == "projects"
            for fk in foreign_keys
        )

        # Tasks.assigned_to -> Users.id
        assert any(
            fk[0] == "tasks" and fk[1] == "assigned_to" and fk[2] == "users" for fk in foreign_keys
        )
