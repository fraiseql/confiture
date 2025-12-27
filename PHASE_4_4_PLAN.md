# Phase 4.4: Custom Anonymization Strategies

**Status**: Ready for Review
**Complexity**: High (architectural design + new feature)
**Estimated Scope**: ~1500 lines of code + tests
**Core Principle**: Extensible, YAML-configurable, deterministic hashing

---

## Current State Analysis

### Existing Anonymization System (Phase 3)

**Location**: `python/confiture/core/syncer.py` (lines 32-206)

**Current Implementation**:
- 5 hardcoded strategies: `email`, `phone`, `name`, `redact`, `hash`
- Simple rule application in `_anonymize_value()` method
- String-based strategy selection with if/elif chain
- No composability or extensibility

**Limitations Addressed by Phase 4.4**:
- ❌ Cannot add custom strategies without modifying syncer.py
- ❌ No profile system (YAML configs for strategy groups)
- ❌ No chainable/composable strategies
- ❌ No verification/compliance checking
- ❌ No context-aware rules (conditional application)
- ❌ No audit trail or detailed reporting

---

## Architecture Design

### 1. AnonymizationStrategy Interface (Abstract Base Class)

**Location**: `python/confiture/core/anonymization/strategy.py` (NEW)

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

@dataclass
class StrategyConfig:
    """Base configuration for any strategy."""
    seed: int | None = None
    name: str = ""

class AnonymizationStrategy(ABC):
    """Base class for all anonymization strategies.

    Strategies must be:
    1. Deterministic (same input = same output if seeded)
    2. Type-aware (handle NULL, integers, strings differently)
    3. PII-preserving (maintain data properties for testing)
    4. Chainable (can be composed with other strategies)
    """

    def __init__(self, config: StrategyConfig | None = None):
        self.config = config or StrategyConfig()

    @abstractmethod
    def anonymize(self, value: Any) -> Any:
        """Apply anonymization to value.

        Must handle None/NULL values (return None).
        Must be deterministic if seed is set.
        """
        raise NotImplementedError

    @abstractmethod
    def validate(self, value: Any) -> bool:
        """Check if strategy can handle this value type."""
        raise NotImplementedError

    def name_short(self) -> str:
        """Short name for strategy (e.g., 'email_mask')."""
        return self.__class__.__name__.replace("Strategy", "").lower()
```

### 2. Built-in Strategies (6 implementations)

**Location**: `python/confiture/core/anonymization/strategies/` (NEW DIRECTORY)

#### **2.1 DeterministicHashStrategy**
```python
# strategies/hash.py
@dataclass
class DeterministicHashConfig(StrategyConfig):
    algorithm: str = "sha256"  # sha256, sha1, md5
    length: int | None = None   # Truncate to N chars (None = full)
    prefix: str = ""            # Add prefix (e.g., "hash_")

class DeterministicHashStrategy(AnonymizationStrategy):
    """One-way hash with configurable algorithm and truncation.

    Features:
    - Preserves uniqueness (same input = same hash)
    - Supports algorithm selection
    - Optional length truncation
    - Optional prefix (e.g., "user_")

    Example:
        DeterministicHashStrategy(
            DeterministicHashConfig(
                algorithm="sha256",
                length=16,
                prefix="user_"
            )
        )
    """
```

#### **2.2 EmailMaskingStrategy**
```python
# strategies/email.py
@dataclass
class EmailMaskConfig(StrategyConfig):
    format: str = "user_{hash}@example.com"  # Customizable format
    hash_length: int = 8
    preserve_domain: bool = False  # Optional: keep original domain

class EmailMaskingStrategy(AnonymizationStrategy):
    """Generate deterministic fake emails from real ones.

    Features:
    - Deterministic: same email = same fake email (if seeded)
    - Format customization (template-based)
    - Optional domain preservation for testing
    - Proper email format validation

    Examples:
        - Input: "john@example.com" → Output: "user_a1b2c3d4@example.com"
        - With preserve_domain: "john@example.com" → "user_a1b2c3d4@example.com"
    """
