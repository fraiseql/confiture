# PostgreSQL Version Detection API Reference

[← Back to API Reference](index.md)

**Stability**: Library API 🧩

---

## Overview

Detect the live PostgreSQL version and gate features / generate version-aware
SQL accordingly. Useful when a migration must adapt to the server it runs
against (e.g. `REINDEX CONCURRENTLY` needs PG 12+).

```python
from confiture import detect_version, PGFeature, VersionAwareSQL
```

---

## Quick Start

```python
import psycopg
from confiture import detect_version, PGFeature, VersionAwareSQL

conn = psycopg.connect("postgresql://localhost/myapp")
version = detect_version(conn)          # → PGVersionInfo

if version.supports(PGFeature.REINDEX_CONCURRENTLY):
    sql = VersionAwareSQL(version)
    print(sql.reindex_concurrently("idx_users_email"))
```

---

## Public Surface

| Symbol | Kind | Purpose |
|--------|------|---------|
| `detect_version(connection)` | function | Detect the live server version → `PGVersionInfo` |
| `parse_version_string(s)` | function | Parse a `server_version` string → `PGVersionInfo` |
| `check_version_compatibility(...)` | function | Validate a version against requirements |
| `get_recommended_settings(version)` | function | Suggested settings for a given version |
| `PGVersionInfo` | dataclass | Major/minor version + feature queries |
| `PGFeature` | enum | Named features tagged with their minimum major version |
| `VersionAwareSQL` | class | Emit SQL that adapts to the detected version |

`PGFeature` members (e.g. `GENERATED_COLUMNS`, `REINDEX_CONCURRENTLY`,
`JSON_PATH`, `VACUUM_PARALLEL`) each carry the minimum PostgreSQL major version
that supports them, so feature gating is a single `version.supports(feature)`
check.

---

## See Also

- [Migrator](migrator.md) — applies migrations against a live server
- [Linting](linting.md) — static schema validation
