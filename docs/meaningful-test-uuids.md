# Meaningful Test UUIDs for Seed Data

**Generate human-readable, debuggable UUIDs for test and development environments**

---

## The Modern Identity Trinity Pattern

Modern PostgreSQL tables use **three identifiers** for different purposes:

```sql
CREATE TABLE tb_user (
    -- 1. Integer identity: Fast joins, sequences, migrations
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,

    -- 2. UUID primary key: External references, distributed systems, public APIs
    pk_user UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),

    -- 3. Human-readable slug: URLs, search, user-facing
    identifier TEXT NOT NULL UNIQUE,

    username TEXT NOT NULL,
    email TEXT NOT NULL
);
```

**Why three identifiers?**
- **`id`**: Fast integer for internal joins and ordering
- **`pk_user`**: Stable UUID for external systems and APIs (never changes)
- **`identifier`**: Human-readable slug for URLs and user-facing features

**Foreign keys** typically reference the UUID (`pk_user`) for stability across systems.

---

## The Problem with Random UUIDs

Traditional approach with random UUIDs:

```sql
-- Random UUIDs are hard to debug
INSERT INTO tb_user (pk_user, identifier, username, email) VALUES
    ('7f3e8c2a-9d41-4b5f-a8e3-1c9d7e2b4f6a', 'alice', 'Alice', 'alice@example.com'),
    ('3a9f7d4e-2b8c-4f1a-9e3d-8c7b6a5f4e3d', 'bob', 'Bob', 'bob@example.com');

INSERT INTO tb_post (pk_post, fk_author, identifier, title) VALUES
    ('9e4f7c3a-8d2b-4a1f-b7e9-3d8c7f6a5e4b', '7f3e8c2a-9d41-4b5f-a8e3-1c9d7e2b4f6a', 'first-post', 'First Post');
    -- Which user is fk_author referencing? Hard to tell!
```

**Problems**:
- ❌ Hard to recognize entities in logs
- ❌ Difficult to debug foreign key relationships
- ❌ Can't tell what UUID references what
- ❌ Copy-paste errors are common
- ❌ Test assertions are unreadable

---

## Solution: Semantic UUID Encoding

Encode meaningful information directly into test UUIDs using a structured pattern:

```
{table}-{type}-{scenario}-{variant}-{context}-{sequence}

Example:
01010000-1000-0001-0000-0000-00000001
│       │    │    │    │    │
│       │    │    │    │    └─ Sequence: 1st record
│       │    │    │    └────── Context: 0000 = common, 1000 = test-specific
│       │    │    └─────────── Variant: entity subtype
│       │    └──────────────── Scenario: which test/seed file
│       └───────────────────── Type: entity type within table
└───────────────────────────── Table: which table
```

---

## Basic Pattern

### Simple Projects: Table + Sequence

```sql
-- Pattern: {table_code}000000-0000-0000-0000-0000-{sequence}

-- Users table (code: 01, naming: tb_user)
CREATE TABLE tb_user (
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    pk_user UUID NOT NULL UNIQUE,
    identifier TEXT NOT NULL UNIQUE,
    username TEXT NOT NULL,
    email TEXT NOT NULL
);

INSERT INTO tb_user (pk_user, identifier, username, email) VALUES
    ('01000000-0000-0000-0000-000000000001', 'admin', 'Admin User', 'admin@example.com'),
    ('01000000-0000-0000-0000-000000000002', 'editor', 'Editor User', 'editor@example.com'),
    ('01000000-0000-0000-0000-000000000003', 'reader', 'Reader User', 'reader@example.com');

-- Posts table (code: 02, naming: tb_post)
CREATE TABLE tb_post (
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    pk_post UUID NOT NULL UNIQUE,
    fk_author UUID NOT NULL REFERENCES tb_user(pk_user),
    identifier TEXT NOT NULL UNIQUE,  -- Slug for URLs
    title TEXT NOT NULL
);

INSERT INTO tb_post (pk_post, fk_author, identifier, title) VALUES
    ('02000000-0000-0000-0000-000000000001', '01000000-0000-0000-0000-000000000001', 'welcome-post', 'Welcome Post'),
    ('02000000-0000-0000-0000-000000000002', '01000000-0000-0000-0000-000000000001', 'second-post', 'Second Post');

-- Comments table (code: 03, naming: tb_comment)
CREATE TABLE tb_comment (
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    pk_comment UUID NOT NULL UNIQUE,
    fk_post UUID NOT NULL REFERENCES tb_post(pk_post),
    fk_author UUID NOT NULL REFERENCES tb_user(pk_user),
    identifier TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL
);

INSERT INTO tb_comment (pk_comment, fk_post, fk_author, identifier, content) VALUES
    ('03000000-0000-0000-0000-000000000001', '02000000-0000-0000-0000-000000000001', '01000000-0000-0000-0000-000000000002', 'comment-1-on-welcome', 'Great post!');
```