```

#### **2.3 PhoneMaskingStrategy**
```python
# strategies/phone.py
@dataclass
class PhoneMaskConfig(StrategyConfig):
    format: str = "+1-555-{number}"  # Customizable format
    preserve_country_code: bool = False

class PhoneMaskingStrategy(AnonymizationStrategy):
    """Generate deterministic fake phone numbers.

    Features:
    - Format templates (e.g., "+1-555-{number}", "555-{number}")
    - Deterministic generation from original number
    - Preserves international format if requested
    - Validates output format

    Examples:
        - Input: "+1-202-555-0123" → Output: "+1-555-0123"
        - Input: "202-555-0123" → Output: "555-0123"
    """
```

#### **2.4 PatternBasedStrategy**
```python
# strategies/pattern.py
@dataclass
class PatternBasedConfig(StrategyConfig):
    pattern: str  # Regex pattern to match
    replacement: str = "[MASKED]"  # What to replace with

class PatternBasedStrategy(AnonymizationStrategy):
    """Regex-based redaction of PII patterns.

    Features:
    - Custom regex patterns for PII detection
    - Flexible replacement (static or dynamic)
    - Useful for SSNs, credit cards, etc.

    Examples:
        PatternBasedConfig(
            pattern=r"\d{3}-\d{2}-\d{4}",  # SSN
            replacement="[SSN]"
        )
    """
```

#### **2.5 ConditionalStrategy**
```python
# strategies/conditional.py
from typing import Callable

@dataclass
class ConditionalConfig(StrategyConfig):
    condition: Callable[[Any], bool]  # Predicate function
    strategy_if_true: AnonymizationStrategy
    strategy_if_false: AnonymizationStrategy | None = None

class ConditionalStrategy(AnonymizationStrategy):
    """Apply different strategies based on a condition.

    Features:
    - Context-aware anonymization
    - Chainable strategy selection
    - Useful for column-specific rules

    Example:
        # Anonymize emails differently based on domain
        ConditionalStrategy(
            ConditionalConfig(
                condition=lambda val: "@internal.com" in val,
                strategy_if_true=SimpleRedactStrategy(),
                strategy_if_false=EmailMaskingStrategy()
            )
        )
    """
```

#### **2.6 SimpleRedactStrategy**
```python
# strategies/redact.py
@dataclass
class RedactConfig(StrategyConfig):
    replacement: str = "[REDACTED]"

class SimpleRedactStrategy(AnonymizationStrategy):
    """Simple one-size-fits-all redaction.

    Features:
    - Customizable replacement text
    - Fast (no hashing needed)
    - Zero information leakage

    Use when: PII is sensitive and no testing needs real-like data
    """
```

### 3. AnonymizationProfile System

**Location**: `python/confiture/core/anonymization/profile.py` (NEW)

**YAML Configuration Format**:

```yaml
# db/anonymization-profiles/production.yaml

name: production

# Environment inheritance (optional)
inherits_from: base

# Strategy definitions (reusable across tables)
strategies:
  email_mask:
    type: email
    config:
      format: "user_{hash}@example.com"
      hash_length: 8

  phone_mask:
    type: phone
    config:
      format: "+1-555-{number}"

  hash_pii:
    type: hash
    config:
      algorithm: sha256
      length: 16
      prefix: "h_"

  redact_ssn:
    type: pattern
    config:
      pattern: "\d{3}-\d{2}-\d{4}"
      replacement: "[SSN]"

# Table anonymization rules
tables:
  users:
    rules:
      - column: email
        strategy: email_mask
        seed: 12345  # Optional: for deterministic results

      - column: phone
        strategy: phone_mask

      - column: ssn
        strategy: redact_ssn

      - column: bio
        strategy: hash_pii

  orders:
    rules:
      - column: user_email
        strategy: email_mask

      - column: payment_method
        strategy: hash_pii

      - column: notes
        strategy: hash_pii

