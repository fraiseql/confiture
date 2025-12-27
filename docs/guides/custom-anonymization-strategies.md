# Custom Anonymization Strategies

**Build your own data anonymization functions for production data sync**

---

## What are Custom Strategies?

Custom anonymization strategies are user-defined functions that transform sensitive data when syncing production data to development/staging environments. Instead of relying on built-in anonymizers, you define exactly how each field should be masked.

### Key Concept

> **"Own your anonymization - define rules that match your compliance requirements"**

Custom strategies let you handle industry-specific PII, custom data formats, and complex anonymization logic.

---

## When to Use Custom Strategies

### ✅ Perfect For

- **Industry-specific data** - Healthcare records, financial data, biometric data
- **Custom formats** - Phone numbers, SSNs, company-specific identifiers
- **Complex rules** - Multi-field anonymization, conditional logic
- **Regulatory compliance** - HIPAA, GDPR, SOX, PCI-DSS requirements
- **Data relationships** - Anonymize linked records consistently
- **Reversibility needs** - Deterministic anonymization for testing
- **Performance optimization** - Custom indexed anonymization

### ❌ Not For

- **Simple names/emails** - Use built-in strategies instead
- **One-time anonymization** - Use SQL migrations for static data
- **Real-time filtering** - Use database views instead
- **Access control** - Use database row-level security instead

---

## How Custom Strategies Work

### The Anonymization Pipeline

```
confiture sync --from production --to staging --anonymize
         │
         ├─→ Load production data
         │
         ├─→ For each row:
         │   ├─ Identify sensitive columns
         │   ├─ Look up custom strategy function
         │   ├─ Apply transformation
         │   └─ Write anonymized data
         │
         └─→ Complete sync
```

### Strategy Function Signature

All custom strategies follow this pattern:

```python
from confiture.anonymization import AnonymizationStrategy

def my_strategy(
    value: str | int | None,
    field_name: str,
    row_context: dict | None = None
) -> str | int | None:
    """
    Transform sensitive data.

    Args:
        value: The raw value to anonymize
        field_name: Name of the column
        row_context: Optional dict with other row values

    Returns:
        Anonymized value of same type as input
    """
    if value is None:
        return None

    # Your anonymization logic here
    return anonymized_value
```

---

## Defining Custom Strategies

### Option 1: Function-Based (Recommended)

```python
# db/anonymization/strategies.py

from confiture.anonymization import register_strategy

@register_strategy('email')
def anonymize_email(value: str, field_name: str, row_context: dict = None) -> str:
    """Replace email with generic pattern."""
    if not value:
        return "invalid@example.com"

    # Extract domain
    domain = value.split('@')[1] if '@' in value else 'example.com'

    # Generate generic email
    return f"user_{hash(value) % 10000}@{domain}"
```

### Option 2: Class-Based (Advanced)

```python
# db/anonymization/strategies.py

from confiture.anonymization import AnonymizationStrategy

class PhoneNumberStrategy(AnonymizationStrategy):
    """Custom phone number anonymization."""

    def __call__(
        self,
        value: str,
        field_name: str,
        row_context: dict = None
    ) -> str:
        """Anonymize phone number."""
        if not value:
            return None

        # Keep last 4 digits, mask the rest
        last_four = value[-4:]
        return f"***-***-{last_four}"

    @property
    def name(self) -> str:
        return "phone"

# Register it
register_strategy('phone')(PhoneNumberStrategy())
```

### Option 3: Configuration File

```yaml
# db/confiture.yaml

anonymization:
  strategies:
    email:
      module: "db.anonymization"
      function: "anonymize_email"
    phone:
      module: "db.anonymization"
      class: "PhoneNumberStrategy"
    ssn:
      module: "db.anonymization"
      function: "anonymize_ssn"
```

---

## Example: Email Anonymization

**Situation**: Anonymize emails while preserving domain for testing.

```python
# db/anonymization/strategies.py

from confiture.anonymization import register_strategy
import hashlib

@register_strategy('email')
def anonymize_email(value: str, field_name: str, row_context: dict = None) -> str:
    """
    Anonymize email while preserving domain.

    Example:
        john.doe@acme.com → user_a2b3c4@acme.com
    """
    if not value or '@' not in value:
        return "invalid@example.com"

    # Split email
    local_part, domain = value.rsplit('@', 1)

    # Generate deterministic hash-based local part
    hash_digest = hashlib.sha256(local_part.encode()).hexdigest()
    new_local = f"user_{hash_digest[:6]}"

    return f"{new_local}@{domain}"
```

