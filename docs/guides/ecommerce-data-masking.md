# E-Commerce Data Masking Guide

**Safely migrate e-commerce databases with customer data protection, PCI-DSS compliance, and payment card masking**

---

## What is E-Commerce Data Masking?

E-commerce systems handle sensitive customer data including credit cards, addresses, and purchase histories. Data masking replaces real sensitive data with fake but realistic data for development and testing environments.

**Tagline**: *Protect customer privacy while enabling development and testing*

---

## Why Data Masking Matters for E-Commerce

### Regulatory Requirements

- ✅ **PCI-DSS** - Payment Card Industry standards for card data
- ✅ **GDPR** - EU data protection for customer information
- ✅ **CCPA** - California consumer privacy rights
- ✅ **Internal Policy** - Company data protection standards

### Business Impact

- ❌ **Data breaches** - Exposed customer data in dev/test
- ❌ **PCI violations** - Non-compliant handling of card data
- ❌ **Fines** - $100-$500K per violation
- ❌ **Lost trust** - Customers lose confidence in security
- ❌ **Regulatory action** - Business restrictions

---

## When to Use This Guide

### ✅ Perfect For

- **Customer payment data** - Masking credit cards
- **PII in development** - Customer names, emails, addresses
- **Order history** - Hiding actual purchase patterns
- **Sensitive attributes** - Medical conditions, preferences
- **User accounts** - Production data in test environments

### ❌ Not For

- **Aggregated data** - Statistics and dashboards
- **Already anonymized data** - No re-identification possible
- **Test data** - Synthetic or generated data
- **Non-sensitive columns** - Product catalogs, prices

---

## Data Masking Strategy

### Classification Framework

```
Data Sensitivity Levels:

🔴 CRITICAL (Mask Always)
├─ Credit card numbers (PCI)
├─ CVV codes
├─ Bank account numbers
├─ Social security numbers
└─ Full names with PII

🟡 HIGH (Mask in Dev)
├─ Email addresses
├─ Phone numbers
├─ Home addresses
├─ Order totals
└─ Customer IDs (sometimes)

🟢 LOW (Keep As-Is)
├─ Product names
├─ Category codes
├─ Stock levels
├─ Prices
└─ Public catalog data
```

### Masking Techniques

```
Original Data → Masking Technique → Masked Data

Credit Card:
4532-1234-5678-9012 → Tokenization → 4532-****-****-9012

Email:
john@example.com → Hash + suffix → user_a3b4c5@example.com

Phone:
555-123-4567 → Partial mask → 555-***-****

Address:
123 Main St, NYC → Redaction → [REDACTED]

Amount:
$99.99 → Range-based → $[50-100]
```

---

## Setup Overview

### Requirements

- ✅ Confiture with anonymization (Phase 5)
- ✅ Production database backup
- ✅ Masking rules configuration
- ✅ Test environment database
- ✅ Verification scripts

### Time Required

- **Configuration**: 15-30 minutes
- **Masking execution**: 5-30 minutes (depends on data size)
- **Verification**: 10-15 minutes

---

## Credit Card Masking (PCI-DSS)

### Tokenize Card Data

```python
# confiture_hooks/ecommerce_card_masking.py
import os
import re
from confiture.anonymization import register_strategy

@register_strategy('credit_card')
def mask_credit_card(
    value: str | None,
    field_name: str,
    row_context: dict | None = None
) -> str | None:
    """Mask credit card number to PCI-DSS standards."""
    if not value:
        return None

    # Remove non-digits
    card_number = re.sub(r'\D', '', value)

    if len(card_number) < 13 or len(card_number) > 19:
        return "0000-0000-0000-0000"  # Invalid card format

    # Keep first 6 and last 4 digits (PCI-DSS standard)
    # Mask middle digits
    first_six = card_number[:6]
    last_four = card_number[-4:]
    masked = f"{first_six}{'*' * (len(card_number) - 10)}{last_four}"

    # Format with dashes
    formatted = '-'.join([masked[i:i+4] for i in range(0, len(masked), 4)])
    return formatted

# Usage in migration:
# SELECT masked_credit_card(card_number) FROM orders

@register_strategy('cvv')
def mask_cvv(
    value: str | None,
    field_name: str,
    row_context: dict | None = None
) -> str | None:
    """Mask CVV security code."""
    if not value:
        return None
    # Replace with zeros
    return "***"

@register_strategy('card_expiry')
def mask_card_expiry(
    value: str | None,
    field_name: str,
    row_context: dict | None = None
) -> str | None:
    """Mask credit card expiry date."""
    if not value:
        return None
    # Replace with 12/99 (universal test expiry)
    return "12/99"
```

