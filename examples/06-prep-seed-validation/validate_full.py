#!/usr/bin/env python3
"""
Validate prep-seed pattern with full database integration (Levels 1-5).

Requires a running PostgreSQL database. Set DATABASE_URL environment variable.

Usage:
    # Export database URL
    export DATABASE_URL="postgresql://postgres:password@localhost/test_db"

    # Run full validation
    python validate_full.py

    # Run up to specific level
    python validate_full.py --level 4
"""

import os
import sys
from pathlib import Path

from confiture.core.seed_validation.prep_seed.models import ViolationSeverity
from confiture.core.seed_validation.prep_seed.orchestrator import (
    OrchestrationConfig,
    PrepSeedOrchestrator,
)


def main() -> int:
    """Run full validation with database support."""
    # Get database URL from environment
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("❌ Error: DATABASE_URL environment variable not set")
        print()
        print("Usage:")
        print("  export DATABASE_URL='postgresql://user:pass@host/dbname'")
        print("  python validate_full.py")
        return 1

    # Get level from command line (default: 5)
    max_level = 5
    if len(sys.argv) > 1:
        if sys.argv[1] == "--level" and len(sys.argv) > 2:
            try:
                max_level = int(sys.argv[2])
            except ValueError:
                print(f"❌ Invalid level: {sys.argv[2]}")
                return 1

    # Configure orchestrator
    script_dir = Path(__file__).parent
    config = OrchestrationConfig(
        max_level=max_level,
        seeds_dir=script_dir / "db" / "seeds" / "prep",
        schema_dir=script_dir / "db" / "schema",
        database_url=database_url,
        prep_seed_schema="prep_seed",
        catalog_schema="catalog",
        level_5_mode="comprehensive",  # Check all constraints
        stop_on_critical=True,
    )

    # Run validation
    print("🌱 Prep-Seed Validation (Full Database)")
    print("=" * 50)
    print(f"Max Level: {config.max_level}")
    print(f"Seeds Dir: {config.seeds_dir}")
    print(f"Schema Dir: {config.schema_dir}")
    print(f"Database: {database_url[:40]}...")
    print()

    orchestrator = PrepSeedOrchestrator(config)
    report = orchestrator.run()

    # Display results
    print("📊 Results")
    print("=" * 50)
    print(f"Files scanned: {len(report.scanned_files)}")
    print(f"Total violations: {report.violation_count}")
    print()

    if report.has_violations:
        # Group by severity
        by_severity = {
            "CRITICAL": [],
            "ERROR": [],
            "WARNING": [],
            "INFO": [],
        }

        for v in report.violations:
            severity = str(v.severity).split(".")[-1]
            if severity in by_severity:
                by_severity[severity].append(v)

        # Display violations
        for severity in ["CRITICAL", "ERROR", "WARNING", "INFO"]:
            violations = by_severity[severity]
            if violations:
                emoji = {
                    "CRITICAL": "🔴",
                    "ERROR": "❌",
                    "WARNING": "⚠️",
                    "INFO": "ℹ️",
                }[severity]

                print(f"{emoji} {severity} ({len(violations)})")
                for v in violations:
                    print(f"   • {v.message}")
                    if v.file_path:
                        print(f"     File: {v.file_path}:{v.line_number}")
                    if v.impact:
                        print(f"     Impact: {v.impact}")
                    if v.suggestion:
                        print(f"     💡 Fix: {v.suggestion}")
                print()

        # Exit with failure if critical
        critical = [v for v in report.violations
                    if v.severity == ViolationSeverity.CRITICAL]
        if critical:
            print(f"❌ Validation failed: {len(critical)} critical violations")
            return 1
    else:
        print("✅ All validation checks passed!")

    return 0


if __name__ == "__main__":
    exit(main())
