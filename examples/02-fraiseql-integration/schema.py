"""
Blog API Schema using FraiseQL

This schema is the SINGLE SOURCE OF TRUTH for:
1. GraphQL API types
2. PostgreSQL table definitions
3. Python type hints

FraiseQL automatically generates:
- GraphQL schema with proper types
- PostgreSQL DDL with constraints
- Type-safe resolvers

Usage:
    # Generate PostgreSQL DDL
    fraiseql generate-ddl schema.py --output db/schema/10_tables/

    # Build database with Confiture
    confiture build --env local

    # Run GraphQL API
    python app.py
"""

from datetime import datetime
from typing import Optional

import strawberry

# ============================================================================
# Type Definitions
# ============================================================================


@strawberry.type
class User:
    """User account with profile information.

    GraphQL Type: User
    PostgreSQL Table: tb_user (command side) / tv_user (query side)

    Example GraphQL query:
        query {
            user(id: "123") {
                id
                email
                username
                fullName
                publishedPostCount
            }
        }
    """

    id: str
    email: str
    username: str
    full_name: str = strawberry.field(name="fullName")
    bio: str | None = None
    avatar_url: str | None = strawberry.field(name="avatarUrl", default=None)
    is_active: bool = strawberry.field(name="isActive")

    # Computed fields (from query-side denormalization)
    published_post_count: int = strawberry.field(name="publishedPostCount", default=0)
    comment_count: int = strawberry.field(name="commentCount", default=0)

    # Timestamps
    created_at: datetime = strawberry.field(name="createdAt")
    updated_at: datetime = strawberry.field(name="updatedAt")


@strawberry.type
class Author:
    """Embedded author information in posts/comments.

    This is a subset of User fields optimized for embedding.
    """

    id: str
    username: str
    full_name: str = strawberry.field(name="fullName")
    avatar_url: str | None = strawberry.field(name="avatarUrl", default=None)


@strawberry.type
class Comment:
    """Comment on a blog post.

    GraphQL Type: Comment
    PostgreSQL Table: tb_comment / tv_comment

    Supports nested comments via parent_comment.
    """

    id: str
    content: str
    is_edited: bool = strawberry.field(name="isEdited")

    # Embedded relations
    author: Author
    parent_comment: Optional["Comment"] = strawberry.field(name="parentComment", default=None)

    # Metadata
    depth: int = 0  # Comment nesting level
    reply_count: int = strawberry.field(name="replyCount", default=0)

    # Timestamps
    created_at: datetime = strawberry.field(name="createdAt")
    updated_at: datetime = strawberry.field(name="updatedAt")


@strawberry.type
class Post:
    """Blog post with content and metadata.

    GraphQL Type: Post
    PostgreSQL Table: tb_post / tv_post

    Query-side table (tv_post) includes denormalized data:
    - Author information
    - Comment count
    - All comments (embedded)
    """

    id: str
    title: str
    slug: str
    content: str
    excerpt: str | None = None

    # Metadata
    tags: list[str] = strawberry.field(default_factory=list)
    is_published: bool = strawberry.field(name="isPublished")
    published_at: datetime | None = strawberry.field(name="publishedAt", default=None)
    view_count: int = strawberry.field(name="viewCount", default=0)

    # Embedded relations
    author: Author
    comments: list[Comment] = strawberry.field(default_factory=list)
    comment_count: int = strawberry.field(name="commentCount", default=0)

    # Timestamps
    created_at: datetime = strawberry.field(name="createdAt")
    updated_at: datetime = strawberry.field(name="updatedAt")


# ============================================================================
# Input Types for Mutations
# ============================================================================


@strawberry.input
class CreateUserInput:
    """Input for creating a new user."""

    email: str
    username: str
    full_name: str = strawberry.field(name="fullName")
    bio: str | None = None
    avatar_url: str | None = strawberry.field(name="avatarUrl", default=None)


@strawberry.input
class UpdateUserInput:
    """Input for updating user profile."""

    full_name: str | None = strawberry.field(name="fullName", default=None)
    bio: str | None = None
    avatar_url: str | None = strawberry.field(name="avatarUrl", default=None)


