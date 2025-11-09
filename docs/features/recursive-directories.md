# Recursive Directory Support

**Deep file discovery with deterministic ordering**

---

## Overview

Recursive directory support enables Confiture to discover SQL files in nested directory structures while maintaining consistent, predictable build order. This is essential for large projects with complex schema organizations.

---

## Use Cases

### When to Use Recursive Directories

- **Large schemas** with hierarchical organization
- **Complex domains** split across multiple subdirectories
- **Enterprise projects** with hundreds of SQL files
- **Team collaboration** with feature-based directory structures

### Example Scenarios

```bash
# Enterprise schema structure
db/schema/
├── 00_common/
│   ├── 000_security/
│   │   ├── 0001_roles.sql
│   │   └── 0002_schemas.sql
│   └── 001_extensions/
│       └── 0010_postgis.sql
├── 01_core/
│   ├── 010_users/
│   │   ├── 0101_user.sql
│   │   └── 0102_user_profile.sql
│   └── 020_content/
│       └── 0201_posts.sql
└── 02_views/
    └── 010_user_views/
        └── 0101_user_stats.sql
```

---

## Configuration

### Recursive Mode (Default)

```yaml
# Recursive discovery (default behavior)
include_dirs:
  - path: db/schema
    recursive: true  # Finds files in all subdirectories
```

### Non-Recursive Mode

```yaml
# Non-recursive: Only immediate children
include_dirs:
  - path: db/schema
    recursive: false
    include:
      - "*.sql"  # Only files directly in db/schema/
```

### Mixed Configuration

```yaml
# Different settings per directory
include_dirs:
  - path: db/schema
    recursive: true   # Deep discovery
  - path: db/seeds
    recursive: false  # Only root level seeds
```

---

## Ordering Behavior

### Deterministic Ordering

Files are processed in alphabetical order by full path:

```bash
# Example file order
db/schema/00_common/000_security/0001_roles.sql
db/schema/00_common/000_security/0002_schemas.sql
db/schema/00_common/001_extensions/0010_postgis.sql
db/schema/01_core/010_users/0101_user.sql
db/schema/01_core/010_users/0102_user_profile.sql
db/schema/01_core/020_content/0201_posts.sql
db/schema/02_views/010_user_views/0101_user_stats.sql
```

### Directory-Level Ordering

When using multiple include directories, order is controlled by the `order` parameter:

```yaml
include_dirs:
  - path: db/extensions
    order: 10  # Process first
  - path: db/schema
    order: 20  # Process second
  - path: db/views
    order: 30  # Process last
```

---

## Examples

### Enterprise Schema

```yaml
# db/environments/production.yaml
include_dirs:
  - path: db/schema
    recursive: true
```

**Directory structure**:
```
db/schema/
├── 00_common/
│   ├── 000_security/
│   │   ├── 0001_roles.sql
│   │   └── 0002_schemas.sql
│   └── 001_extensions/
│       ├── 0010_postgis.sql
│       └── 0011_uuid.sql
├── 01_core/
│   ├── 010_users/
│   │   ├── 0101_user.sql
│   │   ├── 0102_user_profile.sql
│   │   └── 0103_user_settings.sql
│   ├── 020_organizations/
│   │   └── 0201_organization.sql
│   └── 030_locations/
│       ├── 0301_country.sql
│       └── 0302_address.sql
├── 02_views/
│   ├── 010_user_views/
│   │   └── 0101_active_users.sql
│   └── 020_org_views/
│       └── 0201_org_hierarchy.sql
└── 03_functions/
    └── 010_user_functions/
        ├── 0101_create_user.sql
        └── 0102_authenticate.sql
```

### Feature-Based Organization

```yaml
include_dirs:
  - path: db/features
    recursive: true
```

**Structure**:
```
db/features/
├── user_management/
│   ├── schema/
│   │   ├── 010_user.sql
│   │   └── 020_user_profile.sql
│   └── seeds/
│       └── 010_test_users.sql
├── content/
│   ├── schema/
│   │   └── 010_posts.sql
│   └── seeds/
│       └── 010_sample_posts.sql
└── analytics/
    └── schema/
        └── 010_page_views.sql
```

### Mixed Recursive/Non-Recursive

```yaml
include_dirs:
  - path: db/schema
    recursive: true   # Deep structure
  - path: db/seeds
    recursive: false  # Flat seeds directory
    include:
      - "*.sql"
```

### Complex Nested Structures

```yaml
# Enterprise with feature-based organization
include_dirs:
  - path: db/features
    recursive: true
```