**Benefits**:
- ✅ Instantly recognize table by first 2 digits: `01` = tb_user, `02` = tb_post
- ✅ Foreign keys are readable: `fk_author = '01...'` clearly references tb_user
- ✅ Sequence number at end: `...0001`, `...0002`, `...0003`
- ✅ Integer `id` for fast joins, UUID `pk_*` for stability, `identifier` for humans

---

## Intermediate Pattern: Scenario + Sequence

Add scenario identifier for test-specific data:

```sql
-- Pattern: {table}-{scenario}-0000-0000-0000-{sequence}

-- Common seed data (scenario: 0000)
INSERT INTO tb_user (pk_user, identifier, username, email) VALUES
    ('01000000-0000-0000-0000-000000000001', 'admin', 'Admin', 'admin@example.com'),
    ('01000000-0000-0000-0000-000000000002', 'editor', 'Editor', 'editor@example.com');

-- Test scenario: user authentication (scenario: 1001)
INSERT INTO tb_user (pk_user, identifier, username, email, password_hash, locked) VALUES
    ('01000000-1001-0000-0000-000000000001', 'test-user-valid', 'Test Valid', 'valid@test.com', '$2b$...', false),
    ('01000000-1001-0000-0000-000000000002', 'test-user-locked', 'Test Locked', 'locked@test.com', '$2b$...', true);

-- Test scenario: user permissions (scenario: 1002)
INSERT INTO tb_user (pk_user, identifier, username, email) VALUES
    ('01000000-1002-0000-0000-000000000001', 'test-admin-perms', 'Test Admin', 'admin_perms@test.com'),
    ('01000000-1002-0000-0000-000000000002', 'test-readonly-perms', 'Test Readonly', 'readonly@test.com');
```

**Benefits**:
- ✅ Scenario code tells you which test: `1001` = auth tests, `1002` = permission tests
- ✅ Easy to clean up: `DELETE FROM tb_user WHERE pk_user::text LIKE '01000000-1001-%'`
- ✅ Group related test data together

---

## Advanced Pattern: Full Semantic Encoding

For complex domains with multiple entity types:

```sql
-- Pattern: {table}{type}-{scenario}-{variant}-{context}-{sequence}

-- Users table (table: 010, naming: tb_user)
-- User types: 10=admin, 20=editor, 30=regular
INSERT INTO tb_user (pk_user, identifier, username, email, role) VALUES
    ('01010000-0000-0000-0000-000000000001', 'admin', 'Admin User', 'admin@example.com', 'admin'),
    ('01020000-0000-0000-0000-000000000001', 'editor', 'Editor User', 'editor@example.com', 'editor'),
    ('01030000-0000-0000-0000-000000000001', 'reader', 'Reader User', 'reader@example.com', 'user');

-- Organizations table (table: 020, naming: tb_organization)
-- Org types: 10=company, 20=department, 30=team
INSERT INTO tb_organization (pk_organization, identifier, name, type) VALUES
    ('02010000-0000-0000-0000-000000000001', 'acme-corp', 'Acme Corp', 'company'),
    ('02020000-0000-0000-0000-000000000001', 'engineering', 'Engineering', 'department'),
    ('02030000-0000-0000-0000-000000000001', 'backend-team', 'Backend Team', 'team');

-- Test-specific context (context: 1000)
INSERT INTO tb_user (pk_user, identifier, username, email) VALUES
    ('01010000-2001-0000-1000-000000000001', 'test-delete-user', 'Test Delete', 'delete@test.com');
    -- 01 = tb_user, 010 = admin type, 2001 = delete test, 1000 = test context
```

---

## Table Naming Convention

Follow the **`tb_entity`** naming pattern for consistency:

```sql
-- Good: Consistent tb_ prefix
tb_user              -- Not "users"
tb_post              -- Not "posts"
tb_comment           -- Not "comments"
tb_organization      -- Not "organizations"
tb_organizational_unit  -- Singular, even if conceptually plural

-- UUID columns: pk_{entity}
pk_user, pk_post, pk_comment

-- Foreign keys: fk_{referenced_entity}
fk_author   (references pk_user)
fk_post     (references pk_post)
fk_parent   (references same table)
```

**Why singular?**
- Consistent with ORM conventions
- Easier to generate: `tb_{entity_name}`
- Clearer foreign keys: `fk_user` vs `fk_users`

