"""Confiture: PostgreSQL migrations, sweetly done 🍓

Confiture is a modern PostgreSQL migration tool with a build-from-scratch
philosophy and 4 migration strategies.

Library API example::

    from confiture import Migrator

    with Migrator.from_config("db/environments/prod.yaml") as m:
        status = m.status()
        if status.has_pending:
            result = m.up()
"""

from importlib.metadata import PackageNotFoundError, version
from typing import Any

__author__ = "Lionel Hamayon"
__email__ = "lionel.hamayon@evolution-digitale.fr"

__all__ = [
    "AnonymizationProfile",
    # PII anonymization framework (library API; powers `confiture sync --anonymize`)
    "AnonymizationStrategy",
    "ApplyResult",
    "AuditConfig",
    # Built-in migration lifecycle hooks (opt-in via Migrator.register_hook)
    "AuditHook",
    "BackupConfig",
    "BackupHook",
    "BaselineDetector",
    "BatchConfig",
    "BatchProgress",
    # Large table operations
    "BatchedMigration",
    "BlueGreenConfig",
    # Blue-green orchestration (library API)
    "BlueGreenOrchestrator",
    "ConfigurationError",
    # Exceptions
    "ConfiturError",
    "ConfitureEmitter",
    "ConflictSeverity",
    "DependencyGraph",
    # Diff
    "DiffResult",
    "DriftItem",
    "DriftReport",
    "DriftSeverity",
    "DriftType",
    # Dry run
    "DryRunError",
    "DryRunExecutor",
    "DryRunResult",
    # Scaffold / generate tree
    "EmittedFunction",
    "Environment",
    "ExternalGeneratorError",
    "FKReference",
    "FunctionCatalog",
    "FunctionInfo",
    # Introspection layer
    "FunctionIntrospector",
    "FunctionParam",
    # Git accompaniment
    "GrantAccompanimentChecker",
    "GrantAccompanimentError",
    "GrantAccompanimentReport",
    "HealthCheckResult",
    "HookPhase",
    # Multi-agent coordination
    "IntentRegistry",
    "IntentStatus",
    "IntrospectedColumn",
    "IntrospectedTable",
    "IntrospectionResult",
    "LockConfig",
    "MigrateDownResult",
    "MigrateRebuildResult",
    "MigrateReinitResult",
    "MigrateUpResult",
    "MigrationAnalyzer",
    "MigrationApplied",
    "MigrationError",
    "MigrationInfo",
    # Locking
    "MigrationLock",
    "MigrationPhase",
    "MigrationPreflightInfo",
    "MigrationState",
    # Result models
    "MigrationStatus",
    # Migration verification
    "MigrationVerifier",
    # Core classes
    "Migrator",
    "MigratorSession",
    "OnlineIndexBuilder",
    "PGFeature",
    "PGVersionInfo",
    "PreconditionError",
    "PreconditionValidationError",
    "PreflightAgainstMigration",
    "PreflightAgainstResult",
    # Preflight
    "PreflightResult",
    "RebuildError",
    "RestoreError",
    "RollbackError",
    "RollbackSuggestion",
    "RollbackTestResult",
    "RollbackTester",
    "SQLError",
    "SchemaBuilder",
    # Drift detection
    "SchemaDriftDetector",
    "SchemaError",
    # Table/schema introspection
    "SchemaIntrospector",
    "SchemaLinter",
    "SchemaSnapshotGenerator",
    # Seed operations
    "SeedApplier",
    "SeedError",
    "StatementResult",
    "StatusResult",
    "StrategyConfig",
    "StrategyRegistry",
    "TableSizeEstimator",
    "TrafficController",
    "TypeMapper",
    "VerifyAllResult",
    "VerifyFileError",
    "VerifyResult",
    "VersionAwareSQL",
    "__author__",
    "__email__",
    "__version__",
    "check_version_compatibility",
    # PostgreSQL version detection / feature gating (library API)
    "detect_version",
    "export_all",
    # Rollback generation (library API)
    "generate_rollback",
    "generate_rollback_script",
    # Schema export
    "generate_schema",
    "get_recommended_settings",
    "parse_version_string",
    "register_strategy",
    "suggest_backup_for_destructive_operations",
]

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    # Core
    "SchemaBuilder": ("confiture.core.builder", "SchemaBuilder"),
    "Migrator": ("confiture.core.migrator", "Migrator"),
    "MigratorSession": ("confiture.core.migrator", "MigratorSession"),
    "Environment": ("confiture.config.environment", "Environment"),
    "SchemaSnapshotGenerator": ("confiture.core.schema_snapshot", "SchemaSnapshotGenerator"),
    "BaselineDetector": ("confiture.core.baseline_detector", "BaselineDetector"),
    # Introspection layer
    "FunctionIntrospector": ("confiture.core.introspection.functions", "FunctionIntrospector"),
    "FunctionInfo": ("confiture.models.function_info", "FunctionInfo"),
    "FunctionParam": ("confiture.models.function_info", "FunctionParam"),
    "FunctionCatalog": ("confiture.models.function_info", "FunctionCatalog"),
    "TypeMapper": ("confiture.core.introspection.type_mapping", "TypeMapper"),
    "DependencyGraph": ("confiture.core.introspection.dependency_graph", "DependencyGraph"),
    # Drift detection
    "SchemaDriftDetector": ("confiture.core.drift", "SchemaDriftDetector"),
    "DriftReport": ("confiture.core.drift", "DriftReport"),
    "DriftItem": ("confiture.core.drift", "DriftItem"),
    "DriftType": ("confiture.core.drift", "DriftType"),
    "DriftSeverity": ("confiture.core.drift", "DriftSeverity"),
    # Locking
    "MigrationLock": ("confiture.core.locking", "MigrationLock"),
    "LockConfig": ("confiture.core.locking", "LockConfig"),
    # Preflight
    "PreflightResult": ("confiture.models.results", "PreflightResult"),
    "MigrationPreflightInfo": ("confiture.models.results", "MigrationPreflightInfo"),
    "PreflightAgainstMigration": ("confiture.models.results", "PreflightAgainstMigration"),
    "PreflightAgainstResult": ("confiture.models.results", "PreflightAgainstResult"),
    "MigrationAnalyzer": ("confiture.core.migration_analyzer", "MigrationAnalyzer"),
    # Diff
    "DiffResult": ("confiture.models.results", "DiffResult"),
    # Result models
    "MigrationStatus": ("confiture.models.results", "MigrationStatus"),
    "StatusResult": ("confiture.models.results", "StatusResult"),
    "MigrationInfo": ("confiture.models.results", "MigrationInfo"),
    "MigrateUpResult": ("confiture.models.results", "MigrateUpResult"),
    "MigrateDownResult": ("confiture.models.results", "MigrateDownResult"),
    "MigrateReinitResult": ("confiture.models.results", "MigrateReinitResult"),
    "MigrateRebuildResult": ("confiture.models.results", "MigrateRebuildResult"),
    "MigrationApplied": ("confiture.models.results", "MigrationApplied"),
    "VerifyAllResult": ("confiture.models.results", "VerifyAllResult"),
    # Exceptions
    "RebuildError": ("confiture.exceptions", "RebuildError"),
    "GrantAccompanimentError": ("confiture.exceptions", "GrantAccompanimentError"),
    "VerifyFileError": ("confiture.exceptions", "VerifyFileError"),
    "ConfiturError": ("confiture.exceptions", "ConfiturError"),
    "ConfigurationError": ("confiture.exceptions", "ConfigurationError"),
    "MigrationError": ("confiture.exceptions", "MigrationError"),
    "SchemaError": ("confiture.exceptions", "SchemaError"),
    "SQLError": ("confiture.exceptions", "SQLError"),
    "RollbackError": ("confiture.exceptions", "RollbackError"),
    "SeedError": ("confiture.exceptions", "SeedError"),
    "RestoreError": ("confiture.exceptions", "RestoreError"),
    # Preconditions
    "PreconditionError": ("confiture.core.preconditions", "PreconditionError"),
    "PreconditionValidationError": ("confiture.core.preconditions", "PreconditionValidationError"),
    # Grant accompaniment
    "GrantAccompanimentChecker": (
        "confiture.core.grant_accompaniment",
        "GrantAccompanimentChecker",
    ),
    "GrantAccompanimentReport": ("confiture.models.git", "GrantAccompanimentReport"),
    # Migration verification
    "MigrationVerifier": ("confiture.core.migration_verifier", "MigrationVerifier"),
    "VerifyResult": ("confiture.core.migration_verifier", "VerifyResult"),
    # Table/schema introspection
    "SchemaIntrospector": ("confiture.core.introspection.tables", "SchemaIntrospector"),
    "IntrospectionResult": ("confiture.models.introspection", "IntrospectionResult"),
    "IntrospectedTable": ("confiture.models.introspection", "IntrospectedTable"),
    "IntrospectedColumn": ("confiture.models.introspection", "IntrospectedColumn"),
    "FKReference": ("confiture.models.introspection", "FKReference"),
    # Seed operations
    "SeedApplier": ("confiture.core.seed.applier", "SeedApplier"),
    "ApplyResult": ("confiture.core.seed.applier", "ApplyResult"),
    # Large table operations
    "BatchedMigration": ("confiture.core.large_tables", "BatchedMigration"),
    "BatchConfig": ("confiture.core.large_tables", "BatchConfig"),
    "BatchProgress": ("confiture.core.large_tables", "BatchProgress"),
    "OnlineIndexBuilder": ("confiture.core.large_tables", "OnlineIndexBuilder"),
    "TableSizeEstimator": ("confiture.core.large_tables", "TableSizeEstimator"),
    # Multi-agent coordination
    "IntentRegistry": (
        "confiture.integrations.pggit.coordination.registry",
        "IntentRegistry",
    ),
    "ConflictSeverity": (
        "confiture.integrations.pggit.coordination.models",
        "ConflictSeverity",
    ),
    "IntentStatus": (
        "confiture.integrations.pggit.coordination.models",
        "IntentStatus",
    ),
    # Dry run
    "DryRunError": ("confiture.core.dry_run", "DryRunError"),
    "DryRunExecutor": ("confiture.core.dry_run", "DryRunExecutor"),
    "DryRunResult": ("confiture.core.dry_run", "DryRunResult"),
    "StatementResult": ("confiture.core.dry_run", "StatementResult"),
    # Schema export
    "generate_schema": ("confiture.core.schema_exporter", "generate_schema"),
    "export_all": ("confiture.core.schema_exporter", "export_all"),
    "SchemaLinter": ("confiture.core.linting", "SchemaLinter"),
    "ExternalGeneratorError": ("confiture.exceptions", "ExternalGeneratorError"),
    # Scaffold / generate tree
    "EmittedFunction": ("confiture.core.scaffold.emitter", "EmittedFunction"),
    "ConfitureEmitter": ("confiture.core.scaffold.emitter", "ConfitureEmitter"),
    # Blue-green orchestration (library API)
    "BlueGreenOrchestrator": ("confiture.core.blue_green", "BlueGreenOrchestrator"),
    "BlueGreenConfig": ("confiture.core.blue_green", "BlueGreenConfig"),
    "TrafficController": ("confiture.core.blue_green", "TrafficController"),
    "MigrationPhase": ("confiture.core.blue_green", "MigrationPhase"),
    "MigrationState": ("confiture.core.blue_green", "MigrationState"),
    "HealthCheckResult": ("confiture.core.blue_green", "HealthCheckResult"),
    # PostgreSQL version detection / feature gating (library API)
    "detect_version": ("confiture.core.pg_version", "detect_version"),
    "parse_version_string": ("confiture.core.pg_version", "parse_version_string"),
    "check_version_compatibility": ("confiture.core.pg_version", "check_version_compatibility"),
    "get_recommended_settings": ("confiture.core.pg_version", "get_recommended_settings"),
    "PGVersionInfo": ("confiture.core.pg_version", "PGVersionInfo"),
    "PGFeature": ("confiture.core.pg_version", "PGFeature"),
    "VersionAwareSQL": ("confiture.core.pg_version", "VersionAwareSQL"),
    # Rollback generation (library API)
    "generate_rollback": ("confiture.core.rollback_generator", "generate_rollback"),
    "generate_rollback_script": ("confiture.core.rollback_generator", "generate_rollback_script"),
    "suggest_backup_for_destructive_operations": (
        "confiture.core.rollback_generator",
        "suggest_backup_for_destructive_operations",
    ),
    "RollbackSuggestion": ("confiture.core.rollback_generator", "RollbackSuggestion"),
    "RollbackTester": ("confiture.core.rollback_generator", "RollbackTester"),
    "RollbackTestResult": ("confiture.core.rollback_generator", "RollbackTestResult"),
    # Built-in migration lifecycle hooks (opt-in via Migrator.register_hook)
    "AuditHook": ("confiture.core.hooks.builtin.audit_hook", "AuditHook"),
    "AuditConfig": ("confiture.core.hooks.builtin.audit_hook", "AuditConfig"),
    "BackupHook": ("confiture.core.hooks.builtin.backup_hook", "BackupHook"),
    "BackupConfig": ("confiture.core.hooks.builtin.backup_hook", "BackupConfig"),
    "HookPhase": ("confiture.core.hooks.phases", "HookPhase"),
    # PII anonymization framework (library API). Imported from the package
    # facade so the built-in strategies are registered on first access.
    "AnonymizationStrategy": ("confiture.core.anonymization", "AnonymizationStrategy"),
    "StrategyConfig": ("confiture.core.anonymization", "StrategyConfig"),
    "StrategyRegistry": ("confiture.core.anonymization", "StrategyRegistry"),
    "register_strategy": ("confiture.core.anonymization", "register_strategy"),
    "AnonymizationProfile": ("confiture.core.anonymization", "AnonymizationProfile"),
}


def _installed_version() -> str:

    try:
        return version("fraiseql-confiture")
    except PackageNotFoundError:
        return "0.0.0+unknown"


def __getattr__(name: str) -> Any:
    """The lazy public surface: names resolve on first use, so ``import confiture`` stays cheap."""
    if name == "__version__":
        value = _installed_version()
        globals()["__version__"] = value
        return value
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        module = __import__(module_path, fromlist=[attr_name])
        return getattr(module, attr_name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
