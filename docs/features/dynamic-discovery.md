# Dynamic Discovery

**Flexible SQL file discovery with patterns and advanced filtering**

---

## Overview

Dynamic discovery enhances Confiture's file discovery capabilities with include/exclude patterns, recursive directory traversal control, and flexible project structure support. This allows for sophisticated file selection while maintaining deterministic build order.

---

## Use Cases

### When to Use Dynamic Discovery

- **Complex project structures** with mixed file types
- **Selective builds** (e.g., exclude test fixtures in production)
- **Multi-environment schemas** with different requirements
- **Large codebases** needing fine-grained control

### Example Scenarios

```bash
# E-commerce project
include_dirs:
  - path: db/schema
    include:
      - "**/*.sql"
    exclude:
      - "**/test_*"
      - "**/temp/**"

# Development environment (includes seeds)
include_dirs:
  - path: db/schema
  - path: db/seeds/common
  - path: db/seeds/development

# Production environment (no seeds)
include_dirs:
  - path: db/schema
```

---

## Configuration

### Basic Include Directory

```yaml
# Simple directory inclusion
include_dirs:
  - db/schema
```

### Advanced Configuration

```yaml
include_dirs:
  - path: db/schema
    recursive: true          # Default: true
    include:
      - "**/*.sql"           # Include patterns
    exclude:
      - "**/*.bak"           # Exclude patterns
      - "**/temp/**"
    order: 10                # Processing order
    auto_discover: false     # Default: false
```

### Multiple Directories

```yaml
include_dirs:
  - path: db/schema
    order: 10
  - path: db/seeds
    order: 20
    include:
      - "**/*.sql"
    exclude:
      - "**/development/**"  # Skip dev seeds
```

---

## Pattern Syntax

### Glob Patterns

Uses standard glob syntax with `**` for recursive matching:

```
*         Match any characters (non-recursive)
**        Match any characters (recursive)
?         Match single character
[abc]     Match any character in set
[!abc]    Match any character not in set
```

### Common Patterns

```yaml
include:
  # All SQL files
  - "**/*.sql"

  # Specific naming patterns
  - "**/*_table.sql"
  - "**/*_view.sql"

  # Migration files
  - "**/migrations/*.up.sql"

exclude:
  # Backup files
  - "**/*.bak"
  - "**/*.backup"

  # Temporary files
  - "**/temp/**"
  - "**/tmp/**"

  # Test files
  - "**/test_*"
  - "**/*_test.sql"
```

---

## Directory Options

### Recursive vs Non-Recursive

```yaml
# Recursive (default): Find files in subdirectories
include_dirs:
  - path: db/schema
    recursive: true

# Non-recursive: Only immediate children
include_dirs:
  - path: db/schema
    recursive: false
    include:
      - "*.sql"  # Only root level
```

### Auto-Discovery

```yaml
# Auto-discover: Skip missing directories silently
include_dirs:
  - path: db/optional_feature
    auto_discover: true  # Won't error if missing

# Strict (default): Error on missing directories
include_dirs:
  - path: db/required_schema
    auto_discover: false  # Errors if missing
```

### Processing Order

```yaml
# Control execution order with explicit ordering
include_dirs:
  - path: db/extensions
    order: 10     # Process first
  - path: db/tables
    order: 20     # Process second
  - path: db/views
    order: 30     # Process last
```

---

## Examples

### E-commerce Schema

```yaml
# db/environments/production.yaml
name: production
database_url: postgresql://...

include_dirs:
  - path: db/schema
    include:
      - "**/*.sql"
    exclude:
      - "**/test_*"
      - "**/development/**"
      - "**/*.bak"
    recursive: true
```

**Directory structure**:
```
db/schema/
├── extensions/
│   ├── postgis.sql
│   └── uuid.sql
├── tables/
│   ├── users.sql
│   ├── products.sql
│   └── orders.sql
├── views/
│   ├── user_stats.sql
│   └── product_catalog.sql
└── development/
    ├── debug_functions.sql  # Excluded
    └── test_data.sql        # Excluded
```

### Multi-Environment Setup

```yaml
# db/environments/development.yaml
include_dirs:
  - path: db/schema
    order: 10
  - path: db/seeds/common
    order: 20
  - path: db/seeds/development
    order: 30
  - path: db/debug
    order: 40
    auto_discover: true  # OK if missing

# db/environments/production.yaml
include_dirs:
  - path: db/schema
    order: 10
  - path: db/seeds/common
    order: 20
    exclude:
      - "**/development/**"
```

### Migration-Based Projects

```yaml
# For projects using migrations + schema files
include_dirs:
  - path: db/schema
    include:
      - "**/*.sql"
    exclude:
      - "**/migrations/**"  # Exclude if migrations separate
    recursive: true
  - path: db/migrations
    include:
      - "**/*.up.sql"
    order: 50  # Apply after schema
```

---

## Advanced Patterns

### Conditional Includes

