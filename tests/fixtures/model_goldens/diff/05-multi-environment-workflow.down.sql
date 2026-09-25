-- Migration: golden
-- Version: <version>

-- confiture:tier destructive
DROP TRIGGER IF EXISTS update_users_updated_at ON users;

-- confiture:tier destructive
DROP TRIGGER IF EXISTS update_tasks_updated_at ON tasks;

-- confiture:tier destructive
DROP TRIGGER IF EXISTS set_task_completed_at_trigger ON tasks;

-- confiture:tier destructive
DROP TRIGGER IF EXISTS update_projects_updated_at ON projects;

-- confiture:tier destructive
DROP TRIGGER IF EXISTS prevent_delete_project_with_tasks_trigger ON projects;

-- confiture:tier destructive
DROP VIEW IF EXISTS user_project_summary;

-- confiture:tier destructive
DROP VIEW IF EXISTS project_task_stats;

-- confiture:tier destructive
DROP VIEW IF EXISTS active_user_dashboard;

-- confiture:tier destructive
DROP FUNCTION IF EXISTS public.update_updated_at_column();

-- confiture:tier destructive
DROP FUNCTION IF EXISTS public.set_task_completed_at();

-- confiture:tier destructive
DROP FUNCTION IF EXISTS public.prevent_delete_project_with_tasks();

-- confiture:tier irreversible
DROP TABLE tasks;

-- confiture:tier irreversible
DROP TABLE projects;

-- confiture:tier irreversible
DROP TABLE users;

-- confiture:tier destructive
DROP EXTENSION IF EXISTS "uuid-ossp";

-- confiture:tier destructive
DROP EXTENSION IF EXISTS pgcrypto;

-- confiture:tier destructive
DROP EXTENSION IF EXISTS pg_trgm;

-- confiture:tier destructive
DROP EXTENSION IF EXISTS btree_gist;
