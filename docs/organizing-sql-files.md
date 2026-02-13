# Organizing SQL Files in Confiture

**Best practices for structuring complex database schemas**

---

## Philosophy

Confiture uses **deterministic file ordering** to build schemas. Files are processed in **alphabetical order**, which gives you complete control over execution order through **numbered prefixes**.

This approach works for projects of any size:
- **Simple projects**: A few flat files (`tables.sql`, `views.sql`)
- **Complex domains**: Hundreds of files in a deep hierarchy

---

## The Number Prefix Pattern

### Basic Principle

Use **numeric prefixes** to control execution order:

```
db/schema/
├── 00_extensions.sql       # Load first
├── 10_types.sql            # Then types
├── 20_tables.sql           # Then tables
├── 30_views.sql            # Then views
└── 40_functions.sql        # Finally functions
```

**Why it works**:
- `00` < `10` < `20` in alphabetical sort
- Clear intent: numbers show dependency order
- Easy to insert: Leave gaps (00, 10, 20) for future additions

---

## Hexadecimal Prefix Pattern (Advanced)

### When to Use Hex Prefixes

For large schemas requiring more than 9 main categories, or when you need clearer visual separation between major sections, use hexadecimal prefixes with `sort_mode: hex` in your configuration.

### Hex Prefix Format

```
0x{HH}_{description}.sql

Where:
- 0x: Literal hex prefix
- HH: Two hexadecimal digits (00-FF, allowing 255 categories)
- _: Underscore separator
- description: Human-readable name
```

### Example with Hex Sorting

```yaml
# db/environments/production.yaml
build:
  sort_mode: hex  # Enable hex sorting
```

```bash
db/schema/
├── 0x00_extensions.sql       # 0   - Extensions
├── 0x01_security.sql         # 1   - Security
├── 0x0A_users.sql            # 10  - User domain
├── 0x0B_posts.sql            # 11  - Content domain
├── 0x14_views.sql            # 20  - Views
├── 0x1E_functions.sql        # 30  - Functions
├── 0x28_triggers.sql         # 40  - Triggers
└── 0xFF_finalize.sql         # 255 - Final steps
```

**Benefits**:
- **255 possible categories** (vs 9 with decimal)
- **Clear visual hierarchy** with hex notation
- **Easy insertion** of new categories
- **Deterministic sorting** across all locales

**See [Hexadecimal Sorting](../features/hexadecimal-sorting.md)** for complete documentation.

---

## Directory Organization Patterns

### Pattern 1: Flat Structure (Simple Projects)

Good for small projects (<20 files):

```
db/schema/
├── 00_extensions.sql
├── 10_domains.sql
├── 20_users_table.sql
├── 21_posts_table.sql
├── 22_comments_table.sql
├── 30_user_views.sql
└── 40_triggers.sql
```

**Pros**: Simple, visible, easy to navigate
**Cons**: Doesn't scale beyond ~20 files

---

### Pattern 2: Single-Level Directories (Medium Projects)

Good for projects with 20-100 files:

```
db/schema/
├── 00_common/
│   ├── extensions.sql
│   └── security.sql
├── 10_tables/
│   ├── users.sql
│   ├── posts.sql
│   └── comments.sql
├── 20_views/
│   ├── user_stats.sql
│   └── post_stats.sql
└── 30_functions/
    ├── create_user.sql
    └── delete_user.sql
```

**Pros**: Clear separation of concerns
**Cons**: All tables in one directory can be overwhelming

---

### Pattern 3: Hierarchical Structure (Complex Projects)

Good for large projects (100+ files) with complex domains:

```
db/schema/
├── 00_common/
│   ├── 000_security/
│   │   ├── 0001_roles.sql
│   │   └── 0002_schemas.sql
│   ├── 001_extensions/
│   │   └── 0010_enable_extensions.sql
│   └── 002_types/
│       └── 0020_common_types.sql
│
├── 01_core_domain/
│   ├── 010_users/
│   │   ├── 0101_user_table.sql
│   │   ├── 0102_user_profile.sql
│   │   └── 0103_user_settings.sql
│   ├── 020_content/
│   │   ├── 0201_posts.sql
│   │   ├── 0202_comments.sql
│   │   └── 0203_reactions.sql
│   └── 030_analytics/
│       └── 0301_page_views.sql
│
├── 02_views/
│   ├── 010_user_views/
│   │   └── 0101_user_stats.sql
│   └── 020_content_views/
│       └── 0201_post_rankings.sql
│
└── 03_functions/
    ├── 010_user_functions/
    │   ├── 0101_create_user.sql
    │   └── 0102_authenticate.sql
    └── 020_content_functions/
        └── 0201_publish_post.sql
```

