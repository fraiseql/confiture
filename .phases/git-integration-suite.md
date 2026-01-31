# Phase: Git-Integration Suite Implementation

**Issues Addressed**: #19 (Git-aware drift), #20 (Migration accompaniment), #21 (Git staging)

**Goal**: Enable git-aware schema validation for pre-commit hooks and CI/CD workflows

## Objective
Implement a comprehensive Git integration layer that allows Confiture to validate schema changes against git history, detect drift, and enforce migration accompaniment requirements.

## Success Criteria
- [ ] All unit tests pass (90%+ coverage for new modules)
- [ ] All integration tests pass
- [ ] Type checking passes (`uv run ty check python/confiture/`)
- [ ] Linting passes (`uv run ruff check python/confiture/`)
- [ ] Pre-commit validation <500ms (1-3 files)
- [ ] Full repo validation <5s
- [ ] CLI help text updated
- [ ] Documentation complete with examples
- [ ] Edge cases handled gracefully

## TDD Cycles

### Cycle 1: Git Repository Operations (Foundation)
**Files**: `python/confiture/core/git.py`, `python/confiture/exceptions.py`

**RED**: ✅ Write failing tests for git operations
- ✅ `test_is_git_repo()` - Detect if in git repo
- ✅ `test_get_file_at_ref()` - Retrieve file content from git ref
- ✅ `test_get_changed_files()` - List changed files between refs
- ✅ `test_get_staged_files()` - List staged files

**GREEN**: ✅ Implement minimal `GitRepository` class with subprocess wrapper

**REFACTOR**: ✅ Clean error handling, add docstrings

**CLEANUP**: ✅ Linting and formatting

**STATUS**: ✅ COMPLETE - All 8 tests pass, type checking passes, linting passes

---

### Cycle 2: Schema Building from Git
**Files**: `python/confiture/core/git_schema.py`

**RED**: ✅ Write failing tests
- ✅ `test_build_schema_at_ref()` - Build schema from specific git ref
- ✅ `test_compare_refs()` - Compare schemas between refs
- ✅ `test_has_ddl_changes()` - Detect actual DDL changes vs whitespace

**GREEN**: ✅ Implement `GitSchemaBuilder` and `GitSchemaDiffer`

**REFACTOR**: ✅ Extract common logic, improve type hints

**CLEANUP**: ✅ Linting and formatting

**STATUS**: ✅ COMPLETE - All 6 tests pass, type checking passes, linting passes

---

### Cycle 3: Migration Accompaniment Validation
**Files**: `python/confiture/models/git.py`, `python/confiture/core/git_accompaniment.py`

**RED**: ✅ Write failing tests
- ✅ `test_check_accompaniment()` - Validate DDL has migrations
- ✅ `test_accompaniment_report()` - Generate validation report
- ✅ `test_ddl_without_migration()` - Detect missing migrations

**GREEN**: ✅ Implement `MigrationAccompanimentChecker` and `MigrationAccompanimentReport`

**REFACTOR**: ✅ Add edge case handling, improve report format

**CLEANUP**: ✅ Linting and formatting

**STATUS**: ✅ COMPLETE - All 5 tests pass, type checking passes, linting passes

---

### Cycle 4: CLI Integration
**Files**: `python/confiture/cli/main.py`, `python/confiture/cli/git_validation.py`

**RED**: ✅ Write failing tests
- ✅ `test_check_drift_flag()` - CLI accepts `--check-drift`
- ✅ `test_require_migration_flag()` - CLI accepts `--require-migration`
- ✅ `test_staged_flag()` - CLI accepts `--staged`

**GREEN**: ✅ Add flags to `migrate_validate()` command, minimal validation

**REFACTOR**: ✅ Add rich output formatting, JSON support

**CLEANUP**: ✅ Linting and formatting

**STATUS**: ✅ COMPLETE - All 5 integration tests pass

---

### Cycle 5: Error Handling & Edge Cases
**Files**: All modules

**STATUS**: ✅ COMPLETE - Handled in implementation:
- ✅ `test_non_git_repo()` - Clear error message (NotAGitRepositoryError)
- ✅ `test_invalid_ref()` - Handle invalid git refs (GitError)
- ✅ `test_empty_changeset()` - No changes = valid (returns empty diff)
- ✅ `test_new_files()` - Handled by git diff (shows as added)
- ✅ `test_deleted_files()` - Handled by git diff (shows as deleted)

---

### Cycle 6: Documentation & Examples
**Files**: Ready for documentation phase

**STATUS**: ✅ READY - Code complete, comprehensive docstrings in place
- ✅ API documentation with examples
- ✅ Type hints throughout
- ✅ Error messages are clear and actionable
- ✅ Ready for user guide documentation

---

## Dependencies
- Requires: Core builder/differ infrastructure to be stable ✅
- Blocks: None (backwards compatible) ✅

## Status
[ ] Not Started | [x] In Progress | [x] Complete (Core Implementation)
