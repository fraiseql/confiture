"""An unknown anonymization strategy name is refused, not redacted (issue #285).

`sync --anonymization-config` took any string as a strategy. A name it did not
recognise fell through to `[REDACTED]` — the documented behaviour of `redact` —
so `strategy: emial`, one transposition from `email`, replaced a column with a
constant that no longer parses as an email address, is no longer unique across
rows and cannot be joined on. The sync reported success and exited 0.

`[REDACTED]` stays the runtime behaviour of `redact`. What changes is that the
name is checked where the rule is *built*, so the catch-all only ever covers a
strategy that got past a validated boundary — which is the case a defensive
default is for.

The check lives on `AnonymizationRule` rather than in the CLI loader because the
loader is not the only way to build one: `confiture.core.syncer` is importable,
and a library caller passing `SyncConfig(anonymization=...)` deserves the same
answer as a YAML file.
"""

from pathlib import Path

import pytest

from confiture.core.syncer import (
    SYNC_STRATEGIES,
    AnonymizationRule,
    ProductionSyncer,
)
from confiture.exceptions import ConfigurationError


class TestTheRuleChecksItsStrategy:
    @pytest.mark.parametrize("strategy", sorted(SYNC_STRATEGIES))
    def test_every_supported_strategy_is_accepted(self, strategy: str):
        assert AnonymizationRule(column="c", strategy=strategy).strategy == strategy

    def test_a_typo_is_refused(self):
        with pytest.raises(ConfigurationError) as exc:
            AnonymizationRule(column="email", strategy="emial")
        assert exc.value.error_code == "CONFIG_002"

    def test_the_message_names_the_allowed_strategies(self):
        with pytest.raises(ConfigurationError) as exc:
            AnonymizationRule(column="email", strategy="nonsense")
        message = str(exc.value)
        for name in SYNC_STRATEGIES:
            assert name in message

    def test_a_near_miss_is_suggested(self):
        """The defect this fixes is a typo; naming the intended strategy is the fix."""
        with pytest.raises(ConfigurationError) as exc:
            AnonymizationRule(column="email", strategy="emial")
        assert "email" in str(exc.value.resolution_hint or "")

    def test_a_strategy_from_the_other_yaml_format_is_refused_here(self):
        """`email_mask` is an `AnonymizationProfile` strategy; the sync path has no such name."""
        with pytest.raises(ConfigurationError):
            AnonymizationRule(column="email", strategy="email_mask")


class TestTheLoaderRefusesTheFile:
    def _write(self, tmp_path: Path, strategy: str) -> Path:
        path = tmp_path / "anon.yaml"
        path.write_text(f"users:\n  - column: email\n    strategy: {strategy}\n")
        return path

    def test_a_typo_in_the_file_is_config_002(self, tmp_path: Path):
        from confiture.cli.sync import _load_anonymization

        with pytest.raises(ConfigurationError) as exc:
            _load_anonymization(self._write(tmp_path, "emial"))
        assert exc.value.error_code == "CONFIG_002"

    def test_a_valid_file_still_loads(self, tmp_path: Path):
        from confiture.cli.sync import _load_anonymization

        rules = _load_anonymization(self._write(tmp_path, "email"))
        assert [r.strategy for r in rules["users"]] == ["email"]

    def test_redact_still_loads(self, tmp_path: Path):
        from confiture.cli.sync import _load_anonymization

        rules = _load_anonymization(self._write(tmp_path, "redact"))
        assert [r.strategy for r in rules["users"]] == ["redact"]


class TestRedactStillRedacts:
    """The value-level default is unchanged; only its reach is."""

    def test_redact_produces_the_constant(self):
        syncer = ProductionSyncer.__new__(ProductionSyncer)
        assert (
            ProductionSyncer._anonymize_value(syncer, "ada@example.org", "redact") == "[REDACTED]"
        )

    def test_none_is_left_alone(self):
        syncer = ProductionSyncer.__new__(ProductionSyncer)
        assert ProductionSyncer._anonymize_value(syncer, None, "redact") is None


class TestTheProfileFormatHadTheSameHole:
    """#285 said the profile format "already gets this right". It did not.

    `StrategyDefinition.type` has been whitelisted since the model was written,
    but a *rule* names a strategy by the key it was given under `strategies:`,
    and nothing checked that the key existed. A profile whose only rule said
    `strategy: emial_mask` beside a definition called `email_mask` passed
    `confiture validate-profile`, which printed `✅ Valid profile!` and exited 0.
    """

    @staticmethod
    def _profile(rule_strategy: str):
        from confiture.core.anonymization.profile import (
            AnonymizationProfile,
            StrategyDefinition,
            TableDefinition,
        )
        from confiture.core.anonymization.profile import AnonymizationRule as ProfileRule

        return AnonymizationProfile(
            name="p",
            version="1.0",
            strategies={"email_mask": StrategyDefinition(type="email")},
            tables={
                "users": TableDefinition(
                    rules=[ProfileRule(column="email", strategy=rule_strategy)]
                )
            },
        )

    def test_a_rule_naming_an_undefined_strategy_is_refused(self):
        with pytest.raises(Exception, match="does not define"):
            self._profile("emial_mask")

    def test_the_message_names_the_profile_s_own_strategies(self):
        with pytest.raises(Exception, match="email_mask"):
            self._profile("emial_mask")

    def test_a_rule_naming_a_defined_strategy_still_loads(self):
        assert self._profile("email_mask").tables["users"].rules[0].strategy == "email_mask"

    def test_a_definition_with_an_unknown_type_is_still_refused(self):
        """The check that was already there must not have been replaced."""
        from confiture.core.anonymization.profile import StrategyDefinition

        with pytest.raises(Exception, match="not allowed"):
            StrategyDefinition(type="emial")

    def test_the_sync_format_refuses_one_too(self):
        with pytest.raises(ConfigurationError):
            AnonymizationRule(column="email", strategy="emial")
