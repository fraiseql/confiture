-- Migration: golden
-- Version: <version>

-- confiture:tier destructive
DROP VIEW IF EXISTS user_project_summary;

-- confiture:tier destructive
DROP VIEW IF EXISTS project_task_stats;

-- confiture:tier destructive
DROP VIEW IF EXISTS active_user_dashboard;

-- confiture:irreversible no rollback derived for ADD_TRIGGER users.update_users_updated_at

-- confiture:irreversible no rollback derived for ADD_TRIGGER tasks.update_tasks_updated_at

-- confiture:irreversible no rollback derived for ADD_TRIGGER tasks.set_task_completed_at_trigger

-- confiture:irreversible no rollback derived for ADD_TRIGGER projects.update_projects_updated_at

-- confiture:irreversible no rollback derived for ADD_TRIGGER projects.prevent_delete_project_with_tasks_trigger

-- confiture:tier destructive
DROP FUNCTION IF EXISTS public.update_updated_at_column();

-- confiture:tier destructive
DROP FUNCTION IF EXISTS public.set_task_completed_at();

-- confiture:tier destructive
DROP FUNCTION IF EXISTS public.prevent_delete_project_with_tasks();

-- confiture:irreversible no rollback derived for ADD_EXTENSION uuid-ossp

-- confiture:irreversible no rollback derived for ADD_EXTENSION pgcrypto

-- confiture:irreversible no rollback derived for ADD_EXTENSION pg_trgm

-- confiture:irreversible no rollback derived for ADD_EXTENSION btree_gist

-- confiture:tier irreversible
DROP TABLE users;

-- confiture:tier irreversible
DROP TABLE tasks;

-- confiture:tier irreversible
DROP TABLE projects;
