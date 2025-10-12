# Basic Example: Simple Blog Application

**A complete example showing Confiture organization patterns for a small project**

This example demonstrates:
- ✅ Numbered directory prefixes for execution order
- ✅ Environment-specific configurations
- ✅ Seed data management (development/test/production)
- ✅ Clean schema organization
- ✅ Migration generation and application

## Schema

```
blog_app
├── users       (id, username, email, bio, created_at)
├── posts       (id, user_id, title, content, published_at)
└── comments    (id, post_id, user_id, content, created_at)
```

## Quick Start

### 1. Install Confiture

```bash
pip install confiture
```

### 2. Set Up Database

```bash
# Create PostgreSQL database
createdb blog_app_local

# Or using psql
psql -U postgres -c "CREATE DATABASE blog_app_local;"
```

### 3. Configure Environment

Edit `db/environments/local.yaml`:

```yaml
name: local
include_dirs:
  - db/schema/00_common
  - db/schema/10_tables
exclude_dirs: []

database:
  host: localhost
  port: 5432
  database: blog_app_local
  user: postgres
  password: postgres  # Change this!
```

### 4. Apply Initial Migration

```bash
# Apply migrations
confiture migrate up --config db/environments/local.yaml
```

### 5. Verify Schema

```bash
# Check status
confiture migrate status --config db/environments/local.yaml

# Connect to database
psql blog_app_local

# List tables
\dt

# Describe users table
\d users
```

## Step-by-Step Tutorial

### Step 1: Initial Setup

The example includes an initial migration (`001_create_initial_schema.py`) that creates:
- `users` table
- `posts` table
- `comments` table
- Necessary indexes and foreign keys

```bash
confiture migrate up --config db/environments/local.yaml
```

Output:
```
📦 Found 1 pending migration(s)

⚡ Applying 001_create_initial_schema... ✅

✅ Successfully applied 1 migration(s)!
```

### Step 2: Add User Bio Column

Let's add a `bio` column to users:

```bash
# 1. Edit schema file
vim db/schema/10_tables/users.sql
# Add: bio TEXT

# 2. Generate diff (create temp old schema first)
pg_dump blog_app_local --schema-only > /tmp/old_schema.sql

# 3. Generate migration
confiture migrate diff /tmp/old_schema.sql db/schema/10_tables/users.sql \
    --generate \
    --name add_user_bio

# 4. Apply migration
confiture migrate up --config db/environments/local.yaml
```

### Step 3: Verify Changes

```sql
-- psql blog_app_local
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'users'
ORDER BY ordinal_position;
```

### Step 4: Test Rollback

```bash
# Rollback last migration
confiture migrate down --config db/environments/local.yaml

# Verify bio column is gone
psql blog_app_local -c "\d users"

# Re-apply if needed
confiture migrate up --config db/environments/local.yaml
```

## Migration Files

### 001_create_initial_schema.py

Creates the initial database schema with three tables:

```python
def up(self) -> None:
    """Apply migration."""
    # Create users table
    self.execute("""
        CREATE TABLE users (
            id SERIAL PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    # Create posts table
    self.execute("""
        CREATE TABLE posts (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            published_at TIMESTAMP DEFAULT NOW()
        )
    """)

    # Create comments table
    self.execute("""
        CREATE TABLE comments (
            id SERIAL PRIMARY KEY,
            post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    # Create indexes
    self.execute("CREATE INDEX idx_users_username ON users(username)")
    self.execute("CREATE INDEX idx_users_email ON users(email)")
    self.execute("CREATE INDEX idx_posts_user_id ON posts(user_id)")
    self.execute("CREATE INDEX idx_posts_published_at ON posts(published_at)")
    self.execute("CREATE INDEX idx_comments_post_id ON comments(post_id)")
    self.execute("CREATE INDEX idx_comments_user_id ON comments(user_id)")
```

## Testing the Schema

### Insert Sample Data

```sql
-- Insert users
INSERT INTO users (username, email) VALUES
    ('alice', 'alice@example.com'),
    ('bob', 'bob@example.com');

-- Insert posts
INSERT INTO posts (user_id, title, content) VALUES
    (1, 'My First Post', 'Hello world!'),
    (1, 'Second Post', 'More content...');

-- Insert comments
INSERT INTO comments (post_id, user_id, content) VALUES
    (1, 2, 'Great post!'),
    (2, 2, 'Nice!');
```

### Query the Data