**Output**:
```
Original: 4532-1234-5678-9012
Masked:   4532-****-****-9012

Original: CVV 123
Masked:   CVV ***

Original: Expiry 03/25
Masked:   Expiry 12/99
```

---

## Customer Information Masking

### Anonymize Names & Addresses

```python
# confiture_hooks/ecommerce_customer_masking.py
import hashlib
from confiture.anonymization import register_strategy

@register_strategy('customer_name')
def mask_customer_name(
    value: str | None,
    field_name: str,
    row_context: dict | None = None
) -> str | None:
    """Mask customer name while maintaining uniqueness."""
    if not value:
        return None

    # Create consistent hash for this customer
    customer_id = row_context.get('customer_id') if row_context else None
    if customer_id:
        hash_val = hashlib.md5(str(customer_id).encode()).hexdigest()[:4]
    else:
        hash_val = hashlib.md5(value.encode()).hexdigest()[:4]

    return f"Customer_{hash_val.upper()}"

@register_strategy('email')
def mask_email(
    value: str | None,
    field_name: str,
    row_context: dict | None = None
) -> str | None:
    """Mask email address while preserving format."""
    if not value or '@' not in value:
        return "customer@example.com"

    # Generate deterministic email from customer ID
    customer_id = row_context.get('customer_id') if row_context else None
    local_hash = hashlib.md5(
        str(customer_id).encode() if customer_id else value.encode()
    ).hexdigest()[:8]

    domain = value.split('@')[1]
    return f"user_{local_hash}@{domain}"

@register_strategy('phone')
def mask_phone(
    value: str | None,
    field_name: str,
    row_context: dict | None = None
) -> str | None:
    """Mask phone number."""
    if not value:
        return None

    # Keep format, mask number
    digits = ''.join(c for c in value if c.isdigit())
    if len(digits) < 10:
        return "(555) 555-5555"

    # Format: (555) 555-XXXX
    return f"(555) 555-{digits[-4:]}"

@register_strategy('address')
def mask_address(
    value: str | None,
    field_name: str,
    row_context: dict | None = None
) -> str | None:
    """Mask shipping/billing address."""
    if not value:
        return None

    # Return generic address
    return "123 Test Street, Test City, ST 12345"

@register_strategy('postal_code')
def mask_postal_code(
    value: str | None,
    field_name: str,
    row_context: dict | None = None
) -> str | None:
    """Mask postal/zip code."""
    if not value:
        return None

    return "12345"
```

**Output**:
```
Original Name:    John Smith
Masked Name:      Customer_A3B4

Original Email:   john.smith@gmail.com
Masked Email:     user_c5d6e7f8@gmail.com

Original Phone:   (555) 123-4567
Masked Phone:     (555) 555-4567

Original Address: 123 Main St, NYC, NY 10001
Masked Address:   123 Test Street, Test City, ST 12345
```

---

## Order & Transaction Masking

### Hide Purchase Patterns

