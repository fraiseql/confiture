-- Local Development Sample Data
-- Run this after building the schema to populate with test data

-- Sample users
INSERT INTO users (email, display_name, bio, avatar_url)
VALUES
    ('alice@example.com', 'Alice Smith', 'Product designer and UX enthusiast', 'https://i.pravatar.cc/150?img=1'),
    ('bob@example.com', 'Bob Johnson', 'Full-stack developer specializing in PostgreSQL', 'https://i.pravatar.cc/150?img=2'),
    ('charlie@example.com', 'Charlie Davis', 'DevOps engineer and automation expert', 'https://i.pravatar.cc/150?img=3'),
    ('diana@example.com', 'Diana Wilson', 'Technical writer and documentation specialist', 'https://i.pravatar.cc/150?img=4'),
    ('evan@example.com', 'Evan Martinez', 'Backend engineer focused on API design', 'https://i.pravatar.cc/150?img=5')
ON CONFLICT (email) DO NOTHING;

-- Sample projects
INSERT INTO projects (owner_id, name, description, status)
SELECT
    u.id,
    'Project ' || u.display_name,
    'Sample project for ' || u.display_name,
    'active'
FROM users u
WHERE u.email IN ('alice@example.com', 'bob@example.com', 'charlie@example.com')
ON CONFLICT (owner_id, name) DO NOTHING;

-- Sample tasks
INSERT INTO tasks (project_id, assigned_to, title, description, priority, status, due_date)
SELECT
    p.id,
    u.id,
    'Setup development environment',
    'Install and configure local development tools',
    'high',
    'done',
    NOW() - INTERVAL '2 days'
FROM projects p
JOIN users u ON u.id = p.owner_id
WHERE u.email = 'alice@example.com'
ON CONFLICT DO NOTHING;

INSERT INTO tasks (project_id, assigned_to, title, description, priority, status, due_date)
SELECT
    p.id,
    u.id,
    'Review database schema',
    'Analyze and document current database schema',
    'medium',
    'in_progress',
    NOW() + INTERVAL '3 days'
FROM projects p
JOIN users u ON u.id = p.owner_id
WHERE u.email = 'bob@example.com'
ON CONFLICT DO NOTHING;

INSERT INTO tasks (project_id, assigned_to, title, description, priority, status, due_date)
SELECT
    p.id,
    u.id,
    'Deploy to staging',
    'Test and deploy latest changes to staging environment',
    'urgent',
    'todo',
    NOW() + INTERVAL '1 day'
FROM projects p
JOIN users u ON u.id = p.owner_id
WHERE u.email = 'charlie@example.com'
ON CONFLICT DO NOTHING;

-- Display summary
SELECT
    'Sample data loaded successfully' AS status,
    COUNT(DISTINCT u.id) AS users,
    COUNT(DISTINCT p.id) AS projects,
    COUNT(DISTINCT t.id) AS tasks
FROM users u
LEFT JOIN projects p ON p.owner_id = u.id
LEFT JOIN tasks t ON t.project_id = p.id;
