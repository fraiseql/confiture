# Seed Data Pattern Analysis

**Comparison**: Confiture vs PrintOptim Backend
**Date**: October 11, 2025
**Decision**: Should we integrate environment-specific seed data?

---

## PrintOptim Backend Pattern

### Directory Structure

```
db/
├── 0_schema/                   # DDL (CREATE TABLE, functions, etc.)
│   ├── 00_common/
│   ├── 01_write_side/
│   ├── 02_query_side/
│   ├── 03_functions/
│   ├── 04_turbo_router/
│   └── 05_lazy_caching/
│
├── 1_seed_common/              # Common seed data (all envs)
│   └── 11_write_side/
│       └── 113_catalog/
│           ├── tb_color_mode.sql        # INSERT statements
│           ├── tb_paper_format.sql
│           └── ...
│
├── 2_seed_backend/             # Backend-only seeds (local, test)
│   └── ...
│
├── 3_seed_frontend/            # Frontend seeds (development, staging)
│   └── ...
│
├── 5_refresh_mv/               # Materialized view refresh
├── 7_grant/                    # GRANT statements
└── 99_finalize/                # Final cleanup

Generated:
├── database_local.sql          # schema + seed_common + seed_backend
├── database_test.sql           # schema + seed_common + seed_backend
├── database_development.sql    # schema + seed_common + seed_frontend
├── database_staging.sql        # schema + seed_common + seed_frontend
└── database_production.sql     # schema ONLY (no seeds)
```

### Environment-Specific Includes

**Production**:
- `0_schema` only
- No seed data
- Clean deployment

**Local/Test**:
- `0_schema`
- `1_seed_common` (reference data)
- `2_seed_backend` (test users, sample data)

**Development/Staging**:
- `0_schema`
- `1_seed_common` (reference data)
- `3_seed_frontend` (UI test data)

### Key Features

1. **Multiple seed categories**:
   - `1_seed_common`: Reference data shared across all non-prod envs
   - `2_seed_backend`: Backend development data
   - `3_seed_frontend`: Frontend/E2E test data

2. **Environment-specific builds**:
   ```python
   "production": Environment(
       include_dirs=["0_schema"],
       exclude_dirs=["1_seed_common", "2_seed_backend", "3_seed_frontend"],
   ),
   "local": Environment(
       include_dirs=["0_schema", "1_seed_common", "2_seed_backend"],
       exclude_dirs=["3_seed_frontend"],
   ),
   ```

3. **Parallel builds**: All 5 environments in ~2 seconds

4. **Hash-based change detection**: SHA256 of all included files

5. **Version tracking**: `.schema_version.json` with semver

---

## Confiture Current Pattern

### Directory Structure

```
db/
├── schema/                     # DDL only
│   ├── 00_common/
│   │   └── extensions.sql
│   ├── 10_tables/
│   │   ├── users.sql
│   │   ├── posts.sql
│   │   └── comments.sql
│   └── 20_views/
│
├── migrations/                 # Migration files
│   ├── 001_create_initial_schema.py
│   └── ...
│
└── environments/
    ├── local.yaml
    ├── test.yaml
    ├── production.yaml
    └── staging.yaml

Generated:
└── generated/
    ├── schema_local.sql
    ├── schema_test.sql
    └── schema_production.sql
```

### Current Features

1. **Schema-only builds**: DDL concatenation
2. **Environment configs**: YAML-based
3. **Hash computation**: SHA256 for change detection
4. **Migration system**: Python-based migrations
5. **Schema diff**: Automatic migration generation

### What's Missing

❌ **No seed data support**
❌ **No environment-specific data inclusion**
❌ **No reference data management**

---

## Should We Integrate Seed Data?

### ✅ YES - Strong Reasons

#### 1. **Common Real-World Pattern**

Every production application needs:
- Reference data (countries, currencies, statuses)
- Development test data
- E2E test fixtures

**Example**: Blog application
```
db/
├── schema/
│   └── 10_tables/
│       ├── users.sql
│       └── posts.sql
│
├── seeds/
│   ├── common/                 # All non-prod environments
│   │   ├── users.sql          # Test users (admin, editor, reader)
│   │   └── categories.sql     # Post categories
│   │
│   ├── development/           # Rich test data for dev
│   │   └── posts.sql          # 100 sample posts
│   │
│   └── test/                  # Minimal data for tests
│       └── posts.sql          # 5 sample posts
```