```yaml
# Include different files based on environment
include_dirs:
  - path: db/schema
    include:
      - "**/*.sql"
  - path: db/seeds
    include:
      - "**/common/**"
      - "**/production/**"   # Only production seeds
    exclude:
      - "**/development/**"
```

### File Type Filtering

```yaml
# Separate handling for different file types
include_dirs:
  - path: db/schema
    include:
      - "**/*.sql"
    exclude:
      - "**/*.view.sql"  # Handle views separately
  - path: db/views
    include:
      - "**/*.view.sql"
    order: 20  # Process after tables
```

### Environment-Specific Patterns

```yaml
# Development: Include all SQL plus debug files
include_dirs:
  - path: db/schema
    include:
      - "**/*.sql"
  - path: db/debug
    include:
      - "**/*.sql"
    auto_discover: true  # OK if missing

# Testing: Include schema + test fixtures
include_dirs:
  - path: db/schema
    include:
      - "**/*.sql"
  - path: db/tests
    include:
      - "**/fixtures/*.sql"

# Production: Only core schema
include_dirs:
  - path: db/schema
    include:
      - "**/*.sql"
    exclude:
      - "**/development/**"
      - "**/debug/**"
      - "**/test/**"
```

### Backup and Archive Handling

```yaml
# Exclude common backup/archive patterns
include_dirs:
  - path: db/schema
    include:
      - "**/*.sql"
    exclude:
      - "**/*.bak"
      - "**/*.backup"
      - "**/*.old"
      - "**/*.archive"
      - "**/backup/**"
```

---

## Implementation Details

### Discovery Algorithm

1. **Collect directories** in order specified
2. **For each directory**:
   - Check if exists (unless `auto_discover: true`)
   - Apply include patterns
   - Apply exclude patterns
   - Recurse if `recursive: true`
3. **Sort all files** according to global sort mode
4. **Return deterministic order**

### Pattern Precedence

1. **Include patterns** define what to consider
2. **Exclude patterns** remove from included set
3. **Directory existence** checked unless auto_discover

### Performance Considerations

- **Pattern matching** uses efficient glob implementation
- **Caching** available for repeated discoveries
- **Large directories** may benefit from specific include patterns

---

## Migration Guide

### From Simple Configuration

```yaml
# Old: Simple string paths
include_dirs:
  - db/schema
  - db/seeds

# New: Object configuration
include_dirs:
  - path: db/schema
    recursive: true
  - path: db/seeds
    recursive: true
```

### Adding Patterns Gradually

```yaml
# Start simple
include_dirs:
  - db/schema

# Add patterns incrementally
include_dirs:
  - path: db/schema
    include:
      - "**/*.sql"

# Add exclusions
include_dirs:
  - path: db/schema
    include:
      - "**/*.sql"
    exclude:
      - "**/*.bak"
```

---

## Troubleshooting

### Files Not Included

**Problem**: Expected files missing from build

**Check**:
1. Directory path correct?
2. `recursive: true` if files in subdirs?
3. Include patterns match filenames?
4. Exclude patterns too broad?

**Debug**:
```bash
# List all SQL files
find db/schema -name "*.sql"

# Test pattern matching
python -c "
import glob
print(glob.glob('db/schema/**/*.sql', recursive=True))
"
```

### Unexpected Files Included

**Problem**: Extra files appearing in build

**Check**:
1. Exclude patterns correct?
2. Recursive setting appropriate?
3. Multiple directories conflicting?

### Performance Issues

**Problem**: Discovery slow for large directories

**Solutions**:
1. Use specific include patterns
2. Exclude unnecessary subdirectories
3. Consider non-recursive for flat structures

### Edge Cases

#### Complex Pattern Interactions

```yaml
# Include takes precedence over exclude for same file
include_dirs:
  - path: db/schema
    include:
      - "**/important.sql"  # Explicitly included
    exclude:
      - "**/important.sql"  # This exclude is ignored
```

#### Multiple Directory Ordering

```yaml
# Order affects final file sequence
include_dirs:
  - path: db/extensions
    order: 10
  - path: db/tables
    order: 20
  - path: db/views
    order: 30
# Files from extensions run before tables, tables before views
```

#### Auto-Discover with Patterns

```yaml
# Auto-discover skips missing directories even with patterns
include_dirs:
  - path: db/optional_feature
    auto_discover: true
    include:
      - "**/*.sql"  # Patterns still apply if directory exists
```

#### Empty Directories

```yaml
# Empty directories are handled gracefully
include_dirs:
  - path: db/empty_dir  # No error if empty
  - path: db/missing_dir
    auto_discover: true  # No error if missing
```

---

## See Also

- **[Recursive Directories](recursive-directories.md)** - Directory traversal control
- **[Configuration Reference](../reference/configuration.md)** - Complete config options
- **[Organizing SQL Files](../organizing-sql-files.md)** - File organization patterns

---

*Dynamic discovery gives you surgical precision over which files get built!* 🎯