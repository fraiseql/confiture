# Anonymization Strategy API Reference

[← Back to API Reference](index.md)

**Stability**: Stable ✅

---

## Overview

The Anonymization Strategy API enables you to define custom data masking logic for production data syncing. Strategies allow you to selectively anonymize sensitive data (PII, financial info, healthcare records) while maintaining data integrity for testing and development.

**Tagline**: *Define custom data masking for production data safely*

---

## What is an Anonymization Strategy?

An Anonymization Strategy is a Python function that transforms sensitive data into test-safe equivalents. Strategies:
- Transform individual cell values
- Have access to row context for smart masking
- Support deterministic hashing for repeatable anonymization
- Can implement industry-specific compliance rules
- Work column-by-column during data sync

**Key Concept**: Strategies are synchronous transformations. Input value → anonymized value.

---

## Why Use Anonymization Strategies?

### Common Use Cases

1. **Email Anonymization**
   - Transform: `john.smith@example.com` → `user_a3b2c1@example.com`
   - Preserves domain for testing
   - Uses hash for consistency

2. **PII Masking**
   - Phone: `555-123-4567` → `555-000-0000`
   - SSN: `123-45-6789` → `XXX-XX-6789`
   - Name: `John Smith` → `User 12345`

3. **Financial Data**
   - Credit Card: `4111-1111-1111-1111` → `4000-0000-0000-0000`
   - Account Number: `123456789` → `000000000`
   - Amount: `$5,234.50` → Random amount

4. **Healthcare Records**
   - Patient Name: `Jane Doe` → `Patient 789`
   - Medical ID: `MRN123456` → `MRN000000`
   - Diagnosis: `Type 2 Diabetes` → Not copied (excluded)

5. **Compliance**
   - GDPR: Remove directly identifiable data
   - HIPAA: De-identify PHI (Protected Health Information)
   - CCPA: Honor do-not-sell requirements

---

## When to Use Anonymization

**✅ Good Use Cases**:
- Copying production data to dev/staging safely
- Creating test datasets with realistic structure
- Training ML models on actual data patterns
- Load testing with production-scale data
- Team development with shared data

**❌ Don't Use For**:
- Permanent deletion (use actual deletion)
- Access control (use database permissions)
- One-way encryption (use encryption)
- Backup redaction (design schema instead)

---

## Function Signature

### Basic Strategy Definition

```python
from confiture.anonymization import register_strategy, AnonymizationContext

@register_strategy('email')
def anonymize_email(
    value: str | None,
    field_name: str,
    row_context: dict[str, Any] | None = None
) -> str | None:
    """
    Anonymize email address for testing.

    Args:
        value: Email value (may be None)
        field_name: Column name this strategy applies to
        row_context: Full row data for context-aware anonymization

    Returns:
        Anonymized value or None

    Raises:
        AnonymizationError: If anonymization fails
    """
    pass
```

### Parameters

**name** (str): Strategy name for registration
- Used in migration files: `@anonymize('email')`
- Should describe data type being masked

**value** (str | None): The cell value being anonymized
- May be None for NULL database values
- Preserves data type context

**field_name** (str): Column name of this field
- Allows conditional logic based on column name
- Example: `if field_name == 'email':`

**row_context** (dict | None): Full row data
- Provides context for smart masking
- Example: Use `row_context['first_name']` to generate consistent IDs
- Useful for referential integrity

---

## AnonymizationContext Object

The row context provides information about the row being anonymized.

### Context Dictionary

```python
# Example row context
row_context = {
    'id': 123,                    # Primary key
    'email': 'john@example.com',  # Current value being anonymized
    'first_name': 'John',         # Other columns in row
    'last_name': 'Smith',
    'created_at': datetime(...),
    'is_active': True,
}
```

### Using Row Context

```python
@register_strategy('employee_id')
def anonymize_employee_id(
    value: str,
    field_name: str,
    row_context: dict | None = None
) -> str:
    """Generate consistent employee ID based on first/last name."""
    if row_context and 'first_name' in row_context:
        first = row_context['first_name']
        last = row_context['last_name']
        # Generate ID from name for consistency
        return f"EMP_{hash(first + last) % 10000:04d}"
    return "EMP_0000"
```