@strawberry.input
class CreatePostInput:
    """Input for creating a new post."""

    title: str
    content: str
    excerpt: str | None = None
    tags: list[str] = strawberry.field(default_factory=list)
    is_published: bool = strawberry.field(name="isPublished", default=False)


@strawberry.input
class UpdatePostInput:
    """Input for updating a post."""

    title: str | None = None
    content: str | None = None
    excerpt: str | None = None
    tags: list[str] | None = None
    is_published: bool | None = strawberry.field(name="isPublished", default=None)


@strawberry.input
class CreateCommentInput:
    """Input for creating a comment."""

    content: str
    parent_comment_id: str | None = strawberry.field(name="parentCommentId", default=None)


# ============================================================================
# Queries
# ============================================================================


@strawberry.type
class Query:
    """GraphQL queries - all read from tv_* tables (query side)."""

    @strawberry.field
    async def users(self, info, limit: int = 10, offset: int = 0) -> list[User]:
        """Get users with their post/comment counts.

        Example:
            query {
                users(limit: 10) {
                    id
                    username
                    publishedPostCount
                }
            }
        """
        pool = info.context["db_pool"]

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT data FROM tv_user
                ORDER BY (data->>'createdAt')::timestamptz DESC
                LIMIT $1 OFFSET $2
                """,
                limit,
                offset,
            )

        return [User(**row["data"]) for row in rows]

    @strawberry.field
    async def user(self, info, id: str) -> User | None:
        """Get a specific user by ID.

        Example:
            query {
                user(id: "123") {
                    id
                    email
                    fullName
                }
            }
        """
        pool = info.context["db_pool"]

        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT data FROM tv_user WHERE id = $1", id)

        return User(**row["data"]) if row else None

    @strawberry.field
    async def posts(
        self, info, published_only: bool = True, limit: int = 10, offset: int = 0
    ) -> list[Post]:
        """Get posts with embedded author and comments.

        Example:
            query {
                posts(publishedOnly: true, limit: 10) {
                    id
                    title
                    author {
                        username
                    }
                    commentCount
                }
            }
        """
        pool = info.context["db_pool"]

        async with pool.acquire() as conn:
            if published_only:
                rows = await conn.fetch(
                    """
                    SELECT data FROM tv_post
                    WHERE (data->>'isPublished')::boolean = true
                    ORDER BY (data->>'createdAt')::timestamptz DESC
                    LIMIT $1 OFFSET $2
                    """,
                    limit,
                    offset,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT data FROM tv_post
                    ORDER BY (data->>'createdAt')::timestamptz DESC
                    LIMIT $1 OFFSET $2
                    """,
                    limit,
                    offset,
                )

        return [Post(**row["data"]) for row in rows]

    @strawberry.field
    async def post(self, info, id: str) -> Post | None:
        """Get a specific post by ID.

        Example:
            query {
                post(id: "123") {
                    id
                    title
                    content
                    comments {
                        content
                        author {
                            username
                        }
                    }
                }
            }
        """
        pool = info.context["db_pool"]

        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT data FROM tv_post WHERE id = $1", id)

        return Post(**row["data"]) if row else None

    @strawberry.field
    async def post_by_slug(self, info, slug: str) -> Post | None:
        """Get a post by its slug.

        Example:
            query {
                postBySlug(slug: "getting-started-fraiseql") {
                    id
                    title
                    content
                }
            }
        """
        pool = info.context["db_pool"]

        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT data FROM tv_post WHERE data->>'slug' = $1", slug)

        return Post(**row["data"]) if row else None


# ============================================================================
# Mutations
# ============================================================================