#### 2. **Aligns with Build from DDL Philosophy**

Current: "Build schema from DDL in <1s"
Enhanced: "Build complete database (schema + data) from DDL in <1s"

This is still **Medium 1: Build from DDL**, just more complete.

#### 3. **FraiseQL Integration**

FraiseQL generators will need seed data:
```bash
# Generate FraiseQL CRUD API
fraiseql generate blog --seed-data

# Creates:
# - Schema (users, posts)
# - Seed data (test users, sample posts)
# - Migrations
# - GraphQL resolvers
```

#### 4. **Testing Benefits**

**Current** (without seeds):
```python
# tests/integration/test_api.py
def test_get_posts():
    # Manual setup every test
    user = User.create(username="test", email="test@example.com")
    post = Post.create(user_id=user.id, title="Test Post")

    response = client.get("/posts")
    assert response.status_code == 200
```

**With seeds**:
```python
# tests/integration/test_api.py
def test_get_posts(seeded_db):
    # Data already present from seeds/test/
    response = client.get("/posts")
    assert response.status_code == 200
    assert len(response.json()) == 5  # From seeds
```

#### 5. **Developer Experience**

**Without seeds**: Fresh database is empty
```bash
confiture build --env local
psql -f db/generated/schema_local.sql

# Developer must manually create test data
psql> INSERT INTO users ...
```

**With seeds**: Fresh database has data
```bash
confiture build --env local
psql -f db/generated/schema_local.sql

# Database ready with:
# - 3 test users (admin, editor, reader)
# - 20 sample posts
# - 50 comments
# Ready to test API immediately!
```

#### 6. **Production Safety**

```yaml
# db/environments/production.yaml
name: production
include_dirs:
  - db/schema  # Schema only
exclude_dirs:
  - db/seeds   # Explicitly exclude ALL seeds
```

Production builds **never** include seed data. Clean separation.

---

## Proposed Implementation

### Phase: "Seed Data Support" (1.5 weeks)

#### Week 1: Core Seed Support

**1. Update Directory Structure** (Day 1)

```
db/
├── schema/              # DDL (existing)
│   ├── 00_common/
│   ├── 10_tables/
│   └── 20_views/
│
├── seeds/               # NEW: Seed data
│   ├── common/          # All non-prod environments
│   │   ├── 00_users.sql         # INSERT statements
│   │   └── 01_categories.sql
│   │
│   ├── development/     # Development-only
│   │   └── 00_posts.sql         # Rich test data
│   │
│   └── test/            # Test-only
│       └── 00_posts.sql         # Minimal test data
│
├── migrations/          # Existing
└── environments/        # Existing
```

**2. Update Environment Config** (Day 1)

```yaml
# db/environments/local.yaml
name: local
include_dirs:
  - db/schema
  - db/seeds/common      # NEW: Include common seeds
  - db/seeds/development # NEW: Include dev seeds

exclude_dirs: []

database_url: postgresql://localhost/blog_app_local
```

```yaml
# db/environments/production.yaml
name: production
include_dirs:
  - db/schema  # Schema ONLY

exclude_dirs:
  - db/seeds   # Explicitly exclude seeds

database_url: postgresql://prod-host/blog_app
```

**3. Update SchemaBuilder** (Day 2)

No changes needed! Current implementation already supports multiple `include_dirs`.

**4. Update CLI** (Day 2)

```python
# python/confiture/cli/main.py

@app.command()
def build(
    env: str = typer.Option("local", "--env", "-e"),
    output: Path = typer.Option(None, "--output", "-o"),
    schema_only: bool = typer.Option(
        False,
        "--schema-only",
        help="Build schema only, exclude seed data",
    ),
):
    """Build complete database from DDL and seed files."""
    builder = SchemaBuilder(env=env, project_dir=project_dir)

    # Override to exclude seeds if requested
    if schema_only:
        builder.include_dirs = [
            d for d in builder.include_dirs
            if "seed" not in str(d)
        ]

    schema = builder.build(output_path=output)
    # ...
```

**Usage**:
```bash
# Build with seeds (default for non-prod)
confiture build --env local

# Build schema only
confiture build --env local --schema-only

# Production always schema-only (via config)
confiture build --env production
```

**5. Update `confiture init`** (Day 3)

