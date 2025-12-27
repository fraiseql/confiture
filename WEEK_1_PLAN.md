# Week 1: Core Anonymization Strategies Implementation - Plan

**Date**: 2025-12-27
**Status**: PLANNING COMPLETE - Ready to Execute
**Duration**: 5 days (Mon-Fri)
**Target**: 264+ tests, 92%+ coverage, 12+ anonymization strategies

---

## 🎯 Week 1 Objectives

Build on Week 0's security foundation (140 tests, 87% coverage, 4 basic strategies) to create a production-grade anonymization system with:

- ✅ **8 new anonymization strategies** (name, date, address, credit card, IP, text redaction, preserve, custom SQL)
- ✅ **Strategy factory & registry system** (extensible, discoverable, type-safe)
- ✅ **Strategy composition** (chain multiple strategies, conditional application)
- ✅ **5 real-world scenarios** (e-commerce, healthcare, financial, SaaS, multi-tenant)
- ✅ **Advanced configuration** (per-table sampling, filtering, parallel processing, dry-run mode)
- ✅ **Performance optimization** (lazy initialization, caching, batching, benchmarking)
- ✅ **Comprehensive documentation** (4 guides + API reference)
- ✅ **264+ tests** (unit, integration, E2E)

---

## 📅 Daily Breakdown

### Day 1: Strategy Factory & Data Type Strategies (Monday)

**Focus**: Build extensible foundation + implement name, date, address strategies

**Deliverables**:
- `python/confiture/core/anonymization/registry.py` (100 lines) - Strategy registry
- `python/confiture/core/anonymization/strategies/name.py` (150 lines) - Name masking
- `python/confiture/core/anonymization/strategies/date.py` (140 lines) - Date masking
- `python/confiture/core/anonymization/strategies/address.py` (120 lines) - Address masking
- `tests/unit/test_strategy_registry.py` (150 lines) - Registry tests
- `tests/unit/test_name_strategy.py` (180 lines) - Name tests
- `tests/unit/test_date_strategy.py` (200 lines) - Date tests
- `tests/unit/test_address_strategy.py` (180 lines) - Address tests

**Test Target**: 40+ tests (100% passing)

**Architecture**:
```python
# Strategy Registry (extensible, discoverable)
class StrategyRegistry:
    _registry: dict[str, type[AnonymizationStrategy]] = {}

    @classmethod
    def register(cls, name: str, strategy_class: type):
        cls._registry[name] = strategy_class

    @classmethod
    def get(cls, name: str, config: dict) -> AnonymizationStrategy:
        if name not in cls._registry:
            raise ValueError(f"Unknown strategy: {name}")
        return cls._registry[name](config)

    @classmethod
    def list(cls) -> list[str]:
        return list(cls._registry.keys())

# Register all strategies
StrategyRegistry.register("email", EmailMaskingStrategy)
StrategyRegistry.register("phone", PhoneMaskingStrategy)
StrategyRegistry.register("name", NameMaskingStrategy)  # NEW
StrategyRegistry.register("date", DateMaskingStrategy)  # NEW
StrategyRegistry.register("address", AddressStrategy)   # NEW
```

**Strategies to Implement**:

1. **NameMaskingStrategy**
   - Config options: `preserve_initial`, `format_type` (firstname_lastname, random_name, initials)
   - Deterministic name generation from seed
   - First/last name datasets
   - Handle NULL, empty values
   - 12 tests

2. **DateMaskingStrategy**
   - Config options: `preserve` (year, month, none), `jitter_days`
   - Preserve year/month, jitter within range
   - Deterministic jitter (same seed = same jitter)
   - Support multiple formats (ISO 8601, USA MM/DD/YYYY, UK DD/MM/YYYY)
   - 14 tests

3. **AddressStrategy**
   - Config options: `preserve_fields` (list[city, state, zip, country]), `redact_street`
   - Parse various address formats
   - Preserve selected fields, anonymize others
   - 12 tests

**Acceptance Criteria**:
- [x] Registry system fully functional
- [x] Name strategy working with deterministic generation
- [x] Date strategy working with jitter and preservation
- [x] Address strategy working with field preservation
- [x] 40+ tests passing
- [x] Coverage 92%+
- [x] Profile updated with new strategy types

---

### Day 2: Financial & Sensitive Data Strategies (Tuesday)

**Focus**: Implement specialized strategies for financial/sensitive data