**Usage**:
```bash
# Register strategy
confiture sync --from production --to staging \
  --anonymize \
  --strategy email=db.anonymization.anonymize_email
```

**Output**:
```
Production: john.doe@acme.com
Staging:   user_a2b3c4@acme.com

Production: jane.smith@acme.com
Staging:   user_f5e6d7@acme.com
```

---

## Example: Phone Number Masking

**Situation**: Anonymize phone numbers for compliance testing.

```python
# db/anonymization/strategies.py

from confiture.anonymization import register_strategy
import re

@register_strategy('phone')
def anonymize_phone(value: str, field_name: str, row_context: dict = None) -> str:
    """
    Mask phone number, keep last 4 digits.

    Example:
        +1-555-123-4567 → +1-***-***-4567
    """
    if not value:
        return None

    # Remove non-digits
    digits = re.sub(r'\D', '', value)

    if len(digits) < 4:
        return "***-***-****"

    # Keep last 4, mask the rest
    last_four = digits[-4:]
    return f"***-***-{last_four}"
```

**Testing**:
```python
def test_phone_anonymization():
    assert anonymize_phone("+1-555-123-4567") == "***-***-4567"
    assert anonymize_phone("5551234567") == "***-***-4567"
    assert anonymize_phone(None) is None
```

---

## Example: Conditional Anonymization (Row Context)

**Situation**: Anonymize payment info only for customers, not internal test accounts.

```python
# db/anonymization/strategies.py

from confiture.anonymization import register_strategy

@register_strategy('credit_card')
def anonymize_card(value: str, field_name: str, row_context: dict = None) -> str:
    """
    Anonymize credit card, but keep test cards untouched.

    Uses row context to check if customer is a test account.
    """
    if not value:
        return None

    # Check if this is a test account
    if row_context and row_context.get('is_test_account'):
        # Keep test cards as-is
        return value

    # Anonymize real customer cards
    last_four = value[-4:]
    return f"****-****-****-{last_four}"
```

**Usage**:
```bash
confiture sync --from production --to staging \
  --anonymize \
  --strategy credit_card=db.anonymization.anonymize_card
```

---

## Example: Deterministic Anonymization (Reversible)

**Situation**: Anonymize data consistently so test accounts maintain relationships.

```python
# db/anonymization/strategies.py

from confiture.anonymization import register_strategy
from hashlib import sha256
import struct

@register_strategy('user_id')
def anonymize_id_deterministic(value: int, field_name: str, row_context: dict = None) -> int:
    """
    Anonymize ID deterministically.

    Same input → Same output (useful for testing data relationships)
    """
    if value is None:
        return None

    # Generate deterministic hash
    hash_digest = sha256(str(value).encode()).digest()

    # Convert to integer
    return struct.unpack('>Q', hash_digest[:8])[0]
```

**Benefits**:
- ✅ Consistent anonymization (same user always gets same anonymized ID)
- ✅ Relationships preserved (foreign keys still reference correctly)
- ✅ Reversible (can map back to original for testing)

---

## Example: Complex Multi-Field Anonymization

**Situation**: Anonymize address fields together, maintaining data integrity.

```python
# db/anonymization/strategies.py

from confiture.anonymization import register_strategy
import random

@register_strategy('address')
def anonymize_address(value: str, field_name: str, row_context: dict = None) -> str:
    """
    Anonymize address while keeping format valid.

    Replaces street with placeholder, keeps city/state/zip format.
    """
    if not value or ',' not in value:
        return "123 Main St, Anytown, US, 12345"

    # Parse address format: street, city, state, zip
    parts = [p.strip() for p in value.split(',')]

    if len(parts) >= 4:
        # Replace street, keep rest
        parts[0] = f"{random.randint(1, 9999)} Main St"
        return ', '.join(parts)

    # Fallback
    return "123 Main St, Anytown, US, 12345"
```

**Advanced with row context**:
```python
@register_strategy('full_address')
def anonymize_address_smart(value: str, field_name: str, row_context: dict = None) -> str:
    """
    Use row context to preserve relationships.

    All orders from same customer use same anonymized address.
    """
    if not value:
        return None

    customer_id = row_context.get('customer_id') if row_context else None

    if not customer_id:
        # No customer context, use random
        return "123 Main St, Anytown, US, 12345"

    # Generate consistent hash for this customer
    import hashlib
    hash_val = int(hashlib.md5(f"{customer_id}".encode()).hexdigest(), 16)

    # Use hash to pick from predefined addresses
    addresses = [
        "123 Oak Ave, Springfield, IL, 62701",
        "456 Elm St, Portland, OR, 97201",
        "789 Pine Rd, Austin, TX, 78701",
    ]

    return addresses[hash_val % len(addresses)]
```

