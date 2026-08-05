"""The lint rule registry and its `--select` / `--ignore` resolution (#150).

#150 asked for a ruff-style selection surface instead of one flag per rule. Its
own trigger — "a second opt-in `confiture lint` rule family" — had already fired
twice unnoticed (`tenant_001`, then `sec_002` in 0.28.0), which is why the
command carries three inconsistent per-rule flags today.

The registry is the backing store for all of it: `--list-rules` enumerates it,
selection resolves against it, and the legacy flags become aliases over it. It
lists only rules that can actually produce a violation — `check_indexes` and
`check_constraints` are LintConfig fields with no implementation behind them, so
advertising them here would be the same dishonesty in a new place.
"""

from __future__ import annotations

import pytest

from confiture.core.linting.rule_registry import (
    DEFAULT_SELECTOR,
    LINT_RULES,
    families,
    resolve_selection,
)
from confiture.exceptions import ConfigurationError


class TestRegistryContents:
    def test_every_rule_confiture_lint_can_emit_is_listed(self) -> None:
        codes = {rule.code for rule in LINT_RULES}
        assert codes == {
            "naming_001",
            "naming_002",
            "pk_001",
            "doc_001",
            "sec_001",
            "acl_001",
            "tenant_001",
            "replica_001",
            "sec_002",
        }

    def test_the_default_set_is_the_pre_0420_default_behaviour(self) -> None:
        default_on = {rule.code for rule in LINT_RULES if rule.default_on}
        assert default_on == {"naming_001", "naming_002", "pk_001", "doc_001", "sec_001"}

    def test_each_legacy_flag_maps_to_exactly_one_family(self) -> None:
        by_flag = {rule.legacy_flag: rule.family for rule in LINT_RULES if rule.legacy_flag}
        assert by_flag == {
            "--check-tenant-isolation": "tenant",
            "--replica-safe": "replica",
            "--check-security-definer": "security-definer",
        }

    def test_sec_001_and_sec_002_are_separate_families(self) -> None:
        """Shared code prefix, different rules: the flag named one, not the other."""
        by_code = {rule.code: rule.family for rule in LINT_RULES}
        assert by_code["sec_001"] == "security"
        assert by_code["sec_002"] == "security-definer"

    def test_families_are_reported_in_registry_order(self) -> None:
        assert families() == (
            "naming",
            "pk",
            "doc",
            "security",
            "acl",
            "tenant",
            "replica",
            "security-definer",
        )


class TestSelection:
    def test_no_selection_is_the_default_set(self) -> None:
        assert resolve_selection(None, ()) == frozenset(
            {"naming_001", "naming_002", "pk_001", "doc_001", "sec_001"}
        )

    def test_a_family_selects_its_rules_and_nothing_else(self) -> None:
        assert resolve_selection(["naming"], ()) == frozenset({"naming_001", "naming_002"})

    def test_a_code_selects_exactly_that_rule(self) -> None:
        assert resolve_selection(["naming_001"], ()) == frozenset({"naming_001"})

    def test_the_default_selector_composes_with_a_family(self) -> None:
        """This is what the legacy flags mean: the defaults *plus* one family."""
        assert resolve_selection([DEFAULT_SELECTOR, "replica"], ()) == frozenset(
            {"naming_001", "naming_002", "pk_001", "doc_001", "sec_001", "replica_001"}
        )

    def test_comma_separated_values_are_split(self) -> None:
        assert resolve_selection(["naming,pk"], ()) == frozenset(
            {"naming_001", "naming_002", "pk_001"}
        )

    def test_ignore_wins_over_select(self) -> None:
        assert resolve_selection(["naming"], ["naming_001"]) == frozenset({"naming_002"})

    def test_ignore_accepts_a_family(self) -> None:
        assert resolve_selection([DEFAULT_SELECTOR], ["naming"]) == frozenset(
            {"pk_001", "doc_001", "sec_001"}
        )

    def test_ignoring_everything_selects_nothing(self) -> None:
        assert resolve_selection([DEFAULT_SELECTOR], [DEFAULT_SELECTOR]) == frozenset()

    def test_selection_is_case_insensitive(self) -> None:
        assert resolve_selection(["NAMING"], ()) == frozenset({"naming_001", "naming_002"})


class TestUnknownSelectors:
    """Silently selecting nothing is the failure mode this replaces."""

    def test_unknown_select_value_raises_naming_the_valid_set(self) -> None:
        with pytest.raises(ConfigurationError) as exc:
            resolve_selection(["nameing"], ())
        assert "nameing" in str(exc.value)
        # The valid set travels in the resolution hint, which is what the CLI
        # renders to the user and what the JSON error envelope carries.
        assert "naming" in (exc.value.resolution_hint or "")

    def test_unknown_ignore_value_raises_too(self) -> None:
        with pytest.raises(ConfigurationError) as exc:
            resolve_selection(None, ["replika"])
        assert "replika" in str(exc.value)

    def test_the_error_carries_the_usage_error_code(self) -> None:
        """Exit 5 (CONFIG_*), not exit 2 — 2 is PRECON_1001, "no tracking table"."""
        with pytest.raises(ConfigurationError) as exc:
            resolve_selection(["nope"], ())
        assert exc.value.error_code.startswith("CONFIG")
