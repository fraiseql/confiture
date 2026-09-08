-- Trigger Functions
-- Automated database logic

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION public.update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_updated_at_column() IS 'Automatically update updated_at column on row modification';

-- Apply updated_at trigger to all tables
CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_projects_updated_at
    BEFORE UPDATE ON projects
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_tasks_updated_at
    BEFORE UPDATE ON tasks
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Auto-set completed_at when task marked done
CREATE OR REPLACE FUNCTION public.set_task_completed_at()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'done' AND OLD.status != 'done' THEN
        NEW.completed_at = NOW();
    ELSIF NEW.status != 'done' AND OLD.status = 'done' THEN
        NEW.completed_at = NULL;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION set_task_completed_at() IS 'Automatically set/clear completed_at when task status changes to/from done';

CREATE TRIGGER set_task_completed_at_trigger
    BEFORE UPDATE ON tasks
    FOR EACH ROW
    WHEN (OLD.status IS DISTINCT FROM NEW.status)
    EXECUTE FUNCTION set_task_completed_at();

-- Prevent deleting projects with active tasks
CREATE OR REPLACE FUNCTION public.prevent_delete_project_with_tasks()
RETURNS TRIGGER AS $$
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

COMMENT ON FUNCTION prevent_delete_project_with_tasks() IS 'Prevent deletion of projects with active tasks';

CREATE TRIGGER prevent_delete_project_with_tasks_trigger
    BEFORE DELETE ON projects
    FOR EACH ROW
    EXECUTE FUNCTION prevent_delete_project_with_tasks();
