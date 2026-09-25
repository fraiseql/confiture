-- Migration: golden
-- Version: <version>

-- confiture:tier lock_risky
CREATE TABLE IF NOT EXISTS projects (
    id UUID NOT NULL DEFAULT uuid_generate_v4(),
    owner_id UUID NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY (owner_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT projects_owner_name_unique UNIQUE (owner_id, name),
    CONSTRAINT projects_name_length CHECK (char_length(name) >= 3 AND char_length(name) <= 100),
    CONSTRAINT projects_status_valid CHECK (status IN ('active', 'archived', 'deleted'))
);
CREATE INDEX IF NOT EXISTS idx_projects_owner_id ON projects (owner_id);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects (status) WHERE status <> 'deleted';
CREATE INDEX IF NOT EXISTS idx_projects_owner_status ON projects (owner_id, status);
CREATE INDEX IF NOT EXISTS idx_projects_created_at ON projects (created_at DESC);

-- confiture:tier lock_risky
CREATE TABLE IF NOT EXISTS tasks (
    id UUID NOT NULL DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL,
    assigned_to UUID,
    title TEXT NOT NULL,
    description TEXT,
    priority TEXT NOT NULL DEFAULT 'medium',
    status TEXT NOT NULL DEFAULT 'todo',
    due_date TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
    FOREIGN KEY (assigned_to) REFERENCES users (id) ON DELETE SET NULL,
    CONSTRAINT tasks_title_length CHECK (char_length(title) >= 3 AND char_length(title) <= 200),
    CONSTRAINT tasks_priority_valid CHECK (priority IN ('low', 'medium', 'high', 'urgent')),
    CONSTRAINT tasks_status_valid CHECK (status IN ('todo', 'in_progress', 'done', 'cancelled')),
    CONSTRAINT tasks_completed_when_done CHECK ((status = 'done' AND completed_at IS NOT NULL) OR (status <> 'done' AND completed_at IS NULL))
);
CREATE INDEX IF NOT EXISTS idx_tasks_project_id ON tasks (project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_assigned_to ON tasks (assigned_to) WHERE assigned_to IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks (priority);
CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks (due_date) WHERE due_date IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tasks_project_status ON tasks (project_id, status);
CREATE INDEX IF NOT EXISTS idx_tasks_assignee_status ON tasks (assigned_to, status) WHERE assigned_to IS NOT NULL;

-- confiture:tier lock_risky
CREATE TABLE IF NOT EXISTS users (
    id UUID NOT NULL DEFAULT uuid_generate_v4(),
    email TEXT NOT NULL,
    display_name TEXT NOT NULL,
    bio TEXT,
    avatar_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    UNIQUE (email),
    CONSTRAINT users_email_format CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'),
    CONSTRAINT users_display_name_length CHECK (char_length(display_name) >= 2),
    CONSTRAINT users_bio_length CHECK (char_length(bio) <= 1000)
);
CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);
CREATE INDEX IF NOT EXISTS idx_users_created_at ON users (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_users_display_name_trgm ON users USING gin (display_name gin_trgm_ops);

-- confiture:tier additive
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- confiture:tier additive
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- confiture:tier additive
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- confiture:tier additive
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- confiture:tier reversible
CREATE OR REPLACE FUNCTION public.prevent_delete_project_with_tasks() RETURNS trigger AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM tasks
        WHERE project_id = OLD.id
        AND status NOT IN ('done', 'cancelled')
    ) THEN
        RAISE EXCEPTION 'Cannot delete project with active tasks. Complete or cancel tasks first.';
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

-- confiture:tier reversible
CREATE OR REPLACE FUNCTION public.set_task_completed_at() RETURNS trigger AS $$
BEGIN
    IF NEW.status = 'done' AND OLD.status != 'done' THEN
        NEW.completed_at = NOW();
    ELSIF NEW.status != 'done' AND OLD.status = 'done' THEN
        NEW.completed_at = NULL;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- confiture:tier reversible
CREATE OR REPLACE FUNCTION public.update_updated_at_column() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- confiture:tier additive
CREATE OR REPLACE TRIGGER prevent_delete_project_with_tasks_trigger BEFORE DELETE ON projects FOR EACH ROW EXECUTE PROCEDURE prevent_delete_project_with_tasks();

-- confiture:tier additive
CREATE OR REPLACE TRIGGER update_projects_updated_at BEFORE UPDATE ON projects FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column();

-- confiture:tier additive
CREATE OR REPLACE TRIGGER set_task_completed_at_trigger BEFORE UPDATE ON tasks FOR EACH ROW WHEN (old.status IS DISTINCT FROM new.status) EXECUTE PROCEDURE set_task_completed_at();

-- confiture:tier additive
CREATE OR REPLACE TRIGGER update_tasks_updated_at BEFORE UPDATE ON tasks FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column();

-- confiture:tier additive
CREATE OR REPLACE TRIGGER update_users_updated_at BEFORE UPDATE ON users FOR EACH ROW EXECUTE PROCEDURE update_updated_at_column();

-- confiture:tier reversible
CREATE OR REPLACE VIEW active_user_dashboard AS SELECT u.id, u.email, u.display_name, count(DISTINCT t.id) FILTER (WHERE t.assigned_to = u.id AND t.status = 'todo') AS my_todo_tasks, count(DISTINCT t.id) FILTER (WHERE t.assigned_to = u.id AND t.status = 'in_progress') AS my_active_tasks, count(DISTINCT t.id) FILTER (WHERE t.assigned_to = u.id AND t.due_date < now() AND t.status NOT IN ('done', 'cancelled')) AS my_overdue_tasks, count(DISTINCT p.id) FILTER (WHERE p.owner_id = u.id AND p.status = 'active') AS my_active_projects, max(t.updated_at) FILTER (WHERE t.assigned_to = u.id) AS last_task_activity FROM users AS u LEFT JOIN tasks AS t ON t.assigned_to = u.id OR t.project_id IN (SELECT id FROM projects WHERE owner_id = u.id) LEFT JOIN projects AS p ON p.owner_id = u.id GROUP BY u.id, u.email, u.display_name;

-- confiture:tier reversible
CREATE OR REPLACE VIEW project_task_stats AS SELECT p.id AS project_id, p.name AS project_name, p.status AS project_status, u.email AS owner_email, count(t.id) AS total_tasks, count(t.id) FILTER (WHERE t.status = 'todo') AS todo_tasks, count(t.id) FILTER (WHERE t.status = 'in_progress') AS in_progress_tasks, count(t.id) FILTER (WHERE t.status = 'done') AS done_tasks, count(t.id) FILTER (WHERE t.priority = 'urgent') AS urgent_tasks, count(t.id) FILTER (WHERE t.due_date < now() AND t.status <> 'done') AS overdue_tasks, min(t.created_at) AS first_task_created, max(t.updated_at) AS last_task_updated FROM projects AS p LEFT JOIN users AS u ON u.id = p.owner_id LEFT JOIN tasks AS t ON t.project_id = p.id GROUP BY p.id, p.name, p.status, u.email;

-- confiture:tier reversible
CREATE OR REPLACE VIEW user_project_summary AS SELECT u.id AS user_id, u.email, u.display_name, count(DISTINCT p.id) AS total_projects, count(DISTINCT p.id) FILTER (WHERE p.status = 'active') AS active_projects, count(DISTINCT p.id) FILTER (WHERE p.status = 'archived') AS archived_projects, count(DISTINCT t.id) AS total_tasks, count(DISTINCT t.id) FILTER (WHERE t.status = 'done') AS completed_tasks, u.created_at FROM users AS u LEFT JOIN projects AS p ON p.owner_id = u.id LEFT JOIN tasks AS t ON t.project_id = p.id GROUP BY u.id, u.email, u.display_name, u.created_at;