```python
# Create seed directories
(db_dir / "seeds" / "common").mkdir(parents=True, exist_ok=True)
(db_dir / "seeds" / "development").mkdir(parents=True, exist_ok=True)
(db_dir / "seeds" / "test").mkdir(parents=True, exist_ok=True)

# Create example seed file
seed_file = db_dir / "seeds" / "common" / "00_users.sql"
seed_file.write_text("""-- Common seed data: Test users

INSERT INTO users (slug, username, email, bio, created_at) VALUES
    ('admin-user', 'admin', 'admin@example.com', 'Administrator', NOW()),
    ('editor-user', 'editor', 'editor@example.com', 'Content Editor', NOW()),
    ('reader-user', 'reader', 'reader@example.com', 'Regular Reader', NOW());
""")
```

#### Week 2: Testing & Documentation

**6. Add Tests** (Day 4-5)

```python
# tests/unit/test_builder_seeds.py

def test_build_includes_seed_data(tmp_path):
    """Should include seed data in build"""
    # Create schema
    schema_dir = tmp_path / "db" / "schema" / "00_tables"
    schema_dir.mkdir(parents=True)
    (schema_dir / "users.sql").write_text("CREATE TABLE users (id BIGINT);")

    # Create seeds
    seed_dir = tmp_path / "db" / "seeds" / "common"
    seed_dir.mkdir(parents=True)
    (seed_dir / "00_users.sql").write_text("INSERT INTO users VALUES (1);")

    # Config with seeds
    config_dir = tmp_path / "db" / "environments"
    config_dir.mkdir(parents=True)
    (config_dir / "local.yaml").write_text("""
name: local
include_dirs:
  - db/schema
  - db/seeds/common
exclude_dirs: []
database_url: postgresql://localhost/test
""")

    # Build
    builder = SchemaBuilder(env="local", project_dir=tmp_path)
    schema = builder.build()

    # Verify both schema and seeds included
    assert "CREATE TABLE users" in schema
    assert "INSERT INTO users" in schema

def test_production_excludes_seeds(tmp_path):
    """Production should never include seed data"""
    # Create schema
    schema_dir = tmp_path / "db" / "schema" / "00_tables"
    schema_dir.mkdir(parents=True)
    (schema_dir / "users.sql").write_text("CREATE TABLE users (id BIGINT);")

    # Create seeds
    seed_dir = tmp_path / "db" / "seeds" / "common"
    seed_dir.mkdir(parents=True)
    (seed_dir / "00_users.sql").write_text("INSERT INTO users VALUES (1);")

    # Production config WITHOUT seeds
    config_dir = tmp_path / "db" / "environments"
    config_dir.mkdir(parents=True)
    (config_dir / "production.yaml").write_text("""
name: production
include_dirs:
  - db/schema
exclude_dirs:
  - db/seeds
database_url: postgresql://prod-host/db
""")

    # Build
    builder = SchemaBuilder(env="production", project_dir=tmp_path)
    schema = builder.build()

    # Verify seeds excluded
    assert "CREATE TABLE users" in schema
    assert "INSERT INTO users" not in schema
```

**7. Update Documentation** (Day 6)

Create `docs/seed-data.md`:

```markdown
# Seed Data Management

## Overview

Confiture supports environment-specific seed data for development and testing.
Production environments build schema-only.

## Directory Structure

db/
├── schema/          # DDL files
├── seeds/           # Seed data
│   ├── common/      # All non-prod environments
│   ├── development/ # Development-specific
│   └── test/        # Test-specific
└── environments/

## Usage

### Create Seed Files

db/seeds/common/00_users.sql:
INSERT INTO users (slug, username, email) VALUES
    ('admin', 'admin', 'admin@example.com'),
    ('editor', 'editor', 'editor@example.com');

### Configure Environments

# local.yaml - Include seeds
include_dirs:
  - db/schema
  - db/seeds/common
  - db/seeds/development

# production.yaml - Exclude seeds
include_dirs:
  - db/schema
exclude_dirs:
  - db/seeds

### Build

# With seeds (default for local/test)
confiture build --env local

# Schema only (override)
confiture build --env local --schema-only

# Production (always schema-only via config)
confiture build --env production

## Best Practices

1. **Reference Data in common/**: Countries, currencies, statuses
2. **Test Data by Environment**: Development gets rich data, test gets minimal
3. **Never Seed Production**: Use migrations for production data
4. **Use Deterministic Values**: Fixed UUIDs, timestamps for reproducibility
```

**8. Update Examples** (Day 7)

