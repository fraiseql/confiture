-- Migration: golden
-- Version: <version>

-- confiture:tier additive
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- confiture:tier lock_risky
CREATE TABLE IF NOT EXISTS users (
    id BIGINT NOT NULL GENERATED ALWAYS AS IDENTITY,
    pk_user UUID NOT NULL DEFAULT uuid_generate_v4(),
    slug TEXT NOT NULL,
    username TEXT NOT NULL,
    email TEXT NOT NULL,
    bio TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    UNIQUE (pk_user),
    UNIQUE (slug),
    UNIQUE (username),
    UNIQUE (email)
);
CREATE INDEX IF NOT EXISTS idx_users_pk_user ON users (pk_user);
CREATE INDEX IF NOT EXISTS idx_users_slug ON users (slug);
CREATE INDEX IF NOT EXISTS idx_users_username ON users (username);
CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);
CREATE INDEX IF NOT EXISTS idx_users_created_at ON users (created_at DESC);

-- confiture:tier lock_risky
CREATE TABLE IF NOT EXISTS posts (
    id BIGINT NOT NULL GENERATED ALWAYS AS IDENTITY,
    pk_post UUID NOT NULL DEFAULT uuid_generate_v4(),
    slug TEXT NOT NULL,
    user_id BIGINT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    UNIQUE (pk_post),
    UNIQUE (slug)
);
CREATE INDEX IF NOT EXISTS idx_posts_pk_post ON posts (pk_post);
CREATE INDEX IF NOT EXISTS idx_posts_slug ON posts (slug);
CREATE INDEX IF NOT EXISTS idx_posts_user_id ON posts (user_id);
CREATE INDEX IF NOT EXISTS idx_posts_published_at ON posts (published_at DESC) WHERE published_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_posts_created_at ON posts (created_at DESC);

-- confiture:tier lock_risky
CREATE TABLE IF NOT EXISTS comments (
    id BIGINT NOT NULL GENERATED ALWAYS AS IDENTITY,
    pk_comment UUID NOT NULL DEFAULT uuid_generate_v4(),
    post_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    FOREIGN KEY (post_id) REFERENCES posts (id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    UNIQUE (pk_comment)
);
CREATE INDEX IF NOT EXISTS idx_comments_pk_comment ON comments (pk_comment);
CREATE INDEX IF NOT EXISTS idx_comments_post_id ON comments (post_id);
CREATE INDEX IF NOT EXISTS idx_comments_user_id ON comments (user_id);
CREATE INDEX IF NOT EXISTS idx_comments_created_at ON comments (created_at DESC);
