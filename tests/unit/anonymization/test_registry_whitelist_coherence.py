"""Registry ⇄ profile-whitelist coherence guard.

``profile.py``'s ``StrategyType`` whitelists exactly the strategy *types* a YAML
anonymization profile may name: ``hash``, ``email``, ``phone``, ``redact``. For a
profile to be usable, every whitelisted type must resolve through the
``StrategyRegistry``.

Before this fix the two sets were **disjoint**: ``strategies/__init__.py``
registered ``name``/``date``/``address``/… but none of the four whitelisted
types, so ``StrategyRegistry.get("email")`` raised "Unknown strategy" for any
profile-driven lookup. These tests pin that the whitelist is a subset of the
registered strategies and that a profile naming all four resolves end to end.
"""

from __future__ import annotations

import importlib

from confiture.core.anonymization import strategies as strategies_mod
from confiture.core.anonymization.profile import AnonymizationProfile, StrategyType
from confiture.core.anonymization.registry import StrategyRegistry


def _reload_builtin_strategies() -> None:
    """Re-run ``strategies/__init__`` from a clean registry (order-independent)."""
    StrategyRegistry.reset()
    importlib.reload(strategies_mod)


def test_every_profile_whitelisted_type_is_registered() -> None:
    """Each ``StrategyType`` value resolves to a registered strategy class."""
    _reload_builtin_strategies()
    missing = [st.value for st in StrategyType if not StrategyRegistry.is_registered(st.value)]
    assert not missing, f"profile-whitelisted strategies not registered: {missing}"


def test_every_registered_strategy_constructs_via_get() -> None:
    """``StrategyRegistry.get(name)`` builds every built-in (config_type wired).

    A registered strategy whose ``config_type`` is unset would have the registry
    build the base ``StrategyConfig`` and break construction (or first use) — this
    pins that every built-in is genuinely resolvable via the registry path.
    """
    _reload_builtin_strategies()
    broken: list[str] = []
    for name in StrategyRegistry.list_available():
        try:
            StrategyRegistry.get(name)
        except Exception as exc:  # noqa: BLE001 — collect all, report together
            broken.append(f"{name}: {type(exc).__name__}: {exc}")
    assert not broken, f"registered strategies that fail to construct: {broken}"


def test_whitelisted_strategies_instantiate_and_anonymize() -> None:
    """Every whitelisted strategy can be obtained and masks a value."""
    _reload_builtin_strategies()
    for st in StrategyType:
        strategy = StrategyRegistry.get(st.value)
        masked = strategy.anonymize("john.doe@example.com")
        assert masked is not None
        assert masked != "john.doe@example.com"


def test_profile_naming_whitelisted_strategies_resolves() -> None:
    """A profile naming all four whitelisted types resolves each via the registry."""
    _reload_builtin_strategies()
    profile = AnonymizationProfile.from_dict(
        {
            "name": "coherence",
            "version": "1.0",
            "strategies": {
                "mask_email": {"type": "email"},
                "mask_phone": {"type": "phone"},
                "hash_id": {"type": "hash"},
                "redact_ssn": {"type": "redact"},
            },
            "tables": {
                "users": {"rules": [{"column": "email", "strategy": "mask_email"}]},
            },
        }
    )
    for definition in profile.strategies.values():
        # The pre-fix failure mode: this raised ValueError("Unknown strategy").
        strategy = StrategyRegistry.get(definition.type)
        assert strategy is not None
