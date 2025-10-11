-- Development seed data: Sample comments
-- Conversations on posts for development testing

INSERT INTO comments (pk_comment, post_id, user_id, content, created_at) VALUES
    -- Comments on "Welcome to Our Blog"
    ('00000000-0000-0000-0000-000000000021', 1, 2, 'Great to see this platform launch! Looking forward to contributing.', NOW()),
    ('00000000-0000-0000-0000-000000000022', 1, 3, 'Excited to be here! The interface looks fantastic.', NOW()),

    -- Comments on "Getting Started Guide"
    ('00000000-0000-0000-0000-000000000023', 2, 3, 'This guide is super helpful! Thanks for putting it together.', NOW()),
    ('00000000-0000-0000-0000-000000000024', 2, 2, 'Question: How do I format code blocks in posts?', NOW()),
    ('00000000-0000-0000-0000-000000000025', 2, 1, '@editor You can use markdown syntax with triple backticks.', NOW()),

    -- Comments on "Content Strategy Tips"
    ('00000000-0000-0000-0000-000000000026', 4, 1, 'Excellent insights! The tip about consistency really resonates.', NOW()),
    ('00000000-0000-0000-0000-000000000027', 4, 3, 'I''ve been applying these strategies and seeing great results!', NOW())
ON CONFLICT (pk_comment) DO NOTHING;
