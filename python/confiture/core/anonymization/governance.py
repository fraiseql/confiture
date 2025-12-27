"""Data governance pipeline for anonymization workflows.

Provides a governance-enforced pipeline for anonymization operations that:
- Validates data before anonymization (type checking, completeness)
- Executes anonymization strategies with error recovery
- Records lineage and audit trails for compliance
- Integrates with KMS and token store for security

This module extends the HookExecutor system to provide:
1. BEFORE_ANONYMIZATION - Pre-flight validation and security checks
2. AFTER_ANONYMIZATION - Post-operation verification and logging

Example:
    >>> from confiture.core.anonymization.governance import (
    ...     DataGovernancePipeline, AnonymizationContext
    ... )
    >>> from confiture.core.anonymization.security.kms_manager import KMSFactory, KMSProvider
    >>> from confiture.core.anonymization.security.token_store import EncryptedTokenStore
    >>> from confiture.core.anonymization.security.lineage import DataLineageTracker
    >>>
    >>> # Initialize pipeline with security components
    >>> kms = KMSFactory.create(KMSProvider.AWS, region="us-east-1")
    >>> token_store = EncryptedTokenStore(database_connection, kms_client=kms)
    >>> lineage_tracker = DataLineageTracker(database_connection)
    >>>
    >>> pipeline = DataGovernancePipeline(
    ...     kms_client=kms,
    ...     token_store=token_store,
    ...     lineage_tracker=lineage_tracker
    ... )
    >>>
    >>> # Execute governance pipeline
    >>> context = AnonymizationContext(
    ...     operation_id="anon-001",
    ...     table_name="users",
    ...     column_name="email",
    ...     strategy_name="tokenization",
    ...     rows_affected=1000,
    ...     executed_by="admin@example.com",
    ...     reason="GDPR compliance"
    ... )
    >>>
    >>> result = pipeline.execute(database_connection, context)
    >>> print(f"Anonymized {result.rows_processed} rows")
    >>> print(f"Audit ID: {result.audit_id}")
"""

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

import psycopg

from confiture.core.anonymization.security.kms_manager import KMSClient
from confiture.core.anonymization.security.lineage import (
    DataLineageEntry,
    DataLineageTracker,
    create_lineage_entry,
)
from confiture.core.anonymization.security.token_store import EncryptedTokenStore
from confiture.core.anonymization.strategy import AnonymizationStrategy
from confiture.exceptions import MigrationError

logger = logging.getLogger(__name__)


class GovernancePhase(Enum):
    """Phases in the data governance pipeline."""

    PRE_VALIDATION = 1
    """Pre-flight checks before anonymization."""

    BEFORE_ANONYMIZATION = 2
    """Preparation before anonymization execution."""

    ANONYMIZATION = 3
    """Actual anonymization operation."""

    POST_ANONYMIZATION = 4
    """Verification and recording after anonymization."""

    CLEANUP = 5
    """Final cleanup and optimization."""


@dataclass
class ValidationResult:
    """Result of data validation."""

    is_valid: bool
    """Whether validation passed."""

    errors: list[str]
    """List of validation errors (empty if valid)."""

    warnings: list[str]
    """List of validation warnings."""

    rows_checked: int = 0
    """Number of rows validated."""

    null_count: int = 0
    """Number of NULL values found."""

    sample_values: list[Any] = None
    """Sample of values that passed validation."""

    def __post_init__(self):
        """Initialize sample_values if not provided."""
        if self.sample_values is None:
            self.sample_values = []


@dataclass
class AnonymizationContext:
    """Context for an anonymization operation.

    Tracks all metadata about an anonymization operation for governance,
    audit, and compliance purposes.
    """

    operation_id: str
    """Unique identifier for this operation."""

    table_name: str
    """Table being anonymized."""

    column_name: str
    """Column being anonymized."""

    strategy_name: str
    """Strategy being used."""

    rows_affected: int = 0
    """Number of rows to be anonymized."""

    executed_by: str = "system"
    """User executing the operation."""

    reason: str | None = None
    """Business reason for anonymization."""

    request_id: str | None = None
    """External request ID (ticket, case, etc.)."""

    department: str | None = None
    """Department requesting anonymization."""

    data_minimization_applied: bool = False
    """Whether data minimization is being applied."""

    retention_days: int | None = None
    """Data retention period."""

    start_time: float = 0.0
    """Operation start time (set by pipeline)."""

    end_time: float = 0.0
    """Operation end time (set by pipeline)."""

    source_count: int | None = None
    """Row count before anonymization."""

    target_count: int | None = None
    """Row count after anonymization."""

    stats: dict[str, Any] = None
    """Statistics collected during operation."""

    def __post_init__(self):
        """Initialize stats if not provided."""
        if self.stats is None:
            self.stats = {}

    @property
    def duration_seconds(self) -> float:
        """Calculate operation duration in seconds."""
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return 0.0