```bash
# Update examples/basic with seed data
mkdir -p examples/basic/db/seeds/common
mkdir -p examples/basic/db/seeds/development

# Create seed files
cat > examples/basic/db/seeds/common/00_users.sql <<EOF
-- Test users for development and testing

INSERT INTO users (pk_user, slug, username, email, bio, created_at) VALUES
    ('00000000-0000-0000-0000-000000000001', 'admin-user', 'admin', 'admin@example.com', 'Administrator', NOW()),
    ('00000000-0000-0000-0000-000000000002', 'editor-user', 'editor', 'editor@example.com', 'Content Editor', NOW()),
    ('00000000-0000-0000-0000-000000000003', 'reader-user', 'reader', 'reader@example.com', 'Regular Reader', NOW());
EOF

cat > examples/basic/db/seeds/development/00_posts.sql <<EOF
-- Sample posts for development

INSERT INTO posts (pk_post, slug, user_id, title, content, published_at, created_at) VALUES
    ('00000000-0000-0000-0000-000000000011', 'welcome-to-blog', 1, 'Welcome to Our Blog', 'This is the first post!', NOW(), NOW()),
    ('00000000-0000-0000-0000-000000000012', 'getting-started', 1, 'Getting Started Guide', 'Here''s how to use this platform.', NOW(), NOW());
EOF
```

---

## Implementation Checklist

### Core (Week 1)
- [ ] Create `db/seeds/` directory structure in examples
- [ ] Update environment configs to include seeds
- [ ] Add `--schema-only` flag to build command
- [ ] Update `confiture init` to create seed directories
- [ ] Verify SchemaBuilder handles seeds (should already work!)

### Testing (Week 2)
- [ ] Add unit tests for seed inclusion/exclusion
- [ ] Add E2E tests with seeded database
- [ ] Test production config excludes seeds
- [ ] Performance test (schema + seeds < 1s)

### Documentation
- [ ] Create `docs/seed-data.md`
- [ ] Update `docs/getting-started.md` with seed examples
- [ ] Update `docs/cli-reference.md` with --schema-only
- [ ] Update `examples/basic` with seed data

### Polish
- [ ] Update README with seed data section
- [ ] Add seed data to PHASES.md
- [ ] Create blog post about seed management

---

## Comparison Summary

| Feature | PrintOptim Backend | Confiture (Current) | Confiture (Proposed) |
|---------|-------------------|---------------------|----------------------|
| Schema building | ✅ Python script | ✅ SchemaBuilder | ✅ SchemaBuilder |
| Multiple environments | ✅ 5 environments | ✅ Any environment | ✅ Any environment |
| Environment-specific includes | ✅ include_dirs | ✅ include_dirs | ✅ include_dirs |
| Seed data support | ✅ 3 seed categories | ❌ No seeds | ✅ seeds/ directory |
| Production safety | ✅ Schema only | ⚠️ N/A | ✅ Exclude seeds |
| Hash-based detection | ✅ SHA256 | ✅ SHA256 | ✅ SHA256 |
| Parallel builds | ✅ ThreadPool | ⚠️ Sequential | ⚠️ Future |
| Migration system | ❌ No migrations | ✅ Python migrations | ✅ Python migrations |
| Schema diff | ❌ Manual | ✅ Automatic | ✅ Automatic |
| CLI | ✅ Python script | ✅ Typer CLI | ✅ Typer CLI |

---

## Recommendation

**✅ YES - Integrate seed data support**

### Why?

1. **Completes the build story**: Schema + data = complete database
2. **Aligns with real-world needs**: Every app needs test data
3. **Easy to implement**: 1.5 weeks, mostly configuration
4. **No breaking changes**: Optional feature, backward compatible
5. **Production safe**: Configurable exclusion
6. **Better DX**: Fresh databases are immediately usable

### When?

**Now** - This is a natural extension of "Build from DDL" and should be part of Phase 1.

### How?

Follow the 7-day implementation plan above:
1. Days 1-3: Core implementation
2. Days 4-5: Testing
3. Days 6-7: Documentation

---

**Decision**: INTEGRATE SEED DATA SUPPORT

**Reason**: Essential feature for complete database builds, aligns perfectly with existing architecture, minimal implementation effort, massive developer experience improvement.

**Next Action**: Start implementation following the plan above.

---

**Author**: Lionel Hamayon (@evoludigit)
**Date**: October 11, 2025
**Status**: Recommended for immediate implementation
