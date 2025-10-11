-- User statistics view
CREATE VIEW user_stats AS
SELECT
    u.id,
    u.username,
    COUNT(p.id) AS post_count
FROM users u
LEFT JOIN posts p ON p.user_id = u.id
GROUP BY u.id, u.username;