```sql
-- Get all posts with author
SELECT
    p.title,
    p.content,
    u.username AS author,
    p.published_at
FROM posts p
JOIN users u ON p.user_id = u.id
ORDER BY p.published_at DESC;

-- Get post with comments
SELECT
    p.title,
    c.content AS comment,
    u.username AS commenter,
    c.created_at
FROM posts p
LEFT JOIN comments c ON c.post_id = p.id
LEFT JOIN users u ON c.user_id = u.id
WHERE p.id = 1
ORDER BY c.created_at;
```

## Common Operations

### Add a New Index

```bash
# 1. Edit schema file to add index
echo "CREATE INDEX idx_posts_title ON posts(title);" >> db/schema/10_tables/posts.sql

# 2. Generate migration
confiture migrate generate add_posts_title_index

# 3. Edit migration file
vim db/migrations/00X_add_posts_title_index.py

# Add:
# def up(self):
#     self.execute("CREATE INDEX idx_posts_title ON posts(title)")
#
# def down(self):
#     self.execute("DROP INDEX idx_posts_title")

# 4. Apply
confiture migrate up --config db/environments/local.yaml
```

### Add a New Table

```bash
# 1. Create schema file
cat > db/schema/10_tables/tags.sql << 'EOF'
CREATE TABLE tags (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE post_tags (
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (post_id, tag_id)
);
EOF

# 2. Generate migration
confiture migrate generate add_tags

# 3. Edit migration file to include table creation

# 4. Apply
confiture migrate up --config db/environments/local.yaml
```

### Modify Column Type

```bash
# Example: Change username from TEXT to VARCHAR(50)

# 1. Generate migration
confiture migrate generate limit_username_length

# 2. Edit migration
vim db/migrations/00X_limit_username_length.py

# Add:
# def up(self):
#     self.execute("ALTER TABLE users ALTER COLUMN username TYPE VARCHAR(50)")
#
# def down(self):
#     self.execute("ALTER TABLE users ALTER COLUMN username TYPE TEXT")

# 3. Apply
confiture migrate up --config db/environments/local.yaml
```

## Directory Structure

```
examples/basic/
├── README.md                           # This file
├── db/
│   ├── schema/                         # DDL: Single source of truth
│   │   ├── 00_common/
│   │   │   └── extensions.sql          # Load first: PostgreSQL extensions
│   │   └── 10_tables/
│   │       ├── users.sql               # Core tables
│   │       ├── posts.sql               # Posts depend on users
│   │       └── comments.sql            # Comments depend on posts
│   │
│   ├── seeds/                          # INSERT statements
│   │   ├── common/                     # All non-prod environments
│   │   │   └── 00_users.sql            # 3 test users (admin, editor, reader)
│   │   ├── development/                # Dev-specific seeds
│   │   │   ├── 00_posts.sql            # 6 sample blog posts
│   │   │   └── 01_comments.sql         # 7 comments on posts
│   │   └── test/                       # Test-specific seeds
│   │       └── 00_posts.sql            # 3 minimal test posts
│   │
│   ├── environments/                   # Environment configurations
│   │   ├── local.yaml                  # Local: schema + common + dev seeds
│   │   ├── test.yaml                   # Test: schema + common + test seeds
│   │   └── production.yaml             # Production: schema only, no seeds!
│   │
│   ├── migrations/                     # Generated migrations
│   │   └── 001_create_initial_schema.py
│   └── generated/                      # Built schema files (git-ignored)
│       ├── schema_local.sql
│       ├── schema_test.sql
│       └── schema_production.sql
│
└── .gitignore
```

### File Numbering Pattern

**Top-Level Directories:**
```
00_common/     Extensions, types (load first)
10_tables/     Core tables
20_views/      Views (if we had them)
30_functions/  Functions (if we had them)
```

**Why numbered?**
- Deterministic execution order (00 before 10 before 20)
- Leave gaps (00, 10, 20) to insert new categories later
- Clear intent: numbers show dependency order

**Seed Files:**
```
seeds/
├── common/
│   └── 00_users.sql          # Load users first
├── development/
│   ├── 00_posts.sql          # Then posts (reference users)
│   └── 01_comments.sql       # Then comments (reference posts)
└── test/
    └── 00_posts.sql          # Minimal posts for tests
```

**See [docs/organizing-sql-files.md](../../docs/organizing-sql-files.md)** for detailed patterns.

## Configuration

### local.yaml

```yaml
name: local
include_dirs:
  - db/schema/00_common
  - db/schema/10_tables
exclude_dirs: []

database:
  host: localhost
  port: 5432
  database: blog_app_local
  user: postgres
  password: postgres
```

### Environment Configurations

#### Local Development (`local.yaml`)

```yaml
name: local

# Include schema + common seeds + development seeds
includes:
  - ../schema
  - ../seeds/common
  - ../seeds/development

database_url: postgresql://postgres:postgres@localhost:5432/blog_app_local
```

