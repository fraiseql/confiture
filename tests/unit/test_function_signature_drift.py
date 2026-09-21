"""Unit tests for FunctionSignatureDriftDetector and related models."""

import dataclasses

from confiture.core.function_signature_drift import (
    FunctionSignatureDriftDetector,
    StaleOverload,
)
from confiture.core.schema_model import Routine
from tests._helpers import routine


def _sig(name: str, types: tuple[str, ...], schema: str = "public") -> Routine:
    return routine(name, *types, schema=schema)


class TestFunctionSignatureDriftDetectorNoDrift:
    def test_no_drift_when_identical(self):
        source = [_sig("f", ("integer",))]
        live = [_sig("f", ("integer",))]
        report = FunctionSignatureDriftDetector().compare(source, live)
        assert not report.has_drift
        assert report.stale_overloads == []

    def test_unknown_live_function_not_flagged(self):
        # live has a function not in source → not flagged (extension, built-in, etc.)
        source: list[Routine] = []
        live = [_sig("pg_extension_func", ("text",))]
        report = FunctionSignatureDriftDetector().compare(source, live)
        assert not report.has_drift

    def test_missing_from_db_is_informational_not_failure(self):
        source = [_sig("new_func", ("text",))]
        live: list[Routine] = []
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
            _sig("get_user", ("bigint",)),  # current
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


class TestFunctionSignatureDriftArraySafety:
    """Issue #176: array-typed functions must not produce false stale overloads
    (and never a destructive DROP) when they are present identically in source
    and live."""

    def test_array_signature_not_reported_stale(self):
        # Same array signature in both source and live → no drift, no DROP.
        types = ("text", "text", "uuid", "text", "jsonb", "text[]", "jsonb", "jsonb")
        source = [_sig("build_mutation_response", types, schema="core")]
        live = [_sig("build_mutation_response", types, schema="core")]
        report = FunctionSignatureDriftDetector().compare(source, live)
        assert not report.has_drift
        assert report.stale_overloads == []
        assert report.to_dict()["remediation_sql"] == []

    def test_an_array_overload_the_source_does_not_declare_is_stale(self):
        """The #176 safety net is gone with the gap it covered.

        It suppressed a live overload that differed from a declared one only by
        ``[]``, because the source side could lose the suffix. Both sides now key
        an argument through one canonicaliser, which keeps it; ``f(text[])``
        beside a declared ``f(text)`` is a second overload, and is reported.
        """
        source = [_sig("f", ("text",), schema="core")]
        live = [
            _sig("f", ("text",), schema="core"),
            _sig("f", ("text[]",), schema="core"),
        ]
        report = FunctionSignatureDriftDetector().compare(source, live)
        assert [o.stale_signature for o in report.stale_overloads] == ["core.f(text[])"]

    def test_an_array_argument_keeps_its_suffix_on_both_sides(self):
        source = [_sig("f", ("int[]", "varchar[]"), schema="core")]
        live = [_sig("f", ("integer[]", "character varying[]"), schema="core")]
        report = FunctionSignatureDriftDetector().compare(source, live)
        assert report.stale_overloads == []
        assert report.missing_from_db == []

    def test_genuine_scalar_overload_still_flagged(self):
        # Change C must not suppress genuine drift: different base type → still stale.
        source = [_sig("g", ("bigint",))]
        live = [_sig("g", ("bigint",)), _sig("g", ("integer",))]
        report = FunctionSignatureDriftDetector().compare(source, live)
        assert report.has_drift
        assert report.stale_overloads[0].stale_signature == "public.g(integer)"


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

    def test_a_stale_procedure_is_dropped_as_a_procedure(self):
        """``DROP FUNCTION`` on a procedure is an error: "… is not a function"."""
        stale = dataclasses.replace(routine("touch", "integer"), kind="procedure")
        source = [dataclasses.replace(routine("touch", "bigint"), kind="procedure")]

        (overload,) = FunctionSignatureDriftDetector().compare(source, [stale]).stale_overloads

        assert overload.drop_sql == "DROP PROCEDURE public.touch(integer);"


class TestTriggerFunctionsOnTheLiveSide:
    """What widening the live side to trigger functions can and cannot suggest.

    The live side asks for them (#303), because the declared side has
    no such filter and a comparison whose sides hold different kinds of thing is
    not a comparison. `stale_overloads` drives `remediation_sql`, which is
    **destructive**, so what the widening makes newly reportable is pinned here
    rather than discovered in a deploy.
    """

    def test_a_trigger_function_the_source_declares_is_not_stale(self):
        source = [_sig("fn_touch", (), schema="core")]
        live = [_sig("fn_touch", (), schema="core")]
        report = FunctionSignatureDriftDetector().compare(source, live)
        assert report.stale_overloads == []
        assert report.missing_from_db == []

    def test_a_trigger_function_no_source_function_of_that_name_matches_is_left_alone(self):
        """The existing rule, and the one that keeps this safe: an overload is only
        stale when source defines *some* signature for that name."""
        live = [_sig("fn_only_live", (), schema="core")]
        report = FunctionSignatureDriftDetector().compare([], live)
        assert report.stale_overloads == []

    def test_a_live_trigger_overload_of_a_declared_name_is_newly_stale(self):
        """A behaviour change, stated: the source declares `fn_touch(integer)` and
        the database also has a zero-argument `fn_touch()` returning trigger. That
        really is an overload source does not declare, and it was invisible before
        the live side included trigger functions."""
        source = [_sig("fn_touch", ("integer",), schema="core")]
        live = [
            _sig("fn_touch", ("integer",), schema="core"),
            _sig("fn_touch", (), schema="core"),
        ]
        report = FunctionSignatureDriftDetector().compare(source, live)
        assert [o.stale_signature for o in report.stale_overloads] == ["core.fn_touch()"]
