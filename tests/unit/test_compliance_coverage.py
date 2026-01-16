"""Comprehensive tests for compliance automation and reporting.

Tests the ComplianceReportGenerator and related classes for tracking
compliance with multiple data protection regulations.
"""

import pytest
import json
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch
from uuid import uuid4

from confiture.core.anonymization.compliance import (
    Regulation,
    ComplianceRequirement,
    ComplianceReport,
)
from confiture.core.anonymization.security.lineage import DataLineageEntry


class TestRegulation:
    """Test Regulation enum."""

    def test_regulation_gdpr(self):
        """Test GDPR regulation."""
        assert Regulation.GDPR.value == "gdpr"

    def test_regulation_ccpa(self):
        """Test CCPA regulation."""
        assert Regulation.CCPA.value == "ccpa"

    def test_regulation_pipeda(self):
        """Test PIPEDA regulation."""
        assert Regulation.PIPEDA.value == "pipeda"

    def test_regulation_lgpd(self):
        """Test LGPD regulation."""
        assert Regulation.LGPD.value == "lgpd"

    def test_regulation_pipl(self):
        """Test PIPL regulation."""
        assert Regulation.PIPL.value == "pipl"

    def test_regulation_privacy_act(self):
        """Test Privacy Act regulation."""
        assert Regulation.PRIVACY_ACT.value == "privacy_act"

    def test_regulation_popia(self):
        """Test POPIA regulation."""
        assert Regulation.POPIA.value == "popia"

    def test_all_regulations(self):
        """Test all regulations are defined."""
        regulations = list(Regulation)
        assert len(regulations) == 7

    def test_regulation_values_unique(self):
        """Test all regulation values are unique."""
        values = [r.value for r in Regulation]
        assert len(values) == len(set(values))


class TestComplianceRequirement:
    """Test ComplianceRequirement dataclass."""

    def test_create_requirement_minimal(self):
        """Test creating requirement with minimal fields."""
        req = ComplianceRequirement(
            regulation=Regulation.GDPR,
            requirement_id="GDPR-32",
            description="Security of processing",
            article="Article 32",
            requirement="Implement appropriate technical and organizational measures",
        )

        assert req.regulation == Regulation.GDPR
        assert req.requirement_id == "GDPR-32"
        assert req.description == "Security of processing"
        assert req.article == "Article 32"
        assert req.is_met is False

    def test_create_requirement_with_evidence(self):
        """Test creating requirement with evidence."""
        req = ComplianceRequirement(
            regulation=Regulation.GDPR,
            requirement_id="GDPR-32",
            description="Security of processing",
            article="Article 32",
            requirement="Implement encryption",
            is_met=True,
            evidence="Encryption enabled: AES-256-CBC",
        )

        assert req.is_met is True
        assert req.evidence == "Encryption enabled: AES-256-CBC"

    def test_create_requirement_with_remediation(self):
        """Test creating requirement with remediation."""
        remediation = "Enable encryption for all data at rest and in transit"
        req = ComplianceRequirement(
            regulation=Regulation.CCPA,
            requirement_id="CCPA-1798.100",
            description="Right to know",
            article="Section 1798.100",
            requirement="Disclose data collected",
            is_met=False,
            remediation=remediation,
        )

        assert req.is_met is False
        assert req.remediation == remediation

    def test_requirement_different_regulations(self):
        """Test requirements for different regulations."""
        for regulation in Regulation:
            req = ComplianceRequirement(
                regulation=regulation,
                requirement_id=f"{regulation.value.upper()}-1",
                description="Test requirement",
                article="Article 1",
                requirement="Test",
            )
            assert req.regulation == regulation

    def test_requirement_met_status(self):
        """Test requirement met/not met status."""
        req_not_met = ComplianceRequirement(
            regulation=Regulation.GDPR,
            requirement_id="GDPR-1",
            description="Test",
            article="Article 1",
            requirement="Test",
            is_met=False,
        )

        req_met = ComplianceRequirement(
            regulation=Regulation.GDPR,
            requirement_id="GDPR-2",
            description="Test",
            article="Article 2",
            requirement="Test",
            is_met=True,
        )

        assert not req_not_met.is_met
        assert req_met.is_met