# Compliance rules (Phase 4.5+)
compliance:
  min_hash_length: 8
  disallow_strategies:
    - simple_redact  # For sensitive data
  required_patterns:
    - email
    - phone
```

**Python Interface**:

```python
@dataclass
class AnonymizationRule:
    """Enhanced rule structure."""
    column: str
    strategy: str  # Reference to strategy defined in profile
    seed: int | None = None
    options: dict[str, Any] | None = None  # Override strategy config

@dataclass
class AnonymizationProfile:
    """Loaded profile with resolved strategies."""
    name: str
    description: str = ""

    # Strategy instances (resolved from YAML)
    strategies: dict[str, AnonymizationStrategy]

    # Table-specific rules
    tables: dict[str, list[AnonymizationRule]]

    # Inheritance chain
    inherits_from: str | None = None

    # Compliance settings
    compliance_rules: dict[str, Any]

    @classmethod
    def load(cls, profile_name: str, project_dir: Path | None = None) -> "AnonymizationProfile":
        """Load profile from db/anonymization-profiles/{name}.yaml"""
        ...

    def get_rules_for_table(self, table_name: str) -> list[AnonymizationRule]:
        """Get rules for specific table."""
        ...

    def merge(self, other: "AnonymizationProfile") -> "AnonymizationProfile":
        """Merge profiles (for inheritance)."""
        ...
```

### 4. AnonymizationProfileManager

**Location**: `python/confiture/core/anonymization/manager.py` (NEW)

```python
class AnonymizationProfileManager:
    """Manages loading, caching, and composing profiles.

    Features:
    - Load profiles from YAML
    - Cache loaded profiles
    - Resolve strategy inheritance
    - Validate profiles against schemas
    - PrintOptim-specific default profiles
    """

    def __init__(self, project_dir: Path | None = None):
        self.project_dir = project_dir or Path.cwd()
        self.profiles_dir = self.project_dir / "db" / "anonymization-profiles"
        self._cache: dict[str, AnonymizationProfile] = {}

    def load_profile(self, name: str) -> AnonymizationProfile:
        """Load profile with caching."""
        ...

    def get_default_profile(self, env_name: str) -> AnonymizationProfile:
        """Get built-in profile for environment.

        Built-in profiles:
        - local: Full data, no anonymization (EMAIL + PHONE visible)
        - test: Heavy anonymization (all PII masked)
        - staging: Medium anonymization (hashed emails, redacted phones)
        - production: Heavy anonymization (all PII masked/redacted)
        """
        ...

    def list_profiles(self) -> list[str]:
        """List all available profiles."""
        ...
```

### 5. Enhanced ProductionSyncer (Phase 3 Update)

**Location**: `python/confiture/core/syncer.py` (MODIFIED)

```python
from confiture.core.anonymization.strategy import AnonymizationStrategy
from confiture.core.anonymization.profile import AnonymizationProfile

class ProductionSyncer:
    """Update Phase 3 implementation for new strategy system."""

    def __init__(
        self,
        source: DatabaseConfig | str,
        target: DatabaseConfig | str,
        profile: AnonymizationProfile | None = None,  # NEW
    ):
        # ... existing code ...
        self.profile = profile or AnonymizationProfileManager().get_default_profile("test")

    def _anonymize_value(self,
                        value: Any,
                        column_name: str,
                        table_name: str) -> Any:
        """Enhanced anonymization using strategy system.

        NEW: Uses profile-based strategy lookup instead of string matching.
        """
        # Get rules for this column from profile
        rules = self.profile.get_rules_for_table(table_name)
        for rule in rules:
            if rule.column == column_name:
                strategy = self.profile.strategies[rule.strategy]
                return strategy.anonymize(value)

        # No rule found, return unchanged
        return value

    def sync_table_with_profile(self,
                               table_name: str,
                               profile: AnonymizationProfile) -> int:
        """Sync table using profile (replaces anonymization_rules parameter)."""
        rules = profile.get_rules_for_table(table_name)
        return self.sync_table(table_name, rules)