**Numbering System Explained**:

- **Top-level** (`00_`, `01_`, `02_`): Major execution phases
  - `00_common`: Infrastructure (roles, extensions, types)
  - `01_core_domain`: Business tables
  - `02_views`: Computed views
  - `03_functions`: Stored procedures

- **Second-level** (`010_`, `020_`, `030_`): Domain areas
  - `010_users`: User domain
  - `020_content`: Content domain
  - Leave gaps (010, 020, 030) to add domains later

- **Third-level** (`0101`, `0102`): Related entities
  - `0101_user_table.sql`: Main table
  - `0102_user_profile.sql`: Related table

**Pros**: Scales to thousands of files, clear domains
**Cons**: More directory navigation

---

## Real-World Example: Enterprise Project

Example of a scalable three-level directory structure for large projects:

```
db/
├── 0_schema/                    # All DDL
│   ├── 00_common/
│   │   ├── 000_security/
│   │   │   ├── 0001_roles.sql
│   │   │   ├── 0002_schemas.sql
│   │   │   └── 0003_permissions.sql
│   │   ├── 001_extensions/
│   │   │   ├── 0010_postgis.sql
│   │   │   └── 0011_pg_trgm.sql
│   │   ├── 002_types/
│   │   │   ├── 0020_enums.sql
│   │   │   └── 0021_composite_types.sql
│   │   └── 003_versioning/
│   │       └── 0030_version_table.sql
│   │
│   ├── 01_core_tables/
│   │   ├── 010_users/
│   │   │   ├── 0101_user.sql
│   │   │   ├── 0102_role.sql
│   │   │   └── 0103_permission.sql
│   │   ├── 020_organizations/
│   │   │   ├── 0201_organization.sql
│   │   │   └── 0202_org_unit.sql
│   │   └── 030_locations/
│   │       ├── 0301_country.sql
│   │       └── 0302_address.sql
│   │
│   ├── 02_views/
│   │   ├── 010_user_views/
│   │   │   └── 0101_active_users.sql
│   │   └── 020_org_views/
│   │       └── 0201_org_hierarchy.sql
│   │
│   ├── 03_functions/
│   │   ├── 010_user_functions/
│   │   │   ├── 0101_create_user.sql
│   │   │   └── 0102_deactivate_user.sql
│   │   └── 020_org_functions/
│   │       └── 0201_assign_org_unit.sql
│   │
│   └── 99_finalize/
│       └── 9901_analyze_tables.sql
│
├── 1_seed_common/               # Common seed data
│   └── 00_countries.sql
│
├── 2_seed_development/          # Dev-specific data
│   ├── 00_test_users.sql
│   └── 01_test_organizations.sql
│
└── 5_post_build/                # Post-build scripts
    └── 0001_refresh_views.sql
```

**Key Insights**:
1. **Leave gaps**: Use `000`, `010`, `020` (not `001`, `002`, `003`)
   - Allows inserting `015_new_domain` between `010` and `020`
2. **Use `00_` prefix**: For "always first" items (security, extensions)
3. **Use `99_` prefix**: For "always last" items (finalization, grants)
4. **Match depth to complexity**: Simple project = flat, complex = deep

---

## Numbering Conventions

### Top-Level Phase Numbers

```
00_   Foundation (roles, schemas, extensions)
01-09 Core business domains
10-19 Extended domains
20-29 Computed data (views, materialized views)
30-39 Business logic (functions, procedures)
40-49 Triggers and constraints
50-89 Application-specific layers
90-98 Utilities and monitoring
99_   Finalization (grants, analyze)
```

### Domain Numbers (Second Level)

```
010_  First major domain
020_  Second major domain
030_  Third major domain
...
990_  Utilities/shared
```

**Why gaps?**
- Easy to add `015_new_domain` without renumbering
- Clear separation between domains

### Entity Numbers (Third Level)

```
0101  Core entity (main table)
0102  Related entity
0103  Junction table
0104  Audit table
...
```

---

## Dependencies and Execution Order

### Principle: Dependencies First

SQL files must be ordered so dependencies load before dependents:

```sql
-- ❌ BAD: View before table
10_user_stats_view.sql     -- References users table
20_users_table.sql         -- Defines users table (ERROR!)

-- ✅ GOOD: Table before view
10_users_table.sql         -- Defines users table
20_user_stats_view.sql     -- References users table (OK)
```

### Common Dependency Order

```
00_ Extensions         (CREATE EXTENSION)
01_ Schemas            (CREATE SCHEMA)
02_ Types/Enums        (CREATE TYPE)
10_ Base Tables        (CREATE TABLE with no foreign keys)
11_ Dependent Tables   (CREATE TABLE with foreign keys to 10_)
20_ Views              (CREATE VIEW referencing tables)
21_ Materialized Views (CREATE MATERIALIZED VIEW)
30_ Functions          (CREATE FUNCTION referencing tables/views)
40_ Triggers           (CREATE TRIGGER on tables/functions)
50_ Indexes            (CREATE INDEX)
99_ Finalization       (GRANT, ANALYZE, REFRESH MV)
```

### Circular Dependencies

If you have circular foreign keys:

```sql
-- Option 1: Separate constraints
-- 10_users.sql
CREATE TABLE users (
    id UUID PRIMARY KEY,
    org_id UUID  -- No FK yet
);

-- 11_organizations.sql
CREATE TABLE organizations (
    id UUID PRIMARY KEY,
    admin_user_id UUID  -- No FK yet
);

-- 12_constraints.sql
ALTER TABLE users ADD CONSTRAINT fk_users_org
    FOREIGN KEY (org_id) REFERENCES organizations(id);
ALTER TABLE organizations ADD CONSTRAINT fk_orgs_admin
    FOREIGN KEY (admin_user_id) REFERENCES users(id);
```

---

## File Naming Best Practices

### DO: Use Descriptive Names

```
✅ 0101_user_table.sql          # Clear: user table
✅ 0102_user_profile.sql        # Clear: user profile
✅ 0201_create_user_fn.sql      # Clear: function to create user
```

### DON'T: Use Vague Names

```
❌ 01_init.sql                  # Vague: what is initialized?
❌ 02_data.sql                  # Vague: what data?
❌ 03_misc.sql                  # Vague: never use "misc"
```

### Naming Format

```
{number}_{entity}_{type}.sql

Examples:
0101_user_table.sql
0102_user_profile_table.sql
0201_user_stats_view.sql
0301_create_user_fn.sql
0401_audit_user_trigger.sql
```

---

## Environment-Specific Differences

### Problem: Different Schemas Per Environment

Some environments need different SQL:

```
Production:  Extensions + Tables + Views + Functions
Staging:     Extensions + Tables + Views + Functions + Debug Tools
Development: Extensions + Tables + Views + Functions + Debug Tools + Test Data
```

### Solution: Environment Configs

Use `db/environments/{env}.yaml` to specify includes:

```yaml
# db/environments/production.yaml
includes:
  - ../schema  # Only schema

# db/environments/development.yaml
includes:
  - ../schema         # Schema
  - ../seeds/common   # Common seeds
  - ../seeds/development  # Dev-specific seeds
  - ../debug          # Debug views/functions
```

**See [getting-started.md](./getting-started.md)** for environment configuration details.

---

## When to Split Files

### Split When:
- **File > 500 lines**: Hard to navigate
- **Multiple concerns**: One file does users + posts + comments
- **Different dependencies**: Part needs extension A, part needs extension B

### Keep Together When:
- **Tightly coupled**: Table + its indexes + constraints
- **Small entities**: 10-line ENUM type
- **Atomic changes**: View + function that depend on each other

### Example: When to Split Tables

```
❌ TOO MUCH: One file per column
01_user_id.sql
02_user_name.sql
03_user_email.sql

✅ GOOD: Related tables together
01_users/
├── 0101_user.sql           # Main user table
├── 0102_user_profile.sql   # Profile extension
└── 0103_user_settings.sql  # Settings extension

❌ TOO LITTLE: Everything in one file
01_entire_schema.sql  (5000 lines)
```

---

## Migrations and Schema Files

### Principle: Schema is Source of Truth

After applying migrations, **update schema files**:

```bash
# 1. Generate migration
confiture migrate generate --name "add_user_bio"

# 2. Migration created:
db/migrations/003_add_user_bio.sql
    ALTER TABLE users ADD COLUMN bio TEXT;

# 3. Apply migration
confiture migrate up

# 4. UPDATE SCHEMA FILE!
vim db/schema/01_core/010_users/0101_user.sql
    # Add: bio TEXT to CREATE TABLE statement

# 5. Verify build still works
confiture build --env test
```