class TestComplianceReport:
    """Test ComplianceReport dataclass."""

    def test_create_report_minimal(self):
        """Test creating report with minimal fields."""
        now = datetime.now()
        report = ComplianceReport(generated_at=now)

        assert report.generated_at == now
        assert report.regulations == []
        assert report.requirements == {}
        assert report.recommendations == []
        assert report.audit_trail == []

    def test_create_report_with_time_period(self):
        """Test creating report with time period."""
        now = datetime.now()
        report = ComplianceReport(
            generated_at=now,
            time_period_start="2024-01-01",
            time_period_end="2024-12-31",
        )

        assert report.time_period_start == "2024-01-01"
        assert report.time_period_end == "2024-12-31"

    def test_create_report_with_regulations(self):
        """Test creating report with multiple regulations."""
        now = datetime.now()
        regulations = [Regulation.GDPR, Regulation.CCPA, Regulation.LGPD]
        report = ComplianceReport(
            generated_at=now,
            regulations=regulations,
        )

        assert report.regulations == regulations

    def test_create_report_with_requirements(self):
        """Test creating report with requirements."""
        now = datetime.now()
        req1 = ComplianceRequirement(
            regulation=Regulation.GDPR,
            requirement_id="GDPR-32",
            description="Security",
            article="Article 32",
            requirement="Implement measures",
            is_met=True,
        )
        req2 = ComplianceRequirement(
            regulation=Regulation.GDPR,
            requirement_id="GDPR-33",
            description="Breach notification",
            article="Article 33",
            requirement="Notify supervisory authority",
            is_met=False,
        )

        requirements = {
            Regulation.GDPR: [req1, req2],
        }

        report = ComplianceReport(
            generated_at=now,
            requirements=requirements,
        )

        assert report.requirements == requirements

    def test_coverage_percentage_no_requirements(self):
        """Test coverage percentage with no requirements."""
        report = ComplianceReport(generated_at=datetime.now())
        coverage = report.coverage_percentage(Regulation.GDPR)
        assert coverage == 0.0

    def test_coverage_percentage_all_met(self):
        """Test coverage percentage when all requirements met."""
        now = datetime.now()
        reqs = [
            ComplianceRequirement(
                regulation=Regulation.GDPR,
                requirement_id=f"GDPR-{i}",
                description=f"Requirement {i}",
                article=f"Article {i}",
                requirement=f"Requirement {i}",
                is_met=True,
            )
            for i in range(5)
        ]

        report = ComplianceReport(
            generated_at=now,
            requirements={Regulation.GDPR: reqs},
        )

        coverage = report.coverage_percentage(Regulation.GDPR)
        assert coverage == 100.0

    def test_coverage_percentage_partial(self):
        """Test coverage percentage with partial compliance."""
        now = datetime.now()
        reqs = [
            ComplianceRequirement(
                regulation=Regulation.GDPR,
                requirement_id=f"GDPR-{i}",
                description=f"Requirement {i}",
                article=f"Article {i}",
                requirement=f"Requirement {i}",
                is_met=(i < 3),  # First 3 are met, last 2 are not
            )
            for i in range(5)
        ]

        report = ComplianceReport(
            generated_at=now,
            requirements={Regulation.GDPR: reqs},
        )

        coverage = report.coverage_percentage(Regulation.GDPR)
        assert coverage == 60.0  # 3 out of 5

    def test_coverage_percentage_none_met(self):
        """Test coverage percentage when no requirements met."""
        now = datetime.now()
        reqs = [
            ComplianceRequirement(
                regulation=Regulation.CCPA,
                requirement_id=f"CCPA-{i}",
                description=f"Requirement {i}",
                article=f"Section {i}",
                requirement=f"Requirement {i}",
                is_met=False,
            )
            for i in range(5)
        ]

        report = ComplianceReport(
            generated_at=now,
            requirements={Regulation.CCPA: reqs},
        )

        coverage = report.coverage_percentage(Regulation.CCPA)
        assert coverage == 0.0

    def test_total_coverage_percentage_single_regulation(self):
        """Test total coverage with single regulation."""
        now = datetime.now()
        reqs = [
            ComplianceRequirement(
                regulation=Regulation.GDPR,
                requirement_id=f"GDPR-{i}",
                description=f"Requirement {i}",
                article=f"Article {i}",
                requirement=f"Requirement {i}",
                is_met=(i < 4),  # 4 out of 5 met
            )
            for i in range(5)
        ]

        report = ComplianceReport(
            generated_at=now,
            requirements={Regulation.GDPR: reqs},
        )

        total = report.total_coverage_percentage()
        assert total == 80.0

    def test_total_coverage_percentage_multiple_regulations(self):
        """Test total coverage with multiple regulations."""
        now = datetime.now()

        gdpr_reqs = [
            ComplianceRequirement(
                regulation=Regulation.GDPR,
                requirement_id=f"GDPR-{i}",
                description=f"Requirement {i}",
                article=f"Article {i}",
                requirement=f"Requirement {i}",
                is_met=True,
            )
            for i in range(3)
        ]

        ccpa_reqs = [
            ComplianceRequirement(
                regulation=Regulation.CCPA,
                requirement_id=f"CCPA-{i}",
                description=f"Requirement {i}",
                article=f"Section {i}",
                requirement=f"Requirement {i}",
                is_met=(i < 2),  # 2 out of 3 met
            )
            for i in range(3)
        ]

        report = ComplianceReport(
            generated_at=now,
            requirements={
                Regulation.GDPR: gdpr_reqs,
                Regulation.CCPA: ccpa_reqs,
            },
        )

        # (3 + 2) / (3 + 3) = 5/6 = 83.33%
        total = report.total_coverage_percentage()
        assert abs(total - 83.33) < 0.01

    def test_total_coverage_percentage_empty(self):
        """Test total coverage with no requirements."""
        report = ComplianceReport(generated_at=datetime.now())
        total = report.total_coverage_percentage()
        assert total == 0.0

    def test_add_recommendations(self):
        """Test adding recommendations to report."""
        now = datetime.now()
        report = ComplianceReport(generated_at=now)

        recommendations = [
            "Enable encryption at rest",
            "Implement access controls",
            "Setup audit logging",
        ]

        for rec in recommendations:
            report.recommendations.append(rec)

        assert len(report.recommendations) == 3
        assert "Enable encryption at rest" in report.recommendations

    def test_add_audit_trail_entries(self):
        """Test adding audit trail entries."""
        now = datetime.now()
        report = ComplianceReport(generated_at=now)

        entry = {
            "timestamp": now.isoformat(),
            "action": "anonymize_column",
            "table": "users",
            "column": "email",
            "strategy": "email_mask",
            "rows_affected": 1000,
        }

        report.audit_trail.append(entry)

        assert len(report.audit_trail) == 1
        assert report.audit_trail[0]["action"] == "anonymize_column"

    def test_to_json_basic(self):
        """Test serializing report to JSON."""
        now = datetime.now()
        report = ComplianceReport(
            generated_at=now,
            time_period_start="2024-01-01",
            time_period_end="2024-12-31",
            recommendations=["Implement encryption"],
        )

        json_str = report.to_json()
        assert isinstance(json_str, str)

        # Verify it's valid JSON
        data = json.loads(json_str)
        assert data["generated_at"] == now.isoformat()
        assert data["time_period"]["start"] == "2024-01-01"

    def test_to_json_with_requirements(self):
        """Test serializing report with requirements to JSON."""
        now = datetime.now()

        req = ComplianceRequirement(
            regulation=Regulation.GDPR,
            requirement_id="GDPR-32",
            description="Security",
            article="Article 32",
            requirement="Implement measures",
            is_met=True,
            evidence="Encryption enabled",
        )

        report = ComplianceReport(
            generated_at=now,
            requirements={Regulation.GDPR: [req]},
        )

        json_str = report.to_json()
        data = json.loads(json_str)

        # Verify JSON was generated successfully
        assert data["generated_at"] == now.isoformat()
        assert len(json_str) > 0

    def test_to_json_roundtrip_basic(self):
        """Test JSON serialization and parsing."""
        now = datetime.now()
        original = ComplianceReport(
            generated_at=now,
            time_period_start="2024-01-01",
            time_period_end="2024-12-31",
        )

        json_str = original.to_json()
        data = json.loads(json_str)

        # Verify key fields
        assert data["generated_at"] == now.isoformat()
        assert data["time_period"]["start"] == "2024-01-01"
        assert data["time_period"]["end"] == "2024-12-31"

    def test_report_with_multiple_regulations_coverage(self):
        """Test coverage reporting for multiple regulations."""
        now = datetime.now()

        regulations_data = {}
        for regulation in [Regulation.GDPR, Regulation.CCPA, Regulation.LGPD]:
            reqs = [
                ComplianceRequirement(
                    regulation=regulation,
                    requirement_id=f"{regulation.value.upper()}-{i}",
                    description=f"Requirement {i}",
                    article=f"Article {i}",
                    requirement=f"Requirement {i}",
                    is_met=(i % 2 == 0),  # Alternate met/not met
                )
                for i in range(4)
            ]
            regulations_data[regulation] = reqs

        report = ComplianceReport(
            generated_at=now,
            regulations=list(regulations_data.keys()),
            requirements=regulations_data,
        )

        # Each regulation: 2 out of 4 met = 50%
        for regulation in regulations_data.keys():
            coverage = report.coverage_percentage(regulation)
            assert coverage == 50.0

    def test_report_coverage_calculations(self):
        """Test various coverage calculation scenarios."""
        now = datetime.now()

        test_cases = [
            ([], 0.0),  # No requirements
            ([True], 100.0),  # 1 met
            ([False], 0.0),  # 1 not met
            ([True, False], 50.0),  # 1 of 2 met
            ([True, True, True, False, False], 60.0),  # 3 of 5 met
            ([False] * 10, 0.0),  # None met
            ([True] * 10, 100.0),  # All met
        ]

        for i, (met_status, expected) in enumerate(test_cases):
            reqs = [
                ComplianceRequirement(
                    regulation=Regulation.GDPR,
                    requirement_id=f"GDPR-{j}",
                    description=f"Req {j}",
                    article=f"Article {j}",
                    requirement=f"Req {j}",
                    is_met=status,
                )
                for j, status in enumerate(met_status)
            ]

            report = ComplianceReport(
                generated_at=now,
                requirements={Regulation.GDPR: reqs},
            )

            coverage = report.coverage_percentage(Regulation.GDPR)
            assert abs(coverage - expected) < 0.01, f"Test case {i} failed"