---

## Return Value Handling

### NULL/None Values

Strategies must handle None values:

```python
@register_strategy('phone')
def anonymize_phone(
    value: str | None,
    field_name: str,
    row_context: dict | None = None
) -> str | None:
    if value is None:
        return None  # Preserve NULL

    # Anonymize non-NULL values
    return value[:3] + '-000-0000'
```

### Data Type Preservation

Return values must match database column type:

```python
# For INTEGER columns
@register_strategy('salary')
def anonymize_salary(value: int | None, ...) -> int | None:
    if value is None:
        return None
    return value // 1000 * 1000  # Round to nearest 1000

# For BOOLEAN columns
@register_strategy('is_premium')
def anonymize_is_premium(value: bool | None, ...) -> bool | None:
    if value is None:
        return None
    return True  # Everyone is premium in test data
```

---

## Registering Strategies

### Simple Registration

```python
from confiture.anonymization import register_strategy
import hashlib

@register_strategy('email')
def anonymize_email(value: str | None, field_name: str, ...) -> str | None:
    """Mask email addresses."""
    if not value or '@' not in value:
        return "invalid@example.com"

    local, domain = value.rsplit('@', 1)
    hash_digest = hashlib.sha256(local.encode()).hexdigest()[:6]
    return f"user_{hash_digest}@{domain}"
```

### Multiple Columns

One strategy can apply to multiple columns:

```python
@register_strategy('name')
def anonymize_name(value: str | None, field_name: str, ...) -> str | None:
    """Used for first_name, last_name, full_name."""
    if not value:
        return None
    return f"User_{len(value)}"  # User_4, User_5, etc.
```

### Column-Specific Logic

```python
@register_strategy('masked_value')
def smart_masking(value: str | None, field_name: str, ...) -> str | None:
    """Apply different masking based on column name."""
    if not value:
        return None

    if field_name == 'credit_card':
        return 'XXXX-XXXX-XXXX-0000'
    elif field_name == 'ssn':
        return 'XXX-XX-' + value[-4:]
    elif field_name == 'phone':
        return value[:3] + '-000-0000'

    return 'REDACTED'
```

---

## Anonymization Examples

### Example 1: Email Anonymization

```python
import hashlib
from confiture.anonymization import register_strategy

@register_strategy('email')
def anonymize_email(
    value: str | None,
    field_name: str,
    row_context: dict | None = None
) -> str | None:
    """
    Anonymize email while preserving domain.

    john.smith@example.com → user_a3b2c1@example.com
    """
    if not value or '@' not in value:
        return "invalid@example.com"

    local_part, domain = value.rsplit('@', 1)

    # Deterministic hash for consistency
    hash_digest = hashlib.sha256(local_part.encode()).hexdigest()
    masked = f"user_{hash_digest[:6]}@{domain}"

    return masked
```

**Examples**:
- `john@acme.com` → `user_a3b2c1@acme.com`
- `jane.doe@company.org` → `user_f7e3d9@company.org`
- `NULL` → `NULL`

---

### Example 2: Phone Number Masking

```python
import re
from confiture.anonymization import register_strategy

@register_strategy('phone')
def anonymize_phone(
    value: str | None,
    field_name: str,
    row_context: dict | None = None
) -> str | None:
    """
    Mask phone numbers, keep area code for pattern testing.

    555-123-4567 → 555-000-0000
    """
    if not value:
        return None

    # Extract digits
    digits = re.sub(r'\D', '', value)

    if len(digits) < 10:
        return None

    # Keep first 3 digits (area code), mask rest
    area_code = digits[:3]
    return f"{area_code}-000-0000"
```

**Examples**:
- `555-123-4567` → `555-000-0000`
- `(555) 987-6543` → `555-000-0000`
- `NULL` → `NULL`

---

### Example 3: SSN Masking (HIPAA-compliant)

