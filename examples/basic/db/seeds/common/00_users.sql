-- Common seed data: Test users
-- These users are available in all non-production environments

INSERT INTO users (pk_user, slug, username, email, bio, created_at) VALUES
    ('00000000-0000-0000-0000-000000000001', 'admin-user', 'admin', 'admin@example.com', 'System Administrator - Full access to all features', NOW()),
    ('00000000-0000-0000-0000-000000000002', 'editor-user', 'editor', 'editor@example.com', 'Content Editor - Can create and edit posts', NOW()),
    ('00000000-0000-0000-0000-000000000003', 'reader-user', 'reader', 'reader@example.com', 'Regular Reader - Can view and comment on posts', NOW())
ON CONFLICT (pk_user) DO NOTHING;
