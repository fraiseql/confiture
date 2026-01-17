# Hexadecimal Sorting

**Intuitive file ordering for complex database schemas**

---

## Overview

Hexadecimal sorting enables more intuitive file ordering by supporting hex-prefixed filenames like `0x01_`, `0x0A_`, `0x14_`. Instead of pure alphabetical sorting, files are ordered numerically by their hexadecimal prefix values.

This feature is particularly useful for large schemas where you need more than 9 main categories, or when you want clearer visual separation between major sections.

---

## Use Cases

### When to Use Hex Sorting

- **Large schemas** with 10+ major sections
- **Complex domains** requiring clear visual hierarchy
- **Enterprise projects** with hundreds of files
- **Future-proofing** - hex allows 255 main categories (0x00-0xFF)

### Example Scenarios

```bash
# Traditional decimal (limited to 9 main sections)
00_extensions.sql
10_tables.sql
20_views.sql
30_functions.sql
# Can't easily add between 30 and 40

# Hexadecimal (255 possible main sections)
0x00_extensions.sql
0x0A_tables.sql      # 10
0x14_views.sql       # 20
0x1E_functions.sql   # 30
0x28_triggers.sql    # 40 - Easy to insert!
```

---

## Configuration

### Enabling Hex Sorting

Set `sort_mode: hex` in your environment configuration:

```yaml
# db/environments/production.yaml
name: production
database_url: postgresql://...

build:
  sort_mode: hex  # Enable hex sorting

include_dirs:
  - db/schema
```

### Default Behavior

If `sort_mode` is not specified or set to `alphabetical`, files sort alphabetically:

```yaml
# Default: alphabetical sorting
build:
  sort_mode: alphabetical  # or omit entirely
```

---

## File Naming Convention

### Hex Prefix Format

```
0x{HH}_{description}.sql

Where:
- 0x: Literal hex prefix
- HH: Two hexadecimal digits (00-FF)
- _: Underscore separator
- description: Human-readable name
```

### Valid Examples

```bash
0x00_extensions.sql      # 0   - Extensions
0x01_security.sql        # 1   - Security setup
0x0A_users.sql          # 10  - User domain
0x0B_posts.sql          # 11  - Content domain
0x14_views.sql          # 20  - Views
0x1E_functions.sql      # 30  - Functions
0x28_triggers.sql       # 40  - Triggers
0x32_indexes.sql        # 50  - Indexes
0xFF_finalize.sql       # 255 - Final steps
```

### Invalid Examples

```bash
# Missing 0x prefix
10_users.sql            # ❌ Alphabetical sorting

# Wrong case
0X0A_users.sql          # ❌ Must be lowercase 0x

# No underscore
0x0Ausers.sql           # ❌ Must have underscore

# Invalid hex
0xGG_users.sql          # ❌ G is not hex digit

# Single digit (ambiguous)
0xA_users.sql           # ❌ Use 0x0A format
```

---

## Ordering Rules

### Hex Files First

When hex sorting is enabled:
1. **Hex-prefixed files** sort by hex value (0x00, 0x01, 0x0A, etc.)
2. **Non-hex files** sort alphabetically after hex files

```bash
# File order with sort_mode: hex
0x00_extensions.sql     # First (0)
0x0A_tables.sql         # Second (10)
abc_alphabetical.sql    # Third (no hex prefix)
z_alphabetical.sql      # Fourth (no hex prefix)
```

### Within Same Hex Value

Files with identical hex prefixes sort alphabetically by the remainder:

```bash
0x0A_users.sql          # 0x0A prefix, "users" alphabetically first
0x0A_posts.sql          # 0x0A prefix, "posts" alphabetically second
```

---

## Examples

### Basic Schema Organization

```bash
db/schema/
├── 0x00_extensions.sql
├── 0x01_security.sql
├── 0x0A_core_tables/
│   ├── 0x0A_users.sql
│   ├── 0x0B_posts.sql
│   └── 0x0C_comments.sql
├── 0x14_views/
│   └── 0x14_user_stats.sql
└── 0x1E_functions/
    └── 0x1E_create_user.sql
```

### Migration from Decimal

```bash
# Before (decimal)
00_extensions.sql
10_tables.sql
20_views.sql

# After (hex - more flexible)
0x00_extensions.sql
0x0A_tables.sql
0x14_views.sql
# Can now easily add 0x0F_reports.sql between tables and views
```

### Enterprise Structure

```bash
db/schema/
├── 0x00_common/
│   ├── 0x00_extensions.sql
│   └── 0x01_types.sql
├── 0x0A_user_domain/
│   ├── 0x0A_user_table.sql
│   └── 0x0B_user_profile.sql
├── 0x14_content_domain/
│   ├── 0x14_posts.sql
│   └── 0x15_comments.sql
├── 0x1E_analytics/
│   └── 0x1E_reports.sql
└── 0xFF_finalize/
    └── 0xFF_grants.sql
```

