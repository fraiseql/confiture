"""Report generation for dry-run analysis results."""

import logging
from typing import Any

from confiture.core.migration.dry_run.dry_run_mode import DryRunReport
from confiture.core.migration.dry_run.models import StatementClassification

logger = logging.getLogger(__name__)


class DryRunReportGenerator:
    """Generate formatted reports from dry-run analysis."""

    def __init__(self, use_colors: bool = True, verbose: bool = False):
        """Initialize report generator.

        Args:
            use_colors: Whether to use ANSI color codes
            verbose: Whether to include detailed information
        """
        self.use_colors = use_colors
        self.verbose = verbose

    def generate_text_report(self, report: DryRunReport) -> str:
        """Generate plain text report.

        Args:
            report: DryRunReport to format

        Returns:
            Formatted text report
        """
        lines = []

        # Header
        lines.append("=" * 80)
        lines.append("DRY-RUN MIGRATION ANALYSIS REPORT")
        lines.append("=" * 80)
        lines.append("")

        # Summary
        lines.extend(self._format_summary(report))
        lines.append("")

        # Warnings
        if report.warnings:
            lines.extend(self._format_warnings(report))
            lines.append("")

        # Statements
        if self.verbose:
            lines.extend(self._format_statements(report))
            lines.append("")

        # Footer
        lines.extend(self._format_footer(report))

        return "\n".join(lines)

    def generate_json_report(self, report: DryRunReport) -> dict[str, Any]:
        """Generate JSON-serializable report.

        Args:
            report: DryRunReport to convert

        Returns:
            Dictionary with report data
        """
        return {
            "migration_id": report.migration_id,
            "started_at": report.started_at.isoformat() if report.started_at else None,
            "completed_at": (
                report.completed_at.isoformat() if report.completed_at else None
            ),
            "total_execution_time_ms": report.total_execution_time_ms,
            "statements_analyzed": report.statements_analyzed,
            "summary": {
                "unsafe_count": report.unsafe_count,
                "total_estimated_time_ms": report.total_estimated_time_ms,
                "total_estimated_disk_mb": report.total_estimated_disk_mb,
                "has_unsafe_statements": report.has_unsafe_statements,
            },
            "warnings": report.warnings,
            "analyses": [
                {
                    "statement": a.statement,
                    "classification": a.classification.value,
                    "execution_time_ms": a.execution_time_ms,
                    "success": a.success,
                    "error_message": a.error_message,
                    "impact": (
                        {
                            "affected_tables": a.impact.affected_tables,
                            "estimated_size_change_mb": a.impact.estimated_size_change_mb,
                        }
                        if a.impact
                        else None
                    ),
                    "concurrency": (
                        {
                            "risk_level": a.concurrency.risk_level,
                            "tables_locked": a.concurrency.tables_locked,
                            "lock_duration_estimate_ms": a.concurrency.lock_duration_estimate_ms,
                        }
                        if a.concurrency
                        else None
                    ),
                    "cost": (
                        {
                            "estimated_duration_ms": a.cost.estimated_duration_ms,
                            "estimated_disk_usage_mb": a.cost.estimated_disk_usage_mb,
                            "estimated_cpu_percent": a.cost.estimated_cpu_percent,
                            "is_expensive": a.cost.is_expensive,
                        }
                        if a.cost
                        else None
                    ),
                }
                for a in report.analyses
            ],
        }

    def _format_summary(self, report: DryRunReport) -> list[str]:
        """Format report summary section.

        Args:
            report: DryRunReport to summarize

        Returns:
            List of formatted lines
        """
        lines = []

        lines.append("SUMMARY")
        lines.append("-" * 80)
        lines.append(f"Statements analyzed: {report.statements_analyzed}")
        lines.append(f"Analysis duration: {report.total_execution_time_ms:.0f}ms")
        lines.append("")

        # Safety summary
        lines.append("Safety Analysis:")
        lines.append(
            f"  Unsafe statements: {report.unsafe_count} "
            f"{'⚠️  REQUIRES ATTENTION' if report.unsafe_count > 0 else '✓ None'}"
        )
        lines.append("")

        # Cost summary
        lines.append("Cost Estimates:")
        lines.append(f"  Total time: {report.total_estimated_time_ms}ms")
        lines.append(f"  Total disk: {report.total_estimated_disk_mb:.1f}MB")
        lines.append("")

        # Risk summary
        high_risk = sum(
            1
            for a in report.analyses
            if a.concurrency and a.concurrency.risk_level == "high"
        )
        medium_risk = sum(
            1
            for a in report.analyses
            if a.concurrency and a.concurrency.risk_level == "medium"
        )

        if high_risk > 0 or medium_risk > 0:
            lines.append("Concurrency Risk:")
            if high_risk > 0:
                lines.append(f"  High risk: {high_risk} statement(s) ⚠️")
            if medium_risk > 0:
                lines.append(f"  Medium risk: {medium_risk} statement(s) ⚠️")
            lines.append("")

        return lines

    def _format_warnings(self, report: DryRunReport) -> list[str]:
        """Format warnings section.

        Args:
            report: DryRunReport with warnings

        Returns:
            List of formatted lines
        """
        lines = []

        lines.append("WARNINGS")
        lines.append("-" * 80)

        for warning in report.warnings:
            lines.append(f"  {warning}")

        return lines

    def _format_statements(self, report: DryRunReport) -> list[str]:
        """Format detailed statements section.

        Args:
            report: DryRunReport with analyses

        Returns:
            List of formatted lines
        """
        lines = []

        lines.append("STATEMENT DETAILS")
        lines.append("-" * 80)

        for i, analysis in enumerate(report.analyses, 1):
            lines.append(f"\nStatement {i}:")
            lines.append(f"  SQL: {analysis.statement[:70]}...")
            lines.append(
                f"  Classification: {analysis.classification.value.upper()} "
                f"{self._get_classification_icon(analysis.classification)}"
            )

            if analysis.impact:
                lines.append(f"  Impact tables: {', '.join(analysis.impact.affected_tables)}")
                if analysis.impact.constraint_violations:
                    lines.append(
                        f"    Constraint risks: {len(analysis.impact.constraint_violations)}"
                    )

            if analysis.concurrency:
                lines.append(f"  Concurrency risk: {analysis.concurrency.risk_level.upper()}")
                if analysis.concurrency.tables_locked:
                    lines.append(
                        f"    Tables locked: {', '.join(analysis.concurrency.tables_locked)}"
                    )

            if analysis.cost:
                lines.append(f"  Estimated time: {analysis.cost.estimated_duration_ms}ms")
                lines.append(
                    f"  Estimated disk: {analysis.cost.estimated_disk_usage_mb:.1f}MB"
                )
                lines.append(f"  Estimated CPU: {analysis.cost.estimated_cpu_percent:.0f}%")

        return lines

    def _format_footer(self, report: DryRunReport) -> list[str]:
        """Format report footer with recommendations.

        Args:
            report: DryRunReport to conclude

        Returns:
            List of formatted lines
        """
        lines = []

        lines.append("RECOMMENDATIONS")
        lines.append("-" * 80)

        if report.unsafe_count > 0:
            lines.append("⚠️  UNSAFE OPERATIONS DETECTED")
            lines.append(
                "  Review and confirm all unsafe statements before proceeding."
            )
            lines.append("  Consider running during maintenance window.")
            lines.append("")

        high_risk = sum(
            1
            for a in report.analyses
            if a.concurrency and a.concurrency.risk_level == "high"
        )

        if high_risk > 0:
            lines.append("⚠️  HIGH CONCURRENCY RISK DETECTED")
            lines.append(
                "  These operations may block other queries."
            )
            lines.append("  Consider running during low-traffic periods.")
            lines.append("")

        expensive = sum(
            1 for a in report.analyses if a.cost and a.cost.is_expensive
        )

        if expensive > 0:
            lines.append("⏱️  EXPENSIVE OPERATIONS DETECTED")
            lines.append(
                f"  {expensive} statement(s) may require significant resources."
            )
            lines.append("  Monitor system resources during execution.")
            lines.append("")

        if not (report.unsafe_count > 0 or high_risk > 0 or expensive > 0):
            lines.append("✓ All checks passed!")
            lines.append("  This migration appears safe to execute.")

        lines.append("")
        lines.append("=" * 80)

        return lines

    @staticmethod
    def _get_classification_icon(classification: StatementClassification) -> str:
        """Get icon for statement classification.

        Args:
            classification: StatementClassification

        Returns:
            Icon string
        """
        icons = {
            StatementClassification.SAFE: "✓",
            StatementClassification.WARNING: "⚠️",
            StatementClassification.UNSAFE: "❌",
        }
        return icons.get(classification, "?")

    def generate_summary_line(self, report: DryRunReport) -> str:
        """Generate single-line summary for quick viewing.

        Args:
            report: DryRunReport to summarize

        Returns:
            Single line summary
        """
        status = "✓ SAFE" if not report.has_unsafe_statements else "⚠️  UNSAFE"
        time_str = f"{report.total_estimated_time_ms}ms"
        disk_str = f"{report.total_estimated_disk_mb:.1f}MB"

        return (
            f"[{status}] {report.statements_analyzed} statements | "
            f"Time: {time_str} | Disk: {disk_str}"
        )
