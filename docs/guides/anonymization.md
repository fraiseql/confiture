# Anonymization

[← Back to Guides](../index.md) · [Hooks](hooks.md) · [Compliance →](compliance.md)

Mask sensitive data when syncing production data to development/staging.

> The programmatic surface — writing a custom strategy, the registry, the
> profile format — is documented and doctested in the
> **[Anonymization API Reference](../api/anonymization.md)**. For the CLI path,
> see the **[Production Sync guide](03-production-sync.md)**
> (`confiture sync --anonymize`). This guide is the tour; those two are the
> contract.

---

## Quick Start

```bash
confiture sync --from production --to staging --anonymize
```

```yaml
# confiture.yaml
anonymization:
  columns:
    email: text_redaction
    phone: text_redaction:phone_us
    name: name
    ssn: text_redaction
    credit_card: credit_card
```

---

## Built-in Strategies

| Strategy | Example Input | Example Output |
|----------|--------------|----------------|
| `name` | John Smith | Michael Johnson |
| `date` | 1990-05-15 | 1990-05-XX |
| `address` | 123 Main St | 456 Oak Ave |
| `credit_card` | 4532-1234-5678-9010 | 4532-XXXX-XXXX-9010 |
| `ip_address` | 192.168.1.100 | 192.168.XX.XX |
| `text_redaction` | john@example.com | [EMAIL] |
| `preserve` | USR-001 | USR-001 |

---

## Strategy Configuration

### Name Masking

```python
strategy = StrategyRegistry.get(
    "name",
    {
        "seed": 42,
        "format_type": "firstname_lastname",  # or "initials", "random"
    },
)
```

### Date Masking

```python
strategy = StrategyRegistry.get(
    "date",
    {
        "seed": 42,
        "mode": "year_month",  # or "year", "none"
        "format": "iso",  # or "us", "uk"
    },
)
```

### Credit Card (PCI-DSS Compliant)

```python
strategy = StrategyRegistry.get("credit_card", {"preserve_last4": True, "preserve_bin": True})
```

### Text Redaction Patterns

- `email`: john@example.com → [EMAIL]
- `phone_us`: (555) 123-4567 → [PHONE]
- `ssn`: 123-45-6789 → [SSN]
- `credit_card`: 4532-... → [CC]
- `url`: https://... → [URL]
- `ipv4`: 192.168.1.1 → [IP]

---

## Using Profiles

A profile maps tables and columns to named strategies and is validated on load.
The format, the whitelist its `type` values must come from, and a worked example
are in the **[Anonymization API Reference](../api/anonymization.md#anonymizationprofile)**.

```python
from confiture import AnonymizationProfile

profile = AnonymizationProfile.load("db/anonymization/production.yaml")
```

---


## Custom Strategies

### Class-Based

```python
from confiture.core.anonymization.strategy import AnonymizationStrategy


class MyStrategy(AnonymizationStrategy):
    config_type = MyStrategyConfig
    strategy_name = "my_strategy"

    def anonymize(self, value):
        return f"ANON_{value[:5]}"

    def validate(self, value):
        return isinstance(value, str)


# Register
StrategyRegistry.register("my_strategy", MyStrategy)
```

### Deterministic Anonymization

The same input produces the same output, so rows that joined before
anonymization still join after it. `confiture sync --anonymize` gets this from
its keyed pseudonymizer and a per-column `seed`; see the
**[Production Sync guide](03-production-sync.md)**.

---


# GDPR compliance
anonymized = HealthcareScenario.anonymize(data, RegulationType.GDPR)

# Verify compliance
result = HealthcareScenario.verify_compliance(data, anonymized, RegulationType.GDPR)
```

---

## Best Practices

### 1. Use Consistent Seeds

```yaml
# The same seed gives the same pseudonym for the same input, which is what
# keeps a foreign key joinable after both sides are anonymized.
users:
  - column: email
    strategy: email
    seed: 42
```


# Same seed = same output for same input
profile = StrategyProfile(seed=42, ...)
```

### 2. Preserve Identifiers

```python
columns={
    "customer_id": "preserve",  # Keep for joins
    "order_id": "preserve",     # Keep for tracking
    "name": "name",             # Anonymize PII
}
```

### 3. Match Strategy to Data Type

```python
columns = {
    "birth_date": "date",  # Not text_redaction
    "email": "text_redaction",  # Not name
    "full_name": "name",  # Not text_redaction
}
```

### 4. Handle NULL Values

```python
def my_strategy(value, field_name, row_context=None):
    if value is None:
        return None  # Preserve NULL
    return anonymize(value)
```

### 5. Preserve Data Types

```python
# Good: int → int
def anonymize_age(value: int, ...) -> int:
    return value // 10 * 10

# Bad: int → str (breaks schema)
def anonymize_age(value: int, ...) -> str:
    return f"age_{value}"
```

---

## Performance

Fastest to slowest:
1. **Preserve** (~1000+ ops/sec)
2. **Name/Date/IP** (~500-1000 ops/sec)
3. **Text Redaction** (~100-500 ops/sec)
4. **Credit Card** (~50-200 ops/sec)

Reuse factories for batch processing:

```python
# Good
factory = StrategyFactory(profile)
results = [factory.anonymize(r) for r in records]

# Bad
results = [StrategyFactory(profile).anonymize(r) for r in records]
```

---

## Troubleshooting

### Strategy not found

Check registration:
```python
from confiture.core.anonymization.registry import StrategyRegistry

print(StrategyRegistry.list_available())
```

### Value not changing

Check if using `preserve` strategy or if validation fails.

### Performance issues

Cache expensive operations with `@lru_cache`.

---

## See Also

- [Anonymization API](../api/anonymization.md)
- [Production Sync](./03-production-sync.md)
- [Compliance Guide](./compliance.md)