**Why?**: Fresh builds use schema files, not migrations. Keep them in sync.

---

## Tips for Complex Projects

### 1. Document Your Numbering System

Add `db/schema/README.md`:

```markdown
# Schema Organization

## Top-Level Numbers
- `00_common`: Infrastructure (extensions, types, security)
- `01_core`: Core business domain
- `02_views`: Read-optimized views
- `03_functions`: Business logic
- `99_finalize`: Post-build steps

## Second-Level Numbers
- `010`: User domain
- `020`: Organization domain
- `030`: Location domain
```

### 2. Use Consistent Prefixes

Pick a pattern and stick to it:
```
Tables:      0101_user_table.sql
Views:       0201_user_stats_view.sql
Functions:   0301_create_user_fn.sql
Triggers:    0401_audit_user_trigger.sql
```

### 3. Group Related Files in Directories

```
010_users/
├── 0101_user_table.sql
├── 0102_user_profile_table.sql
├── 0103_user_indexes.sql
└── 0104_user_constraints.sql
```

### 4. Use Scripts to Verify Order

```bash
#!/bin/bash
# scripts/verify_order.sh
# Verify no VIEW references undefined tables

# List all files in order
find db/schema -name "*.sql" | sort

# TODO: Parse SQL and verify dependencies
```

---

## Common Mistakes

### ❌ Mistake 1: No Number Prefixes

```
db/schema/
├── extensions.sql
├── tables.sql
├── views.sql      # Which comes first? Depends on filesystem!
└── functions.sql
```

**Fix**: Add numbers
```
├── 00_extensions.sql
├── 10_tables.sql
├── 20_views.sql
└── 30_functions.sql
```

### ❌ Mistake 2: No Gaps in Numbers

```
001_extensions.sql
002_types.sql
003_tables.sql  # Hard to insert between 002 and 003!
```

**Fix**: Leave gaps
```
010_extensions.sql
020_types.sql
030_tables.sql  # Easy to add 025_new_thing.sql
```

### ❌ Mistake 3: Inconsistent Depth

```
db/schema/
├── users.sql                   # Flat
├── posts/                      # Directory
│   └── posts.sql
└── comments/                   # Directory
    ├── comments.sql
    └── comment_votes.sql
```

**Fix**: Consistent structure
```
db/schema/
├── 010_users/
│   └── 0101_users.sql
├── 020_posts/
│   └── 0201_posts.sql
└── 030_comments/
    ├── 0301_comments.sql
    └── 0302_comment_votes.sql
```

---

## Quick Reference

| Project Size | Files | Pattern | Example |
|-------------|-------|---------|---------|
| **Tiny** | <10 | Flat | `10_users.sql`, `20_posts.sql` |
| **Small** | 10-20 | Flat numbered | `10_tables.sql`, `20_views.sql` |
| **Medium** | 20-100 | Single-level dirs | `10_tables/users.sql` |
| **Large** | 100-500 | Two-level dirs | `01_core/010_users/users.sql` |
| **Enterprise** | 500+ | Three-level dirs | `01_core/010_users/0101_user.sql` |

---

## Examples

See working examples in the repository:

- **[examples/basic/](../examples/basic/)**: Simple blog schema
- **[examples/fraiseql/](../examples/fraiseql/)**: FraiseQL integration
- **Complex projects**: Use three-level directory pattern (shown above)

---

## Summary

1. **Use numbered prefixes** (`00_`, `10_`, `20_`) to control order
2. **Leave gaps** (010, 020, 030) for future additions
3. **Match complexity to project size**: Flat → Single-level → Multi-level
4. **Dependencies first**: Extensions → Types → Tables → Views → Functions
5. **Document your system**: Add `db/schema/README.md`
6. **Keep schema files updated**: After migrations, update DDL source

**Remember**: Schema files are the source of truth. Migrations are derived.

---

## Related Documentation

- **[Meaningful Test UUIDs](./meaningful-test-uuids.md)** - Generate debuggable UUIDs for seed data
- **[Getting Started Guide](./getting-started.md)** - First steps with Confiture
- **[Migration Decision Tree](./guides/migration-decision-tree.md)** - When to use each approach

---

*Part of [Confiture](../README.md) - PostgreSQL migrations, sweetly done 🍓*
