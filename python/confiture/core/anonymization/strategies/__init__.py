"""Anonymization strategies module.

Provides standard PII anonymization strategies for common data types.
All strategies are automatically registered with the StrategyRegistry.
"""

from confiture.core.anonymization.registry import StrategyRegistry
from confiture.core.anonymization.strategies.address import AddressStrategy
from confiture.core.anonymization.strategies.credit_card import CreditCardStrategy
from confiture.core.anonymization.strategies.custom import (
    CustomLambdaStrategy,
    CustomStrategy,
)
from confiture.core.anonymization.strategies.date import DateMaskingStrategy
from confiture.core.anonymization.strategies.email import EmailMaskingStrategy
from confiture.core.anonymization.strategies.hash import DeterministicHashStrategy
from confiture.core.anonymization.strategies.ip_address import IPAddressStrategy
from confiture.core.anonymization.strategies.name import NameMaskingStrategy
from confiture.core.anonymization.strategies.phone import PhoneMaskingStrategy
from confiture.core.anonymization.strategies.preserve import PreserveStrategy
from confiture.core.anonymization.strategies.redact import SimpleRedactStrategy
from confiture.core.anonymization.strategies.text_redaction import TextRedactionStrategy

# Register all strategies. The first block covers the profile-whitelisted types
# (profile.py StrategyType: hash/email/phone/redact) — these MUST stay registered
# so a YAML anonymization profile naming them resolves (see
# test_registry_whitelist_coherence). The second block adds the richer set.
StrategyRegistry.register("email", EmailMaskingStrategy)
StrategyRegistry.register("phone", PhoneMaskingStrategy)
StrategyRegistry.register("hash", DeterministicHashStrategy)
StrategyRegistry.register("redact", SimpleRedactStrategy)
StrategyRegistry.register("name", NameMaskingStrategy)
StrategyRegistry.register("date", DateMaskingStrategy)
StrategyRegistry.register("address", AddressStrategy)
StrategyRegistry.register("credit_card", CreditCardStrategy)
StrategyRegistry.register("ip_address", IPAddressStrategy)
StrategyRegistry.register("text_redaction", TextRedactionStrategy)
StrategyRegistry.register("preserve", PreserveStrategy)
StrategyRegistry.register("custom", CustomStrategy)
StrategyRegistry.register("custom_lambda", CustomLambdaStrategy)

__all__ = [
    "EmailMaskingStrategy",
    "PhoneMaskingStrategy",
    "DeterministicHashStrategy",
    "SimpleRedactStrategy",
    "NameMaskingStrategy",
    "DateMaskingStrategy",
    "AddressStrategy",
    "CreditCardStrategy",
    "IPAddressStrategy",
    "TextRedactionStrategy",
    "PreserveStrategy",
    "CustomStrategy",
    "CustomLambdaStrategy",
]