@strawberry.type
class Mutation:
    """GraphQL mutations - write to tb_* then explicitly sync to tv_*."""

    @strawberry.mutation
    async def create_user(self, info, input: CreateUserInput) -> User:
        """Create a new user.

        EXPLICIT SYNC PATTERN:
        1. Insert into tb_user (command side)
        2. Explicitly sync to tv_user (query side)

        Example:
            mutation {
                createUser(input: {
                    email: "alice@example.com"
                    username: "alice"
                    fullName: "Alice Johnson"
                    bio: "Software engineer"
                }) {
                    id
                    username
                }
            }
        """

        pool = info.context["db_pool"]

        async with pool.acquire() as conn:
            # Step 1: Write to command side (tb_user)
            user_id = await conn.fetchval(
                """
                INSERT INTO tb_user (
                    pk_user, email, username, full_name, bio, avatar_url
                )
                VALUES (gen_random_uuid(), $1, $2, $3, $4, $5)
                RETURNING pk_user
                """,
                input.email,
                input.username,
                input.full_name,
                input.bio,
                input.avatar_url,
            )

            # Step 2: Sync to query side (tv_user)
            # In production, use FraiseQL's sync manager
            await conn.execute(
                """
                INSERT INTO tv_user (id, data)
                SELECT
                    pk_user,
                    jsonb_build_object(
                        'id', pk_user::text,
                        'email', email,
                        'username', username,
                        'fullName', full_name,
                        'bio', bio,
                        'avatarUrl', avatar_url,
                        'isActive', is_active,
                        'publishedPostCount', 0,
                        'commentCount', 0,
                        'createdAt', created_at,
                        'updatedAt', updated_at
                    )
                FROM tb_user
                WHERE pk_user = $1
                """,
                user_id,
            )

            # Step 3: Read from query side
            row = await conn.fetchrow("SELECT data FROM tv_user WHERE id = $1", user_id)

        return User(**row["data"])

    @strawberry.mutation
    async def create_post(self, info, author_id: str, input: CreatePostInput) -> Post:
        """Create a new post.

        Example:
            mutation {
                createPost(
                    authorId: "123"
                    input: {
                        title: "My First Post"
                        content: "Hello world!"
                        isPublished: true
                    }
                ) {
                    id
                    title
                    slug
                }
            }
        """
        import re
        from uuid import UUID

        pool = info.context["db_pool"]

        # Generate slug from title
        slug = re.sub(r"[^a-z0-9]+", "-", input.title.lower()).strip("-")

        async with pool.acquire() as conn:
            # Write to command side
            post_id = await conn.fetchval(
                """
                INSERT INTO tb_post (
                    pk_post, fk_user, title, slug, content, excerpt,
                    tags, is_published, published_at
                )
                VALUES (
                    gen_random_uuid(), $1, $2, $3, $4, $5, $6, $7,
                    CASE WHEN $7 THEN NOW() ELSE NULL END
                )
                RETURNING pk_post
                """,
                UUID(author_id),
                input.title,
                slug,
                input.content,
                input.excerpt or input.content[:200],
                input.tags,
                input.is_published,
            )

            # Sync to query side (simplified - use FraiseQL sync in production)
            await conn.execute(
                """
                INSERT INTO tv_post (id, data)
                SELECT
                    p.pk_post,
                    jsonb_build_object(
                        'id', p.pk_post::text,
                        'title', p.title,
                        'slug', p.slug,
                        'content', p.content,
                        'excerpt', p.excerpt,
                        'tags', p.tags,
                        'isPublished', p.is_published,
                        'publishedAt', p.published_at,
                        'viewCount', p.view_count,
                        'author', jsonb_build_object(
                            'id', u.pk_user::text,
                            'username', u.username,
                            'fullName', u.full_name,
                            'avatarUrl', u.avatar_url
                        ),
                        'comments', '[]'::jsonb,
                        'commentCount', 0,
                        'createdAt', p.created_at,
                        'updatedAt', p.updated_at
                    )
                FROM tb_post p
                JOIN tb_user u ON u.pk_user = p.fk_user
                WHERE p.pk_post = $1
                """,
                post_id,
            )

            # Read from query side
            row = await conn.fetchrow("SELECT data FROM tv_post WHERE id = $1", post_id)

        return Post(**row["data"])


# ============================================================================
# Schema
# ============================================================================

schema = strawberry.Schema(query=Query, mutation=Mutation)
