-- Tasks table
-- Stores project tasks and to-do items

CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    assigned_to UUID REFERENCES users(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT,
    priority TEXT NOT NULL DEFAULT 'medium',  -- Added via migration 003_add_task_priority
    status TEXT NOT NULL DEFAULT 'todo',
    due_date TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Constraints
    CONSTRAINT tasks_title_length CHECK (char_length(title) >= 3 AND char_length(title) <= 200),
    CONSTRAINT tasks_priority_valid CHECK (priority IN ('low', 'medium', 'high', 'urgent')),
    CONSTRAINT tasks_status_valid CHECK (status IN ('todo', 'in_progress', 'done', 'cancelled')),
    CONSTRAINT tasks_completed_when_done CHECK (
        (status = 'done' AND completed_at IS NOT NULL) OR
        (status != 'done' AND completed_at IS NULL)
    )
);

-- Table and column comments
COMMENT ON TABLE tasks IS 'Project tasks and to-do items';
COMMENT ON COLUMN tasks.id IS 'Unique task identifier (UUID v4)';
COMMENT ON COLUMN tasks.project_id IS 'Parent project (references projects.id)';
COMMENT ON COLUMN tasks.assigned_to IS 'Assigned user (references users.id, nullable)';
COMMENT ON COLUMN tasks.title IS 'Task title (3-200 characters)';
COMMENT ON COLUMN tasks.description IS 'Task description (optional)';
COMMENT ON COLUMN tasks.priority IS 'Task priority: low, medium, high, or urgent';
COMMENT ON COLUMN tasks.status IS 'Task status: todo, in_progress, done, or cancelled';
COMMENT ON COLUMN tasks.due_date IS 'Task due date (optional)';
COMMENT ON COLUMN tasks.completed_at IS 'Task completion timestamp (set when status = done)';
COMMENT ON COLUMN tasks.created_at IS 'Task creation timestamp';
COMMENT ON COLUMN tasks.updated_at IS 'Last task update timestamp';
