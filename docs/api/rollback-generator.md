# Rollback Generation API Reference

[← Back to API Reference](index.md)

**Stability**: Library API 🧩

---

## Overview

Auto-generate `down`-migration SQL for the common, mechanically-reversible DDL
operations, and flag destructive statements that need a backup instead. Best
effort: each suggestion carries a confidence level so you review before relying
on it.

```python
from confiture import generate_rollback, generate_rollback_script
```

Reversible patterns: `CREATE TABLE → DROP TABLE`, `CREATE INDEX → DROP INDEX`,
`ADD COLUMN → DROP COLUMN`, `ALTER TABLE ADD CONSTRAINT → DROP CONSTRAINT`.

---

## Quick Start

```python
from confiture import generate_rollback, suggest_backup_for_destructive_operations

suggestion = generate_rollback("CREATE TABLE users (id int);")
if suggestion:
    print(suggestion.rollback_sql)   # "DROP TABLE users;"
    print(suggestion.confidence)     # "high" | "medium" | "low"

# Destructive ops can't be auto-reversed — get backup guidance instead:
for hint in suggest_backup_for_destructive_operations("DROP TABLE users;"):
    print(hint)
```

For a multi-statement migration, `generate_rollback_script(sql)` returns a list
of `RollbackSuggestion` (in reverse application order).

---

## Public Surface

| Symbol | Kind | Purpose |
|--------|------|---------|
| `generate_rollback(sql)` | function | One reversible statement → `RollbackSuggestion \| None` |
| `generate_rollback_script(sql)` | function | Multi-statement → `list[RollbackSuggestion]` |
| `suggest_backup_for_destructive_operations(sql)` | function | Backup hints for irreversible ops |
| `RollbackSuggestion` | dataclass | `original_sql`, `rollback_sql`, `confidence`, `notes`; `.to_dict()` |
| `RollbackTester` | class | Validate a generated rollback against a database |
| `RollbackTestResult` | dataclass | Result of a rollback test run |

> **Always review generated rollbacks.** Low/medium-confidence suggestions and
> any destructive operation should be verified (and backed up) before use.

---

## See Also

- [Migrator](migrator.md) — `down()` / rollback execution
- [Dry-Run Guide](../guides/dry-run.md) — test migrations safely