---

## Best Practices

### 1. Handle NULL Values

**Good**:
```python
@register_strategy('email')
def good_strategy(value: str, field_name: str, row_context: dict = None) -> str:
    """Handles NULL/None values."""
    if value is None:
        return None  # Preserve NULL

    return anonymize(value)
```

**Bad**:
```python
@register_strategy('email')
def bad_strategy(value: str, field_name: str, row_context: dict = None) -> str:
    """Crashes on NULL."""
    return value.lower()  # AttributeError if value is None
```

### 2. Preserve Data Types

**Good**:
```python
@register_strategy('age')
def good_age(value: int, field_name: str, row_context: dict = None) -> int:
    """Returns same type as input."""
    if value is None:
        return None

    return value // 10 * 10  # Round to nearest decade
```

**Bad**:
```python
@register_strategy('age')
def bad_age(value: int, field_name: str, row_context: dict = None) -> str:
    """Returns different type - breaks data!"""
    return f"age_{value}"
```

### 3. Test Edge Cases

**Good**:
```python
def test_email_anonymization():
    # Normal case
    assert "@" in anonymize_email("john@acme.com")

    # Edge cases
    assert anonymize_email(None) is not None
    assert anonymize_email("") == "invalid@example.com"
    assert anonymize_email("noadomain") == "invalid@example.com"
```

**Bad**:
```python
def test_email_anonymization():
    # Only tests happy path
    assert anonymize_email("john@acme.com") == "john@acme.com"
```

### 4. Document Requirements

**Good**:
```python
@register_strategy('ssn')
def anonymize_ssn(value: str, field_name: str, row_context: dict = None) -> str:
    """
    Anonymize US Social Security Numbers.

    Accepts:
    - Format: XXX-XX-XXXX or XXXXXXXXX
    - Preserves geographic region (first 3 digits)

    Returns:
    - Format: XXX-00-0000 (anonymized)
    """
    # Implementation
```

---

## Troubleshooting

### ❌ Error: "Strategy not found"

**Cause**: Strategy not registered or wrong name.

**Solution**: Check registration:

```python
from confiture.anonymization import get_registered_strategies
print(get_registered_strategies())  # List all
```

**Explanation**: Strategy names are case-sensitive and must match config.

---

### ❌ Error: "Data type mismatch"

**Cause**: Strategy returns different type than input.

**Solution**: Match input/output types:

```python
# ❌ Bad: Returns string for integer input
@register_strategy('age')
def bad(value: int, field_name: str, row_context: dict = None) -> str:
    return f"age_{value}"

# ✅ Good: Returns integer for integer input
@register_strategy('age')
def good(value: int, field_name: str, row_context: dict = None) -> int:
    return value // 10 * 10
```

---

### ❌ Error: "Strategy too slow"

**Cause**: Expensive operations in strategy function.

**Solution**: Cache expensive computations:

```python
from functools import lru_cache

@lru_cache(maxsize=1000)
def expensive_lookup(value: str) -> str:
    """Expensive operation, cached."""
    return lookup_table[value]

@register_strategy('code')
def anonymize_code(value: str, field_name: str, row_context: dict = None) -> str:
    """Uses cached lookup."""
    return expensive_lookup(value)
```

---

## See Also

- [Advanced Patterns](./advanced-patterns.md) - Custom workflows and strategies
- [Anonymization API](../api/anonymization.md) - Complete API reference
- [Medium 3: Production Sync](./medium-3-production-sync.md) - Sync overview
- [Troubleshooting](./troubleshooting.md) - Common issues

---

## 🎯 Next Steps

**Ready to anonymize your data?**
- ✅ You now understand: Custom strategies, row context, deterministic hashing

**What to do next:**

1. **[Medium 3: Production Sync](./medium-3-production-sync.md)** - Full sync workflow
2. **[Advanced Patterns](./advanced-patterns.md)** - Complex anonymization patterns
3. **[API Reference](../api/anonymization.md)** - Complete strategy API

**Got questions?**
- **[FAQ](../glossary.md)** - Glossary and definitions
- **[Troubleshooting](./troubleshooting.md)** - Common issues

---

*Part of Confiture documentation* 🍓

*Making migrations sweet and simple*