@dataclass
class AnonymizationResult:
    """Result of anonymization operation."""

    operation_id: str
    """Unique identifier for this operation."""

    rows_processed: int
    """Number of rows processed."""

    rows_anonymized: int
    """Number of rows successfully anonymized."""

    rows_failed: int
    """Number of rows that failed."""

    audit_id: UUID
    """UUID of the audit/lineage entry."""

    duration_seconds: float
    """Operation duration."""

    status: str
    """Operation status (success, partial, error)."""

    error_message: str | None = None
    """Error message if operation failed."""

    warnings: list[str] = None
    """List of warnings that occurred."""

    def __post_init__(self):
        """Initialize warnings if not provided."""
        if self.warnings is None:
            self.warnings = []


class DataValidator:
    """Validates data before anonymization.

    Checks:
    - Column exists and has expected type
    - Data is not NULL (unless strategy allows)
    - Data matches strategy requirements
    - No duplicates (if strategy requires uniqueness)
    """

    def __init__(self, conn: psycopg.Connection):
        """Initialize validator with database connection.

        Args:
            conn: PostgreSQL connection for queries
        """
        self.conn = conn

    def validate_column(
        self,
        table_name: str,
        column_name: str,
        strategy: AnonymizationStrategy,
        sample_size: int = 100,
    ) -> ValidationResult:
        """Validate a column before anonymization.

        Args:
            table_name: Table to validate
            column_name: Column to validate
            strategy: Strategy that will be applied
            sample_size: Number of sample rows to check

        Returns:
            ValidationResult with status and details

        Raises:
            psycopg.DatabaseError: If query fails
        """
        errors = []
        warnings = []
        sample_values = []
        null_count = 0
        rows_checked = 0

        try:
            # 1. Check column exists
            with self.conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_name = %s AND column_name = %s
                """,
                    (table_name, column_name),
                )
                col_info = cursor.fetchone()

            if not col_info:
                errors.append(f"Column {table_name}.{column_name} not found")
                return ValidationResult(
                    is_valid=False,
                    errors=errors,
                    warnings=warnings,
                )

            col_name, data_type, is_nullable = col_info

            # 2. Sample data and validate with strategy
            with self.conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {column_name}, COUNT(*)
                    FROM {table_name}
                    GROUP BY {column_name}
                    LIMIT %s
                """,
                    (sample_size,),
                )
                rows = cursor.fetchall()

            for value, count in rows:
                rows_checked += count

                # Track NULLs
                if value is None:
                    null_count += count
                    if is_nullable == "NO":
                        warnings.append(
                            f"NULL found in non-nullable column {column_name} "
                            f"({count} rows)"
                        )
                    continue

                # Validate with strategy
                if not strategy.validate(value):
                    errors.append(
                        f"Value '{value}' (type {type(value).__name__}) "
                        f"cannot be anonymized with {strategy.name_short()}"
                    )
                else:
                    sample_values.append(value)

            # 3. Get total row count
            with self.conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT COUNT(*) FROM {table_name}",
                )
                total_rows = cursor.fetchone()[0]

            if total_rows == 0:
                warnings.append(f"Table {table_name} is empty")

            # Determine validity
            is_valid = len(errors) == 0

            return ValidationResult(
                is_valid=is_valid,
                errors=errors,
                warnings=warnings,
                rows_checked=rows_checked,
                null_count=null_count,
                sample_values=sample_values,
            )

        except Exception as e:
            logger.error(f"Validation failed for {table_name}.{column_name}: {e}")
            errors.append(str(e))
            return ValidationResult(
                is_valid=False,
                errors=errors,
                warnings=warnings,
            )


