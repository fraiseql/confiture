"""Unit tests for FunctionSignatureDriftDetector and related models."""


from confiture.core.function_signature_drift import (
    FunctionSignatureDriftDetector,
    StaleOverload,
)
from confiture.core.function_signature_parser import FunctionSignature


def _sig(name: str, types: tuple[str, ...], schema: str = "public") -> FunctionSignature:
    return FunctionSignature(schema=schema, name=name, param_types=types)


class TestFunctionSignatureDriftDetectorNoDrift:
    def test_no_drift_when_identical(self):
        source = [_sig("f", ("integer",))]
        live = [_sig("f", ("integer",))]
        report = FunctionSignatureDriftDetector().compare(source, live)
        assert not report.has_drift
        assert report.stale_overloads == []

    def test_unknown_live_function_not_flagged(self):
        # live has a function not in source → not flagged (extension, built-in, etc.)
        source: list[FunctionSignature] = []
        live = [_sig("pg_extension_func", ("text",))]
        report = FunctionSignatureDriftDetector().compare(source, live)
        assert not report.has_drift

    def test_missing_from_db_is_informational_not_failure(self):
        source = [_sig("new_func", ("text",))]
        live: list[FunctionSignature] = []
        report = FunctionSignatureDriftDetector().compare(source, live)
        assert not report.has_drift
        assert len(report.missing_from_db) == 1
        assert report.missing_from_db[0] == "public.new_func(text)"

    def test_no_drift_multiple_functions_all_match(self):
        source = [_sig("foo", ("integer",)), _sig("bar", ("text",))]
        live = [_sig("foo", ("integer",)), _sig("bar", ("text",))]
        report = FunctionSignatureDriftDetector().compare(source, live)
        assert not report.has_drift


class TestFunctionSignatureDriftDetectorStaleOverloads:
    def test_detects_stale_overload(self):
        source = [_sig("get_user", ("bigint",))]
        live = [
            _sig("get_user", ("bigint",)),   # current
            _sig("get_user", ("integer",)),  # stale
        ]
        report = FunctionSignatureDriftDetector().compare(source, live)
        assert report.has_drift
        assert len(report.stale_overloads) == 1
        assert report.stale_overloads[0].stale_signature == "public.get_user(integer)"

    def test_drop_sql_is_correct(self):
        source = [_sig("get_user", ("bigint",))]
        live = [_sig("get_user", ("bigint",)), _sig("get_user", ("integer",))]
        report = FunctionSignatureDriftDetector().compare(source, live)
        overload = report.stale_overloads[0]
        assert overload.drop_sql == "DROP FUNCTION public.get_user(integer);"

    def test_source_signatures_listed(self):
        source = [_sig("get_user", ("bigint",))]
        live = [_sig("get_user", ("bigint",)), _sig("get_user", ("integer",))]
        report = FunctionSignatureDriftDetector().compare(source, live)
        assert "public.get_user(bigint)" in report.stale_overloads[0].source_signatures

    def test_multiple_stale_overloads_same_function(self):
        # function changed twice without cleanup → two stale sigs in DB
        source = [_sig("f", ("text",))]
        live = [
            _sig("f", ("text",)),
            _sig("f", ("integer",)),
            _sig("f", ("bigint",)),
        ]
        report = FunctionSignatureDriftDetector().compare(source, live)
        assert report.has_drift
        assert len(report.stale_overloads) == 2

    def test_stale_overload_in_non_public_schema(self):
        source = [_sig("f", ("bigint",), schema="auth")]
        live = [_sig("f", ("bigint",), schema="auth"), _sig("f", ("integer",), schema="auth")]
        report = FunctionSignatureDriftDetector().compare(source, live)
        assert report.has_drift
        assert report.stale_overloads[0].schema == "auth"


class TestFunctionSignatureDriftReportToDict:
    def test_to_dict_no_drift(self):
        source = [_sig("f", ("integer",))]
        live = [_sig("f", ("integer",))]
        report = FunctionSignatureDriftDetector().compare(source, live)
        d = report.to_dict()
        assert d["has_drift"] is False
        assert d["stale_overloads"] == []
        assert d["missing_from_db"] == []

    def test_to_dict_with_stale(self):
        source = [_sig("get_user", ("bigint",))]
        live = [_sig("get_user", ("bigint",)), _sig("get_user", ("integer",))]
        report = FunctionSignatureDriftDetector().compare(source, live)
        d = report.to_dict()
        assert d["has_drift"] is True
        assert len(d["stale_overloads"]) == 1
        stale = d["stale_overloads"][0]
        assert stale["stale_signature"] == "public.get_user(integer)"
        assert "drop_sql" in stale

    def test_has_critical_drift_alias(self):
        source = [_sig("f", ("bigint",))]
        live = [_sig("f", ("bigint",)), _sig("f", ("integer",))]
        report = FunctionSignatureDriftDetector().compare(source, live)
        assert report.has_critical_drift == report.has_drift

    def test_detection_time_ms_present(self):
        report = FunctionSignatureDriftDetector().compare([], [])
        assert isinstance(report.detection_time_ms, float)
        assert report.detection_time_ms >= 0


class TestStaleOverload:
    def test_to_dict_shape(self):
        overload = StaleOverload(
            schema="public",
            name="f",
            stale_signature="public.f(integer)",
            source_signatures=["public.f(bigint)"],
        )
        d = overload.to_dict()
        assert d["schema"] == "public"
        assert d["name"] == "f"
        assert d["stale_signature"] == "public.f(integer)"
        assert d["drop_sql"] == "DROP FUNCTION public.f(integer);"