### Advanced Hex Patterns

#### Domain-Based Organization

```bash
# Large enterprise with multiple domains
0x00_infrastructure/     # 0   - Base infrastructure
0x0A_user_domain/        # 10  - User management
0x14_content_domain/     # 20  - Content management
0x1E_billing_domain/     # 30  - Billing & payments
0x28_analytics_domain/   # 40  - Analytics & reporting
0x32_integration/        # 50  - External integrations
0x3C_admin_domain/       # 60  - Administrative functions
0x46_audit_domain/       # 70  - Audit & compliance
0xFF_maintenance/        # 255 - Maintenance scripts
```

#### Version-Based Organization

```bash
# Schema versioning with hex
0x00_v1_base/           # Version 1 foundation
0x0A_v2_users/          # Version 2 user features
0x14_v3_content/        # Version 3 content features
0x1E_v4_analytics/      # Version 4 analytics
# Room for v5-v15 features
0xFF_migrations/        # Migration utilities
```

---

## Implementation Details

### Sort Algorithm

1. Extract hex prefix from filename
2. Convert hex to integer (0x0A → 10)
3. Sort by hex value first
4. For equal hex values, sort alphabetically by remaining filename

### Performance

- **O(n log n)** sorting complexity
- Negligible performance impact for typical schema sizes (< 1000 files)
- Regex-based prefix extraction is efficient

### Backward Compatibility

- **Default**: Alphabetical sorting (existing behavior)
- **Opt-in**: Set `sort_mode: hex` to enable
- **Mixed**: Works with existing decimal-prefixed files

---

## Migration Guide

### For Existing Projects

1. **Test current build**:
   ```bash
   confiture build --env your_env
   ```

2. **Enable hex sorting** in config:
   ```yaml
   build:
     sort_mode: hex
   ```

3. **Test build again**:
   ```bash
   confiture build --env your_env
   ```

4. **Optionally rename files** to hex prefixes:
   ```bash
   # Rename decimal to hex
   mv 10_tables.sql 0x0A_tables.sql
   mv 20_views.sql 0x14_views.sql
   ```

### Gradual Adoption

You can mix decimal and hex prefixes during migration:

```bash
# Mixed prefixes work fine
00_extensions.sql       # Decimal (0)
0x0A_tables.sql         # Hex (10)
20_views.sql            # Decimal (20)
0x14_functions.sql      # Hex (20) - sorts after 20_views.sql
```

---

## Troubleshooting

### Files Not Sorting as Expected

**Problem**: Files appear in wrong order

**Check**:
1. Is `sort_mode: hex` set in config?
2. Do files have correct `0x` prefix format?
3. Are hex digits uppercase? (Should be: `0x0A`, not `0x0a`)

### Performance Issues

**Problem**: Build is slow with many files

**Solution**: Hex sorting is fast, but consider:
- Reduce files if >1000
- Check for filesystem issues
- Profile with `time confiture build`

### Edge Cases

#### Mixed Hex and Non-Hex Files

```bash
# Valid: Hex files sort first, then alphabetical
0x0A_tables.sql         # First (10)
0x14_views.sql          # Second (20)
legacy_functions.sql    # Third (alphabetical)
z_old_backup.sql        # Fourth (alphabetical)
```

#### Duplicate Hex Values

```bash
# Same hex value sorts alphabetically by filename
0x0A_user_auth.sql      # First (0x0A, "user_auth")
0x0A_user_profile.sql   # Second (0x0A, "user_profile")
0x0A_admin.sql          # Third (0x0A, "admin")
```

#### Very Large Hex Values

```bash
# High hex values work fine
0xFE_penultimate.sql    # 254
0xFF_final.sql          # 255 (highest possible)
```

#### Case Sensitivity

```bash
# Hex parsing is case-sensitive
0x0A_Tables.sql         # Valid (uppercase T)
0x0a_tables.sql         # Valid (lowercase a, but different from 0A)
0x0A_tables.sql         # Valid (same as first)
```

### Mixed Environments

**Problem**: Different sorting in different environments

**Solution**: Ensure all environments use same `sort_mode` setting

---

## See Also

- **[Organizing SQL Files](../organizing-sql-files.md)** - Complete file organization guide
- **[Configuration Reference](../reference/configuration.md)** - Build configuration options
- **[Migration Decision Tree](../guides/migration-decision-tree.md)** - When to use different approaches

---

*Hex sorting brings clarity to complex schemas - 255 possible categories instead of 9!* 🎯