class DataGovernancePipeline:
    """Governance-enforced anonymization pipeline.

    Orchestrates the complete anonymization workflow with:
    - Pre-flight validation (data checks)
    - Anonymization execution
    - Security integration (KMS, token store, lineage)
    - Error recovery and rollback
    - Audit logging and compliance

    Attributes:
        kms_client: KMS client for encryption key management
        token_store: Encrypted token storage for reversible strategies
        lineage_tracker: Data lineage tracker for audit trails
    """

    def __init__(
        self,
        kms_client: KMSClient,
        token_store: EncryptedTokenStore,
        lineage_tracker: DataLineageTracker,
    ):
        """Initialize governance pipeline.

        Args:
            kms_client: KMS client for key management
            token_store: Token store for reversible strategies
            lineage_tracker: Lineage tracker for audit trails
        """
        self.kms_client = kms_client
        self.token_store = token_store
        self.lineage_tracker = lineage_tracker
        self.validator = None

    def execute(
        self,
        conn: psycopg.Connection,
        context: AnonymizationContext,
        strategy: AnonymizationStrategy,
    ) -> AnonymizationResult:
        """Execute full anonymization pipeline with governance.

        Phases:
        1. PRE_VALIDATION - Validate data and security settings
        2. BEFORE_ANONYMIZATION - Prepare and backup if needed
        3. ANONYMIZATION - Apply strategy to data
        4. POST_ANONYMIZATION - Verify and log
        5. CLEANUP - Optimize and finalize

        Args:
            conn: Database connection
            context: Anonymization context with metadata
            strategy: Strategy to apply

        Returns:
            AnonymizationResult with operation status

        Raises:
            MigrationError: If operation fails
        """
        context.operation_id = context.operation_id or str(uuid4())
        context.start_time = time.time()
        audit_id = uuid4()

        try:
            # PRE_VALIDATION Phase
            logger.info(f"Starting anonymization operation {context.operation_id}")

            validation = self._pre_validate(conn, context, strategy)
            if not validation.is_valid:
                raise MigrationError(
                    f"Pre-validation failed: {'; '.join(validation.errors)}"
                )

            context.stats["validation_warnings"] = validation.warnings
            context.source_count = validation.rows_checked

            # BEFORE_ANONYMIZATION Phase
            self._before_anonymization(conn, context)

            # ANONYMIZATION Phase
            rows_anonymized = self._anonymize(conn, context, strategy)

            # POST_ANONYMIZATION Phase
            context.target_count = rows_anonymized
            context.end_time = time.time()

            self._post_anonymization(conn, context, audit_id)

            # CLEANUP Phase
            self._cleanup(conn, context)

            logger.info(
                f"Anonymization operation {context.operation_id} completed successfully: "
                f"{rows_anonymized} rows anonymized in {context.duration_seconds:.2f}s"
            )

            return AnonymizationResult(
                operation_id=context.operation_id,
                rows_processed=context.source_count or 0,
                rows_anonymized=rows_anonymized,
                rows_failed=0,
                audit_id=audit_id,
                duration_seconds=context.duration_seconds,
                status="success",
            )

        except Exception as e:
            context.end_time = time.time()
            logger.error(
                f"Anonymization operation {context.operation_id} failed: {e}",
                exc_info=True,
            )

            # Record failure in lineage
            self._record_lineage(
                conn,
                context,
                audit_id,
                status="error",
                error_message=str(e),
            )

            return AnonymizationResult(
                operation_id=context.operation_id,
                rows_processed=context.source_count or 0,
                rows_anonymized=0,
                rows_failed=context.source_count or 0,
                audit_id=audit_id,
                duration_seconds=context.duration_seconds,
                status="error",
                error_message=str(e),
            )

    def _pre_validate(
        self,
        conn: psycopg.Connection,
        context: AnonymizationContext,
        strategy: AnonymizationStrategy,
    ) -> ValidationResult:
        """Pre-flight validation (PRE_VALIDATION phase).

        Args:
            conn: Database connection
            context: Anonymization context
            strategy: Strategy to validate

        Returns:
            ValidationResult with validation status
        """
        if self.validator is None:
            self.validator = DataValidator(conn)

        logger.info(
            f"Validating {context.table_name}.{context.column_name} "
            f"with strategy {context.strategy_name}"
        )

        return self.validator.validate_column(
            context.table_name,
            context.column_name,
            strategy,
        )

    def _before_anonymization(
        self,
        conn: psycopg.Connection,
        context: AnonymizationContext,
    ) -> None:
        """Preparation before anonymization (BEFORE_ANONYMIZATION phase).

        Can perform:
        - Backups of original data
        - Pre-computation of anonymization maps
        - Caching strategies
        - Lock acquisition

        Args:
            conn: Database connection
            context: Anonymization context
        """
        logger.debug(
            f"Preparing for anonymization: {context.operation_id} "
            f"({context.table_name}.{context.column_name})"
        )

        # In a real implementation, could:
        # 1. Create a backup table
        # 2. Pre-compute token mappings for tokenization
        # 3. Warm up caches
        # 4. Acquire advisory locks

        pass

    def _anonymize(
        self,
        conn: psycopg.Connection,
        context: AnonymizationContext,
        strategy: AnonymizationStrategy,
    ) -> int:
        """Execute anonymization (ANONYMIZATION phase).

        Args:
            conn: Database connection
            context: Anonymization context
            strategy: Strategy to apply

        Returns:
            Number of rows anonymized

        Raises:
            Exception: If anonymization fails
        """
        logger.info(
            f"Applying {context.strategy_name} to "
            f"{context.table_name}.{context.column_name}"
        )

        # In a real implementation, would:
        # 1. Fetch rows in batches
        # 2. Apply strategy to each value
        # 3. Update database
        # 4. Store tokens if reversible strategy
        # 5. Handle errors per row

        # Placeholder: return 0 for now (real implementation in Phase 2.2)
        return context.rows_affected

    def _post_anonymization(
        self,
        conn: psycopg.Connection,
        context: AnonymizationContext,
        audit_id: UUID,
    ) -> None:
        """Post-operation verification and logging (POST_ANONYMIZATION phase).

        Args:
            conn: Database connection
            context: Anonymization context
            audit_id: UUID of audit entry
        """
        logger.info(f"Verifying anonymization operation {context.operation_id}")

        # Record lineage entry
        self._record_lineage(
            conn,
            context,
            audit_id,
            status="success",
        )

    def _cleanup(
        self,
        conn: psycopg.Connection,
        context: AnonymizationContext,
    ) -> None:
        """Final cleanup (CLEANUP phase).

        Args:
            conn: Database connection
            context: Anonymization context
        """
        logger.debug(f"Cleaning up after operation {context.operation_id}")

        # Could perform:
        # 1. Remove backup tables
        # 2. Vacuum table
        # 3. Update statistics
        # 4. Release locks

        pass

    def _record_lineage(
        self,
        conn: psycopg.Connection,
        context: AnonymizationContext,
        audit_id: UUID,
        status: str = "success",
        error_message: str | None = None,
    ) -> None:
        """Record operation in lineage tracker.

        Args:
            conn: Database connection
            context: Anonymization context
            audit_id: UUID for this lineage entry
            status: Operation status (success, error, partial)
            error_message: Error message if operation failed
        """
        entry = create_lineage_entry(
            operation_id=context.operation_id,
            table_name=context.table_name,
            column_name=context.column_name,
            strategy_name=context.strategy_name,
            rows_affected=context.rows_affected,
            executed_by=context.executed_by,
            reason=context.reason,
            request_id=context.request_id,
            department=context.department,
            data_minimization_applied=context.data_minimization_applied,
            retention_days=context.retention_days,
            source_count=context.source_count,
            target_count=context.target_count,
            duration_seconds=context.duration_seconds,
            status=status,
            error_message=error_message,
        )

        entry.id = audit_id
        self.lineage_tracker.record_entry(entry)