**Directory structure**:
```
db/features/
├── user_management/
│   ├── schema/
│   │   ├── 010_user.sql
│   │   └── 020_user_profile.sql
│   ├── seeds/
│   │   └── 010_test_users.sql
│   └── migrations/
│       └── 001_add_user_bio.sql
├── content_management/
│   ├── schema/
│   │   └── 010_posts.sql
│   └── seeds/
│       └── 010_sample_content.sql
└── analytics/
    └── schema/
        ├── 010_page_views.sql
        └── 020_user_events.sql
```

### Version-Controlled Schemas

```yaml
# Schema versioning with recursive discovery
include_dirs:
  - path: db/versions
    recursive: true
```

**Structure**:
```
db/versions/
├── v1/
│   ├── base/
│   │   ├── 010_extensions.sql
│   │   └── 020_basic_tables.sql
│   └── features/
│       └── 030_user_auth.sql
├── v2/
│   └── features/
│       ├── 040_user_profiles.sql
│       └── 050_content.sql
└── current/
    └── features/
        └── 060_analytics.sql
```

---

## Performance Considerations

### Large Directory Structures

For projects with 1000+ files:

- **Use specific patterns** to limit discovery scope
- **Exclude unnecessary directories** with patterns
- **Consider shallow structures** for frequently changing files

```yaml
# Optimized for large schemas
include_dirs:
  - path: db/schema
    recursive: true
    include:
      - "**/*.sql"
    exclude:
      - "**/archive/**"
      - "**/temp/**"
```

### Build Time Optimization

- **Recursive discovery** is fast for typical schemas (< 500 files)
- **Pattern filtering** reduces file system operations
- **Caching** helps with repeated builds

---

## Migration Guide

### From Flat Structure

```bash
# Before: Flat directory
db/schema/
├── 00_extensions.sql
├── 10_users.sql
├── 20_posts.sql
└── 30_views.sql

# After: Hierarchical
db/schema/
├── 00_common/
│   └── 00_extensions.sql
├── 10_core/
│   ├── 10_users.sql
│   └── 20_posts.sql
└── 30_views/
    └── 30_user_views.sql
```

### Gradual Adoption

1. **Start with recursive enabled** (default)
2. **Organize files** into logical directories
3. **Test builds** at each step
4. **Update documentation** with new structure

---

## Troubleshooting

### Files in Wrong Order

**Problem**: Files not processing in expected sequence

**Check**:
1. Directory names have correct prefixes?
2. File names follow numbering convention?
3. Multiple include_dirs have correct `order` values?

### Missing Files

**Problem**: Some files not included in build

**Check**:
1. `recursive: true` for nested files?
2. Include patterns match file paths?
3. Exclude patterns too broad?

### Performance Issues

**Problem**: Slow builds with deep directory structures

**Solutions**:
1. Use more specific include patterns
2. Exclude archive/temp directories
3. Consider flatter structure for performance-critical builds

### Edge Cases

#### Very Deep Nesting

```bash
# Extremely deep structures work but may be slow
db/schema/level1/level2/level3/level4/level5/file.sql
# Consider flattening if >5 levels deep
```

#### Symlinks and Special Files

```bash
# Symlinks are followed normally
db/schema/tables.sql -> ../other/tables.sql  # Works
db/schema/circular_link -> ../schema/        # Avoid circular links
```

#### Permission Issues

```bash
# Files without read permission are skipped
# Check permissions if files seem missing
ls -la db/schema/problematic_file.sql
```

#### Concurrent Modifications

```bash
# Directory changes during build may cause inconsistent results
# Avoid modifying schema files during builds
```

#### Empty Subdirectories

```bash
# Empty directories are ignored (no errors)
db/schema/
├── 00_extensions/
│   └── extensions.sql
├── 10_tables/        # Empty - silently ignored
│   └── users.sql
└── 20_views/         # Empty - silently ignored
```

---

## Best Practices

### Directory Naming

- **Use numbered prefixes** for consistent ordering
- **Leave gaps** (010, 020, 030) for future additions
- **Be descriptive** but not verbose

### File Organization

- **Group related files** in same directory
- **Use consistent numbering** within directories
- **Document structure** in `db/schema/README.md`

### Maintenance

- **Regular cleanup** of unused directories
- **Version control** directory structure changes
- **Test builds** after reorganization

---

## See Also

- **[Organizing SQL Files](../organizing-sql-files.md)** - Complete organization guide
- **[Dynamic Discovery](dynamic-discovery.md)** - Advanced file filtering
- **[Hexadecimal Sorting](hexadecimal-sorting.md)** - Alternative ordering method

---

*Recursive directories bring structure to complexity - organize without limits!* 🏗️