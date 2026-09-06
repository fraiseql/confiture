-- CI Test Fixtures
-- Minimal data for automated testing

-- Test users
INSERT INTO users (email, display_name, bio)
VALUES
    ('test1@example.com', 'Test User 1', 'First test user'),
    ('test2@example.com', 'Test User 2', 'Second test user'),
    ('test3@example.com', 'Test User 3', 'Third test user')
ON CONFLICT (email) DO NOTHING;

-- Test projects
INSERT INTO projects (owner_id, name, description, status)
SELECT
    u.id,
    'Test Project ' || ROW_NUMBER() OVER (ORDER BY u.id),
    'Test project description',
    CASE ROW_NUMBER() OVER (ORDER BY u.id) % 3
        WHEN 0 THEN 'active'
        WHEN 1 THEN 'archived'
        ELSE 'active'
    END
FROM users u
WHERE u.email LIKE 'test%@example.com'
ON CONFLICT (owner_id, name) DO NOTHING;

-- Test tasks with various statuses and priorities
INSERT INTO tasks (project_id, assigned_to, title, priority, status, due_date)
SELECT
    p.id,
    p.owner_id,
    'Test Task ' || ROW_NUMBER() OVER (ORDER BY p.id),
    CASE ROW_NUMBER() OVER (ORDER BY p.id) % 4
        WHEN 0 THEN 'low'
        WHEN 1 THEN 'medium'
        WHEN 2 THEN 'high'
        ELSE 'urgent'
    END,
    CASE ROW_NUMBER() OVER (ORDER BY p.id) % 4
        WHEN 0 THEN 'todo'
        WHEN 1 THEN 'in_progress'
        WHEN 2 THEN 'done'
        ELSE 'cancelled'
    END,
    NOW() + (ROW_NUMBER() OVER (ORDER BY p.id) || ' days')::INTERVAL
FROM projects p
ON CONFLICT DO NOTHING;

-- Verify test data
SELECT
    'Test fixtures loaded' AS status,
    COUNT(DISTINCT u.id) AS users,
    COUNT(DISTINCT p.id) AS projects,
    COUNT(DISTINCT t.id) AS tasks
FROM users u
LEFT JOIN projects p ON p.owner_id = u.id
LEFT JOIN tasks t ON t.project_id = p.id
WHERE u.email LIKE 'test%@example.com';