## Table Code Assignment

### Strategy 1: Sequential Assignment

Assign codes as you create tables:

```
01 = tb_user
02 = tb_post
03 = tb_comment
04 = tb_tag
05 = tb_category
...
```

### Strategy 2: Domain-Based Assignment

Group related tables by code prefix:

```
User Domain (01-09):
  01 = tb_user
  02 = tb_user_profile
  03 = tb_user_session

Content Domain (10-19):
  10 = tb_post
  11 = tb_comment
  12 = tb_reaction

Catalog Domain (20-29):
  20 = tb_category
  21 = tb_tag
  22 = tb_label
```

### Strategy 3: Schema-Based Assignment

Mirror your directory structure:

```
db/schema/10_users/       → Table codes 100-199 (tb_user, tb_user_profile)
db/schema/20_content/     → Table codes 200-299 (tb_post, tb_comment)
db/schema/30_catalog/     → Table codes 300-399 (tb_category, tb_tag)
```

---

## Scenario Code Convention

Use meaningful 4-digit scenario codes:

```
0000        = Common seed data (all environments)
1000-1999   = Development seed data
2000-2999   = Test scenarios (by feature)
3000-3999   = Integration test scenarios
9000-9999   = Edge cases and regression tests

Examples:
0000 = Common users (admin, editor, reader)
1001 = Rich dev data for UI work
2001 = Authentication tests
2002 = Authorization tests
2003 = Password reset tests
3001 = API integration tests
9001 = Edge case: deleted user references
```

---

## Context Flags

Use the 4th segment for context:

```
0000 = Regular/persistent data
1000 = Test-specific (can be deleted)
2000 = Temporary/transient
3000 = Mock/stub data
9000 = Invalid/error case data
```

---

## Real-World Example

Blog application with semantic UUIDs and identity trinity:

```sql
-- db/seeds/common/00_users.sql
-- Common users for all environments (scenario: 0000)
INSERT INTO tb_user (pk_user, identifier, username, email, role) VALUES
    ('01010000-0000-0000-0000-000000000001', 'admin', 'Admin User', 'admin@example.com', 'admin'),
    ('01020000-0000-0000-0000-000000000001', 'editor', 'Editor User', 'editor@example.com', 'editor'),
    ('01030000-0000-0000-0000-000000000001', 'reader', 'Reader User', 'reader@example.com', 'user');

-- db/seeds/development/00_posts.sql
-- Development posts (scenario: 1000 = dev data)
INSERT INTO tb_post (pk_post, fk_author, identifier, title, published) VALUES
    ('02000000-1000-0000-0000-000000000001', '01010000-0000-0000-0000-000000000001', 'welcome', 'Welcome', true),
    ('02000000-1000-0000-0000-000000000002', '01010000-0000-0000-0000-000000000001', 'getting-started', 'Getting Started', true),
    ('02000000-1000-0000-0000-000000000003', '01020000-0000-0000-0000-000000000001', 'draft-post', 'Draft Post', false);

-- db/seeds/test/00_auth_tests.sql
-- Test data for authentication tests (scenario: 2001)
INSERT INTO tb_user (pk_user, identifier, username, email, password_hash, locked) VALUES
    ('01030000-2001-0000-1000-000000000001', 'test-valid', 'Test Valid', 'valid@test.com', '$2b$12$...', false),
    ('01030000-2001-0000-1000-000000000002', 'test-locked', 'Test Locked', 'locked@test.com', '$2b$12$...', true),
    ('01030000-2001-0000-1000-000000000003', 'test-expired', 'Test Expired', 'expired@test.com', '$2b$12$...', false);

-- db/seeds/test/01_post_tests.sql
-- Test data for post creation tests (scenario: 2010)
INSERT INTO tb_post (pk_post, fk_author, identifier, title, published) VALUES
    ('02000000-2010-0000-1000-000000000001', '01030000-0000-0000-0000-000000000001', 'test-post-1', 'Test Post 1', true),
    ('02000000-2010-0000-1000-000000000002', '01030000-0000-0000-0000-000000000001', 'test-post-2', 'Test Post 2', false);
```

**Reading the UUIDs**:
- `01010000-0000-0000-0000-000000000001`: tb_user, type 01 (admin), common data, sequence 1
- `02000000-1000-0000-0000-000000000001`: tb_post, dev data (1000), sequence 1
- `01030000-2001-0000-1000-000000000001`: tb_user, type 03 (regular), auth tests (2001), test context (1000), sequence 1

