# Phase 3: Enhanced Features - Implementation Plan (Revised)

**Status**: Ready for Implementation (Post-Expert Review)
**Target Start**: Q1 2026 (January 2026)
**Estimated Duration**: 27-31 days (4-5 weeks) ← **Updated from 15-20 days**
**Total Test Target**: 155+ new tests ← **Updated from 85 tests**
**Previous Phase**: Phase 2 (Complete, 673 passing tests)
**Next Phase**: Phase 4 (Rust Performance Layer)

---

## 📋 Executive Summary

Phase 3 delivers 5 enhanced features that improve developer experience and provide extensibility. This plan has been **updated based on 5 expert specialist reviews** that identified critical gaps and opportunities.

### **Key Changes from Original Plan:**
- ✅ Feature 1: Reframed as "enhancement" (duplication discovered)
- ✅ Feature 2: Added critical security sandbox requirement
- ✅ Feature 3: Added questionary library dependency
- ✅ Feature 4: Fixed architectural flaw (SAVEPOINT strategy)
- ✅ Feature 5: Expanded to 15 rules with AI-assisted implementation

### **Features Included:**
1. **Migration Hooks Enhancement** (2-3 days) - Add built-in hooks
2. **Custom Anonymization Strategies** (7 days) - Plugin system with security sandbox
3. **Interactive Migration Wizard** (7-8 days) - 5-step CLI with questionary
4. **Migration Dry-Run Mode** (4-5 days) - Safe preview with SAVEPOINT strategy
5. **Schema Linting Enhancements** (6-8 days) - 15 comprehensive rules with AI generation

**Team Structure**: 3 developers + 1 architect
**Risk Level**: Low ← **Reduced from Medium** (expert guidance reduces risks)
**Success Criteria**: All 5 features working, 155+ tests passing, zero security vulnerabilities

---

## 🎯 Overview: All 5 Features

| Feature | Days | Tests | Priority | Status |
|---------|------|-------|----------|--------|
| **#1: Hooks Enhancement** | 2-3 | 10-12 | HIGH | Enhancement (not new) |
| **#2: Custom Strategies** | 7 | 36 | HIGH | Needs security sandbox |
| **#3: Interactive Wizard** | 7-8 | 30+ | MEDIUM | Needs questionary lib |
| **#4: Dry-Run Mode** | 4-5 | 30 | MEDIUM | Needs SAVEPOINT fix |
| **#5: Schema Linting** | 6-8 | 51 | LOW | 15 rules (AI-assisted) |
| **TOTAL** | **27-31** | **155+** | — | **Ready** |

---

## 🏗️ Feature 1: Migration Hooks Enhancement

**Revised Status**: Enhancement of existing Phase 2.1 system (NOT new feature)
**Timeline**: 2-3 days (was 4-5 days)
**Tests**: 10-12 (was 25)
**Risk Level**: LOW

### 1.1 Context: What Already Exists

The Phase 2.1 implementation already has:
- ✅ HookExecutor (executes hooks at lifecycle points)
- ✅ HookRegistry (manages registered hooks)
- ✅ HookContext (passes data to hooks)
- ✅ 8 hook phases: BEFORE_VALIDATION, BEFORE_DDL, AFTER_DDL, AFTER_VALIDATION, CLEANUP, ON_ERROR, BEFORE_ANONYMIZATION, AFTER_ANONYMIZATION

**File**: `/python/confiture/core/hooks.py`

### 1.2 Enhancement Scope

**What to Add**:
- ✅ 3 built-in hooks (DatabaseBackup, SlackNotification, AuditLog)
- ✅ Enhanced HookContext with migration metadata
- ✅ Hook testing utilities and fixtures
- ✅ Documentation with 3 real-world examples

**What NOT to Do**:
- ❌ Don't rewrite HookExecutor (already works)
- ❌ Don't create new hook phases (8 is sufficient)
- ❌ Don't redesign HookRegistry (already functional)

### 1.3 Implementation Steps

#### **Day 1: Built-in Hooks**

**Task 1.1.1**: DatabaseBackup Hook
```python
# confiture/core/hooks/builtin/backup_hook.py
class DatabaseBackupHook:
    """Backup database before migration."""

    async def execute(self, context: HookContext) -> HookResult:
        """Create backup file with timestamp."""
        # 1. Connect to source database
        # 2. Run pg_dump with compression
        # 3. Verify backup integrity
        # 4. Store backup path in context
        # 5. Return success/failure
```

**Task 1.1.2**: SlackNotification Hook
```python
# confiture/core/hooks/builtin/notification_hook.py
class SlackNotificationHook:
    """Send Slack notifications at migration milestones."""

    async def execute(self, context: HookContext) -> HookResult:
        """Send message to Slack channel."""
        # 1. Format message with migration details
        # 2. Send to Slack webhook
        # 3. Handle Slack errors gracefully
        # 4. Return success/failure
```

**Task 1.1.3**: AuditLog Hook
```python
# confiture/core/hooks/builtin/logging_hook.py
class AuditLogHook:
    """Log all migration activities for compliance."""

    async def execute(self, context: HookContext) -> HookResult:
        """Write audit log entry."""
        # 1. Format audit entry with user, time, action
        # 2. Write to database audit table
        # 3. Sign entry for tamper-proof trail
        # 4. Handle log rotation
```

**Tests for Day 1** (5 tests):
- test_database_backup_hook_creates_file()
- test_slack_notification_hook_sends_message()
- test_audit_log_hook_writes_entry()
- test_hook_fails_gracefully_on_error()
- test_multiple_hooks_execute_in_order()

#### **Day 2: Enhanced Context & Testing Utilities**

**Task 1.2.1**: Extend HookContext
```python
# Enhance HookContext with:
- migration_config: dict[str, Any]  # Full config
- environment: str                   # e.g., 'production'
- started_at: datetime
- estimated_duration: float
- rollback_plan: str | None
```

**Task 1.2.2**: Hook Testing Utilities
```python
# confiture/core/hooks/testing.py
class HookTestHelper:
    """Utilities for testing custom hooks."""

    def create_test_context(self) -> HookContext:
        """Create mock HookContext for testing."""

    async def assert_hook_called(self, hook_name: str):
        """Verify hook was called."""

    def assert_hook_result(self, result: HookResult, expected_status: str):
        """Verify hook result."""
```

**Tests for Day 2** (5-7 tests):
- test_hook_context_contains_all_fields()
- test_hook_testing_helper_creates_valid_context()
- test_test_helper_tracks_hook_calls()
- test_test_helper_verifies_results()
- test_hook_with_real_database_connection()

