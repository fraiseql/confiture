"""Example: Migration workflow with automatic recovery.

Demonstrates how to use Phase 1-3 systems together for a safe migration:
- Phase 1: Error codes for classification
- Phase 2: Logging and metrics tracking
- Phase 3: Retry and recovery with workflow orchestration
"""

from confiture.workflows.retry import RetryPolicy, with_retry
from confiture.workflows.orchestrator import Workflow


def migration_workflow_example() -> None:
    """Example migration workflow with error handling and recovery.

    Usage:
        migration_workflow_example()
    """

    # Define workflow steps
    workflow = Workflow(
        name="safe_migration",
        steps=[
            ("validate", lambda: print("Validating schema...")),
            ("backup", lambda: print("Creating backup...")),
            ("migrate", lambda: print("Applying migration...")),
            ("verify", lambda: print("Verifying changes...")),
        ],
    )

    # Execute with error handling
    result = workflow.execute()

    if result.success:
        print(f"✅ Migration succeeded: {result.completed_steps}")
    else:
        print(f"❌ Failed at step: {result.failed_step}")
        print(f"   Error: {result.error}")