```python
import re
from confiture.anonymization import register_strategy

@register_strategy('ssn')
def anonymize_ssn(
    value: str | None,
    field_name: str,
    row_context: dict | None = None
) -> str | None:
    """
    Mask SSN, keep last 4 digits for individual identification.

    123-45-6789 → XXX-XX-6789
    """
    if not value:
        return None

    # Extract digits
    digits = re.sub(r'\D', '', value)

    if len(digits) != 9:
        return None

    # Keep last 4 digits only
    last_four = digits[-4:]
    return f"XXX-XX-{last_four}"
```

**Examples**:
- `123-45-6789` → `XXX-XX-6789`
- `987-65-4321` → `XXX-XX-4321`

---

### Example 4: Deterministic Name Generation

```python
import hashlib
from confiture.anonymization import register_strategy

@register_strategy('name')
def anonymize_name(
    value: str | None,
    field_name: str,
    row_context: dict | None = None
) -> str | None:
    """
    Generate consistent pseudonym for person.

    Uses row context for consistency across columns.
    """
    if not value:
        return None

    # Use ID from row context for consistent names
    if row_context and 'id' in row_context:
        user_id = row_context['id']
        return f"User_{user_id:05d}"

    # Fallback: hash-based name
    hash_digest = hashlib.md5(value.encode()).hexdigest()
    hash_int = int(hash_digest, 16) % 100000
    return f"User_{hash_int:05d}"
```

**Examples**:
- Row 1: `John Smith` → `User_00001`
- Row 2: `Jane Doe` → `User_00002`
- Consistent across first_name, last_name, full_name

---

### Example 5: Credit Card Masking (PCI-DSS)

```python
import re
from confiture.anonymization import register_strategy

@register_strategy('credit_card')
def anonymize_credit_card(
    value: str | None,
    field_name: str,
    row_context: dict | None = None
) -> str | None:
    """
    Mask credit card, show only last 4 digits (PCI-DSS).

    4111-1111-1111-1111 → XXXX-XXXX-XXXX-1111
    """
    if not value:
        return None

    # Extract digits
    digits = re.sub(r'\D', '', value)

    if len(digits) not in (15, 16):  # Visa/Mastercard
        return None

    # Keep last 4 digits, mask rest
    last_four = digits[-4:]
    return f"XXXX-XXXX-XXXX-{last_four}"
```

**Examples**:
- `4111-1111-1111-1111` → `XXXX-XXXX-XXXX-1111`
- `5555-5555-5555-4444` → `XXXX-XXXX-XXXX-4444`

---

### Example 6: Conditional Masking

```python
from confiture.anonymization import register_strategy

@register_strategy('conditional')
def conditional_masking(
    value: str | None,
    field_name: str,
    row_context: dict | None = None
) -> str | None:
    """
    Different masking based on other fields.

    Example: Only anonymize if account is premium.
    """
    if not value:
        return None

    # Check if this is a premium account
    is_premium = row_context and row_context.get('is_premium', False)

    if is_premium:
        # More aggressive anonymization for premium accounts
        return f"REDACTED_{len(value)}"
    else:
        # Lighter anonymization for free accounts
        return value[:3] + '*' * (len(value) - 3)
```

**Examples**:
- Premium account: `secret_data` → `REDACTED_11`
- Free account: `secret_data` → `sec****data`

---

## Best Practices

### ✅ Do's

1. **Always handle None**
   ```python
   @register_strategy('email')
   def anonymize_email(value: str | None, ...) -> str | None:
       if value is None:
           return None  # Preserve NULL values
       # Anonymize non-NULL
   ```

2. **Use deterministic hashing**
   ```python
   import hashlib

   # Same input → same output (for consistency)
   hash_digest = hashlib.sha256(value.encode()).hexdigest()
   ```

3. **Preserve data structure**
   ```python
   # Good: Maintain format
   value[:3] + '-000-0000'  # Keeps phone format

   # Bad: Changes format
   "PHONE_" + str(len(value))  # Format change causes issues
   ```