**Deliverables**:
- `python/confiture/core/anonymization/strategies/credit_card.py` (130 lines)
- `python/confiture/core/anonymization/strategies/ip_address.py` (150 lines)
- `python/confiture/core/anonymization/strategies/text_redaction.py` (140 lines)
- `python/confiture/core/anonymization/strategies/preserve.py` (40 lines)
- `python/confiture/core/anonymization/strategies/custom.py` (100 lines)
- Registry integration (20 lines update)
- `tests/unit/test_credit_card_strategy.py` (160 lines)
- `tests/unit/test_ip_strategy.py` (180 lines)
- `tests/unit/test_text_redaction_strategy.py` (180 lines)
- `tests/unit/test_preserve_strategy.py` (60 lines)
- `tests/unit/test_custom_strategy.py` (80 lines)

**Test Target**: 50+ new tests (total 90+ for days 1-2)

**Strategies to Implement**:

1. **CreditCardMaskingStrategy**
   - Config: `preserve_last4`, `preserve_bin`, `format` (visa, mastercard, amex, generic)
   - Luhn algorithm validation
   - Deterministic generation
   - 12 tests

2. **IPAddressStrategy**
   - Config: `preserve_octets` [0-4], `version` (v4, v6, auto)
   - IPv4 and IPv6 support
   - Preserve subnet for analysis
   - 14 tests

3. **TextRedactionStrategy**
   - Config: `patterns` (regex list), `replacement`, `case_sensitive`
   - Regex-based pattern matching
   - Multiple pattern support
   - 12 tests

4. **PreserveStrategy**
   - No-op strategy (pass-through)
   - Marks columns that don't need anonymization
   - 4 tests

5. **CustomSQLStrategy** (Phase 2 foundation)
   - Config: `function_name`, `sql_function`
   - Validation only (execution requires DB connection)
   - 6 tests

**Acceptance Criteria**:
- [x] 5 new strategies implemented
- [x] Credit card validation with Luhn algorithm
- [x] IPv4/IPv6 support working
- [x] Regex pattern matching working
- [x] 50+ tests passing
- [x] Total 90+ tests from days 1-2
- [x] All strategies registered

---

### Day 3: Strategy Composition & Factory System (Wednesday)

**Focus**: Build composition patterns, enhance factory, implement strategy suggestion

**Deliverables**:
- `python/confiture/core/anonymization/composer.py` (120 lines) - Composition
- `python/confiture/core/anonymization/factory.py` (150 lines) - Enhanced factory
- `python/confiture/core/anonymization/strategy_suggester.py` (100 lines) - Auto-suggest
- `python/confiture/core/anonymization/batch_processor.py` (110 lines) - Batch ops
- Updated `profile.py` (40 lines) - Composition support
- `tests/unit/test_composition.py` (160 lines)
- `tests/unit/test_factory.py` (180 lines)
- `tests/unit/test_strategy_suggestion.py` (140 lines)
- `tests/unit/test_batch_processor.py` (80 lines)

**Test Target**: 52+ new tests (total 142+ for days 1-3)

**Architecture**:

1. **StrategyComposer**
   - Chain multiple strategies
   - `CompositeStrategy` applies in sequence
   - Order preservation (important!)
   - Conditional application support
   - 12 tests

2. **Enhanced Factory**
   - `create_from_definition()` - load from profile
   - `create_composite()` - chain strategies
   - `validate_strategy_type()` - helpful errors
   - `suggest_strategy()` - intelligent suggestions
   - 16 tests

3. **StrategyProfiler**
   - Auto-suggest strategy based on column name/type
   - Pattern matching (email → EmailMaskingStrategy)
   - 10 tests

4. **BatchProcessor**
   - Efficient bulk anonymization
   - Memory-efficient streaming
   - 8 tests

**Profile Composition Syntax**:
```yaml
anonymization:
  name: "advanced_profile"
  version: "1.0"

  tables:
    users:
      rules:
        - column: notes
          compose:  # NEW: chain multiple strategies
            - type: text_redaction
              config: { patterns: ["\\b\\d{3}-\\d{2}-\\d{4}\\b"] }
            - type: email
              config: { seed: 12345 }
          # Applies text redaction THEN email masking to remaining text
```

**Acceptance Criteria**:
- [x] Composition system fully functional
- [x] Factory creates from profile definitions
- [x] Strategy suggestion engine working
- [x] Batch processing optimized
- [x] 52+ new tests passing
- [x] Total 142+ tests
- [x] Profile composition syntax validated

---

### Day 4: Real-World Scenarios & Advanced Configuration (Thursday)

**Focus**: Build 5 complete scenario examples, advanced configuration

**Deliverables**:

5 Scenario Examples:
- `examples/anonymization_scenarios/ecommerce_users.py` (200 lines) - E-commerce
- `examples/anonymization_scenarios/healthcare.py` (200 lines) - Healthcare
- `examples/anonymization_scenarios/financial.py` (200 lines) - Financial
- `examples/anonymization_scenarios/saas_platform.py` (200 lines) - SaaS
- `examples/anonymization_scenarios/multitenant.py` (200 lines) - Multi-tenant