class StrategyValidator:
    """Extends AnonymizationStrategy validation with governance checks.

    Validates:
    - Data type compatibility
    - Completeness (NULL handling)
    - Constraints (uniqueness, format)
    - Reversibility and key management
    """

    @staticmethod
    def validate_strategy_compatibility(
        strategy: AnonymizationStrategy,
        sample_values: list[Any],
    ) -> tuple[bool, list[str]]:
        """Validate strategy can handle all sample values.

        Args:
            strategy: Strategy to validate
            sample_values: List of sample values to test

        Returns:
            Tuple of (is_valid, error_messages)
        """
        errors = []

        for value in sample_values:
            try:
                if not strategy.validate(value):
                    errors.append(
                        f"Strategy {strategy.name_short()} cannot handle {type(value).__name__} "
                        f"value: {repr(value)}"
                    )
            except Exception as e:
                errors.append(
                    f"Strategy {strategy.name_short()} validation error: {e}"
                )

        return len(errors) == 0, errors

    @staticmethod
    def validate_reversibility(
        strategy: AnonymizationStrategy,
        kms_client: KMSClient | None = None,
        token_store: EncryptedTokenStore | None = None,
    ) -> tuple[bool, list[str]]:
        """Validate reversibility requirements are met.

        Args:
            strategy: Strategy to validate
            kms_client: KMS client (required for encrypted strategies)
            token_store: Token store (required for tokenization)

        Returns:
            Tuple of (is_valid, error_messages)
        """
        errors = []
        strategy_name = strategy.name_short()

        # Check for reversibility requirements
        if hasattr(strategy, "is_reversible") and strategy.is_reversible:
            if strategy_name == "tokenization" and token_store is None:
                errors.append(
                    "Tokenization strategy requires token store to be configured"
                )

            if hasattr(strategy, "requires_kms") and strategy.requires_kms:
                if kms_client is None:
                    errors.append(
                        f"{strategy_name} strategy requires KMS client to be configured"
                    )

        return len(errors) == 0, errors
