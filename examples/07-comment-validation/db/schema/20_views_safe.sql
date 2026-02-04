-- Safe views file with proper SQL

-- User statistics view
CREATE OR REPLACE VIEW v_user_stats AS
SELECT
    u.id,
    u.username,
    COUNT(p.id) as post_count,
    MAX(p.created_at) as last_post_date
FROM users u
LEFT JOIN posts p ON u.id = p.user_id
GROUP BY u.id, u.username;

-- Posts view
CREATE OR REPLACE VIEW v_recent_posts AS
SELECT
    p.id,
    p.title,
    p.content,
    u.username as author,
    p.created_at
FROM posts p
JOIN users u ON p.user_id = u.id
ORDER BY p.created_at DESC
LIMIT 100;