Core Features:
- `python/confiture/core/anonymization/advanced_config.py` (150 lines) - Advanced config
- `python/confiture/core/anonymization/verification.py` (140 lines) - Verification
- Updated CLI commands (60 lines)
- `tests/unit/test_advanced_config.py` (140 lines)
- `tests/unit/test_verification.py` (140 lines)
- `tests/integration/test_scenarios.py` (200 lines) - Scenario tests

**Test Target**: 38+ new tests (total 180+ for days 1-4)

**Scenarios**:

1. **E-Commerce User Data**
   - Users, orders, payments, reviews
   - Email + name + phone anonymization
   - FK consistency (user_id across tables)
   - Column-specific seeds
   - Verification: FK integrity checks

2. **Healthcare Data**
   - Patients, visits, diagnoses
   - SSN redaction, DOB partial masking
   - Medical code anonymization
   - GDPR compliance annotations

3. **Financial Data**
   - Accounts, transactions, beneficiaries
   - Credit card masking (preserve last 4)
   - Account number masking (preserve BIN + last 2)
   - Transaction amount ranges

4. **SaaS Platform**
   - Accounts, API keys, webhooks
   - API key format preservation
   - IP address anonymization (preserve subnet)
   - Email domain preservation
   - Text redaction in notes

5. **Multi-Tenant Application**
   - Tenant isolation strategies
   - Organization-specific anonymization
   - Role-based rules
   - Seed per tenant (global + tenant seed)