**Result**: Full database with realistic test data for development.

#### Test Environment (`test.yaml`)

```yaml
name: test

# Include schema + common seeds + minimal test seeds
includes:
  - ../schema
  - ../seeds/common
  - ../seeds/test

database_url: postgresql://postgres:postgres@localhost:5432/blog_app_test
```

**Result**: Minimal data optimized for fast test execution.

#### Production (`production.yaml`)

```yaml
name: production

# Schema ONLY - no seed data!
includes:
  - ../schema

database_url: ${DATABASE_URL}
```

**Result**: Clean schema, no test data accidentally in production.

**Usage**:
```bash
export DATABASE_URL=postgresql://user:pass@prod-db.example.com:5432/blog_app_production
confiture build --env production
```

## Troubleshooting

### "Database connection failed"

```bash
# Check PostgreSQL is running
pg_isready

# Test connection
psql -h localhost -U postgres -d blog_app_local

# Check config file
cat db/environments/local.yaml
```

### "Migration already applied"

```bash
# Check status
confiture migrate status --config db/environments/local.yaml

# If migration was partially applied, rollback
confiture migrate down --config db/environments/local.yaml
```

### "Table already exists"

Migration was partially applied. Either:

1. Manually drop the table:
```sql
DROP TABLE comments CASCADE;
DROP TABLE posts CASCADE;
DROP TABLE users CASCADE;
```

2. Or reset tracking:
```sql
DELETE FROM confiture_migrations WHERE version = '001';
```

Then re-apply:
```bash
confiture migrate up --config db/environments/local.yaml
```

## Understanding Seed Data

### Common Seeds (`seeds/common/00_users.sql`)

```sql
-- Test users for all non-production environments
-- Fixed UUIDs for referential integrity in seed data

INSERT INTO users (id, username, email, password_hash, bio) VALUES
    (
        '00000000-0000-0000-0000-000000000001',
        'admin',
        'admin@example.com',
        '$2b$12$...',  -- bcrypt hash
        'System administrator'
    ),
    ('00000000-0000-0000-0000-000000000002', 'editor', 'editor@example.com', '$2b$12$...', 'Content editor'),
    ('00000000-0000-0000-0000-000000000003', 'reader', 'reader@example.com', '$2b$12$...', 'Regular user');
```

**Why fixed UUIDs?**
- Allows seed files to reference specific users
- Deterministic: Same UUIDs every build
- Easy to test: `author_id = '00000000-0000-0000-0000-000000000001'`

**See [Meaningful Test UUIDs](../../docs/meaningful-test-uuids.md)** for advanced patterns to encode table, scenario, and context information directly into UUIDs for better debuggability.

### Development Seeds

**`seeds/development/00_posts.sql`**: 6 sample blog posts
**`seeds/development/01_comments.sql`**: 7 comments across posts

These reference common seed UUIDs for foreign keys.

### Test Seeds

**`seeds/test/00_posts.sql`**: 3 minimal posts only

Minimal data for fast test execution.

## Working with Seeds

### Build with Seeds

```bash
# Local: includes schema + common + development seeds
confiture build --env local

# Test: includes schema + common + test seeds
confiture build --env test

# Production: schema only, no seeds
confiture build --env production
```

### Override: Build Without Seeds

```bash
# Skip seeds on any environment
confiture build --env local --schema-only
```

### Verify Build Plan

```bash
confiture build --env local --dry-run
```

**Output**:
```
📋 Build Plan for environment: local

📂 Files to process (7 total):
  ✓ db/schema/00_common/extensions.sql
  ✓ db/schema/10_tables/users.sql
  ✓ db/schema/10_tables/posts.sql
  ✓ db/schema/10_tables/comments.sql
  ✓ db/seeds/common/00_users.sql
  ✓ db/seeds/development/00_posts.sql
  ✓ db/seeds/development/01_comments.sql

📊 Output: 8,262 bytes (7 files)
```

## Next Steps

- **[Organizing SQL Files](../../docs/organizing-sql-files.md)** - Patterns for complex schemas
- **[Getting Started Guide](../../docs/getting-started.md)** - Complete walkthrough
- **[CLI Reference](../../docs/reference/cli.md)** - All commands documented
- **[Migration Strategies](../../docs/migration-strategies.md)** - When to use each approach

## Resources

- **Confiture Documentation**: https://github.com/fraiseql/confiture
- **FraiseQL**: https://github.com/fraiseql/fraiseql
- **PostgreSQL Docs**: https://www.postgresql.org/docs/

---

**Part of the FraiseQL family** 🍓

*Vibe-engineered with ❤️ by [evoludigit](https://github.com/evoludigit)*