class TestComplianceIntegration:
    """Integration tests for compliance reporting."""

    def test_full_compliance_workflow(self):
        """Test complete compliance workflow."""
        now = datetime.now()

        # Create requirements for GDPR
        gdpr_reqs = [
            ComplianceRequirement(
                regulation=Regulation.GDPR,
                requirement_id=f"GDPR-{i}",
                description=f"Requirement {i}",
                article=f"Article {i}",
                requirement=f"Requirement {i}",
                is_met=(i < 2),  # 2 out of 3 met
                evidence="Audit log entry" if i < 2 else None,
                remediation="Action needed" if i >= 2 else None,
            )
            for i in range(3)
        ]

        # Create report
        report = ComplianceReport(
            generated_at=now,
            time_period_start="2024-01-01",
            time_period_end="2024-12-31",
            regulations=[Regulation.GDPR],
            requirements={Regulation.GDPR: gdpr_reqs},
            recommendations=[
                "Implement missing security measures",
                "Review access controls",
            ],
        )

        # Verify coverage (2 out of 3 met = 66.67%)
        coverage = report.coverage_percentage(Regulation.GDPR)
        assert abs(coverage - 66.67) < 0.01
        assert len(report.recommendations) == 2

        # Serialize
        json_str = report.to_json()
        assert json_str is not None

    def test_multi_regulation_compliance_report(self):
        """Test compliance report across multiple regulations."""
        now = datetime.now()

        regulations_and_reqs = {}
        for regulation in Regulation:
            reqs = [
                ComplianceRequirement(
                    regulation=regulation,
                    requirement_id=f"{regulation.value.upper()}-{i}",
                    description=f"Requirement {i}",
                    article=f"Article {i}",
                    requirement=f"Requirement {i}",
                    is_met=True,
                )
                for i in range(3)
            ]
            regulations_and_reqs[regulation] = reqs

        report = ComplianceReport(
            generated_at=now,
            regulations=list(regulations_and_reqs.keys()),
            requirements=regulations_and_reqs,
        )

        # All regulations should show 100% compliance
        for regulation in regulations_and_reqs.keys():
            assert report.coverage_percentage(regulation) == 100.0

        # Total should also be 100%
        assert report.total_coverage_percentage() == 100.0

    def test_compliance_report_with_remediation_plan(self):
        """Test compliance report with remediation recommendations."""
        now = datetime.now()

        reqs = [
            ComplianceRequirement(
                regulation=Regulation.GDPR,
                requirement_id="GDPR-32",
                description="Security of processing",
                article="Article 32",
                requirement="Implement encryption",
                is_met=False,
                remediation="Deploy AES-256 encryption for data at rest and in transit",
            ),
            ComplianceRequirement(
                regulation=Regulation.GDPR,
                requirement_id="GDPR-33",
                description="Breach notification",
                article="Article 33",
                requirement="Notify supervisory authority",
                is_met=False,
                remediation="Setup automated breach notification system",
            ),
        ]

        report = ComplianceReport(
            generated_at=now,
            requirements={Regulation.GDPR: reqs},
            recommendations=[
                "Enable encryption for all data at rest",
                "Implement breach notification workflow",
                "Conduct security audit",
            ],
        )

        assert report.coverage_percentage(Regulation.GDPR) == 0.0
        assert len(report.recommendations) == 3

        # Verify remediation info is available
        for req in reqs:
            assert req.remediation is not None
