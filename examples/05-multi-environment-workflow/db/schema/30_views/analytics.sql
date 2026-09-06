-- Analytics Views
-- Reporting and dashboard queries

-- User project summary
CREATE OR REPLACE VIEW user_project_summary AS
SELECT
    u.id AS user_id,
    u.email,
    u.display_name,
    COUNT(DISTINCT p.id) AS total_projects,
    COUNT(DISTINCT p.id) FILTER (WHERE p.status = 'active') AS active_projects,
    COUNT(DISTINCT p.id) FILTER (WHERE p.status = 'archived') AS archived_projects,
    COUNT(DISTINCT t.id) AS total_tasks,
    COUNT(DISTINCT t.id) FILTER (WHERE t.status = 'done') AS completed_tasks,
    u.created_at
FROM users u
LEFT JOIN projects p ON p.owner_id = u.id
LEFT JOIN tasks t ON t.project_id = p.id
GROUP BY u.id, u.email, u.display_name, u.created_at;

COMMENT ON VIEW user_project_summary IS 'User activity summary: projects and tasks per user';

-- Project task statistics
CREATE OR REPLACE VIEW project_task_stats AS
SELECT
    p.id AS project_id,
    p.name AS project_name,
    p.status AS project_status,
    u.email AS owner_email,
    COUNT(t.id) AS total_tasks,
    COUNT(t.id) FILTER (WHERE t.status = 'todo') AS todo_tasks,
    COUNT(t.id) FILTER (WHERE t.status = 'in_progress') AS in_progress_tasks,
    COUNT(t.id) FILTER (WHERE t.status = 'done') AS done_tasks,
    COUNT(t.id) FILTER (WHERE t.priority = 'urgent') AS urgent_tasks,
    COUNT(t.id) FILTER (WHERE t.due_date < NOW() AND t.status != 'done') AS overdue_tasks,
    MIN(t.created_at) AS first_task_created,
    MAX(t.updated_at) AS last_task_updated
FROM projects p
LEFT JOIN users u ON u.id = p.owner_id
LEFT JOIN tasks t ON t.project_id = p.id
GROUP BY p.id, p.name, p.status, u.email;

COMMENT ON VIEW project_task_stats IS 'Project task statistics: counts by status and priority';

-- Active user dashboard
CREATE OR REPLACE VIEW active_user_dashboard AS
SELECT
    u.id,
    u.email,
    u.display_name,
    COUNT(DISTINCT t.id) FILTER (WHERE t.assigned_to = u.id AND t.status = 'todo') AS my_todo_tasks,
    COUNT(DISTINCT t.id) FILTER (WHERE t.assigned_to = u.id AND t.status = 'in_progress') AS my_active_tasks,
    COUNT(DISTINCT t.id) FILTER (
        WHERE t.assigned_to = u.id
        AND t.due_date < NOW()
        AND t.status NOT IN ('done', 'cancelled')
    ) AS my_overdue_tasks,
    COUNT(DISTINCT p.id) FILTER (WHERE p.owner_id = u.id AND p.status = 'active') AS my_active_projects,
    MAX(t.updated_at) FILTER (WHERE t.assigned_to = u.id) AS last_task_activity
FROM users u
LEFT JOIN tasks t ON t.assigned_to = u.id OR t.project_id IN (
    SELECT id FROM projects WHERE owner_id = u.id
)
LEFT JOIN projects p ON p.owner_id = u.id
GROUP BY u.id, u.email, u.display_name;

COMMENT ON VIEW active_user_dashboard IS 'User dashboard: my tasks and projects at a glance';
