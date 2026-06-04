# Anonymization Strategy API Reference

[← Back to API Reference](index.md)

**Stability**: Stable ✅

---

## Overview

The anonymization framework is the **extensible library API** for masking
sensitive data (PII, financial, healthcare) — for example when copying
production data to a development environment. A *strategy* transforms one column
value into a test-safe equivalent; strategies are registered in a central
registry and can be driven from a YAML profile.

The real API is **class-based**: you subclass
[`AnonymizationStrategy`](#anonymizationstrategy), register the class with the
[`StrategyRegistry`](#strategyregistry), and (optionally) declare table/column
rules in an [`AnonymizationProfile`](#anonymizationprofile).

```python
from confiture import (
    AnonymizationProfile,
    AnonymizationStrategy,
    StrategyConfig,
    StrategyRegistry,
    register_strategy,
)
```

> **Relationship to `confiture sync`.** The `confiture sync --anonymize` command
> (see the [Production Sync guide](../guides/03-production-sync.md)) uses the
> syncer's own built-in `email`/`phone`/`name`/`redact`/`hash` strategies via a
> simple `db/sync/anonymization.yaml` (`table → [{column, strategy, seed}]`).
> This framework is the *programmatic, extensible* layer — use it to write
> custom strategies or drive anonymization from your own code.

---

## Built-in strategies

Importing the framework registers these strategies automatically:

| Name | Class | Profile-nameable¹ |
|------|-------|:-:|
| `email` | `EmailMaskingStrategy` | ✅ |
| `phone` | `PhoneMaskingStrategy` | ✅ |
| `hash` | `DeterministicHashStrategy` | ✅ |
| `redact` | `SimpleRedactStrategy` | ✅ |
| `name` | `NameMaskingStrategy` | |
| `date` | `DateMaskingStrategy` | |
| `address` | `AddressStrategy` | |
| `credit_card` | `CreditCardStrategy` | |
| `ip_address` | `IPAddressStrategy` | |
| `text_redaction` | `TextRedactionStrategy` | |
| `preserve` | `PreserveStrategy` | |
| `custom` / `custom_lambda` | `CustomStrategy` / `CustomLambdaStrategy` | |
| `salted_hashing` | `SaltedHashingStrategy` | |
| `masking_retention` | `MaskingRetentionStrategy` | |
| `differential_privacy` | `DifferentialPrivacyStrategy` | |

¹ Only the four whitelisted types (`email`, `phone`, `hash`, `redact`) may be
named in an `AnonymizationProfile` YAML (`StrategyType`). Every strategy —
whitelisted or not — is usable programmatically through the registry.

```python
from confiture import StrategyRegistry

masker = StrategyRegistry.get("email", {"seed": 12345})
masked = masker.anonymize("john@example.com")  # -> 'user_<hash>@example.com'
```

---

## `AnonymizationStrategy`

Abstract base class for all strategies. Subclasses implement two methods and may
declare a `config_type` so the registry builds the right configuration object.

```python
from typing import Any

from confiture import AnonymizationStrategy, StrategyConfig, StrategyRegistry


class UpperCaseStrategy(AnonymizationStrategy):
    """Replace a value with its upper-cased form (illustrative)."""

    config_type = StrategyConfig
    strategy_name = "uppercase"

    def anonymize(self, value: Any) -> Any:
        # Must preserve NULLs — they carry meaning in the target schema.
        if value is None:
            return None
        return str(value).upper()

    def validate(self, value: Any) -> bool:
        # Whether this strategy can handle a column of this value's type.
        return value is None or isinstance(value, str)


StrategyRegistry.register("uppercase", UpperCaseStrategy)
assert StrategyRegistry.get("uppercase").anonymize("alice") == "ALICE"
```

### Contract

- **`anonymize(value)`** — transform one value. Must return `None` for `None`,
  and must be **deterministic** when a seed is configured (same input + seed →
  same output), so reruns and referential integrity hold.
- **`validate(value)`** — whether the strategy can handle this value's type
  (used to vet a strategy against a column).
- **`config_type`** — the `StrategyConfig` subclass the registry instantiates in
  `StrategyRegistry.get(name, config_dict)`. Defaults to `StrategyConfig`.

---

## `StrategyConfig`

Base configuration. Seeds make anonymization deterministic; prefer an
environment variable over a hard-coded seed in production.

```python
from confiture import StrategyConfig

# Resolution order (see resolve_seed): env var → hard-coded seed → 0.
config = StrategyConfig(seed_env_var="ANONYMIZATION_SEED")
config_for_tests = StrategyConfig(seed=12345)
```

A strategy that needs extra knobs subclasses `StrategyConfig` (e.g.
`EmailMaskConfig` adds `format` / `hash_length`) and points `config_type` at it.

---

## `StrategyRegistry`

Central registry of strategies by name.

```python
from confiture import StrategyRegistry

StrategyRegistry.is_registered("email")           # -> True
sorted_names = StrategyRegistry.list_available()  # all registered names
strategy = StrategyRegistry.get("hash", {"length": 16})
```

| Method | Purpose |
|--------|---------|
| `register(name, cls)` | Register a strategy class (raises if the name is taken). |
| `get(name, config=None)` | Build a strategy instance (config dict → `config_type`). |
| `is_registered(name)` | Whether a name is registered. |
| `list_available()` | Sorted list of registered names. |
| `get_strategy_class(name)` | The class (not an instance) for introspection. |
| `register_from_file(path)` | Load + register a strategy from a **sandboxed** file. |
| `unregister(name)` / `reset()` | Remove one / clear all (mainly for tests). |

### The `@register_strategy` decorator

A class-level shorthand for `StrategyRegistry.register`:

```python
from typing import Any

from confiture import AnonymizationStrategy, register_strategy


@register_strategy("reverse")
class ReverseStrategy(AnonymizationStrategy):
    def anonymize(self, value: Any) -> Any:
        return None if value is None else str(value)[::-1]

    def validate(self, value: Any) -> bool:
        return True
```

---

## `AnonymizationProfile`

A validated YAML profile mapping tables and columns to strategies. Loading uses
`yaml.safe_load` and Pydantic validation; the `type` of each strategy must be in
the whitelist (`hash`, `email`, `phone`, `redact`).

<!-- doctest:anonymization-profile-yaml -->
```yaml
# db/anonymization/production.yaml
name: production
version: "1.0"
global_seed: 12345          # optional; column-level seed overrides this
strategies:
  mask_email:
    type: email
  redact_ssn:
    type: redact
tables:
  users:
    rules:
      - column: email
        strategy: mask_email
      - column: ssn
        strategy: redact_ssn
```

```python
from confiture import AnonymizationProfile

# From a file …
# profile = AnonymizationProfile.load("db/anonymization/production.yaml")

# … or from a dict (handy in tests):
profile = AnonymizationProfile.from_dict(
    {
        "name": "production",
        "version": "1.0",
        "global_seed": 12345,
        "strategies": {
            "mask_email": {"type": "email"},
            "redact_ssn": {"type": "redact"},
        },
        "tables": {
            "users": {
                "rules": [
                    {"column": "email", "strategy": "mask_email"},
                    {"column": "ssn", "strategy": "redact_ssn"},
                ]
            }
        },
    }
)
assert profile.name == "production"
```

Seed precedence for a column is resolved by `resolve_seed_for_column(rule,
profile)`: a rule's own `seed` wins, else the profile's `global_seed`, else `0`.

---

## Security notes

- **Seeds are secrets.** Use `seed_env_var` (or `salt_env_var` for
  `salted_hashing`) in production; never commit seeds to version control.
- **Custom strategy files are sandboxed.** `register_from_file` rejects files
  with blocked imports (`os`, `subprocess`, …) before loading them.
- **Anonymization is not encryption.** The hashing strategies are one-way (no
  reversal). For reversible needs, use real encryption instead.

---

## See Also

- [Production Sync](../guides/03-production-sync.md) — using anonymization with `confiture sync`
- [Compliance Guide](../guides/compliance.md) — HIPAA, GDPR, PCI-DSS examples
