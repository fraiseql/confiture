# FraiseQL Integration with Confiture

**GraphQL-first schema management meets instant database builds**

This example demonstrates how FraiseQL and Confiture work together to provide a seamless GraphQL-to-PostgreSQL development workflow. Define your schema once in Python types, automatically generate DDL, and use Confiture to manage your database lifecycle.

**Time to complete**: 20 minutes

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Why FraiseQL + Confiture?](#why-fraiseql--confiture)
4. [Project Structure](#project-structure)
5. [Step 1: Define GraphQL Schema](#step-1-define-graphql-schema)
6. [Step 2: Generate PostgreSQL DDL](#step-2-generate-postgresql-ddl)
7. [Step 3: Build Database with Confiture](#step-3-build-database-with-confiture)
8. [Step 4: Run the GraphQL API](#step-4-run-the-graphql-api)
9. [Step 5: Test GraphQL Queries](#step-5-test-graphql-queries)
10. [Step 6: Schema Evolution](#step-6-schema-evolution)
11. [Advanced Patterns](#advanced-patterns)
12. [Troubleshooting](#troubleshooting)

---

## Overview

### The Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│                    FraiseQL + Confiture Workflow                 │
└─────────────────────────────────────────────────────────────────┘

1. Define GraphQL Schema (Python types)
   ↓
2. FraiseQL generates PostgreSQL DDL
   ↓
3. Confiture builds database from DDL (Medium 1)
   ↓
4. Run GraphQL API with instant database
   ↓
5. Evolve schema with Confiture migrations (Medium 2)
```

### What You'll Build

A production-ready blog API with:
- **Type-safe GraphQL schema** using FraiseQL's `@fraise_type` decorator
- **Auto-generated PostgreSQL tables** with proper constraints and indexes
- **Instant database builds** using `confiture build`
- **Incremental migrations** for schema evolution
- **CQRS pattern** with tb_/tv_ tables for command/query separation

---

## Prerequisites

### Software Requirements

- Python 3.11 or higher
- PostgreSQL 14 or higher
- pip or uv package manager

### Install Dependencies

```bash
# Install FraiseQL and Confiture
pip install fraiseql confiture

# Or using uv
uv pip install fraiseql confiture

# Verify installations
fraiseql --version
confiture --version
```

### Database Setup

```bash
# Create database
createdb fraiseql_blog

# Verify connection
psql fraiseql_blog -c "SELECT version()"
```

---

## Why FraiseQL + Confiture?

### The Problem

Traditional approaches have pain points:

**Problem 1: Schema Duplication**
```python
# GraphQL schema
type User {
  id: ID!
  email: String!
  name: String!
}

# SQL schema (separate!)
CREATE TABLE users (
  id UUID PRIMARY KEY,
  email TEXT NOT NULL,
  name TEXT NOT NULL
);
```

**Problem 2: Migration Hell**
- ORM migrations break on production data
- Long migration chains slow down CI/CD
- Fresh databases take minutes to set up

### The Solution: FraiseQL + Confiture

**Single Source of Truth**
```python
from fraiseql import fraise_type

@fraise_type
class User:
    id: str  # GraphQL ID! → PostgreSQL UUID
    email: str  # GraphQL String! → PostgreSQL TEXT
    name: str  # GraphQL String! → PostgreSQL TEXT
```

**Instant Database Builds**
```bash
# Generate DDL from GraphQL types
fraiseql generate-ddl schema.py --output db/schema/

# Build database in <1 second
confiture build --env local

# Database is ready!
```

### Key Benefits

| Feature | Traditional ORM | FraiseQL + Confiture |
|---------|----------------|---------------------|
| **Schema Definition** | Duplicate (GraphQL + SQL) | Single (Python types) |
| **Fresh DB Setup** | 2-10 minutes (run migrations) | <1 second (build from DDL) |
| **Type Safety** | ❌ (manual mapping) | ✅ (auto-generated) |
| **Schema Evolution** | Migration files only | DDL files + migrations |
| **Rollback** | Complex (undo migrations) | Simple (rebuild from DDL) |
| **CI/CD Speed** | Slow (replay history) | Fast (instant build) |

---

## Project Structure

```
02-fraiseql-integration/
├── README.md                       # This file
├── requirements.txt                # Python dependencies
├── .gitignore                      # Ignore generated files
│
├── schema.py                       # FraiseQL GraphQL schema (SOURCE OF TRUTH)
├── app.py                          # FastAPI + GraphQL application
│
├── db/
│   ├── schema/                     # Generated DDL files
│   │   ├── 00_extensions/
│   │   │   └── extensions.sql      # PostgreSQL extensions
│   │   ├── 10_tables/
│   │   │   └── generated.sql       # Auto-generated from schema.py
│   │   └── 20_indexes/
│   │       └── indexes.sql         # Performance indexes
│   │
│   ├── migrations/                 # Incremental migrations
│   │   └── 001_add_post_views.py   # Example migration
│   │
│   └── environments/
│       ├── local.yaml              # Local development config
│       └── production.yaml         # Production config
│
├── confiture.yaml                  # Confiture configuration
└── .env.example                    # Environment variables template
```

---

## Step 1: Define GraphQL Schema

### The FraiseQL Type System

FraiseQL uses Python type hints to define GraphQL schemas that automatically map to PostgreSQL tables.

**schema.py**:

```python
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
"""

from datetime import datetime
from typing import Optional
from uuid import uuid4

from fraiseql import fraise_type, Field, foreign_key, unique, index


@fraise_type
class User:
    """User account with profile information.

    GraphQL Type: User
    PostgreSQL Table: tb_user (command side) / tv_user (query side)
    """

    # Primary key (auto-generated UUID)
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)

    # User credentials
    email: str = Field(unique=True, index=True)
    username: str = Field(unique=True, index=True)

    # Profile data
    full_name: str
    bio: Optional[str] = None
    avatar_url: Optional[str] = None

    # Status
    is_active: bool = Field(default=True, index=True)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


@fraise_type
class Post:
    """Blog post with content and metadata.

    GraphQL Type: Post
    PostgreSQL Table: tb_post / tv_post
    """

    # Primary key
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)

    # Foreign key to User
    author_id: str = Field(foreign_key="User.id", index=True)

    # Content
    title: str = Field(max_length=500)
    slug: str = Field(unique=True, index=True)
    content: str
    excerpt: Optional[str] = Field(max_length=1000)

    # Metadata
    tags: list[str] = Field(default_factory=list)
    is_published: bool = Field(default=False, index=True)
    published_at: Optional[datetime] = None
    view_count: int = Field(default=0)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


@fraise_type
class Comment:
    """Comment on a blog post.

    GraphQL Type: Comment
    PostgreSQL Table: tb_comment / tv_comment
    """

    # Primary key
    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)

    # Foreign keys
    post_id: str = Field(foreign_key="Post.id", index=True)
    author_id: str = Field(foreign_key="User.id", index=True)
    parent_comment_id: Optional[str] = Field(
        foreign_key="Comment.id",
        index=True,
        nullable=True
    )

    # Content
    content: str
    is_edited: bool = Field(default=False)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
```

### Type Mapping

FraiseQL automatically maps Python types to PostgreSQL:

| Python Type | GraphQL Type | PostgreSQL Type |
|-------------|--------------|-----------------|
| `str` | `String!` | `TEXT` |
| `int` | `Int!` | `INTEGER` |
| `float` | `Float!` | `DOUBLE PRECISION` |
| `bool` | `Boolean!` | `BOOLEAN` |
| `datetime` | `DateTime!` | `TIMESTAMPTZ` |
| `Optional[T]` | `T` (nullable) | `T NULL` |
| `list[T]` | `[T!]!` | `T[]` |
| `dict` | `JSON!` | `JSONB` |

### Field Constraints

```python
# Primary key
id: str = Field(primary_key=True)

# Unique constraint
email: str = Field(unique=True)

# Foreign key
author_id: str = Field(foreign_key="User.id")

# Index
created_at: datetime = Field(index=True)

# Max length
title: str = Field(max_length=500)

# Default value
is_active: bool = Field(default=True)

# Nullable (Optional)
bio: Optional[str] = None
```

---

## Step 2: Generate PostgreSQL DDL

### Generate DDL Files

FraiseQL can generate PostgreSQL DDL from your Python types:

```bash
# Generate DDL files
fraiseql generate-ddl schema.py --output db/schema/10_tables/

# Expected output:
# ✓ Generated db/schema/10_tables/generated.sql (478 lines)
# ✓ Detected 3 types: User, Post, Comment
# ✓ Created 6 tables: tb_user, tv_user, tb_post, tv_post, tb_comment, tv_comment
```

### Generated DDL Structure

**db/schema/10_tables/generated.sql**:

```sql
-- Auto-generated from schema.py
-- DO NOT EDIT MANUALLY - regenerate with: fraiseql generate-ddl

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "btree_gist";

-- User tables (CQRS pattern)
CREATE TABLE IF NOT EXISTS tb_user (
    -- Sacred Trinity
    id INTEGER GENERATED BY DEFAULT AS IDENTITY,
    pk_user UUID DEFAULT gen_random_uuid() NOT NULL,
    identifier TEXT,

    -- Fields from @fraise_type
    email TEXT NOT NULL,
    username TEXT NOT NULL,
    full_name TEXT NOT NULL,
    bio TEXT,
    avatar_url TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Constraints
    CONSTRAINT pk_tb_user PRIMARY KEY (id),
    CONSTRAINT uq_tb_user_pk UNIQUE (pk_user),
    CONSTRAINT uq_tb_user_email UNIQUE (email),
    CONSTRAINT uq_tb_user_username UNIQUE (username)
);

-- Query-side view (denormalized)
CREATE TABLE IF NOT EXISTS tv_user (
    id UUID PRIMARY KEY,
    data JSONB NOT NULL
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_tb_user_email ON tb_user(email);
CREATE INDEX IF NOT EXISTS idx_tb_user_username ON tb_user(username);
CREATE INDEX IF NOT EXISTS idx_tb_user_active ON tb_user(is_active);

-- Post tables
CREATE TABLE IF NOT EXISTS tb_post (
    id INTEGER GENERATED BY DEFAULT AS IDENTITY,
    pk_post UUID DEFAULT gen_random_uuid() NOT NULL,
    identifier TEXT,

    fk_user UUID NOT NULL,
    title VARCHAR(500) NOT NULL,
    slug VARCHAR(500) NOT NULL,
    content TEXT NOT NULL,
    excerpt VARCHAR(1000),
    tags TEXT[] DEFAULT ARRAY[]::TEXT[],
    is_published BOOLEAN DEFAULT false,
    published_at TIMESTAMPTZ,
    view_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT pk_tb_post PRIMARY KEY (id),
    CONSTRAINT uq_tb_post_pk UNIQUE (pk_post),
    CONSTRAINT uq_tb_post_slug UNIQUE (slug),
    CONSTRAINT fk_tb_post_user FOREIGN KEY (fk_user)
        REFERENCES tb_user(pk_user) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tv_post (
    id UUID PRIMARY KEY,
    data JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tb_post_author ON tb_post(fk_user);
CREATE INDEX IF NOT EXISTS idx_tb_post_slug ON tb_post(slug);
CREATE INDEX IF NOT EXISTS idx_tb_post_published ON tb_post(is_published);
CREATE INDEX IF NOT EXISTS idx_tb_post_created ON tb_post(created_at);
CREATE INDEX IF NOT EXISTS idx_tb_post_tags ON tb_post USING gin(tags);

-- Comment tables
CREATE TABLE IF NOT EXISTS tb_comment (
    id INTEGER GENERATED BY DEFAULT AS IDENTITY,
    pk_comment UUID DEFAULT gen_random_uuid() NOT NULL,
    identifier TEXT,

    fk_post UUID NOT NULL,
    fk_user UUID NOT NULL,
    fk_parent_comment UUID,
    content TEXT NOT NULL,
    is_edited BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    CONSTRAINT pk_tb_comment PRIMARY KEY (id),
    CONSTRAINT uq_tb_comment_pk UNIQUE (pk_comment),
    CONSTRAINT fk_tb_comment_post FOREIGN KEY (fk_post)
        REFERENCES tb_post(pk_post) ON DELETE CASCADE,
    CONSTRAINT fk_tb_comment_user FOREIGN KEY (fk_user)
        REFERENCES tb_user(pk_user) ON DELETE CASCADE,
    CONSTRAINT fk_tb_comment_parent FOREIGN KEY (fk_parent_comment)
        REFERENCES tb_comment(pk_comment) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tv_comment (
    id UUID PRIMARY KEY,
    data JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tb_comment_post ON tb_comment(fk_post);
CREATE INDEX IF NOT EXISTS idx_tb_comment_user ON tb_comment(fk_user);
CREATE INDEX IF NOT EXISTS idx_tb_comment_parent ON tb_comment(fk_parent_comment);
```

### CQRS Pattern Explained

FraiseQL uses the **Command Query Responsibility Segregation (CQRS)** pattern:

**Command Side (tb_* tables)**:
- Normalized tables for writes (INSERT, UPDATE, DELETE)
- Strong constraints and foreign keys
- Optimized for data integrity

**Query Side (tv_* tables)**:
- Denormalized JSONB for reads (SELECT)
- Pre-computed aggregations
- Optimized for query performance

```
Write → tb_post → Sync → tv_post → Read
         ↑                  ↑
      (normalized)    (denormalized)
```

---

## Step 3: Build Database with Confiture

### Configure Confiture

**confiture.yaml**:

```yaml
project:
  name: fraiseql-blog
  description: Blog API with FraiseQL + Confiture

environments:
  local:
    database:
      host: localhost
      port: 5432
      database: fraiseql_blog
      user: postgres
      password: postgres

    schema_dirs:
      - db/schema/00_extensions
      - db/schema/10_tables
      - db/schema/20_indexes

    migrations_dir: db/migrations

  production:
    database:
      host: ${DB_HOST}
      port: ${DB_PORT}
      database: ${DB_NAME}
      user: ${DB_USER}
      password: ${DB_PASSWORD}

    schema_dirs:
      - db/schema/00_extensions
      - db/schema/10_tables
      - db/schema/20_indexes

    migrations_dir: db/migrations
```

### Build the Database

```bash
# Build database from DDL files (Medium 1)
confiture build --env local

# Expected output:
# Building schema for environment: local
# Found 3 SQL files:
#   ✓ db/schema/00_extensions/extensions.sql
#   ✓ db/schema/10_tables/generated.sql
#   ✓ db/schema/20_indexes/indexes.sql
# Executing schema...
# ✅ Schema built successfully in 0.4s
```

### Verify Database

```bash
# List tables
psql fraiseql_blog -c "\dt"

#  Schema |    Name     | Type  |  Owner
# --------+-------------+-------+---------
#  public | tb_user     | table | postgres
#  public | tv_user     | table | postgres
#  public | tb_post     | table | postgres
#  public | tv_post     | table | postgres
#  public | tb_comment  | table | postgres
#  public | tv_comment  | table | postgres

# Describe tb_user table
psql fraiseql_blog -c "\d tb_user"

#                        Table "public.tb_user"
#    Column    |           Type           | Nullable | Default
# -------------+--------------------------+----------+-------------------
#  id          | integer                  | not null | nextval('...')
#  pk_user     | uuid                     | not null | gen_random_uuid()
#  identifier  | text                     |          |
#  email       | text                     | not null |
#  username    | text                     | not null |
#  full_name   | text                     | not null |
#  bio         | text                     |          |
#  avatar_url  | text                     |          |
#  is_active   | boolean                  |          | true
#  created_at  | timestamptz              |          | now()
#  updated_at  | timestamptz              |          | now()
```

**That's it!** Your database is ready in under 1 second.

---

## Step 4: Run the GraphQL API

### FastAPI Application

**app.py**:

```python
"""
FastAPI + FraiseQL Blog API

Demonstrates:
1. GraphQL schema from @fraise_type decorators
2. CQRS pattern with explicit sync
3. Type-safe resolvers
"""

from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from strawberry.fastapi import GraphQLRouter

from schema import schema


# Global database pool
db_pool: asyncpg.Pool = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    global db_pool

    # Startup: Create database pool
    db_pool = await asyncpg.create_pool(
        "postgresql://postgres:postgres@localhost/fraiseql_blog",
        min_size=5,
        max_size=20
    )
    print("✓ Database connection pool created")

    yield

    # Shutdown: Close database pool
    await db_pool.close()
    print("✓ Database connections closed")


# Create FastAPI app
app = FastAPI(
    title="FraiseQL Blog API",
    description="Blog API with FraiseQL + Confiture",
    version="1.0.0",
    lifespan=lifespan
)


# GraphQL context provider
async def get_context():
    """Provide database pool to GraphQL resolvers."""
    return {"db_pool": db_pool}


# Mount GraphQL router
graphql_app = GraphQLRouter(schema, context_getter=get_context)
app.include_router(graphql_app, prefix="/graphql")


@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "name": "FraiseQL Blog API",
        "graphql": "/graphql",
        "health": "/health"
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    try:
        async with db_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

### Run the Server

```bash
# Install server dependencies
pip install fastapi uvicorn strawberry-graphql asyncpg

# Run the application
python app.py

# Expected output:
# ✓ Database connection pool created
# INFO:     Uvicorn running on http://0.0.0.0:8000
# INFO:     Application startup complete
```

### Access GraphQL Playground

Open browser to: **http://localhost:8000/graphql**

You'll see the GraphQL Playground with auto-generated schema documentation!

---

## Step 5: Test GraphQL Queries

### Create a User

```graphql
mutation CreateUser {
  createUser(
    email: "alice@example.com"
    username: "alice"
    fullName: "Alice Johnson"
    bio: "Software engineer and tech blogger"
  ) {
    id
    email
    username
    fullName
    createdAt
  }
}
```

**Response**:
```json
{
  "data": {
    "createUser": {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "email": "alice@example.com",
      "username": "alice",
      "fullName": "Alice Johnson",
      "createdAt": "2025-10-12T10:30:00Z"
    }
  }
}
```

### Create a Post

```graphql
mutation CreatePost {
  createPost(
    authorId: "550e8400-e29b-41d4-a716-446655440000"
    title: "Getting Started with FraiseQL"
    slug: "getting-started-fraiseql"
    content: "FraiseQL makes GraphQL development a breeze..."
    excerpt: "Learn how to build GraphQL APIs with FraiseQL"
    tags: ["graphql", "python", "tutorial"]
    isPublished: true
  ) {
    id
    title
    slug
    author {
      username
      fullName
    }
    tags
    createdAt
  }
}
```

### Query Posts

```graphql
query GetPosts {
  posts(publishedOnly: true, limit: 10) {
    id
    title
    slug
    excerpt
    author {
      username
      fullName
    }
    tags
    commentCount
    viewCount
    createdAt
  }
}
```

### Query Single Post

```graphql
query GetPost {
  post(id: "550e8400-e29b-41d4-a716-446655440000") {
    id
    title
    content
    author {
      username
      fullName
      bio
    }
    comments {
      id
      content
      author {
        username
      }
      createdAt
    }
    createdAt
    updatedAt
  }
}
```

### Create a Comment

```graphql
mutation CreateComment {
  createComment(
    postId: "550e8400-e29b-41d4-a716-446655440000"
    authorId: "660e8400-e29b-41d4-a716-446655440000"
    content: "Great article! Very helpful."
  ) {
    id
    content
    author {
      username
    }
    createdAt
  }
}
```

---

## Step 6: Schema Evolution

### Adding New Fields

Let's add a `view_count` field to posts (already in schema, let's demonstrate the workflow):

**Step 1: Update schema.py**

```python
@fraise_type
class Post:
    # ... existing fields ...

    # New field
    view_count: int = Field(default=0)
```

**Step 2: Regenerate DDL**

```bash
fraiseql generate-ddl schema.py --output db/schema/10_tables/
```

**Step 3: Create Migration**

For existing databases, create a migration:

**db/migrations/001_add_post_views.py**:

```python
"""Add view_count to posts

This migration adds view tracking to blog posts.
"""

from confiture.models.migration import Migration


class AddPostViews(Migration):
    """Add view_count to posts."""

    version = "001"
    name = "add_post_views"

    def up(self) -> None:
        """Apply migration: Add view_count column."""
        self.execute("""
            ALTER TABLE tb_post
            ADD COLUMN IF NOT EXISTS view_count INTEGER DEFAULT 0
        """)

        # Create index for sorting by popularity
        self.execute("""
            CREATE INDEX IF NOT EXISTS idx_tb_post_views
            ON tb_post(view_count DESC)
        """)

    def down(self) -> None:
        """Rollback migration: Remove view_count."""
        self.execute("""
            DROP INDEX IF EXISTS idx_tb_post_views
        """)

        self.execute("""
            ALTER TABLE tb_post
            DROP COLUMN IF EXISTS view_count
        """)
```

**Step 4: Apply Migration**

```bash
# Check migration status
confiture migrate status --env local

# Expected output:
# ⏳ 001_add_post_views (pending)

# Apply migration
confiture migrate up --env local

# Expected output:
# Applying migration 001_add_post_views...
# ✅ Migration 001_add_post_views applied successfully (52ms)
```

**Step 5: Test New Field**

```graphql
query GetPopularPosts {
  posts(orderBy: "view_count", limit: 10) {
    id
    title
    viewCount
    author {
      username
    }
  }
}
```

### Fresh Database Still Works

The beauty of Confiture: fresh databases don't need migrations!

```bash
# Drop and recreate
dropdb fraiseql_blog
createdb fraiseql_blog

# Build from updated DDL files (includes view_count)
confiture build --env local

# Database has all fields without running migrations!
```

---

## Advanced Patterns

### Pattern 1: Type-Safe Foreign Keys

```python
@fraise_type
class Comment:
    # Type-safe foreign key reference
    post_id: str = Field(foreign_key="Post.id", index=True)
    author_id: str = Field(foreign_key="User.id", index=True)
```

FraiseQL automatically:
- Creates foreign key constraints
- Adds indexes for join performance
- Validates references at database level

### Pattern 2: Composite Indexes

```python
@fraise_type
class Post:
    author_id: str = Field(foreign_key="User.id")
    is_published: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Meta:
        indexes = [
            ("author_id", "is_published"),  # Composite index
            ("is_published", "created_at"),  # Published posts by date
        ]
```

### Pattern 3: Custom Constraints

```python
@fraise_type
class User:
    email: str = Field(unique=True)
    username: str = Field(unique=True)

    class Meta:
        constraints = [
            # Email must contain @
            "CHECK (email LIKE '%@%')",

            # Username length
            "CHECK (LENGTH(username) >= 3 AND LENGTH(username) <= 30)",
        ]
```

### Pattern 4: JSON Fields

```python
@fraise_type
class Post:
    # Store structured metadata as JSONB
    metadata: dict = Field(default_factory=dict)

    # Example metadata:
    # {
    #   "reading_time_minutes": 5,
    #   "featured_image": "https://...",
    #   "seo": {"title": "...", "description": "..."}
    # }
```

### Pattern 5: Array Fields

```python
@fraise_type
class Post:
    # PostgreSQL array for tags
    tags: list[str] = Field(default_factory=list)

    # GIN index for fast array searches
    class Meta:
        indexes = [
            ("tags", "gin"),  # Full-text search on tags
        ]
```

Query tags with PostgreSQL operators:

```sql
-- Posts with specific tag
SELECT * FROM tb_post WHERE 'python' = ANY(tags);

-- Posts with any of multiple tags
SELECT * FROM tb_post WHERE tags && ARRAY['python', 'graphql'];

-- Posts with all tags
SELECT * FROM tb_post WHERE tags @> ARRAY['python', 'tutorial'];
```

---

## Troubleshooting

### Issue: DDL Generation Fails

**Symptom**:
```bash
fraiseql generate-ddl schema.py
# Error: No @fraise_type decorators found
```

**Solution**: Ensure your types use `@fraise_type` decorator:
```python
from fraiseql import fraise_type

@fraise_type  # Don't forget this!
class User:
    id: str
    email: str
```

### Issue: Database Build Fails

**Symptom**:
```bash
confiture build --env local
# Error: relation "tb_user" already exists
```

**Solution**: Drop and rebuild:
```bash
dropdb fraiseql_blog
createdb fraiseql_blog
confiture build --env local
```

Or use `IF NOT EXISTS` in your DDL:
```sql
CREATE TABLE IF NOT EXISTS tb_user (...);
```

### Issue: GraphQL Type Mismatch

**Symptom**:
```
GraphQL error: Cannot return null for non-nullable field User.email
```

**Solution**: Ensure database has non-null constraints:
```python
# In schema.py
email: str  # Non-nullable

# Generated SQL
email TEXT NOT NULL
```

### Issue: Migration Out of Sync

**Symptom**:
```bash
confiture migrate up
# Error: Migration 001 already applied
```

**Solution**: Check migration status:
```bash
# View applied migrations
confiture migrate status --env local

# Reset migration history (development only!)
psql fraiseql_blog -c "DROP TABLE IF EXISTS confiture_migrations CASCADE"
confiture migrate up --env local
```

---

## Next Steps

### Explore More Examples

- **[01-basic-migration](../01-basic-migration/)** - Learn Confiture fundamentals
- **[03-zero-downtime-migration](../03-zero-downtime-migration/)** - Production deployments
- **[04-production-sync-anonymization](../04-production-sync-anonymization/)** - Data syncing
- **[05-multi-environment-workflow](../05-multi-environment-workflow/)** - CI/CD integration

### Read the Guides

- **[FraiseQL Documentation](https://fraiseql.readthedocs.io/)** - Complete FraiseQL guide
- **[Confiture Migration Strategies](../../docs/guides/migration-strategies.md)** - When to use each medium
- **[CQRS Pattern Guide](../../docs/guides/cqrs-pattern.md)** - Command/query separation

### Production Deployment

1. **Use environment variables** for database credentials
2. **Enable connection pooling** (FraiseQL handles this automatically)
3. **Set up monitoring** for sync performance
4. **Test migrations** on staging before production
5. **Use confiture sync** for production data replication

---

## Summary

You've learned:

- ✅ **Single source of truth**: Define schema once in Python types
- ✅ **Auto-generated DDL**: FraiseQL generates PostgreSQL schema
- ✅ **Instant builds**: Confiture builds databases in <1 second
- ✅ **Type safety**: End-to-end type checking from GraphQL to PostgreSQL
- ✅ **CQRS pattern**: Separate command/query tables for performance
- ✅ **Schema evolution**: Migrations for existing databases, DDL for fresh ones

### Key Commands

```bash
# Generate DDL from GraphQL schema
fraiseql generate-ddl schema.py --output db/schema/

# Build database from DDL
confiture build --env local

# Apply migrations
confiture migrate up --env local

# Check migration status
confiture migrate status --env local
```

### The Workflow

```
1. Edit schema.py (source of truth)
2. fraiseql generate-ddl (update DDL)
3. confiture build (instant database)
4. python app.py (run GraphQL API)
5. Test queries (GraphQL playground)
```

---

**Part of the Confiture examples** 🍓

*GraphQL-first development with instant database builds*
