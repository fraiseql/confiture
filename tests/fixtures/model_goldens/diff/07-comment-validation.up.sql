-- Migration: golden
-- Version: <version>

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS posts (
    id SERIAL NOT NULL,
    user_id INTEGER NOT NULL,
    title VARCHAR(500) NOT NULL,
    content TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    FOREIGN KEY (user_id) REFERENCES users (id)
);

-- confiture:tier additive
CREATE TABLE IF NOT EXISTS users (
    id SERIAL NOT NULL,
    username VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE (username),
    UNIQUE (email)
);

-- confiture:tier reversible
CREATE OR REPLACE VIEW v_recent_posts AS SELECT p.id, p.title, p.content, u.username AS author, p.created_at FROM posts AS p INNER JOIN users AS u ON p.user_id = u.id ORDER BY p.created_at DESC LIMIT 100;

-- confiture:tier reversible
CREATE OR REPLACE VIEW v_user_stats AS SELECT u.id, u.username, count(p.id) AS post_count, max(p.created_at) AS last_post_date FROM users AS u LEFT JOIN posts AS p ON u.id = p.user_id GROUP BY u.id, u.username;
