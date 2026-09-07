"""Pseudonyms are keyed by a per-deployment secret, never plain SHA-256.

``confiture sync --anonymize`` replaced PII with ``sha256(value)[:n]``.  Anyone
holding the anonymised copy can hash a candidate email and match it — the
hash is a lookup key, not a pseudonym.  The ``hash`` strategy was HMAC-keyed,
but with ``"default-secret"`` as the key when ``ANONYMIZATION_SECRET`` was
unset, which is the same thing with extra steps.  And ``random.seed(pii)``
pushed the PII into the interpreter-wide RNG state.

D8: the secret is mandatory.  Every keyed pseudonym goes through one
``Pseudonymizer`` (HMAC-SHA256 under ``ANONYMIZATION_SECRET``); an unset or
empty secret is a ``ConfigurationError`` before any row is read.
"""

from __future__ import annotations

import hashlib
import hmac
import random
import re

import pytest

from confiture.config.environment import DatabaseConfig
from confiture.core.syncer import ProductionSyncer
from confiture.exceptions import ConfigurationError

SECRET_ENV = "ANONYMIZATION_SECRET"
KEYED = ["email", "phone", "name", "hash"]
PII = "john.doe@example.com"


def _syncer() -> ProductionSyncer:
    return ProductionSyncer(DatabaseConfig(), DatabaseConfig())


def _anonymize(
    monkeypatch: pytest.MonkeyPatch,
    secret: str,
    value: object,
    strategy: str,
    seed: int | None = None,
) -> object:
    monkeypatch.setenv(SECRET_ENV, secret)
    return _syncer()._anonymize_value(value, strategy, seed)


# ---------------------------------------------------------------------------
# Keying
# ---------------------------------------------------------------------------


class TestKeying:
    @pytest.mark.parametrize("strategy", KEYED)
    def test_same_input_differs_under_two_secrets(
        self, monkeypatch: pytest.MonkeyPatch, strategy: str
    ) -> None:
        under_a = _anonymize(monkeypatch, "secret-a", PII, strategy)
        under_b = _anonymize(monkeypatch, "secret-b", PII, strategy)
        assert under_a != under_b

    @pytest.mark.parametrize("strategy", KEYED)
    def test_same_input_same_secret_is_stable_across_instances(
        self, monkeypatch: pytest.MonkeyPatch, strategy: str
    ) -> None:
        first = _anonymize(monkeypatch, "secret-a", PII, strategy)
        second = _anonymize(monkeypatch, "secret-a", PII, strategy)
        assert first == second

    @pytest.mark.parametrize("strategy", KEYED)
    def test_missing_secret_is_a_configuration_error(
        self, monkeypatch: pytest.MonkeyPatch, strategy: str
    ) -> None:
        monkeypatch.delenv(SECRET_ENV, raising=False)
        with pytest.raises(ConfigurationError) as excinfo:
            _syncer()._anonymize_value(PII, strategy)
        assert excinfo.value.error_code.startswith("CONFIG_")
        assert SECRET_ENV in str(excinfo.value)

    def test_empty_secret_counts_as_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(SECRET_ENV, "")
        with pytest.raises(ConfigurationError):
            _syncer()._anonymize_value(PII, "hash")

    @pytest.mark.parametrize("strategy", ["redact", "unknown-strategy"])
    def test_unkeyed_strategies_do_not_need_the_secret(
        self, monkeypatch: pytest.MonkeyPatch, strategy: str
    ) -> None:
        monkeypatch.delenv(SECRET_ENV, raising=False)
        assert _syncer()._anonymize_value(PII, strategy) == "[REDACTED]"

    def test_null_passes_through_without_the_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(SECRET_ENV, raising=False)
        assert _syncer()._anonymize_value(None, "email") is None


# ---------------------------------------------------------------------------
# Not plain SHA-256
# ---------------------------------------------------------------------------


class TestNotPlainSha256:
    def test_hash_is_not_a_prefix_of_sha256(self, monkeypatch: pytest.MonkeyPatch) -> None:
        out = _anonymize(monkeypatch, "s", PII, "hash")
        assert isinstance(out, str)
        assert not hashlib.sha256(PII.encode()).hexdigest().startswith(out)

    def test_email_local_part_is_not_a_sha256_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        out = _anonymize(monkeypatch, "s", PII, "email")
        digest = hashlib.sha256(PII.encode()).hexdigest()
        assert out != f"user_{digest[:8]}@example.com"

    def test_name_is_not_a_sha256_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        out = _anonymize(monkeypatch, "s", "John Doe", "name")
        digest = hashlib.sha256(b"John Doe").hexdigest()
        assert out != f"User {digest[:4].upper()}"

    def test_seeded_phone_is_not_a_sha256_residue(self, monkeypatch: pytest.MonkeyPatch) -> None:
        out = _anonymize(monkeypatch, "s", "+1-555-1234", "phone", seed=1)
        digest = hashlib.sha256(b"+1-555-1234").hexdigest()
        assert out != f"+1-555-{int(digest[:8], 16) % 10000}"


# ---------------------------------------------------------------------------
# The interpreter-wide RNG is not touched
# ---------------------------------------------------------------------------


class TestGlobalRandomUntouched:
    @pytest.mark.parametrize("seed", [None, 7])
    def test_random_state_unchanged_after_every_strategy(
        self, monkeypatch: pytest.MonkeyPatch, seed: int | None
    ) -> None:
        monkeypatch.setenv(SECRET_ENV, "s")
        random.seed(12345)
        before = random.getstate()

        syncer = _syncer()
        for strategy in KEYED:
            syncer._anonymize_value(PII, strategy, seed)

        assert random.getstate() == before