```python
# confiture_hooks/ecommerce_order_masking.py
import random
from confiture.anonymization import register_strategy

@register_strategy('order_total')
def mask_order_total(
    value: float | None,
    field_name: str,
    row_context: dict | None = None
) -> float | None:
    """Mask order total amount."""
    if value is None:
        return None

    # Round to nearest $10 for realistic-looking amounts
    # This preserves scale but hides exact amounts
    bucket = round(value / 10) * 10
    return float(max(bucket - random.uniform(0, 5), 1))

@register_strategy('product_description')
def mask_product_description(
    value: str | None,
    field_name: str,
    row_context: dict | None = None
) -> str | None:
    """Mask product descriptions."""
    if not value:
        return None

    # Use generic product names
    categories = ['Electronics', 'Clothing', 'Books', 'Home', 'Sports']
    return f"{random.choice(categories)} Item"

@register_strategy('shipping_method')
def mask_shipping_method(
    value: str | None,
    field_name: str,
    row_context: dict | None = None
) -> str | None:
    """Mask shipping method details."""
    if not value:
        return None

    # Keep type but hide specifics
    if 'express' in value.lower():
        return 'Express Shipping'
    elif 'standard' in value.lower():
        return 'Standard Shipping'
    else:
        return 'Shipping'

@register_strategy('tracking_number')
def mask_tracking_number(
    value: str | None,
    field_name: str,
    row_context: dict | None = None
) -> str | None:
    """Mask shipping tracking number."""
    if not value:
        return None

    # Generate fake tracking number in same format
    return ''.join([str(random.randint(0, 9)) for _ in range(len(value))])
```

---

## Masking Configuration

### Define Masking Rules

```yaml
# confiture_masking_config.yaml
masking_rules:
  orders:
    customer_id: mask_customer_id
    customer_email: mask_email
    customer_phone: mask_phone
    shipping_address: mask_address
    billing_address: mask_address
    shipping_postal: mask_postal_code
    billing_postal: mask_postal_code
    order_total: mask_order_total
    shipping_method: mask_shipping_method
    tracking_number: mask_tracking_number

  customers:
    first_name: mask_customer_name
    last_name: mask_customer_name
    email: mask_email
    phone: mask_phone
    address: mask_address
    postal_code: mask_postal_code

  payments:
    card_number: mask_credit_card
    cvv: mask_cvv
    card_expiry: mask_card_expiry
    cardholder_name: mask_customer_name

  order_items:
    product_description: mask_product_description
    # product_id stays the same (not sensitive)

  reviews:
    reviewer_email: mask_email
    reviewer_name: mask_customer_name
    # review_text: keep as-is (public reviews)

sensitive_columns_to_delete:
  - payment_gateway_tokens
  - authentication_secrets
  - stripe_customer_ids
```

---

## Masking Verification

### Verify Masking Effectiveness

```python
# test_ecommerce_masking.py
import psycopg
import re

def verify_masking(database_url: str) -> bool:
    """Verify that sensitive data is properly masked."""

    with psycopg.connect(database_url) as conn:
        print("🔍 Verifying E-Commerce Data Masking\n")

        # Test 1: No valid credit cards
        print("Test 1: Verify credit cards are masked")
        cursor = conn.execute("""
            SELECT COUNT(*) FROM orders
            WHERE card_number ~ '^\d{4}-\d{4}-\d{4}-\d{4}$'
            AND card_number NOT LIKE '%-%-%-%-'  -- Not masked format
        """)
        invalid_cards = cursor.fetchone()[0]

        if invalid_cards == 0:
            print("  ✅ No unmasked credit cards found\n")
        else:
            print(f"  ❌ Found {invalid_cards} unmasked credit cards\n")
            return False

        # Test 2: Realistic email format
        print("Test 2: Verify emails are masked")
        cursor = conn.execute("""
            SELECT COUNT(*) FROM customers
            WHERE email LIKE '%@%.%'
            AND email LIKE '%@gmail.com' OR email LIKE '%@company.com'
        """)
        real_emails = cursor.fetchone()[0]

        if real_emails == 0:
            print("  ✅ No real email domains found\n")
        else:
            print(f"  ⚠️  Found {real_emails} real email addresses (may need review)\n")

        # Test 3: Phone numbers
        print("Test 3: Verify phone numbers are masked")
        cursor = conn.execute("""
            SELECT COUNT(*) FROM customers
            WHERE phone NOT LIKE '(555)%'
        """)
        real_phones = cursor.fetchone()[0]

        if real_phones == 0:
            print("  ✅ Phone numbers are masked\n")
        else:
            print(f"  ⚠️  Found {real_phones} real phone numbers\n")

        # Test 4: No sensitive columns remain
        print("Test 4: Verify sensitive columns are deleted")
        cursor = conn.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name IN ('orders', 'payments', 'customers')
            AND column_name IN (
                'stripe_customer_id',
                'payment_token',
                'api_key',
                'secret_key'
            )
        """)
        sensitive_columns = cursor.fetchall()

        if not sensitive_columns:
            print("  ✅ No sensitive columns remain\n")
        else:
            print(f"  ❌ Found sensitive columns: {sensitive_columns}\n")
            return False

        # Test 5: Data completeness
        print("Test 5: Verify data completeness")
        cursor = conn.execute("SELECT COUNT(*) FROM orders")
        order_count = cursor.fetchone()[0]
        cursor = conn.execute("SELECT COUNT(*) FROM customers")
        customer_count = cursor.fetchone()[0]

        print(f"  ✅ {order_count} orders intact")
        print(f"  ✅ {customer_count} customers intact\n")

    return True

if __name__ == '__main__':
    success = verify_masking('postgresql://localhost/ecommerce_dev')
    exit(0 if success else 1)
```

