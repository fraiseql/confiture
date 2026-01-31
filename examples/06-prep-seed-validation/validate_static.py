#!/usr/bin/env python3
"""
Validate prep-seed pattern with static analysis (Levels 1-3).

No database required - perfect for pre-commit hooks.

Usage:
    python validate_static.py
"""

from pathlib import Path

from confiture.core.seed_validation.prep_seed.models import ViolationSeverity
from confiture.core.seed_validation.prep_seed.orchestrator import (
    OrchestrationConfig,
    PrepSeedOrchestrator,
)


def main() -> None:
    """Run static validation (Levels 1-3) without database."""
    # Configure orchestrator
    script_dir = Path(__file__).parent
    config = OrchestrationConfig(
        max_level=3,  # Levels 1-3 only (static analysis)
        seeds_dir=script_dir / "db" / "seeds" / "prep",
        schema_dir=script_dir / "db" / "schema",
        stop_on_critical=True,  # Stop on first critical violation
    )

    # Run validation
    print("🌱 Prep-Seed Validation (Static Analysis)")
    print("=" * 50)
    print(f"Max Level: {config.max_level}")
    print(f"Seeds Dir: {config.seeds_dir}")
    print(f"Schema Dir: {config.schema_dir}")
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
                        print(f"     {v.file_path}:{v.line_number}")
                    if v.suggestion:
                        print(f"     💡 {v.suggestion}")
                print()

        # Exit with failure if critical
        critical = [v for v in report.violations
                    if v.severity == ViolationSeverity.CRITICAL]
        if critical:
            print(f"❌ Validation failed: {len(critical)} critical violations")
            return 1
    else:
        print("✅ All static validation checks passed!")

    return 0


if __name__ == "__main__":
    exit(main())
