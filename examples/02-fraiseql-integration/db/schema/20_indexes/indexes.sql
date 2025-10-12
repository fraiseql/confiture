-- Additional Performance Indexes
--
-- These indexes are manually created to optimize specific query patterns.
-- They complement the auto-generated indexes in 10_tables/generated.sql

-- =============================================================================
-- Composite Indexes for Common Query Patterns
-- =============================================================================

-- Posts by author + published status (for author's published posts)
CREATE INDEX IF NOT EXISTS idx_tb_post_user_published
    ON tb_post(fk_user, is_published)
    WHERE is_published = true;

-- Posts by published status + creation date (for recent published posts)
CREATE INDEX IF NOT EXISTS idx_tb_post_published_created
    ON tb_post(is_published, created_at DESC)
    WHERE is_published = true;

-- Comments by post + creation date (for post's comments sorted by date)
CREATE INDEX IF NOT EXISTS idx_tb_comment_post_created
    ON tb_comment(fk_post, created_at DESC);

-- Comments by user + creation date (for user's comment history)
CREATE INDEX IF NOT EXISTS idx_tb_comment_user_created
    ON tb_comment(fk_user, created_at DESC);

-- =============================================================================
-- JSONB Indexes for tv_* Tables
-- =============================================================================

-- Full-text search on post content (tv_post)
CREATE INDEX IF NOT EXISTS idx_tv_post_content_search
    ON tv_post USING gin(to_tsvector('english', data->>'content'));

-- Search on post title
CREATE INDEX IF NOT EXISTS idx_tv_post_title_search
    ON tv_post USING gin(to_tsvector('english', data->>'title'));

-- Trigram search for fuzzy matching on post titles
CREATE INDEX IF NOT EXISTS idx_tv_post_title_trgm
    ON tv_post USING gin((data->>'title') gin_trgm_ops);

-- Author username search
CREATE INDEX IF NOT EXISTS idx_tv_user_username_trgm
    ON tv_user USING gin(username gin_trgm_ops);

-- =============================================================================
-- Covering Indexes for Common Queries
-- =============================================================================

-- Post list query (id, title, excerpt, author, created_at)
-- Uses generated columns in tv_post
CREATE INDEX IF NOT EXISTS idx_tv_post_list
    ON tv_post(created_at DESC)
    INCLUDE (id, slug);

-- User list query
CREATE INDEX IF NOT EXISTS idx_tv_user_list
    ON tv_user(created_at DESC)
    INCLUDE (id, username);

-- =============================================================================
-- Partial Indexes for Specific Conditions
-- =============================================================================

-- Active users only (most queries filter by is_active)
CREATE INDEX IF NOT EXISTS idx_tb_user_active_username
    ON tb_user(username)
    WHERE is_active = true;

-- Unpublished posts (for author's draft management)
CREATE INDEX IF NOT EXISTS idx_tb_post_unpublished
    ON tb_post(fk_user, updated_at DESC)
    WHERE is_published = false;

-- Top-level comments (for post's comment tree root)
CREATE INDEX IF NOT EXISTS idx_tb_comment_top_level
    ON tb_comment(fk_post, created_at DESC)
    WHERE fk_parent_comment IS NULL;

-- =============================================================================
-- Statistics and Optimization
-- =============================================================================

-- Update statistics for better query planning
ANALYZE tb_user;
ANALYZE tb_post;
ANALYZE tb_comment;
ANALYZE tv_user;
ANALYZE tv_post;
ANALYZE tv_comment;

-- Index comments
COMMENT ON INDEX idx_tb_post_user_published IS 'Optimize author published posts query';
COMMENT ON INDEX idx_tv_post_content_search IS 'Full-text search on post content';
COMMENT ON INDEX idx_tv_post_title_trgm IS 'Fuzzy search on post titles';
