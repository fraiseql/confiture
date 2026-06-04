"""PII anonymization framework (library API).

Public extension point for masking production data during a sync (Medium 3) or
any custom anonymization pipeline. Subclass :class:`AnonymizationStrategy`,
register it with :class:`StrategyRegistry` (or the :func:`register_strategy`
decorator), and drive table/column rules from an :class:`AnonymizationProfile`
YAML.

Importing this package registers the built-in strategies (``email``, ``phone``,
``hash``, ``redact``, ``name``, ``date``, ``address``, ``credit_card``,
``ip_address``, ``text_redaction``, ``preserve``, ``custom``, ``custom_lambda``,
``salted_hashing``, ``masking_retention``, ``differential_privacy``) so the
registry is ready to use. The four profile-whitelisted types (``email``,
``phone``, ``hash``, ``redact``) are the ones an :class:`AnonymizationProfile`
may name.

See ``docs/api/anonymization.md``.
"""

from __future__ import annotations

# Importing the strategies subpackage registers every built-in strategy with the
# StrategyRegistry (side-effect import — keep it first so the registry is
# populated before anyone calls StrategyRegistry.get).
from confiture.core.anonymization import strategies as _strategies  # noqa: F401
from confiture.core.anonymization.profile import (
    AnonymizationProfile,
    AnonymizationRule,
    StrategyDefinition,
    StrategyType,
    TableDefinition,
    resolve_seed_for_column,
)
from confiture.core.anonymization.registry import StrategyRegistry, register_strategy
from confiture.core.anonymization.strategy import (
    AnonymizationStrategy,
    StrategyConfig,
    resolve_seed,
)

__all__ = [
    # Extension-point base classes
    "AnonymizationStrategy",
    "StrategyConfig",
    "resolve_seed",
    # Registry
    "StrategyRegistry",
    "register_strategy",
    # YAML profile
    "AnonymizationProfile",
    "AnonymizationRule",
    "StrategyDefinition",
    "StrategyType",
    "TableDefinition",
    "resolve_seed_for_column",
]