```

### 6. AnonymizationVerifier (Compliance & Audit)

**Location**: `python/confiture/core/anonymization/verifier.py` (NEW)

```python
@dataclass
class VerificationResult:
    """Verification result for a sync operation."""
    table_name: str
    compliant: bool
    issues: list[str]
    coverage: dict[str, float]  # % of sensitive columns anonymized
    anonymized_columns: list[str]
    unprotected_columns: list[str]

class AnonymizationVerifier:
    """Verify anonymization compliance and coverage.

    Features:
    - Check if sensitive columns are anonymized
    - Detect PII patterns in data (regex-based)
    - Generate audit reports
    - Validate against compliance rules
    - Coverage reporting (which % of PII is protected)
    """

    def __init__(self, profile: AnonymizationProfile, schema: Schema):
        self.profile = profile
        self.schema = schema

    def verify_sync(self, target_conn: psycopg.Connection) -> dict[str, VerificationResult]:
        """Verify synced data matches anonymization rules.

        Returns:
            Dictionary of table -> verification results
        """
        ...

    def detect_pii_patterns(self,
                           table_name: str,
                           column_name: str,
                           sample_size: int = 100) -> list[str]:
        """Detect PII patterns in column data.

        Uses regex patterns:
        - SSN: \d{3}-\d{2}-\d{4}
        - Credit card: \d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}
        - Phone: various formats
        - Email: basic pattern
        """
        ...

    def generate_audit_report(self) -> str:
        """Generate detailed compliance audit report."""
        ...
```

---

## Implementation Plan

### Phase 4.4a: Core Strategy System (Week 1)

#### Step 1: Create strategy directory structure
```
python/confiture/core/anonymization/
├── __init__.py
├── strategy.py           # Base class + interfaces
├── profile.py            # Profile data structures
├── manager.py            # Profile loading & caching
├── verifier.py           # Compliance checking
└── strategies/           # Built-in implementations
    ├── __init__.py
    ├── hash.py
    ├── email.py
    ├── phone.py
    ├── pattern.py
    ├── conditional.py
    └── redact.py
```

#### Step 2: Test structure
```
tests/
├── unit/
│   └── test_anonymization_strategies.py    # Unit tests for each strategy
├── integration/
│   └── test_anonymization_profile.py       # Profile loading & validation
└── e2e/
    └── test_anonymization_full_workflow.py # End-to-end with syncer