**Identity Trinity in Action**:
- **`id`**: Auto-generated integer for fast queries: `SELECT * FROM tb_user WHERE id = 42`
- **`pk_user`**: Semantic UUID for external refs: `fk_author = '01010000-...'`
- **`identifier`**: Human slug for URLs: `/users/admin`, `/posts/welcome`

---

## Benefits in Testing

### Readable Test Assertions

```python
# Without semantic UUIDs
def test_user_can_create_post():
    user = User.get_by_pk('7f3e8c2a-9d41-4b5f-a8e3-1c9d7e2b4f6a')  # Who is this?
    post = create_post(user.pk_user, title='Test')
    assert post.fk_author == '7f3e8c2a-9d41-4b5f-a8e3-1c9d7e2b4f6a'  # Still unclear

# With semantic UUIDs
def test_user_can_create_post():
    user = User.get_by_pk('01030000-0000-0000-0000-000000000001')  # Regular user, common data
    post = create_post(user.pk_user, title='Test')
    assert post.fk_author == '01030000-0000-0000-0000-000000000001'  # Clear!
```

### Debugging Logs

```
# Without semantic UUIDs
[ERROR] Foreign key violation: post 9e4f7c3a referenced user 7f3e8c2a not found
                              (which tables? hard to tell)

# With semantic UUIDs
[ERROR] Foreign key violation: post 02000000-1000-... referenced user 01030000-0000-... not found
                              (post table 02, user table 01 - instantly clear!)
```

### Database Queries

```sql
-- Easy to find all test data for a specific scenario
SELECT * FROM tb_user WHERE pk_user::text LIKE '01______-2001-%';  -- Auth test users

-- Clean up test data for specific scenario
DELETE FROM tb_post WHERE pk_post::text LIKE '02______-2010-____-1000-%';  -- Post creation tests

-- Find all dev seed data across tables
SELECT pk_user AS pk, identifier, username FROM tb_user WHERE pk_user::text LIKE '________-1000-%'
UNION ALL
SELECT pk_post AS pk, identifier, title FROM tb_post WHERE pk_post::text LIKE '________-1000-%';
```

---

## UUID Registry Document

Create `db/UUID_REGISTRY.md` to document your encoding:

```markdown
# UUID Registry

## Table Codes
| Code | Table | Description |
|------|-------|-------------|
| 01   | tb_user | User accounts |
| 02   | tb_post | Blog posts |
| 03   | tb_comment | Post comments |
| 04   | tb_tag | Content tags |

## Type Codes (2nd segment)
### tb_user (01)
- 10 = Admin users
- 20 = Editor users
- 30 = Regular users

### tb_post (02)
- 10 = Published posts
- 20 = Draft posts
- 30 = Archived posts

## Scenario Codes (3rd segment)
| Code | Purpose |
|------|---------|
| 0000 | Common seed data |
| 1000 | Development rich data |
| 2001 | Authentication tests |
| 2002 | Authorization tests |
| 2010 | Post creation tests |
| 2011 | Post editing tests |

## Context Codes (4th segment)
| Code | Purpose |
|------|---------|
| 0000 | Persistent data |
| 1000 | Test-specific (transient) |
```

---

## Helper Script

Generate UUIDs following your convention:

```python
# scripts/generate_test_uuid.py
def generate_test_uuid(table_code: int, type_code: int = 0,
                       scenario: int = 0, context: int = 0,
                       sequence: int = 1) -> str:
    """Generate semantic test UUID.

    Args:
        table_code: Table identifier (01-99)
        type_code: Entity type (0-99)
        scenario: Test scenario (0000-9999)
        context: Context flag (0000, 1000, etc)
        sequence: Sequence number (1-9999...)

    Returns:
        Formatted UUID string

    Example:
        >>> generate_test_uuid(table_code=1, type_code=10, scenario=2001, context=1000, sequence=1)
        '01100000-2001-0000-1000-000000000001'
    """
    return f"{table_code:02d}{type_code:02d}0000-{scenario:04d}-0000-{context:04d}-{sequence:012d}"

# Usage examples
admin_user = generate_test_uuid(table_code=1, type_code=10, scenario=0, context=0, sequence=1)
# '01100000-0000-0000-0000-000000000001'

test_user = generate_test_uuid(table_code=1, type_code=30, scenario=2001, context=1000, sequence=1)
# '01300000-2001-0000-1000-000000000001'

test_post = generate_test_uuid(table_code=2, scenario=2010, context=1000, sequence=1)
# '02000000-2010-0000-1000-000000000001'
```

---

## Best Practices

### DO