# ---------------------------------------------------------------------------
# Output shapes (the contract downstream fixtures rely on)
# ---------------------------------------------------------------------------


class TestShapes:
    def test_email(self, monkeypatch: pytest.MonkeyPatch) -> None:
        out = _anonymize(monkeypatch, "s", PII, "email")
        assert re.fullmatch(r"user_[0-9a-f]{8}@example\.com", str(out))

    @pytest.mark.parametrize("seed", [None, 3])
    def test_phone_is_four_digits_and_deterministic(
        self, monkeypatch: pytest.MonkeyPatch, seed: int | None
    ) -> None:
        first = _anonymize(monkeypatch, "s", "+1-555-1234", "phone", seed)
        second = _anonymize(monkeypatch, "s", "+1-555-1234", "phone", seed)
        assert first == second
        match = re.fullmatch(r"\+1-555-(\d{4})", str(first))
        assert match and 1000 <= int(match.group(1)) <= 9999

    def test_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        out = _anonymize(monkeypatch, "s", "John Doe", "name")
        assert re.fullmatch(r"User [0-9A-F]{4}", str(out))

    def test_hash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        out = _anonymize(monkeypatch, "s", PII, "hash")
        assert re.fullmatch(r"[0-9a-f]{16}", str(out))

    @pytest.mark.parametrize("strategy", KEYED)
    def test_seed_separates_domains(self, monkeypatch: pytest.MonkeyPatch, strategy: str) -> None:
        unseeded = _anonymize(monkeypatch, "s", PII, strategy)
        seed_one = _anonymize(monkeypatch, "s", PII, strategy, seed=1)
        seed_two = _anonymize(monkeypatch, "s", PII, strategy, seed=2)
        assert len({unseeded, seed_one, seed_two}) == 3

    def test_non_string_values_are_pseudonymized_by_their_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert _anonymize(monkeypatch, "s", 42, "hash") == _anonymize(
            monkeypatch, "s", "42", "hash"
        )


# ---------------------------------------------------------------------------
# The one Pseudonymizer
# ---------------------------------------------------------------------------


class TestPseudonymizer:
    def test_hex_is_hmac_sha256_under_the_secret(self) -> None:
        from confiture.core.anonymization.pseudonymizer import Pseudonymizer

        expected = hmac.new(b"k", PII.encode(), hashlib.sha256).hexdigest()
        assert Pseudonymizer("k").hex(PII) == expected

    def test_seed_is_folded_into_the_key(self) -> None:
        from confiture.core.anonymization.pseudonymizer import Pseudonymizer

        expected = hmac.new(b"5k", PII.encode(), hashlib.sha256).hexdigest()
        assert Pseudonymizer("k").hex(PII, seed=5) == expected

    def test_length_truncates(self) -> None:
        from confiture.core.anonymization.pseudonymizer import Pseudonymizer

        assert len(Pseudonymizer("k").hex(PII, length=12)) == 12

    def test_integer_is_within_the_modulus(self) -> None:
        from confiture.core.anonymization.pseudonymizer import Pseudonymizer

        values = {Pseudonymizer("k").integer(f"v{i}", 9000) for i in range(200)}
        assert all(0 <= v < 9000 for v in values)
        assert len(values) > 150  # spread, not a constant

    def test_explicit_secret_wins_over_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from confiture.core.anonymization.pseudonymizer import Pseudonymizer

        monkeypatch.setenv(SECRET_ENV, "from-env")
        assert Pseudonymizer("explicit").hex(PII) == Pseudonymizer("explicit").hex(PII)
        assert Pseudonymizer("explicit").hex(PII) != Pseudonymizer().hex(PII)

    def test_unset_and_empty_secret_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from confiture.core.anonymization.pseudonymizer import Pseudonymizer

        monkeypatch.delenv(SECRET_ENV, raising=False)
        with pytest.raises(ConfigurationError, match=SECRET_ENV):
            Pseudonymizer()
        with pytest.raises(ConfigurationError, match=SECRET_ENV):
            Pseudonymizer("")
        monkeypatch.setenv(SECRET_ENV, "   ")
        with pytest.raises(ConfigurationError, match=SECRET_ENV):
            Pseudonymizer()


# ---------------------------------------------------------------------------
# The `hash` strategy of the registry
# ---------------------------------------------------------------------------


class TestDeterministicHashStrategy:
    def test_unset_secret_is_a_configuration_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from confiture.core.anonymization.strategies.hash import DeterministicHashStrategy

        monkeypatch.delenv(SECRET_ENV, raising=False)
        with pytest.raises(ConfigurationError, match=SECRET_ENV):
            DeterministicHashStrategy().anonymize(PII)

    def test_derivation_is_unchanged_for_anyone_who_already_set_a_secret(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from confiture.core.anonymization.strategies.hash import (
            DeterministicHashConfig,
            DeterministicHashStrategy,
        )

        monkeypatch.setenv(SECRET_ENV, "s")
        strategy = DeterministicHashStrategy(DeterministicHashConfig(seed=5))
        assert strategy.anonymize(PII) == hmac.new(b"5s", PII.encode(), hashlib.sha256).hexdigest()

    def test_two_secrets_differ(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from confiture.core.anonymization.strategies.hash import DeterministicHashStrategy

        monkeypatch.setenv(SECRET_ENV, "a")
        under_a = DeterministicHashStrategy().anonymize(PII)
        monkeypatch.setenv(SECRET_ENV, "b")
        under_b = DeterministicHashStrategy().anonymize(PII)
        assert under_a != under_b