```

#### Step 3: Implementation order (TDD - RED → GREEN → REFACTOR → QA)

**3.1 Strategy Base Class**
- RED: Write test for AnonymizationStrategy interface
- GREEN: Implement abstract base class with methods
- REFACTOR: Add docstrings, type hints, validation
- QA: Verify all methods are abstract, proper inheritance

**3.2 DeterministicHashStrategy**
- RED: Test SHA256 hashing with seed, length truncation
- GREEN: Implement hash strategy
- REFACTOR: Add algorithm parameter, prefix support
- QA: Test determinism, NULL handling, type validation

**3.3 EmailMaskingStrategy**
- RED: Test fake email generation from real emails
- GREEN: Implement basic email masking
- REFACTOR: Add format template, hash length parameter
- QA: Test determinism with seeds, validate output format

**3.4 PhoneMaskingStrategy**
- RED: Test phone number generation
- GREEN: Implement phone masking
- REFACTOR: Add format templates
- QA: Test various input formats, determinism

**3.5-3.7: PatternBased, Conditional, SimpleRedact**
- Follow same TDD cycle for each

### Phase 4.4b: Profile System (Week 2)

#### Step 4: AnonymizationProfile & YAML loading
- RED: Test loading profile from YAML
- GREEN: Implement YAML parser + profile dataclass
- REFACTOR: Add validation, error messages
- QA: Test valid/invalid profiles, nested strategies

#### Step 5: ProfileManager with built-in profiles
- RED: Test get_default_profile("test")
- GREEN: Implement with hardcoded defaults
- REFACTOR: Extract to constants, add caching
- QA: Test all 4 environments, cache invalidation

#### Step 6: Profile inheritance
- RED: Test profile.yaml with inherits_from
- GREEN: Implement inheritance resolution
- REFACTOR: Add merge logic for strategy overrides
- QA: Test multi-level inheritance, cycle detection

### Phase 4.4c: ProductionSyncer Integration (Week 2-3)

#### Step 7: Update ProductionSyncer
- RED: Test syncer with profile parameter
- GREEN: Update _anonymize_value() to use profile
- REFACTOR: Maintain backward compatibility with old rule format
- QA: Test old + new code paths work

#### Step 8: CLI sync command updates
```bash
# New CLI flags:
confiture sync source target --profile production
confiture sync source target --profile custom/my-profile.yaml
confiture sync source target --profile test  # Built-in
```

### Phase 4.4d: AnonymizationVerifier & Testing (Week 3)

#### Step 9: Verifier implementation
- RED: Test PII pattern detection
- GREEN: Implement detector with regex patterns
- REFACTOR: Add more patterns (SSN, credit card, etc.)
- QA: Test pattern coverage

#### Step 10: Compliance checking
- RED: Test verify_sync() returns correct coverage
- GREEN: Implement coverage calculation
- REFACTOR: Add audit report generation
- QA: Test report formatting

---

## File Changes Summary

### NEW FILES (11)
1. `python/confiture/core/anonymization/__init__.py`
2. `python/confiture/core/anonymization/strategy.py`
3. `python/confiture/core/anonymization/profile.py`
4. `python/confiture/core/anonymization/manager.py`
5. `python/confiture/core/anonymization/verifier.py`
6. `python/confiture/core/anonymization/strategies/__init__.py`
7. `python/confiture/core/anonymization/strategies/hash.py`
8. `python/confiture/core/anonymization/strategies/email.py`
9. `python/confiture/core/anonymization/strategies/phone.py`
10. `python/confiture/core/anonymization/strategies/pattern.py`
11. `python/confiture/core/anonymization/strategies/conditional.py`
12. `python/confiture/core/anonymization/strategies/redact.py`

### MODIFIED FILES (3)
1. `python/confiture/core/syncer.py` - Update ProductionSyncer to use profiles
2. `python/confiture/cli/main.py` - Add --profile flag to sync command
3. `python/confiture/__init__.py` - Export new anonymization module

### TEST FILES (NEW - 8)
1. `tests/unit/test_anonymization_strategies.py`
2. `tests/unit/test_anonymization_profile.py`
3. `tests/unit/test_anonymization_verifier.py`
4. `tests/integration/test_anonymization_profile_yaml.py`
5. `tests/integration/test_syncer_profile_integration.py`
6. `tests/e2e/test_anonymization_full_workflow.py`
7. `tests/e2e/test_compliance_audit.py`
8. `tests/e2e/test_profile_examples.py`

### EXAMPLE PROFILES (NEW - 4)
1. `db/anonymization-profiles/base.yaml` - Common strategies
2. `db/anonymization-profiles/local.yaml` - Development (minimal anonymization)
3. `db/anonymization-profiles/test.yaml` - Testing (heavy anonymization)
4. `db/anonymization-profiles/production.yaml` - Production (maximum anonymization)

---

## Key Design Decisions

### 1. Strategy System
- **Decision**: Use abstract base class + composition
- **Rationale**: Extensible, testable, follows OCP
- **Alternative**: String-based mapping (current) - less extensible
- **Trade-off**: Slightly more code, much more flexibility

### 2. YAML Configuration
- **Decision**: YAML profiles over CLI flags
- **Rationale**: Complex rules need structure, version-controllable, shareable
- **Alternative**: CLI-only - too verbose for complex rules
- **Trade-off**: Requires file I/O, but enables code-less configuration

### 3. Deterministic Hashing
- **Decision**: Optional seed-based determinism for all strategies
- **Rationale**: Enables reproducible anonymization (important for testing)
- **Alternative**: Always random - simpler but breaks reproducibility
- **Trade-off**: Slightly more code, but essential for compliance

### 4. Backward Compatibility
- **Decision**: Keep old AnonymizationRule format, add profile-based path
- **Rationale**: Existing code continues working
- **Alternative**: Break existing API - cleaner but migrations needed
- **Trade-off**: Slightly more code in syncer, but safe rollout

### 5. Built-in Profiles
- **Decision**: Provide 4 default profiles (local, test, staging, production)
- **Rationale**: Users can start without writing YAML
- **Alternative**: No defaults - users must configure
- **Trade-off**: Slightly more code, but better DX

---

## Success Criteria

### Functional Requirements
- ✅ 6 built-in strategies all working
- ✅ YAML profile loading functional
- ✅ Profile inheritance working
- ✅ ProductionSyncer can use profiles
- ✅ 4 default profiles available
- ✅ CLI --profile flag working
- ✅ Compliance verification working

### Quality Requirements
- ✅ All new code covered by tests (>80%)
- ✅ Backward compatibility maintained
- ✅ No breaking changes to existing APIs
- ✅ Type hints on all public methods
- ✅ Docstrings for all classes/methods
- ✅ Ruff linting passes
- ✅ Type checking passes (Astral ty)

### Documentation Requirements
- ✅ Update CLAUDE.md with Phase 4.4 notes
- ✅ Add anonymization strategy guide (docs/guides/)
- ✅ Add profile YAML reference (docs/reference/)
- ✅ Add 3 example profiles (docs/examples/)
- ✅ Update CLI help for sync --profile

---

## Risk Analysis

### High Risk
- **Profile YAML parsing errors** → Mitigation: Pydantic validation, clear error messages
- **Strategy composition complexity** → Mitigation: ConditionalStrategy has limits, document well
- **Determinism issues with seeding** → Mitigation: Comprehensive test of seed behavior

### Medium Risk
- **Backward compatibility break** → Mitigation: Keep both old and new code paths
- **Database performance with verification** → Mitigation: Sample-based PII detection (not full scan)

### Low Risk
- **Profile naming conflicts** → Mitigation: Use distinct names, reserved prefixes
- **Missing strategies** → Mitigation: Good error messages when strategy not found

---

## Dependencies

**No new Python dependencies** - Uses existing:
- `pydantic` - YAML validation
- `psycopg` - Database access
- `pathlib` - File operations
- `yaml` - YAML parsing (already imported in environment.py)
- `regex` - Pattern matching (built-in)

---

## Next Steps (Phase 4.5+)

- **4.5: Advanced Compliance** - Encryption support, PII pattern library, audit logging
- **4.6: UI/Wizard** - Interactive profile generator, compliance checker CLI
- **4.7: Performance** - Parallel anonymization, streaming for large tables

---

## Questions for User

Before proceeding with implementation, please clarify:

1. **Profile Inheritance**: Should we support multi-level inheritance or just one level?
2. **Conditional Strategies**: Are lambda functions in YAML acceptable, or should we use string-based predicates?
3. **Default Profiles**: Should we include a "development" profile (zero anonymization) or just local/test/staging/production?
4. **Verification Sampling**: For PII detection, should we sample 100 rows per column or entire table?
5. **Error Handling**: Should invalid profiles fail fast (cannot start sync) or warn and continue?

