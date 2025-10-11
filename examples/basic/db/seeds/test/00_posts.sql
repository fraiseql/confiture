-- Test seed data: Minimal posts
-- Just enough data for automated tests

INSERT INTO posts (pk_post, slug, user_id, title, content, published_at, created_at) VALUES
    -- Published post for testing
    ('00000000-0000-0000-0000-000000000101', 'test-post-published', 1, 'Test Post (Published)',
     'This is a published test post.',
     NOW(), NOW()),

    -- Draft post for testing
    ('00000000-0000-0000-0000-000000000102', 'test-post-draft', 1, 'Test Post (Draft)',
     'This is a draft test post.',
     NULL, NOW()),

    -- Post with specific slug for testing
    ('00000000-0000-0000-0000-000000000103', 'test-specific-slug', 2, 'Test Post with Known Slug',
     'This post has a predictable slug for testing.',
     NOW(), NOW())
ON CONFLICT (pk_post) DO NOTHING;