✅ **Use semantic UUIDs in test/dev environments only**
```yaml
# Production: random UUIDs (security)
name: production
includes:
  - ../schema

# Test: semantic UUIDs (debuggability)
name: test
includes:
  - ../schema
  - ../seeds/common    # Semantic UUIDs
  - ../seeds/test      # Semantic UUIDs
```

✅ **Document your encoding scheme**
```
Create db/UUID_REGISTRY.md with all codes
```

✅ **Keep codes consistent across files**
```sql
-- All tb_user UUIDs start with 01
-- All tb_post UUIDs start with 02
-- Never mix!
```

✅ **Use leading zeros for alignment**
```sql
'01000000-0000-0000-0000-000000000001'  -- Good: aligned
'1000000-0-0-0-1'                        -- Bad: misaligned
```

### DON'T

❌ **Don't use semantic UUIDs in production**
```
Predictable UUIDs are a security risk
Production should use random UUIDs
```

❌ **Don't reuse scenario codes**
```sql
-- BAD: 2001 means different things
-- In users: 2001 = auth tests
-- In posts: 2001 = creation tests (CONFUSING!)

-- GOOD: Unique codes
-- Users: 2001 = auth tests
-- Posts: 2010 = creation tests (CLEAR!)
```

❌ **Don't make codes too complex**
```sql
-- BAD: Too many segments
'01-02-03-04-2001-0001-1000-0000-0000-0001-0002-0003'

-- GOOD: Simple pattern
'01020000-2001-0000-1000-000000000001'
```

---

## Scaling the Pattern

### Small Projects (<10 tables)

Simple 2-segment pattern:

```
{table_code}000000-0000-0000-0000-0000-{sequence}
```

### Medium Projects (10-50 tables)

Add scenario code:

```
{table_code}000000-{scenario}-0000-0000-{sequence}
```

### Large Projects (50+ tables)

Full semantic encoding:

```
{table_code}{type_code}0000-{scenario}-{variant}-{context}-{sequence}
```

---

## Migration Strategy

### Transitioning to Semantic UUIDs

1. **Start with new seed files**
   ```
   Keep existing random UUIDs
   Use semantic UUIDs in new seeds
   ```

2. **Adopt identity trinity for new tables**
   ```sql
   CREATE TABLE tb_new_entity (
       id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
       pk_new_entity UUID NOT NULL UNIQUE,
       identifier TEXT NOT NULL UNIQUE,
       ...
   );
   ```

3. **Document the change**
   ```
   Add UUID_REGISTRY.md
   Update seed file comments
   Document trinity pattern in README
   ```

4. **Gradually migrate**
   ```sql
   -- Old (keep for now)
   INSERT INTO tb_user (pk_user, ...) VALUES ('7f3e8c2a-...', ...);

   -- New (use going forward)
   INSERT INTO tb_user (pk_user, identifier, ...) VALUES
       ('01100000-0000-0000-0000-000000000001', 'admin', ...);
   ```

---

## Summary

### The Modern Identity Trinity

```sql
CREATE TABLE tb_entity (
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,  -- Fast joins
    pk_entity UUID NOT NULL UNIQUE,                       -- Stable external refs
    identifier TEXT NOT NULL UNIQUE,                      -- Human-readable slugs
    ...
);
```

**Three identifiers, three purposes:**
- **`id`**: Integer for internal queries and ordering
- **`pk_entity`**: UUID for APIs and distributed systems
- **`identifier`**: Slug for URLs and user-facing features

### Semantic UUID Encoding

**Encode meaning into the `pk_entity` UUID for test/dev environments:**

| Segment | Purpose | Example |
|---------|---------|---------|
| 1st | Table + Type | `01100000` = tb_user, admin type |
| 2nd | Scenario | `2001` = authentication tests |
| 3rd | Variant | `0000` = default variant |
| 4th | Context | `1000` = test-specific data |
| 5th | Sequence | `000000000001` = first record |

**Benefits:**
- 🔍 **Debuggable**: Instantly recognize entities in logs
- 🧪 **Testable**: Clear, readable test assertions
- 🗑️ **Cleanable**: Easy to delete specific test data
- 📊 **Queryable**: Simple SQL patterns to find data
- 🤝 **Collaborative**: Team members understand UUIDs at a glance

**Security:**
- ✅ Use semantic UUIDs in **development and test** environments
- ❌ Use **random UUIDs** in **production** for security

**Naming Conventions:**
- Tables: `tb_entity` (singular, with tb_ prefix)
- UUID PKs: `pk_entity` (matches table name)
- Foreign keys: `fk_referenced_entity` (descriptive)
- Slugs: `identifier` (human-readable, URL-friendly)

---

*Part of [Confiture](../README.md) - PostgreSQL migrations, sweetly done 🍓*