#### **Day 3: Documentation & Integration**

**Task 1.3.1**: Documentation
- User guide: `docs/guides/migration-hooks-enhancement.md`
- Example 1: Backup before migration
- Example 2: Slack notifications on success/failure
- Example 3: Audit logging for compliance

**Task 1.3.2**: Integration Tests
- Test with actual migration workflows
- Test hook error handling
- Test hook ordering and dependencies

### 1.4 Acceptance Criteria

- ✅ 3 built-in hooks implemented and tested
- ✅ HookContext extended with metadata
- ✅ Hook testing utilities provided
- ✅ Documentation with 3 working examples
- ✅ 10-12 tests passing (100%)
- ✅ No performance degradation

---

## 🏗️ Feature 2: Custom Anonymization Strategies

**Timeline**: 7 days (was 3-4 days)
**Tests**: 36 (was 20)
**Risk Level**: HIGH (security-critical)

### 2.1 Context: What Already Exists

Phase 2.2 already has:
- ✅ AnonymizationStrategy base class
- ✅ 5 built-in strategies (Masking, Tokenization, FPE, Hashing, Differential Privacy)
- ✅ StrategyRegistry for discovery
- ✅ Strategy factory pattern

**What's Missing** (Critical):
- ❌ NO SANDBOXING for user code execution
- ❌ NO IMPORT RESTRICTIONS (users can import os, subprocess, etc.)
- ❌ NO TIMEOUT ENFORCEMENT (code could hang indefinitely)
- ❌ NO AUDIT LOGGING (can't track custom strategy execution)

### 2.2 Enhancement Scope

**CRITICAL: Add Security Sandbox**

```
BEFORE (Unsafe):
├─ User writes custom strategy
├─ User imports whatever they want (os, subprocess, requests)
├─ Code runs with full Python permissions
└─ ❌ Can delete files, exfiltrate data, DoS

AFTER (Safe):
├─ User writes custom strategy
├─ Sandbox restricts imports (block os, subprocess, socket, etc.)
├─ Code runs with 5-second timeout
├─ All executions logged for audit
└─ ✅ Cannot harm system
```

### 2.3 Implementation Steps

#### **Days 1-2: Security Sandbox Foundation**

**Task 2.1.1**: StrategySandbox Implementation
```python
# confiture/core/anonymization/plugins/sandbox.py
class StrategySandbox:
    """Execute custom strategies in sandboxed environment."""

    # Blocked imports (dangerous)
    BLOCKED_MODULES = {
        'os', 'sys', 'subprocess', 'socket', 'socket_client',
        'requests', 'urllib', 'http', 'smtplib',
        'boto3', 'google.cloud', 'azure', 'paramiko', 'fabric',
        '__import__', 'eval', 'exec', 'compile', 'code',
    }

    def __init__(self, timeout: float = 5.0):
        self.timeout = timeout  # 5 second max per value

    async def execute(
        self,
        strategy: StrategyBase,
        value: str,
        context: dict[str, Any] | None = None
    ) -> str:
        """Execute strategy with security constraints."""
        # 1. Check imports used by strategy code
        # 2. Verify no blacklisted modules
        # 3. Execute with timeout
        # 4. Log execution attempt
        # 5. Return result or error
```

**Task 2.1.2**: Import Restriction Checker
```python
# confiture/core/anonymization/plugins/import_checker.py
class ImportChecker:
    """Verify custom strategy code only uses safe imports."""

    def check_strategy_code(self, code: str | types.FunctionType) -> CheckResult:
        """Analyze code for dangerous imports."""
        # Use ast.parse() to find all imports
        # Check against BLOCKED_MODULES
        # Report violations with line numbers
```

**Task 2.1.3**: Execution Timeout Enforcement
```python
# Use signal.alarm() or asyncio.wait_for() for timeout
async def execute_with_timeout(
    coroutine,
    timeout: float = 5.0
) -> Any:
    """Execute coroutine with timeout."""
    try:
        return await asyncio.wait_for(coroutine, timeout=timeout)
    except asyncio.TimeoutError:
        raise StrategyExecutionError(f"Strategy exceeded {timeout}s timeout")
```

**Tests for Days 1-2** (12 tests):
- test_sandbox_blocks_os_import()
- test_sandbox_blocks_subprocess_import()
- test_sandbox_blocks_socket_import()
- test_sandbox_blocks_requests_import()
- test_sandbox_allows_safe_imports(json, re, hashlib)
- test_import_checker_detects_forbidden_imports()
- test_timeout_enforced_on_infinite_loop()
- test_timeout_enforced_on_slow_operation()
- test_audit_log_records_execution()
- test_audit_log_records_blocked_imports()
- test_sandbox_execution_returns_correct_value()
- test_sandbox_execution_on_error_logs_failure()

#### **Day 3: Plugin System Integration**

**Task 2.2.1**: Entry Points for Plugin Discovery
```python
# confiture/core/anonymization/plugins/loader.py
class PluginLoader:
    """Load custom strategies from entry points."""

    def load_from_entry_points(self) -> list[StrategyBase]:
        """Discover strategies from setuptools entry points."""
        # Entry point: confiture.strategies
        # Example: user-package setup.py
        # [options.entry_points]
        # confiture.strategies =
        #     my_strategy = my_package.strategies:MyStrategy
```

**Task 2.2.2**: Strategy Configuration with Pydantic
```python
# confiture/core/anonymization/plugins/config.py
from pydantic import BaseModel, ValidationError

class StrategyConfig(BaseModel):
    """Validated configuration for custom strategy."""

    name: str
    module_path: str
    config: dict[str, Any]
    enabled: bool = True
    timeout_seconds: float = 5.0

    class Config:
        extra = "allow"  # Allow custom fields
```

**Task 2.2.3**: Registry Integration
```python
class StrategyRegistry:
    """Enhanced registry with sandbox integration."""

    async def execute_strategy(
        self,
        strategy_name: str,
        value: str
    ) -> str:
        """Execute strategy (built-in or custom) with proper sandboxing."""
        strategy = self.get_strategy(strategy_name)

        if strategy.is_custom():
            # Execute custom strategy in sandbox
            return await self.sandbox.execute(strategy, value)
        else:
            # Built-in strategies already safe
            return strategy.anonymize(value)
```

**Tests for Day 3** (8 tests):
- test_plugin_loader_discovers_entry_points()
- test_plugin_loader_loads_custom_strategy()
- test_strategy_config_validation()
- test_strategy_config_rejects_invalid_format()
- test_registry_executes_builtin_without_sandbox()
- test_registry_executes_custom_with_sandbox()
- test_registry_sandboxes_only_custom_strategies()
- test_registry_timeout_applied_to_custom_only()

#### **Days 4-5: Testing & Documentation**

**Task 2.3.1**: Comprehensive Security Testing
- 8 security-specific tests (above)
- Adversarial test cases (attempts to bypass sandbox)
- Performance benchmarks (overhead of sandboxing)

**Task 2.3.2**: User Documentation
- Plugin development guide
- YAML configuration reference
- 3 example custom strategies:
  - Industry-specific anonymization (healthcare, finance)
  - Custom PII detection
  - Domain-specific transformations

**Task 2.3.3**: Example Custom Strategies
```python
# examples/custom_strategies/healthcare_anonymization.py
class HealthcareAnonymizer(StrategyBase):
    """Anonymize medical record identifiers."""

    def anonymize(self, value: str) -> str:
        # Only use safe imports and operations
        import re
        return re.sub(r'\d', 'X', value)
```

**Tests for Days 4-5** (16 tests):
- 8 integration tests (with real strategies)
- 4 false-positive tests (sandboxing doesn't block safe code)
- 2 performance tests (sandbox overhead < 5%)
- 2 documentation tests (examples work as shown)

### 2.4 Acceptance Criteria

- ✅ StrategySandbox implemented with import restrictions
- ✅ Timeout enforcement (5 seconds per value)
- ✅ Audit logging for all custom strategy executions
- ✅ Entry points mechanism for plugin discovery
- ✅ Pydantic configuration validation
- ✅ 36 tests passing (including 12 security-specific tests)
- ✅ **Zero security vulnerabilities** in sandbox
- ✅ User documentation with working examples
- ✅ No performance degradation (<5% overhead)

---

## 🏗️ Feature 3: Interactive Migration Wizard

**Timeline**: 7-8 days (was 5-6 days)
**Tests**: 30+ (was 15)
**Risk Level**: MEDIUM
**New Dependency**: `questionary>=2.0.0`

### 3.1 Context: Critical Library Limitation

**Problem**: Rich library doesn't support multi-select or autocomplete.
```python
# ❌ Rich can't do this:
from rich.console import Console
console = Console()
# No way to select multiple items with arrow keys

# ✅ Questionary can do this:
import questionary
tables = questionary.checkbox(
    "Select tables:",
    choices=['users', 'orders', 'products']
).ask()
```

### 3.2 Revised Workflow (5 Steps instead of 7)

**Original 7 Steps** → **Revised 5 Steps**:
1. **Select source** ← Merged from (source DB + target env)
2. **Select tables** ← Same
3. **Configure migration** ← Merged from (rules + anonymization)
4. **Review & confirm** ← Same
5. **Execute & verify** ← Merged from (execute + verify)

### 3.3 Implementation Steps

#### **Days 1-2: Questionary Integration & State Management**

**Task 3.1.1**: Add questionary dependency
```toml
# pyproject.toml
[project.dependencies]
questionary = ">=2.0.0"
```

**Task 3.1.2**: WizardSession State Machine
```python
# confiture/cli/wizard/session.py
@dataclass
class WizardSession:
    """Persistent state for migration wizard."""

    session_id: str
    created_at: datetime
    last_saved_at: datetime
    state: dict[str, Any]  # Stores all step selections

    async def save(self) -> None:
        """Auto-save to ~/.confiture/wizard_sessions/."""
        # Serialize to JSON
        # Write to disk

    async def load(self, session_id: str) -> None:
        """Restore previous session."""
        # Read from disk
        # Deserialize state
```

**Task 3.1.3**: Wizard State Persistence
```python
class WizardStatePersistence:
    """Handle auto-saving wizard state."""

    def __init__(self):
        self.session_dir = Path.home() / ".confiture" / "wizard_sessions"
        self.session_dir.mkdir(parents=True, exist_ok=True)

    async def save_checkpoint(self, session: WizardSession) -> None:
        """Save state after each step."""
        # 1. Serialize step data
        # 2. Write to JSON file
        # 3. Keep last 5 sessions
```

**Tests for Days 1-2** (8 tests):
- test_questionary_checkbox_returns_list()
- test_questionary_confirm_returns_bool()
- test_wizard_session_creates_new_state()
- test_wizard_session_saves_to_disk()
- test_wizard_session_restores_from_disk()
- test_wizard_session_checkpoint_after_each_step()
- test_wizard_session_cleanup_old_sessions()
- test_wizard_session_encryption_of_sensitive_data()

#### **Days 3-4: Wizard Steps Implementation**

**Task 3.2.1**: Step 1 - Select Source (Database & Connection)
```python
# confiture/cli/wizard/steps.py
class WizardStep1SelectSource:
    """Select source database and connection details."""

    async def run(self) -> dict:
        """Present options and collect selection."""
        # 1. List available databases from config
        # 2. Use questionary.select() for single choice
        # 3. If custom, prompt for connection string
        # 4. Validate connection
        # 5. Save to session state

        db_choice = questionary.select(
            "Select source database:",
            choices=[
                "Local development",
                "Staging",
                "Custom connection..."
            ]
        ).ask()
```

**Task 3.2.2**: Step 2 - Select Tables (Multi-select with questionary)
```python
class WizardStep2SelectTables:
    """Select which tables to migrate."""

    async def run(self) -> dict:
        """Let user select multiple tables."""

        # Get available tables from schema
        tables = await self.get_tables_from_schema()

        # Use questionary for multi-select
        selected = questionary.checkbox(
            "Select tables to migrate:",
            choices=tables,
            validate=lambda x: len(x) > 0 or "Select at least one table"
        ).ask()

        return {"selected_tables": selected}
```

**Task 3.2.3**: Step 3 - Configure Migration (Rules + Anonymization)
```python
class WizardStep3ConfigureMigration:
    """Configure migration options and anonymization."""

    async def run(self) -> dict:
        """Collect configuration."""

        config = {}

        # Option 1: Full migration or incremental
        config["type"] = questionary.select(
            "Migration type:",
            choices=["Full (schema + data)", "Schema only"]
        ).ask()

        # Option 2: Apply anonymization?
        apply_anon = questionary.confirm(
            "Apply anonymization rules?",
            default=True
        ).ask()

        if apply_anon:
            # Option 3: Choose anonymization rules
            config["rules"] = questionary.checkbox(
                "Select anonymization rules:",
                choices=await self.get_available_rules()
            ).ask()

        return config
```

**Task 3.2.4**: Step 4 - Review & Confirm
```python
class WizardStep4ReviewPlan:
    """Show migration plan and get confirmation."""

    async def run(self) -> dict:
        """Display plan and collect confirmation."""

        # Generate migration plan summary
        plan_text = await self.generate_plan_summary()

        # Display plan with Rich formatting
        console.print(plan_text)

        # Get confirmation
        confirmed = questionary.confirm(
            "Proceed with migration?",
            default=False  # Require explicit confirmation
        ).ask()

        # Optional: Run dry-run first
        if confirmed:
            dry_run = questionary.confirm(
                "Run dry-run first?",
                default=True
            ).ask()
            return {"confirmed": confirmed, "run_dry_run": dry_run}
```

**Task 3.2.5**: Step 5 - Execute & Verify
```python
class WizardStep5ExecuteAndVerify:
    """Execute migration and verify results."""

    async def run(self) -> dict:
        """Execute migration with progress display."""

        # Display progress bar
        with Progress() as progress:
            task = progress.add_task("[green]Migrating...", total=100)

            # Execute migration
            result = await self.execute_migration(progress, task)

        # Display results
        console.print(result.to_table())

        # Verify success
        verified = await self.verify_migration()

        return {
            "success": result.success,
            "verified": verified,
            "duration": result.duration,
            "rows_migrated": result.rows_migrated
        }
```

**Tests for Days 3-4** (12 tests):
- test_step1_lists_available_databases()
- test_step1_validates_connection()
- test_step2_returns_multiple_tables()
- test_step2_requires_at_least_one_table()
- test_step3_collects_configuration()
- test_step3_conditionally_asks_for_rules()
- test_step4_displays_plan_summary()
- test_step4_requires_explicit_confirmation()
- test_step5_executes_migration()
- test_step5_displays_progress()
- test_step5_verifies_results()
- test_wizard_saves_checkpoint_after_each_step()

#### **Days 5-6: Error Recovery & Integration**

**Task 3.3.1**: Error Recovery
```python
class WizardErrorRecovery:
    """Handle errors during wizard execution."""

    async def handle_connection_error(self, error):
        """User can fix connection and retry."""
        console.print(f"[red]Connection failed: {error}")
        retry = questionary.confirm("Retry?").ask()
        if retry:
            return await step1.run()  # Re-run step 1
```

**Task 3.3.2**: CLI Command Integration
```python
# confiture/cli/commands/wizard.py
@app.command()
def wizard():
    """Run interactive migration wizard."""
    wizard = InteractiveMigrationWizard()
    result = asyncio.run(wizard.run())

    if result.success:
        console.print("[green]✅ Migration complete!")
    else:
        console.print("[red]❌ Migration failed!")
```

**Tests for Days 5-6** (8+ tests):
- test_wizard_handles_connection_error()
- test_wizard_allows_retry_on_error()
- test_wizard_saves_state_on_error()
- test_wizard_recovers_from_saved_state()
- test_cli_wizard_command_works()
- test_wizard_full_workflow_end_to_end()
- test_wizard_cancels_gracefully()
- test_wizard_output_formatting_with_rich()

#### **Days 7-8: Documentation & Testing**

**Documentation**:
- Interactive wizard user guide
- Screenshot walkthrough
- Error recovery guide
- Configuration reference

**Tests for Days 7-8** (4+ tests):
- test_wizard_with_real_database()
- test_wizard_with_large_schema()
- test_wizard_performance_acceptable()
- test_wizard_accessibility_and_formatting()

### 3.4 Acceptance Criteria

- ✅ **Questionary dependency added**
- ✅ 5-step workflow implemented (not 7)
- ✅ Multi-select for table selection works
- ✅ WizardSession state persists across runs
- ✅ Auto-save checkpoint after each step
- ✅ Error recovery and retry mechanism
- ✅ `confiture wizard` command works
- ✅ 30+ tests passing
- ✅ Progress display during execution
- ✅ User documentation with screenshots

---

## 🏗️ Feature 4: Migration Dry-Run Mode

**Timeline**: 4-5 days (was 2-3 days)
**Tests**: 30 (was 10)
**Risk Level**: HIGH (critical transaction safety)
**Critical Fix**: Use SAVEPOINT strategy (NOT READ ONLY)

### 4.1 Critical Architectural Fix

**BLOCKER FIX**: PostgreSQL `READ ONLY` transactions don't prevent DDL changes.

```sql
-- ❌ WRONG: This will execute and commit!
BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE READ ONLY;
ALTER TABLE users ADD COLUMN bio TEXT;  -- Executes!
COMMIT;  -- Changes committed!

-- ✅ CORRECT: Use SAVEPOINT + ROLLBACK
BEGIN TRANSACTION;
SAVEPOINT dry_run_checkpoint;
ALTER TABLE users ADD COLUMN bio TEXT;  -- Executes in transaction
-- Analyze impact while visible
ROLLBACK TO SAVEPOINT dry_run_checkpoint;  -- Always rollback
```

### 4.2 New Components Required

**Components to implement**:
1. StatementClassifier (detect unsafe statements)
2. DryRunTransaction (SAVEPOINT strategy)
3. ImpactAnalyzer (size, constraint violations)
4. DependencyAnalyzer (check prerequisites)
5. ConcurrencyAnalyzer (predict locks)
6. CostEstimator (time, disk, CPU)
7. ReportGenerator (streaming output)

### 4.3 Implementation Steps

#### **Days 1-2: Transaction Safety**

**Task 4.1.1**: DryRunTransaction (SAVEPOINT Strategy)
```python
# confiture/core/migration/dry_run/transaction.py
class DryRunTransaction:
    """Execute migration in rolled-back transaction."""

    async def execute(self, migration: Migration) -> DryRunResult:
        """Execute migration and rollback changes."""

        async with self.conn.transaction():
            # Create savepoint
            await self.conn.execute("SAVEPOINT dry_run_checkpoint")

            results = []
            try:
                for statement in migration.statements:
                    # Execute statement (changes visible in transaction)
                    await self.conn.execute(statement)

                    # Collect impact data while changes are visible
                    impact = await self.analyzer.analyze(statement)
                    results.append(impact)

                # Generate report before rollback
                report = await self.reporter.generate(results)

            finally:
                # ALWAYS rollback - changes never commit
                await self.conn.execute("ROLLBACK TO SAVEPOINT dry_run_checkpoint")

        return DryRunResult(success=True, report=report)
```

**Task 4.1.2**: StatementClassifier (Detect Unsafe Statements)
```python
# confiture/core/migration/dry_run/classifier.py
class StatementClassifier:
    """Classify SQL statements by dry-run safety."""

    UNSAFE_PATTERNS = [
        r'pg_advisory_lock',  # Advisory locks
        r'NOTIFY',            # Sends notifications immediately
        r'LISTEN',            # Starts listening
        r'CREATE EXTENSION',  # Global state change
        r'COPY.*FROM STDIN',  # Can't replay data
        r'pg_sleep',          # Wastes time in transaction
    ]

    def classify(self, statement: str) -> StatementType:
        """Determine if statement is safe for dry-run."""
        for pattern in self.UNSAFE_PATTERNS:
            if re.search(pattern, statement, re.IGNORECASE):
                return StatementType.UNSAFE

        return StatementType.SAFE
```

**Tests for Days 1-2** (10 tests):
- test_dry_run_transaction_executes_statements()
- test_dry_run_transaction_always_rolls_back()
- test_dry_run_transaction_not_affected_by_errors()
- test_savepoint_rollback_verified()
- test_statement_classifier_detects_unsafe_lock()
- test_statement_classifier_detects_unsafe_notify()
- test_statement_classifier_allows_safe_ddl()
- test_statement_classifier_allows_safe_dml()
- test_dry_run_skips_unsafe_statements()
- test_dry_run_warns_about_unsafe_statements()

#### **Days 2-3: Impact Analysis**

**Task 4.2.1**: ImpactAnalyzer (Size, Constraints, Performance)
```python
# confiture/core/migration/dry_run/impact.py
class ImpactAnalyzer:
    """Analyze impact of migration statements."""

    async def analyze_add_column(self, table: str, column: str, column_type: str):
        """Analyze impact of ADD COLUMN."""

        # Get table size and row count
        table_size = await self.get_table_size(table)
        row_count = await self.get_approximate_row_count(table)

        # Estimate column size per row
        column_size_per_row = self._estimate_column_size(column_type)
        total_size_increase = column_size_per_row * row_count

        # Check for DEFAULT value (may trigger rewrite)
        has_default = ...
        will_rewrite = has_default and pg_version < 11

        return ImpactReport(
            operation="ADD COLUMN",
            size_increase=total_size_increase,
            will_rewrite_table=will_rewrite,
            estimated_duration=...,
        )

    async def check_constraint_violations(self, constraint_type: str, table: str, column: str):
        """Check if constraint would fail."""

        if constraint_type == "NOT NULL":
            null_count = await self.conn.fetchval(
                f"SELECT COUNT(*) FROM {table} WHERE {column} IS NULL"
            )
            if null_count > 0:
                return ConstraintViolation(
                    type="NOT NULL",
                    affected_rows=null_count,
                    will_fail=True
                )

        return ConstraintViolation(will_fail=False)
```

**Task 4.2.2**: DependencyAnalyzer (Check Prerequisites)
```python
# confiture/core/migration/dry_run/dependency.py
class DependencyAnalyzer:
    """Analyze migration dependencies."""

    async def check_dependencies(self, migration: Migration):
        """Check if migration has unmet dependencies."""

        issues = []

        for statement in migration.statements:
            if self.is_table_reference(statement):
                table = self.extract_table_name(statement)
                if not await self.table_exists(table):
                    issues.append(f"Table {table} does not exist")

            if self.is_foreign_key(statement):
                ref_table = self.extract_reference(statement)
                if not await self.table_exists(ref_table):
                    issues.append(f"Referenced table {ref_table} does not exist")

        return DependencyReport(issues=issues)
```

**Task 4.2.3**: ConcurrencyAnalyzer (Predict Locks)
```python
# confiture/core/migration/dry_run/concurrency.py
class ConcurrencyAnalyzer:
    """Analyze migration concurrency impact."""

    async def analyze_locks(self, statement: str) -> LockAnalysis:
        """Predict lock types and duration."""

        if self.is_add_column(statement):
            return LockAnalysis(
                lock_type="AccessExclusiveLock",
                blocks_reads=True,
                blocks_writes=True,
                estimated_duration=self.estimate_duration(statement),
                recommendation="Use CONCURRENTLY option if available",
            )
```

**Tests for Days 2-3** (12 tests):
- test_analyze_add_column_estimates_size()
- test_analyze_add_column_with_default()
- test_check_not_null_constraint_violations()
- test_check_foreign_key_violations()
- test_check_dependency_missing_table()
- test_check_dependency_missing_reference()
- test_analyze_locks_add_column()
- test_analyze_locks_create_index()
- test_estimate_duration_accuracy()
- test_estimate_row_count_from_statistics()
- test_estimate_disk_space_needed()
- test_estimate_cost_with_multiple_operations()

#### **Days 3-4: Cost Estimation & Reporting**

**Task 4.3.1**: CostEstimator (Time, Disk, CPU)
```python
# confiture/core/migration/dry_run/cost.py
class CostEstimator:
    """Estimate migration costs."""

    async def estimate_migration_cost(self, migration: Migration) -> CostEstimate:
        """Estimate total migration cost."""

        total_time = 0
        total_disk = 0

        for statement in migration.statements:
            if self.is_table_rewrite(statement):
                table = self.extract_table(statement)
                table_size = await self.get_table_size(table)

                # Rule of thumb: 1GB per 30 seconds on SSD
                rewrite_time = table_size / (1_000_000_000 / 30)
                disk_needed = table_size * 2  # Needs temp space

                total_time += rewrite_time
                total_disk += disk_needed

        return CostEstimate(
            estimated_duration_seconds=total_time,
            disk_space_required_bytes=total_disk,
        )
```

**Task 4.3.2**: ReportGenerator (Streaming Output)
```python
# confiture/core/migration/dry_run/reporter.py
class ReportGenerator:
    """Generate dry-run impact report."""

    async def generate_report(self, migration: Migration, output_path: Path):
        """Stream report to file (avoid memory issues)."""

        async with aiofiles.open(output_path, 'w') as f:
            await f.write("# Dry-Run Impact Analysis\n\n")

            for statement in migration.statements:
                impact = await self.analyze(statement)
                # Write immediately, don't accumulate
                await f.write(impact.to_markdown())
                del impact  # Free memory
```

**Tests for Days 3-4** (8 tests):
- test_estimate_add_column_with_default()
- test_estimate_add_column_without_default()
- test_estimate_table_rewrite_cost()
- test_estimate_index_creation_cost()
- test_cost_estimate_includes_disk_space()
- test_report_generation_completes()
- test_report_includes_all_impacts()
- test_report_memory_efficient_for_large_migrations()

#### **Days 4-5: Integration & Testing**

**Task 4.4.1**: DryRunOrchestrator (Coordinate All Components)
```python
# confiture/core/migration/dry_run/orchestrator.py
class DryRunOrchestrator:
    """Coordinate dry-run execution."""

    async def execute_dry_run(self, migration: Migration) -> DryRunResult:
        """Execute full dry-run workflow."""

        # 1. Classify statements
        classified = await self.classifier.classify_all(migration.statements)

        # 2. Check dependencies
        deps = await self.dependency_analyzer.check(classified.safe_statements)

        # 3. Execute in transaction
        result = await self.transaction.execute(classified.safe_statements)

        # 4. Analyze impact
        impact = await self.impact_analyzer.analyze_all(result.statements)

        # 5. Estimate costs
        costs = await self.cost_estimator.estimate(impact)

        # 6. Generate report
        report = await self.reporter.generate(impact, costs)

        return DryRunResult(
            success=True,
            report=report,
            unsafe_statements=classified.unsafe_statements,
        )
```

**Task 4.4.2**: CLI Integration
```python
# confiture/cli/commands/migrate.py
@app.command()
def migrate_dry_run(
    migration: str,
    env: str = "test"
):
    """Run migration in dry-run mode."""
    orchestrator = DryRunOrchestrator(env=env)
    result = asyncio.run(orchestrator.execute_dry_run(migration))

    console.print(result.report)
```

**Tests for Days 4-5** (10+ tests):
- test_dry_run_with_add_column()
- test_dry_run_detects_constraint_violation()
- test_dry_run_with_large_table()
- test_dry_run_with_foreign_keys()
- test_dry_run_multi_statement_migration()
- test_dry_run_rollback_verified()
- test_cli_dry_run_command()
- test_dry_run_then_actual_migration()
- test_dry_run_performance_acceptable()
- test_dry_run_memory_usage_acceptable()

### 4.4 Acceptance Criteria

- ✅ **SAVEPOINT strategy prevents all changes** (not READ ONLY)
- ✅ StatementClassifier detects unsafe statements
- ✅ ImpactAnalyzer provides size/constraint analysis
- ✅ DependencyAnalyzer checks prerequisites
- ✅ ConcurrencyAnalyzer predicts locks
- ✅ CostEstimator provides time/disk/CPU estimates
- ✅ ReportGenerator produces reports
- ✅ 30 tests passing
- ✅ Transaction safety verified
- ✅ `confiture migrate dry-run` command works

---

## 🏗️ Feature 5: Schema Linting Enhancements

**Timeline**: 6-8 days (was 3-4 days)
**Tests**: 51 (was 15)
**Rules**: 15 (was 10, now AI-assisted)
**Risk Level**: LOW

### 5.1 Rule Architecture (15 Rules with AI-Assisted Generation)

**Approach**: Design 3-4 exemplar rules with full implementation + tests, then use AI to generate remaining 11-12 rules from pattern.

### 5.2 Core Rules (15 Total)

#### **Category 1: Structural (4 rules)**
1. ✅ **Missing primary key** (ERROR)
2. ✅ **Missing FK index** (ERROR) ← Top priority!
3. ✅ **Redundant indexes** (WARNING)
4. ✅ **Unused indexes** (INFO)

#### **Category 2: Naming (4 rules)**
5. ✅ **Table naming consistency** (WARNING)
6. ✅ **Column naming consistency** (WARNING)
7. ✅ **Index naming standards** (INFO)
8. ✅ **Constraint naming standards** (INFO)

#### **Category 3: Constraints (4 rules)**
9. ✅ **Missing foreign keys** (WARNING, configurable)
10. ✅ **Missing NOT NULL on critical columns** (WARNING)
11. ✅ **Orphaned tables** (INFO, with whitelist)
12. ✅ **Missing audit triggers** (INFO)

#### **Category 4: Security (2 rules)**
13. ✅ **PII detection** (INFO, with whitelist)
14. ✅ **Hardcoded secrets** (ERROR)

#### **Category 5: Design Patterns (1 rule)**
15. ✅ **Improper table inheritance** (WARNING)

### 5.3 Implementation Strategy with AI

**Phase 1: Architecture & Exemplars** (Days 1-2)

**Task 5.1.1**: Rule Engine Architecture
```python
# confiture/core/linting/engine.py
class LintEngine:
    """Execute linting rules against schema."""

    def __init__(self, config: LintConfig):
        self.rules: list[LintRule] = self._load_rules()
        self.config = config

    async def lint(self, schema: SchemaMetadata) -> LintResult:
        """Run all enabled rules."""
        violations = []
        for rule in self.rules:
            if self.config.is_enabled(rule.rule_id):
                violations.extend(await rule.check(schema))
        return LintResult(violations=violations)

class LintRule(Protocol):
    """Base for all lint rules."""
    rule_id: str
    severity: Severity
    async def check(self, schema: SchemaMetadata) -> list[LintViolation]:
        ...
```

**Task 5.1.2**: Configuration System (YAML-based)
```python
# confiture/core/linting/config.py
# Usage:
# confiture.lint.yml
# rules:
#   missing_fk_index:
#     enabled: true
#     severity: error
#   orphaned_table:
#     enabled: true
#     severity: info
#     exclude_tables:
#       - "*_log"
#       - config
```

**Task 5.1.3**: Output Formatters (3 formats)
```python
# confiture/core/linting/reporters/
├── table_reporter.py         # Human-readable table
├── json_reporter.py          # CI-friendly JSON
└── github_actions_reporter.py # GitHub annotations
```

**Tests for Days 1-2** (5 tests):
- test_lint_engine_executes_all_rules()
- test_lint_engine_respects_enabled_config()
- test_config_loads_from_yaml()
- test_table_reporter_formats_violations()
- test_json_reporter_produces_valid_json()

#### **Phase 2: Exemplar Rules** (Days 2-3)

**Design 3-4 exemplars that AI will use as patterns**:

**Exemplar 1: Missing Primary Key** (Simple query-based rule)
```python
# confiture/core/linting/rules/missing_pk.py
@dataclass
class MissingPrimaryKeyRule(LintRule):
    """Detect tables without primary key."""

    rule_id = "missing_primary_key"
    severity = Severity.ERROR
    enabled_by_default = True

    async def check(self, schema: SchemaMetadata) -> list[LintViolation]:
        violations = []
        for table in schema.tables:
            if not table.primary_key:
                violations.append(LintViolation(
                    rule_id=self.rule_id,
                    severity=self.severity,
                    message=f"Table '{table.name}' has no primary key",
                    location=f"table {table.name}",
                    fix_suggestion=f"ALTER TABLE {table.name} ADD PRIMARY KEY (id);"
                ))
        return violations

# Comprehensive tests (unit + integration + false positive)
@pytest.mark.asyncio
async def test_missing_pk_detects_violation():
    """Should flag table without PK."""
    ...

@pytest.mark.asyncio
async def test_missing_pk_ignores_table_with_pk():
    """Should not flag table with PK."""
    ...

@pytest.mark.asyncio
async def test_missing_pk_with_uuid_pk():
    """Should handle UUID primary keys."""
    ...

@pytest.mark.asyncio
async def test_missing_pk_with_composite_pk():
    """Should handle composite primary keys."""
    ...
```

**Exemplar 2: Missing FK Index** (Complex query + configuration)
```python
# confiture/core/linting/rules/missing_fk_index.py
@dataclass
class MissingFKIndexRule(LintRule):
    """Detect FK without supporting index."""

    rule_id = "missing_fk_index"
    severity = Severity.ERROR
    enabled_by_default = True

    async def check(self, schema: SchemaMetadata) -> list[LintViolation]:
        violations = []

        for table in schema.tables:
            for fk in table.foreign_keys:
                fk_columns = self._parse_fk_columns(fk.column)

                # Check if index exists with FK columns as leftmost prefix
                has_index = any(
                    index.columns[:len(fk_columns)] == fk_columns
                    for index in table.indexes
                )

                if not has_index:
                    violations.append(...)

        return violations

    def _parse_fk_columns(self, column_spec: str) -> list[str]:
        """Parse "col1, col2" to ["col1", "col2"]."""
        return [c.strip() for c in column_spec.split(",")]

# Comprehensive tests
@pytest.mark.asyncio
async def test_missing_fk_index_simple():
    """Single FK column missing index."""
    ...

@pytest.mark.asyncio
async def test_missing_fk_index_composite():
    """Composite FK missing partial index."""
    ...

@pytest.mark.asyncio
async def test_missing_fk_index_ignores_partial():
    """Partial index (wrong column) doesn't count."""
    ...

@pytest.mark.asyncio
async def test_missing_fk_index_composite_leftmost_prefix():
    """Composite index with extra columns okay."""
    ...
```

**Exemplar 3: PII Detection** (Pattern-matching + whitelist)
```python
# confiture/core/linting/rules/pii_detection.py
@dataclass
class PIIDetectionRule(LintRule):
    """Detect columns that may contain PII."""

    rule_id = "pii_detection"
    severity = Severity.INFO
    enabled_by_default = True

    patterns: dict[str, str] = field(default_factory=lambda: {
        "email": r".*email.*",
        "phone": r".*(phone|mobile|tel).*",
        "ssn": r".*(ssn|social_security).*",
        "dob": r".*(birth|dob|birthday).*",
    })

    exclude_columns: list[str] = field(default_factory=list)

    async def check(self, schema: SchemaMetadata) -> list[LintViolation]:
        violations = []

        for table in schema.tables:
            for column in table.columns:
                if column.name in self.exclude_columns:
                    continue

                pii_type = self._detect_pii(column.name)
                if pii_type:
                    violations.append(...)

        return violations

    def _detect_pii(self, column_name: str) -> str | None:
        """Check if column matches PII pattern."""
        for pii_type, pattern in self.patterns.items():
            if re.match(pattern, column_name, re.IGNORECASE):
                return pii_type
        return None

# Tests with whitelist
@pytest.mark.asyncio
async def test_pii_detection_email():
    """Detects email columns."""
    ...

@pytest.mark.asyncio
async def test_pii_detection_whitelist():
    """Respects exclude_columns."""
    ...

@pytest.mark.asyncio
async def test_pii_detection_false_positive():
    """email_template should be whitelisted."""
    ...
```

**Tests for Days 2-3** (10 tests):
- test_missing_pk_rule_implementation()
- test_missing_pk_with_various_key_types()
- test_missing_fk_index_rule_implementation()
- test_missing_fk_index_composite_scenarios()
- test_pii_detection_rule_implementation()
- test_pii_detection_whitelist_behavior()
- test_rule_base_protocol_satisfied()
- test_rule_integration_with_engine()
- test_rule_configuration_loading()
- test_rule_output_formatting()

#### **Phase 3: AI-Assisted Rule Generation** (Days 3-4)

**Task 5.2.1**: Prompt AI Model to Generate 12 More Rules
```
You are a linting rule generation expert. I've provided 3 complete rule implementations
as exemplars. Your task: Generate 12 more rules following the same pattern.

EXEMPLAR RULES PROVIDED:
1. MissingPrimaryKeyRule - Simple query-based rule
2. MissingFKIndexRule - Complex query with configuration
3. PIIDetectionRule - Pattern matching with whitelist

RULES TO GENERATE (Apply pattern from exemplars):
4. RedundantIndexesRule (query-based)
5. UnusedIndexesRule (query-based with statistics)
6. TableNamingRule (pattern-based)
7. ColumnNamingRule (pattern-based)
8. IndexNamingRule (pattern-based)
9. ConstraintNamingRule (pattern-based)
10. MissingForeignKeysRule (query-based, configurable)
11. MissingNotNullRule (query-based, configurable)
12. OrphanedTablesRule (graph-based with whitelist)
13. MissingAuditTriggerRule (query-based)
14. HardcodedSecretsRule (pattern-based)
15. ImproperInheritanceRule (complex query-based)

FOR EACH RULE:
- Implement following LintRule protocol
- Include 2-3 test cases (happy path + edge cases)
- Add configuration support (enable/disable, whitelist)
- Include fix_suggestion in violations
- Return as Python classes ready to use

OUTPUT: Python module with all 12 rules + tests
```

**Task 5.2.2**: Verify & Integrate Generated Rules
- Review generated rules for correctness
- Fix any hallucinations or issues
- Integrate into rule registry
- Run all tests together

**Tests for Days 3-4** (36 tests):
- 2 tests per generated rule = 24 tests
- 4 integration tests (all rules together)
- 4 false positive tests
- 4 performance tests

#### **Phase 4: Polish & Documentation** (Days 5-6)

**Task 5.3.1**: CLI Integration
```python
# confiture/cli/commands/lint.py
@app.command()
def lint(schema_file: str, config_file: str | None = None):
    """Run schema linting."""
    config = LintConfig.from_yaml(config_file or "confiture.lint.yml")
    engine = LintEngine(config)

    schema = SchemaMetadata.from_file(schema_file)
    result = asyncio.run(engine.lint(schema))

    # Output based on config
    reporter = config.get_reporter()
    reporter.report(result)

    # Exit code
    exit(result.max_severity == Severity.ERROR)
```

**Task 5.3.2**: Documentation
- Lint command reference
- Rule reference (all 15 rules)
- Configuration guide
- Examples for each rule

**Tests for Days 5-6** (10+ tests):
- test_cli_lint_command()
- test_lint_with_custom_config()
- test_lint_exit_code_on_error()
- test_lint_exit_code_on_warning()
- test_lint_output_formats(table, json, github)
- test_lint_large_schema_performance()
- Additional: Documentation examples tests

### 5.4 Acceptance Criteria

- ✅ 15 rules implemented (exemplars + AI-generated)
- ✅ Rule engine with plugin architecture
- ✅ YAML configuration support
- ✅ 3 output formats (table, JSON, GitHub Actions)
- ✅ Whitelist/exclusion support for all rules
- ✅ 51+ tests passing
- ✅ <5 second linting time for 100-table schema
- ✅ False positive rate <5%
- ✅ `confiture lint` command works
- ✅ Documentation with examples

---

## 📅 Revised Timeline

### **Phase 3: All Features (27-31 days)**

**Week 1: Foundation**
- Days 1-3: Feature 1 (Hooks Enhancement)
- Days 1-3: Feature 5 (Linting Architecture + Exemplars)

**Week 2: Core Features**
- Days 4-10: Feature 2 (Custom Strategies with Security Sandbox)
- Days 4-8: Feature 4 (Dry-Run Mode with SAVEPOINT strategy)

**Week 3: User Experience**
- Days 9-16: Feature 3 (Interactive Wizard with questionary)
- Days 4-16: Feature 5 (Linting AI-assisted rule generation)

**Week 4: Integration & Buffer**
- Days 17-31: Integration testing, documentation, edge cases

### **Parallel Work Streams**

```
Developer A (Backend):
├─ Days 1-3: Feature 1 (Hooks)
└─ Days 4-8: Feature 4 (Dry-Run)

Developer B (Security):
├─ Days 4-10: Feature 2 (Custom Strategies + Sandbox)
└─ Ongoing: Code review for security

Developer C (CLI/UX):
├─ Days 1-3: Feature 5 Architecture (parallel)
├─ Days 9-16: Feature 3 (Wizard)
└─ Days 4-16: Feature 5 Linting Rules

Architect (Oversight):
├─ Daily code review
├─ Architecture decisions
├─ Risk management
└─ Dependency coordination
```

---

## 🧪 Complete Test Breakdown

| Feature | Unit | Integration | E2E | Performance | Total |
|---------|------|-------------|-----|-------------|-------|
| **#1: Hooks** | 6 | 4 | - | - | **10-12** |
| **#2: Strategies** | 15 | 12 | 3 | 6 | **36** |
| **#3: Wizard** | 12 | 12 | 4 | 2 | **30+** |
| **#4: Dry-Run** | 18 | 10 | 2 | - | **30** |
| **#5: Linting** | 20 | 10 | 5 | 3 | **38** |
| **TOTAL** | **71** | **48** | **14** | **11** | **155+** |

---

## 🎯 Success Criteria

### **Completion**
- ✅ All 5 features fully implemented
- ✅ 155+ tests passing (100%)
- ✅ 90%+ code coverage
- ✅ 0 security vulnerabilities

### **Quality**
- ✅ No critical bugs in first month
- ✅ <5% false positive rate on linting
- ✅ <1 second latency for hooks
- ✅ All examples working end-to-end

### **Security** (Feature 2 Focus)
- ✅ StrategySandbox prevents code injection
- ✅ Import restrictions enforced
- ✅ Timeout enforcement verified
- ✅ Audit logging complete

### **Architecture** (Feature 4 Focus)
- ✅ SAVEPOINT strategy verified safe
- ✅ DDL changes never committed in dry-run
- ✅ Transaction isolation tested
- ✅ No data loss risk

### **User Experience** (Feature 3 Focus)
- ✅ Questionary library working
- ✅ Multi-select functioning
- ✅ State persistence working
- ✅ Error recovery smooth

### **Documentation**
- ✅ User guides for all features
- ✅ API reference complete
- ✅ 10+ working examples
- ✅ Troubleshooting guides

---

## 🚀 Dependencies & Setup

### **New Dependencies to Add**

```toml
# pyproject.toml
[project.dependencies]
questionary = ">=2.0.0"  # Feature 3: Interactive wizard multi-select
```

### **No Breaking Changes**
- All existing APIs unchanged
- Phase 2 functionality preserved
- Backward compatibility maintained

---

## 📋 Next Steps

### **Before Implementation**
1. ✅ Get user approval of this revised plan
2. ✅ Create feature branches (one per feature)
3. ✅ Assign developers to features
4. ✅ Schedule daily standup

### **Week 1 Kickoff**
1. ✅ Feature 1 begins (simplest, warm-up)
2. ✅ Feature 5 architecture begins (parallel)
3. ✅ Team alignment meeting

### **Ongoing**
1. ✅ Daily standup (15 min)
2. ✅ Daily code review (focus on quality)
3. ✅ Weekly integration check
4. ✅ Risk tracking & escalation

---

## 📞 Critical Review Reminders

**Feature 1: Hooks Enhancement**
- ✅ Building on Phase 2.1 (don't duplicate)
- ✅ 3 built-in hooks only (not redesign)
- ✅ 2-3 days is realistic

**Feature 2: Custom Strategies**
- ✅ **StrategySandbox is non-negotiable** (security)
- ✅ Import restrictions must be enforced
- ✅ Timeout enforcement critical
- ✅ 7 days is realistic with sandbox

**Feature 3: Interactive Wizard**
- ✅ **Questionary dependency required** (Rich limitation)
- ✅ 5 steps not 7 (reduced complexity)
- ✅ State persistence important (UX)
- ✅ 7-8 days is realistic

**Feature 4: Dry-Run Mode**
- ✅ **SAVEPOINT strategy mandatory** (READ ONLY won't work)
- ✅ StatementClassifier prevents unsafe ops
- ✅ Transaction safety must be verified
- ✅ 4-5 days is realistic

**Feature 5: Schema Linting**
- ✅ **15 rules achievable with AI-assisted approach** (exemplar pattern)
- ✅ Architecture-first (engine, config, formatters)
- ✅ 51 tests for comprehensive coverage
- ✅ 6-8 days is realistic

---

**Status**: Ready for Implementation ✅

**Prepared By**: Expert review synthesis + AI-assisted planning

**Date**: December 27, 2025

**Next Action**: User approval → Feature branches → Begin development