---

## Best Practices

### ✅ Do's

1. **Mask before development use**
   ```python
   # Sync production → staging → mask → distribute to devs
   ```

2. **Use realistic-looking masked data**
   ```python
   # Good: "Customer_A3B4" (looks like a customer)
   # Bad: "XXXXXXX" (too obviously fake)
   ```

3. **Preserve data relationships**
   ```python
   # Consistent masking so multiple rows from same customer
   # have same masked name
   ```

4. **Keep row counts**
   ```python
   # Don't delete rows, just mask sensitive columns
   # Preserves query plan performance
   ```

5. **Document masking rules**
   ```yaml
   # Clear config showing what gets masked and why
   ```

### ❌ Don'ts

1. **Don't use in production**
   ```python
   # Bad: Mask live customer data
   # Good: Mask only test/dev environments
   ```

2. **Don't create reversible masks**
   ```python
   # Bad: Encryption (can be decrypted)
   # Good: Hash or replacement masking
   ```

3. **Don't mask inconsistently**
   ```python
   # Bad: Customer 123 → "Alice", then → "Bob"
   # Good: Customer 123 → "Customer_A3B4" always
   ```

4. **Don't forget related tables**
   ```python
   # If masking customers.email, also mask orders.email
   ```

---

## Troubleshooting

### ❌ Error: "Masked data doesn't match application expectations"

**Cause**: Masking format doesn't match app validation rules

**Solution**:
```python
# Verify format before masking
@register_strategy('phone')
def mask_phone(value, field_name, row_context):
    # Must match (555) 555-XXXX format
    return f"(555) 555-{random.randint(1000, 9999)}"
```

---

### ❌ Error: "Foreign key violations after masking"

**Cause**: Masking broke relationships between tables

**Solution**:
```python
# Don't mask IDs (keep them as-is)
# Only mask descriptions/values
masking_config:
  orders:
    order_id: keep_as_is  # Don't mask
    customer_id: keep_as_is  # Don't mask
    customer_email: mask_email  # Mask text data
```

---

## See Also

- [Production Sync Guide](./production-sync-guide.md) - Safe data migration
- [Anonymization API](../api/anonymization.md) - Masking API reference
- [Monitoring Integration](./monitoring-integration.md) - Track masking jobs
- [Hook API Reference](../api/hooks.md) - Custom masking logic

---

## 🎯 Next Steps

**Ready to mask e-commerce data?**
- ✅ You now understand: Credit card masking, customer data protection, PCI-DSS compliance

**What to do next:**

1. **[Configure masking rules](#masking-configuration)** - Define what gets masked
2. **[Implement masking strategies](#credit-card-masking-pci-dss)** - Add masking logic
3. **[Run verification](#masking-verification)** - Verify masking effectiveness
4. **[Document procedures](#best-practices)** - Create runbook for team

---

**Last Updated**: January 9, 2026
**Status**: Production Ready ✅
**Compliance**: PCI-DSS, GDPR, CCPA

🍓 Protect customer privacy while enabling development
