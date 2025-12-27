"""Anonymization strategies module.

Provides standard PII anonymization strategies for common data types.
All strategies are automatically registered with the StrategyRegistry.
"""

from confiture.core.anonymization.registry import StrategyRegistry
from confiture.core.anonymization.strategies.name import NameMaskingStrategy
from confiture.core.anonymization.strategies.date import DateMaskingStrategy
from confiture.core.anonymization.strategies.address import AddressStrategy
from confiture.core.anonymization.strategies.credit_card import CreditCardStrategy
from confiture.core.anonymization.strategies.ip_address import IPAddressStrategy
from confiture.core.anonymization.strategies.text_redaction import TextRedactionStrategy
from confiture.core.anonymization.strategies.preserve import PreserveStrategy
from confiture.core.anonymization.strategies.custom import (
    CustomStrategy,
    CustomLambdaStrategy,
)

# Register all strategies
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
