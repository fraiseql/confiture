"""
pgGit integration module for Confiture.

This module provides optional integration with pgGit for development
coordination. pgGit must be installed as a PostgreSQL extension.

pgGit is designed for DEVELOPMENT and STAGING databases only.
Do NOT install pgGit on production databases.

Usage:
    from confiture.integrations.pggit import PgGitClient, is_pggit_available

    if is_pggit_available(connection):
        client = PgGitClient(connection)
        branches = client.list_branches()

Example workflow:
    # On development database with pgGit installed
    client = PgGitClient(conn)
    client.create_branch("feature/payments")
    client.checkout("feature/payments")
    # ... make schema changes ...
    client.merge("feature/payments", "main")

    # Generate migrations for production (which has NO pgGit)
    from confiture.integrations.pggit.generator import MigrationGenerator
    generator = MigrationGenerator(conn)
    migrations = generator.generate_from_branch("feature/payments")
"""

from confiture.integrations.pggit.detection import (
    is_pggit_available,
    get_pggit_version,
    require_pggit,
    MIN_PGGIT_VERSION,
)
from confiture.integrations.pggit.exceptions import (
    PgGitError,
    PgGitNotAvailableError,
    PgGitVersionError,
    PgGitBranchError,
    PgGitMergeConflictError,
)
from confiture.integrations.pggit.client import PgGitClient
from confiture.integrations.pggit.coordination import (
    ConflictDetector,
    ConflictReport,
    ConflictSeverity,
    ConflictType,
    Intent,
    IntentRegistry,
    IntentStatus,
    RiskLevel,
)
from confiture.integrations.pggit.generator import (
    GeneratedMigration,
    MigrationGenerator,
)

__all__ = [
    # Detection
    "is_pggit_available",
    "get_pggit_version",
    "require_pggit",
    "MIN_PGGIT_VERSION",
    # Client
    "PgGitClient",
    # Generator
    "GeneratedMigration",
    "MigrationGenerator",
    # Coordination
    "Intent",
    "IntentRegistry",
    "IntentStatus",
    "ConflictReport",
    "ConflictType",
    "ConflictSeverity",
    "ConflictDetector",
    "RiskLevel",
    # Exceptions
    "PgGitError",
    "PgGitNotAvailableError",
    "PgGitVersionError",
    "PgGitBranchError",
    "PgGitMergeConflictError",
]
