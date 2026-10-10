"""Tests for signature violation integration in MigrationAccompanimentChecker."""

from confiture.core.function_signature_checker import FunctionSignatureViolation
from confiture.models.git import MigrationAccompanimentReport


def _build_report(
    has_ddl: bool = False,
    has_migrations: bool = True,
    signature_violations: list | None = None,
) -> MigrationAccompanimentReport:
    return MigrationAccompanimentReport(
        has_ddl_changes=has_ddl,
        has_new_migrations=has_migrations,
        signature_violations=signature_violations or [],
    )


class TestMigrationAccompanimentReportSignatureFields:
    def test_has_signature_violations_false_when_empty(self):
        report = _build_report()
        assert not report.has_signature_violations

    def test_has_signature_violations_true_when_present(self):
        v = FunctionSignatureViolation(
            function_key="public.f",
            old_signature="public.f(integer)",
            new_signature="public.f(bigint)",
            migration_file=None,
            message="missing DROP",
        )
        report = _build_report(signature_violations=[v])
        assert report.has_signature_violations

    def test_is_valid_false_when_signature_violation(self):
        v = FunctionSignatureViolation(
            function_key="public.f",
            old_signature="public.f(integer)",
            new_signature="public.f(bigint)",
            migration_file=None,
            message="missing DROP",
        )
        report = _build_report(has_ddl=True, has_migrations=True, signature_violations=[v])
        assert not report.is_valid

    def test_is_valid_true_no_violations_no_ddl(self):
        report = _build_report(has_ddl=False)
        assert report.is_valid

    def test_is_valid_true_ddl_with_migrations_no_violations(self):
        report = _build_report(has_ddl=True, has_migrations=True)
        assert report.is_valid

    def test_to_dict_includes_signature_violations(self):
        v = FunctionSignatureViolation(
            function_key="public.f",
            old_signature="public.f(integer)",
            new_signature="public.f(bigint)",
            migration_file=None,
            message="missing DROP",
        )
        report = _build_report(signature_violations=[v])
        d = report.to_dict()
        assert "signature_violations" in d
        assert len(d["signature_violations"]) == 1
        assert d["signature_violations"][0]["function_key"] == "public.f"

    def test_to_dict_violations_empty_list_when_none(self):
        report = _build_report()
        d = report.to_dict()
        assert d["signature_violations"] == []
