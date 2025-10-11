# Seed Data for Blog Application

This directory contains seed data (INSERT statements) for different environments.

## Directory Structure

```
seeds/
├── common/          # Shared across all non-production environments
│   └── 00_users.sql       # Test users (admin, editor, reader)
│
├── development/     # Development environment only
│   ├── 00_posts.sql       # Sample blog posts
│   └── 01_comments.sql    # Sample comments
│
└── test/            # Test environment only
    └── 00_posts.sql       # Minimal test data
```

## Seed Categories

### common/
Reference data and test users needed in all non-production environments.

**Files:**
- `00_users.sql`: 3 test users with fixed UUIDs
  - Admin (pk: 00000000-0000-0000-0000-000000000001)
  - Editor (pk: 00000000-0000-0000-0000-000000000002)
  - Reader (pk: 00000000-0000-0000-0000-000000000003)

### development/
Rich content for local development and manual testing.

**Files:**
- `00_posts.sql`: 6 sample posts (5 published, 1 draft)
- `01_comments.sql`: 7 comments across multiple posts

**Use case:** Immediately usable database for API testing and UI development.

### test/
Minimal data for automated tests - predictable and fast.

**Files:**
- `00_posts.sql`: 3 test posts (2 published, 1 draft)

**Use case:** Fast test execution with known data states.

## Environment Configuration

Seeds are included via environment configuration:

### Local Development (includes common + development seeds)
```yaml
# db/environments/local.yaml
include_dirs:
  - db/schema
  - db/seeds/common
  - db/seeds/development
```

### Test (includes common + test seeds)
```yaml
# db/environments/test.yaml
include_dirs:
  - db/schema
  - db/seeds/common
  - db/seeds/test
```

### Production (NO seeds)
```yaml
# db/environments/production.yaml
include_dirs:
  - db/schema
exclude_dirs:
  - db/seeds
```

## Building with Seeds

```bash
# Build with seeds (default for local)
confiture build --env local

# Build schema only (override)
confiture build --env local --schema-only

# Production (always schema-only via config)
confiture build --env production
```

## Best Practices

1. **Use Fixed UUIDs**: Deterministic primary keys for reproducibility
2. **Handle Conflicts**: Use `ON CONFLICT DO NOTHING` for idempotency
3. **Reference by ID**: Foreign keys use internal IDs (1, 2, 3), not UUIDs
4. **Minimal Test Data**: Keep test seeds small for fast execution
5. **Rich Dev Data**: Development seeds can be comprehensive
6. **Never Seed Production**: Use migrations for production data changes

## File Naming Convention

Files are executed in alphabetical order:
- `00_*.sql` - Core reference data (users, categories)
- `01_*.sql` - Dependent data (posts)
- `02_*.sql` - Further dependent data (comments)

## Example: Adding New Seed Data

```sql
-- seeds/development/02_tags.sql

INSERT INTO tags (pk_tag, slug, name, created_at) VALUES
    ('00000000-0000-0000-0000-000000000031', 'tutorial', 'Tutorial', NOW()),
    ('00000000-0000-0000-0000-000000000032', 'announcement', 'Announcement', NOW())
ON CONFLICT (pk_tag) DO NOTHING;
```

Then rebuild:
```bash
confiture build --env local
```

## Resetting Development Database

```bash
# Drop and recreate
dropdb blog_app_local && createdb blog_app_local

# Apply fresh schema + seeds
confiture build --env local
psql -d blog_app_local -f db/generated/schema_local.sql

# Ready to develop!
```
