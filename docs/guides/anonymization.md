# Anonymization

[← Back to Guides](../index.md) · [Hooks](hooks.md) · [Compliance →](compliance.md)

Mask sensitive data when syncing production data to development/staging.

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
strategy = StrategyRegistry.get("name", {
    "seed": 42,
    "format_type": "firstname_lastname"  # or "initials", "random"
})
```

### Date Masking

```python
strategy = StrategyRegistry.get("date", {
    "seed": 42,
    "mode": "year_month",  # or "year", "none"
    "format": "iso"        # or "us", "uk"
})
```

### Credit Card (PCI-DSS Compliant)

```python
strategy = StrategyRegistry.get("credit_card", {
    "preserve_last4": True,
    "preserve_bin": True
})
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

Define column mappings in a profile:

```python
from confiture.core.anonymization.factory import StrategyFactory, StrategyProfile

profile = StrategyProfile(
    name="user_data",
    seed=42,
    columns={
        "user_id": "preserve",
        "name": "name",
        "email": "text_redaction",
        "phone": "text_redaction:phone_us",
        "birthdate": "date:year_month",
        "ip_address": "ip_address",
    },
    defaults="preserve"
)

factory = StrategyFactory(profile)
anonymized = factory.anonymize(record)
```

---

## Custom Strategies

### Function-Based

```python
from confiture.anonymization import register_strategy

@register_strategy('email')
def anonymize_email(value: str, field_name: str, row_context: dict = None) -> str:
    if not value or '@' not in value:
        return "invalid@example.com"

    local, domain = value.rsplit('@', 1)
    hash_val = hashlib.sha256(local.encode()).hexdigest()[:6]
    return f"user_{hash_val}@{domain}"
```

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

### Row Context

Access other columns for conditional logic:

```python
@register_strategy('credit_card')
def anonymize_card(value, field_name, row_context=None):
    # Keep test accounts unchanged
    if row_context and row_context.get('is_test_account'):
        return value

    return f"****-****-****-{value[-4:]}"
```

### Deterministic Anonymization

Same input always produces same output (preserves relationships):

```python
@register_strategy('user_id')
def anonymize_id(value, field_name, row_context=None):
    hash_digest = sha256(str(value).encode()).digest()
    return struct.unpack('>Q', hash_digest[:8])[0]
```

---

## Compliance Scenarios

```python
from confiture.scenarios.healthcare import HealthcareScenario
from confiture.scenarios.compliance import RegulationType

# GDPR compliance
anonymized = HealthcareScenario.anonymize(data, RegulationType.GDPR)

# Verify compliance
result = HealthcareScenario.verify_compliance(data, anonymized, RegulationType.GDPR)
```

---

## Best Practices

### 1. Use Consistent Seeds

```python
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
columns={
    "birth_date": "date",        # Not text_redaction
    "email": "text_redaction",   # Not name
    "full_name": "name",         # Not text_redaction
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