4. **Document assumptions**
   ```python
   @register_strategy('email')
   def anonymize_email(value: str | None, ...) -> str | None:
       """
       Anonymize email addresses.

       Assumes: value is valid email format
       Returns: email with masked local part
       """
   ```

### ❌ Don'ts

1. **Don't use random values**
   ```python
   # Bad: Non-deterministic (causes inconsistency)
   import random
   return f"user_{random.randint(1000, 9999)}"

   # Good: Deterministic (consistent across runs)
   return f"user_{hash(value) % 10000}"
   ```

2. **Don't modify database during anonymization**
   ```python
   # Bad: Modifies data
   conn.execute("UPDATE table SET anonymized = true")

   # Good: Just return transformed value
   return anonymized_value
   ```

3. **Don't break referential integrity**
   ```python
   # Bad: Changes primary key
   return str(value).upper() + "_modified"

   # Good: Preserve referential keys
   return str(value)  # Keep ID structure
   ```

4. **Don't ignore validation errors**
   ```python
   # Bad: Silent failure
   try:
       return process_value(value)
   except:
       return value

   # Good: Explicit error handling
   try:
       return process_value(value)
   except ValueError as e:
       raise AnonymizationError(f"Invalid format: {e}")
   ```

---

## Performance Characteristics

### Typical Processing Speeds

| Operation | Rows/Second | Notes |
|-----------|------------|-------|
| Email hash | 100,000+ | Fast deterministic hash |
| Phone mask | 150,000+ | Regex simple replacement |
| Name generation | 80,000+ | Hash computation |
| Database lookup | 5,000-50,000 | Depends on DB |

**Recommendation**: Use pure Python operations when possible. Minimize database calls.

---

## Testing Strategies

### Unit Test Example

```python
import pytest
from my_strategies import anonymize_email

def test_email_anonymization():
    """Test email anonymization produces valid emails."""
    result = anonymize_email('john@example.com', 'email', None)

    assert result is not None
    assert '@' in result
    assert 'example.com' in result
    assert 'john' not in result

def test_email_deterministic():
    """Test same email produces same result."""
    email = 'john@example.com'

    result1 = anonymize_email(email, 'email', None)
    result2 = anonymize_email(email, 'email', None)

    assert result1 == result2  # Deterministic

def test_email_null_handling():
    """Test NULL email values."""
    result = anonymize_email(None, 'email', None)
    assert result is None
```

---

## Troubleshooting

### Problem: Inconsistent Anonymization

**Cause**: Using random values or non-deterministic functions

**Solution**:
```python
# Bad
return f"user_{random.randint(1000, 9999)}"

# Good: Use hash for determinism
import hashlib
hash_digest = hashlib.sha256(value.encode()).hexdigest()
return f"user_{hash_digest[:6]}"
```

### Problem: NULL Handling

**Cause**: Not checking for None before processing

**Solution**:
```python
# Bad
return value.upper() + "_masked"  # Fails if value is None

# Good
if value is None:
    return None
return value.upper() + "_masked"
```

### Problem: Type Mismatch

**Cause**: Returning wrong type for column

**Solution**:
```python
# For INTEGER columns
def anonymize_amount(value: int | None, ...) -> int | None:
    if value is None:
        return None
    return int(value / 1000) * 1000  # Return int, not str
```

---

## Security Considerations

### Anonymization ≠ Encryption

- ✅ **Anonymization**: Irreversible transformation (suitable for test data)
- ❌ **Encryption**: Reversible (only for actual encryption needs)

Use anonymization when:
- Creating test datasets from production data
- Developers need realistic data structure
- Data doesn't need to be recovered

### Compliance Notes

- **GDPR**: Fully anonymized data is exempt from GDPR
- **HIPAA**: De-identification must follow specific standards
- **PCI-DSS**: Card data must use PCI-compliant masking

---

## See Also

- [Anonymization Guide](../guides/anonymization.md) - User guide with patterns
- [Production Sync](../guides/03-production-sync.md) - Using anonymization with data sync
- [Compliance Guide](../guides/compliance.md) - HIPAA, GDPR, PCI-DSS examples

---

**Last Updated**: January 17, 2026

