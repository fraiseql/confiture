-- Development seed data: Sample posts
-- Rich content for development and manual testing

INSERT INTO posts (pk_post, slug, user_id, title, content, published_at, created_at) VALUES
    -- Admin's posts
    ('00000000-0000-0000-0000-000000000011', 'welcome-to-our-blog', 1, 'Welcome to Our Blog',
     'Welcome to our new blog platform! We''re excited to share our thoughts and stories with you. This is just the beginning of something great.',
     NOW(), NOW()),

    ('00000000-0000-0000-0000-000000000012', 'getting-started-guide', 1, 'Getting Started Guide',
     'Here''s a comprehensive guide to get you started with our platform. Follow these simple steps to create your first post and start engaging with the community.',
     NOW(), NOW()),

    ('00000000-0000-0000-0000-000000000013', 'best-practices-2024', 1, 'Best Practices for 2024',
     'As we enter a new year, let''s discuss the best practices for content creation and community engagement. Here are our top 10 recommendations.',
     NOW(), NOW()),

    -- Editor's posts
    ('00000000-0000-0000-0000-000000000014', 'content-strategy-tips', 2, 'Content Strategy Tips',
     'As a content editor, I''ve learned many valuable lessons about creating engaging content. Let me share my top strategies with you.',
     NOW(), NOW()),

    ('00000000-0000-0000-0000-000000000015', 'writing-workflow', 2, 'My Writing Workflow',
     'Here''s how I organize my writing process from ideation to publication. A structured workflow makes all the difference.',
     NOW(), NOW()),

    -- Draft post (not published)
    ('00000000-0000-0000-0000-000000000016', 'upcoming-features', 1, 'Upcoming Features (Draft)',
     'This is a draft post about upcoming features. It won''t show up in public listings.',
     NULL, NOW())
ON CONFLICT (pk_post) DO NOTHING;
