# Phase 4.2 Addendum - Python Architect Notes

**Source**: Python Architect Specialist Review (2025-12-26)
**Status**: Phase 4.1 APPROVED - Phase 4.2 Enhancement Notes
**Priority**: Medium (nice-to-have, not blocking)
**Effort Estimate**: 1-2 days total

---

## Overview

During the Python Architect specialist review, two minor enhancements were identified for Phase 4.2. These are **not blocking** Phase 4.1 approval but will improve production readiness and extensibility.

---

## Enhancement 1: Entry Points Support for Third-Party Hooks

**Status**: Phase 4.1 ❌ Not needed | Phase 4.2 ✅ Recommended
**Priority**: Medium
**Effort**: 4-6 hours
**Breaking Changes**: None

### Current State (Phase 4.1)

Hooks are registered via global registry:

```python
from confiture.core import register_hook, Hook

class MyCustomHook(Hook):
    phase = HookPhase.AFTER_DDL
    def execute(self, conn, context):
        return HookResult(...)

# Registration (requires importing)
register_hook("my_hook", MyCustomHook)
```

**Works for**: Internal hooks, monolithic applications

**Problem**: Third-party packages can't auto-register hooks without code changes

### Phase 4.2 Enhancement

Add setuptools entry points support alongside the registry:

**1. Update pyproject.toml** (or setup.py):

```toml
[project.entry-points."confiture.hooks"]
# Built-in hooks (future)
# backfill_read_model = "confiture.hooks.built_in:BackfillReadModelHook"

# Users can add their own in their projects
# my_package.hooks = "my_package.hooks:MyCustomHook"
```

**2. Update HookRegistry to discover entry points**:

```python
from importlib.metadata import entry_points

class HookRegistry:
    def __init__(self):
        self._hooks: dict[str, type[Hook]] = {}
        self._load_entry_points()

    def _load_entry_points(self) -> None:
        """Load hooks from setuptools entry points."""
        try:
            # Python 3.10+
            eps = entry_points(group="confiture.hooks")
        except TypeError:
            # Python 3.9
            eps = entry_points().get("confiture.hooks", [])

        for ep in eps:
            try:
                hook_class = ep.load()
                self.register(ep.name, hook_class)
            except Exception as e:
                logger.warning(
                    f"Failed to load hook from entry point {ep.name}: {e}"
                )

    def register(self, name: str, hook_class: type[Hook]) -> None:
        """Register a hook class by name."""
        if not issubclass(hook_class, Hook):
            raise TypeError(f"{hook_class} must be a subclass of Hook")
        self._hooks[name] = hook_class
```

**3. Usage Example**:

```python
# User's project (my_package/pyproject.toml)
[project.entry-points."confiture.hooks"]
backfill_customers = "my_package.hooks:BackfillCustomersHook"
validate_tenant_id = "my_package.hooks:ValidateTenantIdHook"

# User's hooks (my_package/hooks.py)
from confiture.core import Hook, HookPhase, HookResult

class BackfillCustomersHook(Hook):
    phase = HookPhase.AFTER_DDL

    def execute(self, conn, context):
        # Custom logic
        return HookResult(...)

# Usage: Hooks are automatically discovered
# No registration code needed!
```

### Benefits

✅ **Automatic Discovery**: Hooks loaded without code changes
✅ **Plugin Architecture**: Third-party packages can provide hooks
✅ **Decoupled**: Hooks don't need to import Confiture code at module level
✅ **Standards-Based**: Uses Python's entry points (standard mechanism)

### Implementation Checklist for Phase 4.2

```markdown
- [ ] Add importlib.metadata import to hooks.py
- [ ] Implement _load_entry_points() method
- [ ] Add logging for entry point load failures
- [ ] Update documentation with entry point example
- [ ] Add tests for entry point loading
- [ ] Add tests for entry point load failure handling
- [ ] Update PLUGIN_DEVELOPMENT.md guide
```

### Backward Compatibility

✅ Fully backward compatible:
- Current registry.register() still works
- No changes to Hook interface
- No changes to HookContext, HookResult
- Existing code unaffected

---

## Enhancement 2: Structured Logging for Production Observability

**Status**: Phase 4.1 ❌ Not needed | Phase 4.2 ✅ Recommended
**Priority**: Medium
**Effort**: 6-8 hours
**Breaking Changes**: None

