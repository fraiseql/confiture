"""Prep-seed transformation pattern validation.

This module validates the prep_seed pattern where UUID FKs in prep_seed schema
transform to BIGINT FKs in final tables via resolution functions.

Five-level validation:
- Level 1: Seed file validation (schema target, FK naming, UUID format)
- Level 2: Schema consistency (table mapping, FK types, trinity pattern)
- Level 3: Resolution function validation (schema drift detection)
- Level 4: Runtime validation (database dry-run)
- Level 5: Full seed execution (integration test)
"""

from __future__ import annotations

from confiture.core.seed_validation.prep_seed.level_1_seed_files import (
    Level1SeedValidator,
)
from confiture.core.seed_validation.prep_seed.level_2_schema import (
    Level2SchemaValidator,
    SchemaMapping,
    TableDefinition,
)
from confiture.core.seed_validation.prep_seed.level_3_resolvers import (
    Level3ResolutionValidator,
)
from confiture.core.seed_validation.prep_seed.level_4_runtime import (
    Level4RuntimeValidator,
)
from confiture.core.seed_validation.prep_seed.level_5_execution import (
    Level5ExecutionValidator,
)
from confiture.core.seed_validation.prep_seed.models import (
    PrepSeedPattern,
    PrepSeedReport,
    PrepSeedViolation,
    ViolationSeverity,
)
from confiture.core.seed_validation.prep_seed.orchestrator import (
    OrchestrationConfig,
    PrepSeedOrchestrator,
)

__all__ = [
    # Models
    "PrepSeedPattern",
    "PrepSeedReport",
    "PrepSeedViolation",
    "ViolationSeverity",
    # Validators
    "Level1SeedValidator",
    "Level2SchemaValidator",
    "Level3ResolutionValidator",
    "Level4RuntimeValidator",
    "Level5ExecutionValidator",
    # Orchestrator
    "OrchestrationConfig",
    "PrepSeedOrchestrator",
    # Schema utilities
    "SchemaMapping",
    "TableDefinition",
]