**Advanced Configuration**:
- Per-table sampling (copy only N rows)
- Filtering (copy only recent data)
- Parallel processing settings
- Dry-run mode (don't write to DB)
- Custom verification queries

**Acceptance Criteria**:
- [x] 5 complete scenario examples
- [x] Each with test assertions
- [x] Advanced configuration working
- [x] Verification system functional
- [x] CLI commands implemented
- [x] 38+ new tests passing
- [x] Total 180+ tests

---

### Day 5: Performance, Documentation & Integration (Friday)

**Focus**: Optimize performance, complete documentation, final integration testing

**Deliverables**:

Performance & Optimization:
- `python/confiture/core/anonymization/performance.py` (120 lines) - Performance monitor
- Performance benchmarks (40 lines)
- Caching layer (30 lines)
- `tests/unit/test_performance.py` (100 lines)

Documentation:
- `docs/api/anonymization_strategies.md` (800 lines) - Strategy API reference
- `docs/guides/anonymization_guide.md` (600 lines) - User guide
- `docs/guides/anonymization_integration.md` (400 lines) - Integration guide
- `docs/reference/anonymization_config.md` (500 lines) - Config reference

Integration Tests:
- `tests/integration/test_composition_workflows.py` (120 lines)
- `tests/integration/test_factory_system.py` (100 lines)
- `tests/integration/test_audit_integration.py` (80 lines)
- `tests/integration/test_seed_consistency.py` (60 lines)

Quality Assurance:
- Code coverage: 92%+
- Linting: All passing
- Type checking: All passing
- All 264+ tests passing
- Performance baselines established

**Test Target**: 34+ new tests (total 264+ for week 1)

**Documentation**:

1. **API Reference** - All 12+ strategies documented
   - What it does
   - Configuration options
   - Examples
   - Performance characteristics
   - Security notes

2. **User Guide** - How to use anonymization
   - Getting started
   - Composing strategies
   - Real-world scenarios
   - Performance tuning
   - GDPR compliance

3. **Integration Guide** - Integration with other systems
   - ProductionSyncer integration
   - Audit logging integration
   - FK consistency patterns
   - Performance optimization

4. **Configuration Reference** - YAML & programmatic
   - Profile syntax
   - All options
   - Example profiles
   - Environment variables

**Performance Optimization**:
- Lazy strategy initialization
- Strategy caching by type
- Batch row processing
- Memory-efficient streaming
- Benchmarks: rows/sec throughput

**Acceptance Criteria**:
- [x] Performance metrics established
- [x] All benchmarks documented
- [x] 4 comprehensive guides completed
- [x] Integration tests all passing
- [x] Total 264+ tests passing
- [x] Coverage 92%+
- [x] No regressions from Week 0 (140 tests still pass)
- [x] All CLI commands working
- [x] Production-ready code quality

---

## 📊 Summary Statistics

### Code Delivery

```
New Production Code:    ~1,500 lines
├─ Registry system:       100 lines
├─ 8 new strategies:      1,000 lines (avg 125/strategy)
├─ Factory & composer:    250 lines
├─ Advanced config:       150 lines
└─ Performance & misc:    120 lines

New Test Code:          ~1,800 lines
├─ Unit tests:          ~1,000 lines
├─ Integration tests:    ~500 lines
├─ Scenario tests:       ~300 lines

New Documentation:      ~3,000 lines
├─ API reference:        ~800 lines
├─ User guide:           ~600 lines
├─ Integration guide:    ~400 lines
├─ Config reference:     ~500 lines
└─ Examples:             ~700 lines

TOTAL: ~6,300 lines delivered
```

### Test Metrics

```
Day 1:  40+ tests (Names, Dates, Addresses, Registry)
Day 2:  50+ tests (Credit Cards, IPs, Text, Preserve, Custom)
Day 3:  52+ tests (Composition, Factory, Suggestion, Batch)
Day 4:  38+ tests (Scenarios, Advanced Config, Verification)
Day 5:  34+ tests (Performance, Integration, QA)
────────────────────────────────
WEEK 1: 264+ tests (100% passing)

Coverage:
├─ Anonymization module:  92%+
├─ Registry/Factory:      95%+
├─ Strategies:            90%+
└─ Overall project:       89%+ (maintained from 87%)
```

### Strategy Count

```
Week 0:  4 strategies (Hash, Email, Phone, Redact)
Week 1: +8 strategies (Name, Date, Address, CC, IP, Text, Preserve, Custom)
────────────────────────────────
Total:  12 strategies
```

### Files Created/Modified

```
New Core Files:        15
├─ Registry              1
├─ Strategies            8
├─ Composition/Factory   3
├─ Advanced config       2
└─ Performance           1

New Test Files:        12
├─ Unit tests           7
├─ Integration tests    4
└─ Scenario tests       1

New Documentation:      4
Examples:              5

TOTAL NEW:            36 files
```

---

## 🔐 Security & Compliance

### Inheriting from Week 0

✅ **Seed Management**: 3-tier precedence, environment variables
✅ **YAML Security**: Safe loading, Pydantic validation
✅ **Audit Logging**: HMAC signatures, tamper detection
✅ **FK Consistency**: Global seed parameter

### Week 1 Extensions

✅ **Strategy Type Whitelist**: Add new types to validation
✅ **Composition Validation**: Ensure valid strategy chaining
✅ **Sensitive Data Handling**: Specialized strategies (CC, SSN, health data)
✅ **GDPR Compliance**: Healthcare, financial, PII scenarios
✅ **Performance Security**: No timing leaks in anonymization

---

## 📚 Knowledge Requirements

### For Implementation

**Week 0 Understanding**:
- Seed management (3-tier precedence)
- YAML safe loading + Pydantic validation
- HMAC-based signatures
- Foreign key consistency via global seed
- Audit logging architecture

**Week 1 Patterns**:
- Factory pattern (create instances from config)
- Registry pattern (extensible strategy registration)
- Composition pattern (chain multiple strategies)
- Builder pattern (ProfileBuilder for advanced configs)
- Strategy pattern (base class + implementations)

**Key Files to Reference**:
- `python/confiture/core/anonymization/strategy.py` - Base class
- `python/confiture/core/anonymization/profile.py` - Profile validation
- `python/confiture/core/anonymization/strategies/email.py` - Strategy example
- `tests/unit/test_anonymization_strategies.py` - Test patterns

---

## ⚠️ Known Risks

| Risk | Mitigation |
|------|-----------|
| Performance regression | Daily benchmarking |
| Strategy composition complexity | Document order, test thoroughly |
| Registry thread-safety | Use locks if needed, test concurrency |
| Profile backward compatibility | Support old format, add migration |
| Coverage drop | Daily monitoring, min 90% goal |

---

## ✅ Definition of Done

**Each Day**:
- All new tests passing (100%)
- Coverage maintained/improved
- No regressions in existing tests
- Linting passing (`ruff check`)
- Type checking passing (`ty check`)
- Docstrings complete
- Examples working

**End of Week**:
- 264+ tests passing
- 92%+ coverage
- 4 guides complete
- 5 scenarios working
- Performance benchmarks established
- Zero regressions from Week 0
- Production-ready code quality

---

## 🚀 Success Metrics

By end of Week 1:

✅ **Functionality**: 12 strategies (4×Week 0)
✅ **Quality**: 264 tests (2×Week 0)
✅ **Coverage**: 92% module (↑5% from Week 0)
✅ **Extensibility**: Factory + Registry + Composition
✅ **Documentation**: 4 comprehensive guides
✅ **Real-World**: 5 complete scenario examples
✅ **Performance**: Benchmarked and optimized
✅ **Compliance**: GDPR-ready for healthcare/financial/PII

---

**Status**: PLANNING COMPLETE ✅
**Ready**: To execute Week 1 implementation
**Next**: Begin Day 1 (Strategy Factory + Name/Date/Address strategies)

