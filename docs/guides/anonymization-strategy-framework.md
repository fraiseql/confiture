# Anonymization Strategy Framework Guide

**Table of Contents**
1. [Overview](#overview)
2. [Core Components](#core-components)
3. [Available Strategies](#available-strategies)
4. [Using Strategies](#using-strategies)
5. [Creating Custom Strategies](#creating-custom-strategies)
6. [Strategy Composition](#strategy-composition)
7. [Best Practices](#best-practices)

---

## Overview

The Confiture anonymization framework provides a flexible, extensible system for data protection through multiple anonymization strategies. Each strategy implements a specific anonymization technique designed for particular data types.

### Key Design Principles

- **Separation of Concerns**: Each strategy handles one type of anonymization
- **Composability**: Strategies can be chained together for complex anonymization
- **Determinism**: Seed-based hashing ensures reproducible anonymization
- **Type Safety**: Full type hints for production readiness
- **Extensibility**: Create custom strategies by extending the base class

---

## Core Components

### 1. AnonymizationStrategy (Base Class)

```python
from confiture.core.anonymization.strategy import AnonymizationStrategy

class AnonymizationStrategy(ABC):
    """Base class for all anonymization strategies."""

    config_type: Type[StrategyConfig]  # Configuration class
    strategy_name: str                  # Unique strategy identifier

    @abstractmethod
    def anonymize(self, value: Any) -> Any:
        """Anonymize a single value."""

    @abstractmethod
    def validate(self, value: Any) -> bool:
        """Check if value is valid for this strategy."""
```

**Key Methods**:
- `anonymize()`: Core method that performs the anonymization
- `validate()`: Checks if a value is appropriate for the strategy
- `config_type`: Pydantic model defining strategy configuration

### 2. StrategyRegistry

Singleton registry for managing strategies:

```python
from confiture.core.anonymization.registry import StrategyRegistry

# Register a strategy
StrategyRegistry.register("my_strategy", MyCustomStrategy)

# Retrieve a strategy
strategy = StrategyRegistry.get("my_strategy", config={"seed": 42})

# List available strategies
available = StrategyRegistry.list_available()

# Check if strategy is registered
is_registered = StrategyRegistry.is_registered("my_strategy")
```

### 3. StrategyFactory

Creates anonymization operations from profiles:

```python
from confiture.core.anonymization.factory import StrategyFactory, StrategyProfile

# Define a profile
profile = StrategyProfile(
    name="user_anonymization",
    seed=42,
    columns={
        "name": "name",
        "email": "text_redaction",
        "age": "preserve",
    },
    defaults="preserve"
)

# Create factory
factory = StrategyFactory(profile)

# Anonymize data
data = {"name": "John Smith", "email": "john@example.com", "age": 30}
anonymized = factory.anonymize(data)
```

### 4. StrategyComposer

Chain multiple strategies for complex anonymization:

```python
from confiture.core.anonymization.composer import StrategyComposer

# Compose strategies: first hash, then redact
composer = StrategyComposer([
    ("text_redaction", {}),
    ("custom", {"func": lambda x: x[:10]}),  # Truncate to 10 chars
])

result = composer.anonymize("very_long_secret_value")
```

---

## Available Strategies

### 1. **Name Masking** (`name`)

Anonymizes personal names with multiple formats.

```python
strategy = StrategyRegistry.get("name", {
    "seed": 42,
    "format_type": "firstname_lastname",  # Options: firstname_lastname, initials, random
})

result = strategy.anonymize("John Smith")
# Result: "Michael Johnson" (firstname_lastname)
# Result: "J.S." (initials)
# Result: "QX" (random)
```

**Configuration**:
- `seed`: Random seed for reproducibility
- `format_type`: Output format (firstname_lastname, initials, random)

**Use Cases**: Names, author names, provider names

### 2. **Date Masking** (`date`)

Masks dates while preserving temporal patterns.

```python
strategy = StrategyRegistry.get("date", {
    "seed": 42,
    "mode": "year_month",  # Options: none, year, year_month
    "format": "iso",       # Options: iso, us, uk, europe, slash, dash
})

result = strategy.anonymize("1990-05-15")
# Result: "1990-05-XX" (year_month mode)
# Result: "1990-XX-XX" (year mode)
```

**Configuration**:
- `seed`: Random seed
- `mode`: Preservation level (none, year, year_month)
- `format`: Output date format

**Use Cases**: Birthdate, appointment dates, transaction dates

### 3. **Address Masking** (`address`)

Masks address while preserving geographic context.

```python
strategy = StrategyRegistry.get("address", {
    "seed": 42,
    "format": "freetext",  # Options: freetext, structured
    "preserve_fields": ["city", "state", "country"],
})

result = strategy.anonymize("123 Main St, Springfield, IL 62701")
# Result: "456 Oak Ave, Springfield, IL 62701"
```

**Configuration**:
- `seed`: Random seed
- `format`: Address format (freetext, structured)
- `preserve_fields`: Fields to keep unchanged

**Use Cases**: Street addresses, billing addresses

### 4. **Credit Card Masking** (`credit_card`)

PCI-DSS compliant credit card masking.

```python
strategy = StrategyRegistry.get("credit_card", {
    "seed": 42,
    "preserve_last4": True,  # Show last 4 digits
    "preserve_bin": True,    # Preserve Bank Identification Number
})

result = strategy.anonymize("4532-1234-5678-9010")
# Result: "4532-XXXX-XXXX-9010"
```

**Features**:
- Luhn checksum validation
- Preserves card format (dashes, spaces)
- Generates valid test card numbers

**Configuration**:
- `preserve_last4`: Keep last 4 digits visible
- `preserve_bin`: Keep BIN (first 6 digits)
- `seed`: Random seed

**Use Cases**: Payment information, subscription data

### 5. **IP Address Masking** (`ip_address`)

IPv4/IPv6 anonymization with subnet preservation.

```python
strategy = StrategyRegistry.get("ip_address", {
    "seed": 42,
    "preserve_subnet": True,  # Keep subnet
    "ipv6_format": "full",    # Options: full, compressed
})

result = strategy.anonymize("192.168.1.100")
# Result: "192.168.XX.XX" (preserve_subnet=True)
# Result: "XXX.XXX.XXX.XXX" (preserve_subnet=False)
```

**Configuration**:
- `preserve_subnet`: Keep network portion
- `ipv6_format`: IPv6 output format

**Use Cases**: Access logs, tracking data, device information

### 6. **Text Redaction** (`text_redaction`)

Pattern-based redaction using built-in patterns.

```python
strategy = StrategyRegistry.get("text_redaction", {
    "seed": 42,
    "pattern": "email",  # Options: email, phone_us, ssn, credit_card, url, ipv4, date_us
})

result = strategy.anonymize("contact@example.com")
# Result: "[EMAIL]"
```

**Built-in Patterns**:
- `email`: john@example.com → [EMAIL]
- `phone_us`: (555) 123-4567 → [PHONE]
- `ssn`: 123-45-6789 → [SSN]
- `credit_card`: 4532-1234-5678-9010 → [CC]
- `url`: https://example.com → [URL]
- `ipv4`: 192.168.1.1 → [IP]
- `date_us`: 12/25/2024 → [DATE]

**Use Cases**: Email addresses, phone numbers, social security numbers

### 7. **IP Address Masking** (`ip_address`)

Comprehensive IPv4/IPv6 anonymization.

```python
strategy = StrategyRegistry.get("ip_address", {
    "seed": 42,
    "preserve_subnet": True,
})

# IPv4
result = strategy.anonymize("192.168.1.100")

# IPv6
result = strategy.anonymize("2001:db8::1")
```

### 8. **Preserve Strategy** (`preserve`)

No-op strategy for columns that should not be anonymized.

```python
strategy = StrategyRegistry.get("preserve", {})

result = strategy.anonymize("any_value")
# Result: "any_value" (unchanged)
```

**Use Cases**: IDs, reference numbers, business metrics

### 9. **Custom Strategy** (`custom`)

Execute arbitrary function for anonymization.

```python
strategy = StrategyRegistry.get("custom", {
    "seed": 42,
    "func": lambda x: x[:3] + "***" if len(x) > 3 else x,
})

result = strategy.anonymize("secretdata")
# Result: "sec***"
```

### 10. **Custom Lambda Strategy** (`custom_lambda`)

Execute lambda function (alternate form).

```python
strategy = StrategyRegistry.get("custom_lambda", {
    "seed": 42,
    "func": lambda x: "***" + x[-3:] if len(x) > 3 else "***",
})

result = strategy.anonymize("password123")
# Result: "***123"
```

---

## Using Strategies

### Method 1: Direct Strategy Usage

```python
from confiture.core.anonymization.registry import StrategyRegistry

# Get strategy from registry
strategy = StrategyRegistry.get("name", {"seed": 42})

# Anonymize values
data = ["John Smith", "Jane Doe", "Bob Johnson"]
anonymized = [strategy.anonymize(name) for name in data]
```

### Method 2: Using Factory with Profile

```python
from confiture.core.anonymization.factory import StrategyFactory, StrategyProfile

# Define profile
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

# Create and use factory
factory = StrategyFactory(profile)

data = {
    "user_id": "USR-001",
    "name": "John Smith",
    "email": "john@example.com",
    "phone": "(555) 123-4567",
    "birthdate": "1990-05-15",
    "ip_address": "192.168.1.100",
}

anonymized = factory.anonymize(data)
```

### Method 3: Using Scenarios

```python
from confiture.scenarios.healthcare import HealthcareScenario
from confiture.scenarios.compliance import RegulationType

# Anonymize with specific regulation
data = {
    "patient_id": "PAT-001",
    "patient_name": "John Smith",
    "ssn": "123-45-6789",
    "diagnosis": "E11",
}

# GDPR compliance
anonymized = HealthcareScenario.anonymize(data, RegulationType.GDPR)

# Verify compliance
result = HealthcareScenario.verify_compliance(data, anonymized, RegulationType.GDPR)
print(f"Compliant: {result['compliant']}")
```

---

## Creating Custom Strategies

### Step 1: Define Configuration Class

```python
from pydantic import BaseModel

class MyStrategyConfig(BaseModel):
    """Configuration for custom strategy."""
    seed: int = 42
    max_length: int = 10
    prefix: str = "ANON_"
```

### Step 2: Implement Strategy Class

```python
from confiture.core.anonymization.strategy import AnonymizationStrategy
from confiture.core.anonymization.registry import StrategyRegistry

class MyStrategy(AnonymizationStrategy):
    """Custom anonymization strategy."""

    config_type = MyStrategyConfig
    strategy_name = "my_strategy"

    def __init__(self, config: MyStrategyConfig):
        """Initialize strategy with configuration."""
        self.config = config

    def anonymize(self, value: Any) -> Any:
        """Anonymize value."""
        if not self.validate(value):
            return value

        # Custom anonymization logic
        anonymized = str(value)[:self.config.max_length]
        return f"{self.config.prefix}{anonymized}"

    def validate(self, value: Any) -> bool:
        """Validate value for anonymization."""
        return isinstance(value, str) and len(value) > 0
```

### Step 3: Register Strategy

```python
# Register the strategy
StrategyRegistry.register("my_strategy", MyStrategy)

# Use the strategy
strategy = StrategyRegistry.get("my_strategy", {
    "seed": 42,
    "max_length": 5,
    "prefix": "SECRET_"
})

result = strategy.anonymize("sensitive_data")
# Result: "SECRET_sensi"
```

---

## Strategy Composition

### Chaining Strategies

```python
from confiture.core.anonymization.composer import StrategyComposer

# Compose multiple strategies
composer = StrategyComposer([
    ("name", {"seed": 42, "format_type": "firstname_lastname"}),
    ("text_redaction", {"seed": 42, "pattern": "email"}),
])

# First applies name strategy, then text redaction
result = composer.anonymize("John Smith <john@example.com>")
```

### Using in Profiles

```python
profile = StrategyProfile(
    name="complex_anonymization",
    seed=42,
    columns={
        # Chain text redaction with custom truncation
        "document_content": "compose:text_redaction,custom",
    }
)
```

---

## Best Practices

### 1. Use Consistent Seeds

```python
# ✅ GOOD: Same seed across all operations
factory1 = StrategyFactory(profile)  # seed=42
factory2 = StrategyFactory(profile)  # seed=42

data1 = factory1.anonymize({"name": "John"})
data2 = factory2.anonymize({"name": "John"})
assert data1["name"] == data2["name"]  # Guaranteed match

# ❌ BAD: Different seeds produce different results
factory1 = StrategyFactory(profile_a)  # seed=42
factory2 = StrategyFactory(profile_b)  # seed=99
```

### 2. Preserve Identifiers and Business Data

```python
# ✅ GOOD: Preserve identifiers for tracking
profile = StrategyProfile(
    columns={
        "customer_id": "preserve",      # Keep for joins
        "order_id": "preserve",         # Keep for tracking
        "purchase_amount": "preserve",  # Keep for analytics
        "name": "name",                 # Anonymize PII
        "email": "text_redaction",      # Anonymize PII
    }
)

# ❌ BAD: Anonymizing identifiers breaks data relationships
profile = StrategyProfile(
    columns={
        "customer_id": "name",          # Now can't join tables!
        "order_id": "text_redaction",   # Can't track orders!
    }
)
```

### 3. Choose Appropriate Strategies

```python
# ✅ GOOD: Match strategy to data type
profile = StrategyProfile(
    columns={
        "birth_date": "date",           # For dates
        "email": "text_redaction",      # For emails
        "phone": "text_redaction:phone_us",  # For US phones
        "ip_address": "ip_address",     # For IPs
        "full_name": "name",            # For names
    }
)

# ❌ BAD: Generic redaction loses structure
profile = StrategyProfile(
    columns={
        "birth_date": "text_redaction",      # Loses date format
        "email": "name",                      # Wrong strategy
        "phone": "text_redaction",           # Not formatted
        "ip_address": "text_redaction",      # Loses structure
        "full_name": "text_redaction",       # Not natural
    }
)
```

### 4. Validate Before Anonymizing

```python
# ✅ GOOD: Check validation before processing
strategy = StrategyRegistry.get("name")

if strategy.validate(value):
    anonymized = strategy.anonymize(value)
else:
    # Handle invalid values appropriately
    anonymized = value  # Preserve or log

# ❌ BAD: Assume all values are valid
anonymized = strategy.anonymize(value)  # May fail silently
```

### 5. Test Anonymization

```python
# ✅ GOOD: Verify anonymization works as expected
profile = StrategyProfile(
    name="test",
    seed=42,
    columns={"name": "name", "email": "text_redaction"}
)

factory = StrategyFactory(profile)

# Test cases
test_data = [
    {"name": "John Smith", "email": "john@example.com"},
    {"name": "Jane Doe", "email": "jane@example.com"},
]

results = [factory.anonymize(data) for data in test_data]

# Verify structure preserved
for result in results:
    assert "name" in result
    assert "email" in result

# Verify anonymization happened
assert results[0]["name"] != "John Smith"
assert results[0]["email"] != "john@example.com"
```

---

## Configuration Best Practices

### 1. Always Specify Seed

```python
# Specify seed explicitly
profile = StrategyProfile(
    name="reproducible",
    seed=42,  # Explicit seed
    columns={...}
)
```

### 2. Use Defaults Wisely

```python
# Use defaults for consistent behavior
profile = StrategyProfile(
    name="safe_defaults",
    seed=42,
    columns={
        "customer_id": "preserve",
        "order_id": "preserve",
    },
    defaults="preserve"  # Default to preserving unknown columns
)
```

### 3. Document Column Mappings

```python
profile = StrategyProfile(
    name="documented",
    seed=42,
    columns={
        # Identifiers - preserved for data integrity
        "customer_id": "preserve",
        "order_id": "preserve",

        # PII - masked for privacy
        "customer_name": "name",
        "email_address": "text_redaction",
        "phone_number": "text_redaction:phone_us",

        # Sensitive - masked for security
        "credit_card": "credit_card",
        "ssn": "text_redaction",

        # Business metrics - preserved for analysis
        "purchase_amount": "preserve",
        "purchase_date": "date",
    },
    defaults="preserve"
)
```

---

## Performance Considerations

### Strategy Selection Impact

Performance from fastest to slowest:
1. **Preserve** (~1000+ ops/sec) - No-op
2. **Name/Date/IP** (~500-1000 ops/sec) - Simple randomization
3. **Text Redaction** (~100-500 ops/sec) - Pattern matching
4. **Credit Card** (~50-200 ops/sec) - Luhn validation
5. **Custom** (variable) - Depends on function

### Batch Processing

```python
# ✅ GOOD: Reuse factory for batch operations
factory = StrategyFactory(profile)
results = [factory.anonymize(record) for record in large_batch]

# ❌ BAD: Create new factory for each record
results = [StrategyFactory(profile).anonymize(record) for record in large_batch]
```

### Memory Usage

```python
# Strategies are small (~1-5 KB each)
# Factories cache strategy instances
# Profiles are lightweight (100 KB typical)

import sys
from confiture.core.anonymization.registry import StrategyRegistry

strategy = StrategyRegistry.get("name")
size = sys.getsizeof(strategy)  # ~1-5 KB
```

---

## Troubleshooting

### Strategy Not Found

```python
# Error: ValueError: Unknown strategy: 'my_strategy'

# Check if registered
from confiture.core.anonymization.registry import StrategyRegistry
available = StrategyRegistry.list_available()
print(available)

# Register if missing
from confiture.scenarios.healthcare import HealthcareScenario
# import scenarios to trigger registration
```

### Configuration Validation Error

```python
# Error: ValidationError: field 'seed' must be integer

# Check configuration matches config_type
from confiture.core.anonymization.registry import StrategyRegistry

strategy_class = StrategyRegistry.get_strategy_class("name")
config = strategy_class.config_type(seed=42)  # Must be int
```

### Anonymization Not Changing Values

```python
# Check if using 'preserve' strategy
profile = StrategyProfile(
    columns={
        "name": "preserve",  # ← This won't anonymize!
    }
)

# Use appropriate strategy
profile = StrategyProfile(
    columns={
        "name": "name",  # ← This will anonymize
    }
)
```

---

## See Also

- [Performance Benchmarking Guide](./performance-benchmarking.md)
- [Multi-Region Compliance Guide](./multi-region-compliance.md)
- [Real-World Scenarios Guide](./real-world-scenarios.md)
- [API Reference](../api/)