### Current State (Phase 4.1)

No logging. Hooks execute silently:

```python
def execute_phase(self, conn, phase, hooks, context):
    results = []
    for hook in hooks:
        result = hook.execute(conn, context)  # Silent execution
        results.append(result)
    return results
```

**Works for**: Development, testing

**Problem**: No visibility into hook execution in production

### Phase 4.2 Enhancement

Add structured logging at key points:

**1. Import logging**:

```python
import logging

logger = logging.getLogger(__name__)
```

**2. Log hook execution phases**:

```python
class HookExecutor:
    def execute_phase(self, conn, phase, hooks, context):
        """Execute all hooks for a given phase."""
        results = []

        logger.info(
            "executing_hooks",
            extra={
                "phase": phase.name,
                "hook_count": len(hooks),
                "migration": context.migration_name,
            }
        )

        for hook in hooks:
            hook_name = hook.__class__.__name__
            start_time = time.time()

            try:
                logger.debug(
                    "hook_start",
                    extra={
                        "hook": hook_name,
                        "phase": phase.name,
                        "migration": context.migration_name,
                    }
                )

                result = hook.execute(conn, context)
                duration_ms = int((time.time() - start_time) * 1000)

                logger.info(
                    "hook_completed",
                    extra={
                        "hook": hook_name,
                        "phase": phase.name,
                        "duration_ms": duration_ms,
                        "rows_affected": result.rows_affected,
                        "migration": context.migration_name,
                    }
                )

                results.append(result)

            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)

                logger.error(
                    "hook_failed",
                    extra={
                        "hook": hook_name,
                        "phase": phase.name,
                        "duration_ms": duration_ms,
                        "error": str(e),
                        "migration": context.migration_name,
                    },
                    exc_info=True
                )

                raise HookError(
                    hook_name=hook_name,
                    phase=phase.name,
                    error=e,
                ) from e

        logger.info(
            "phase_completed",
            extra={
                "phase": phase.name,
                "hooks_executed": len(results),
                "migration": context.migration_name,
            }
        )

        return results
```

**3. Log dry-run execution**:

```python
class DryRunExecutor:
    def run(self, conn, migration):
        """Execute migration in dry-run mode."""
        logger.info(
            "dry_run_start",
            extra={
                "migration": migration.name,
                "version": migration.version,
            }
        )

        try:
            start_time = time.time()
            migration.up()
            execution_time_ms = int((time.time() - start_time) * 1000)

            logger.info(
                "dry_run_completed",
                extra={
                    "migration": migration.name,
                    "version": migration.version,
                    "execution_time_ms": execution_time_ms,
                    "success": True,
                }
            )

            result = DryRunResult(
                migration_name=migration.name,
                migration_version=migration.version,
                success=True,
                execution_time_ms=execution_time_ms,
                # ... other fields
            )

            return result

        except Exception as e:
            logger.error(
                "dry_run_failed",
                extra={
                    "migration": migration.name,
                    "version": migration.version,
                    "error": str(e),
                },
                exc_info=True
            )

            raise DryRunError(migration_name=migration.name, error=e) from e
```

### Log Output Examples

**Hook execution (INFO level)**:

```
time=2025-12-26T10:30:15.123Z level=INFO message=executing_hooks \
  phase=AFTER_DDL hook_count=2 migration=001_add_users_table

time=2025-12-26T10:30:15.234Z level=DEBUG message=hook_start \
  hook=BackfillReadModelHook phase=AFTER_DDL migration=001_add_users_table

time=2025-12-26T10:30:15.456Z level=INFO message=hook_completed \
  hook=BackfillReadModelHook phase=AFTER_DDL duration_ms=222 \
  rows_affected=1500 migration=001_add_users_table

time=2025-12-26T10:30:15.567Z level=INFO message=phase_completed \
  phase=AFTER_DDL hooks_executed=2 migration=001_add_users_table
```

**Dry-run execution (INFO level)**:

```
time=2025-12-26T10:30:20.100Z level=INFO message=dry_run_start \
  migration=001_add_users_table version=001

time=2025-12-26T10:30:22.450Z level=INFO message=dry_run_completed \
  migration=001_add_users_table version=001 execution_time_ms=2350 success=true
```

**Error case (ERROR level)**:

```
time=2025-12-26T10:30:25.789Z level=ERROR message=hook_failed \
  hook=ValidateConstraintsHook phase=AFTER_VALIDATION duration_ms=15 \
  error="Unique constraint violation on users.email" \
  migration=001_add_users_table \
  traceback="Traceback (most recent call last): ..."
```

### Benefits

✅ **Production Visibility**: See what hooks are doing
✅ **Performance Monitoring**: Track execution time per hook
✅ **Error Tracking**: Structured error logs with context
✅ **Audit Trail**: Immutable record of all hook executions
✅ **Integration**: Works with logging aggregators (ELK, Splunk, etc.)

### Configuration Example

Users can configure logging for their setup:

```python
# In application startup
import logging
import logging.config

logging.config.dictConfig({
    'version': 1,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'json',
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': 'confiture_hooks.log',
            'formatter': 'json',
        },
    },
    'formatters': {
        'json': {
            'class': 'pythonjsonlogger.jsonlogger.JsonFormatter',
        },
    },
    'loggers': {
        'confiture.core.hooks': {
            'level': 'INFO',
            'handlers': ['console', 'file'],
        },
        'confiture.core.dry_run': {
            'level': 'INFO',
            'handlers': ['console', 'file'],
        },
    },
})
```

### Implementation Checklist for Phase 4.2

```markdown
- [ ] Add import logging to hooks.py
- [ ] Add import logging to dry_run.py
- [ ] Add logger = logging.getLogger(__name__) to both modules
- [ ] Add structured logging calls to HookExecutor.execute_phase()
- [ ] Add structured logging calls to DryRunExecutor.run()
- [ ] Add logging configuration example to documentation
- [ ] Add tests for logging output
- [ ] Update TROUBLESHOOTING.md with log examples
- [ ] Add log level guidance to OPERATION.md
```

### Backward Compatibility

✅ Fully backward compatible:
- Logging is non-invasive (just prints to logs)
- No changes to Hook interface
- No changes to HookExecutor interface
- No changes to DryRunExecutor interface
- Users can disable logging by configuring log level

---

## Phase 4.2 Implementation Timeline

These enhancements are planned for Phase 4.2 (Weeks 3-4):

```
Week 3:
  Day 1: Entry points support implementation + tests (4 hours)
  Day 2-3: Structured logging implementation + tests (6 hours)
  Day 4: Documentation updates (2 hours)

Week 4:
  Day 1: Integration testing
  Day 2: Performance verification
  Day 3-4: Documentation review, user guides
```

**Total Effort**: ~1-2 days (8-12 hours)

---

## Summary

### What These Enhancements Add

1. **Entry Points Support**
   - Enable third-party hook packages
   - Auto-discovery mechanism
   - Standards-based plugin architecture

2. **Structured Logging**
   - Production observability
   - Performance monitoring
   - Audit trail for compliance
   - Integration with logging infrastructure

### Why They're Not in Phase 4.1

- **Phase 4.1 Scope**: Prove hooks work, establish dry-run capability
- **Entry Points**: Not needed for internal hooks (registry works fine)
- **Logging**: Not critical for Phase 4.1 (hooks work without it)

### Why They're Important for Phase 4.2

- **Entry Points**: Enable plugin ecosystem and third-party extensions
- **Logging**: Enable production monitoring and troubleshooting

### No Blocking Issues

Both enhancements are:
- ✅ Non-breaking (fully backward compatible)
- ✅ Optional (code works without them)
- ✅ Well-scoped (1-2 days implementation)
- ✅ Industry-standard (entry points, structured logging)

---

## References

### Entry Points
- [Python Packaging Guide - Entry Points](https://packaging.python.org/specifications/entry-points/)
- [importlib.metadata Documentation](https://docs.python.org/3/library/importlib.metadata.html)

### Structured Logging
- [Python Logging Documentation](https://docs.python.org/3/library/logging.html)
- [JSON Logging Best Practices](https://www.kartar.net/2015/12/structured-logging/)
- [python-json-logger Library](https://github.com/madzak/python-json-logger)

---

**Prepared**: 2025-12-26
**Phase**: 4.2 Planning
**Status**: Ready for Phase 4.2 Sprint Planning
**Priority**: Medium (nice-to-have, not blocking)

---

*These enhancements will be integrated during Phase 4.2 implementation to provide production-grade extensibility and observability.*
