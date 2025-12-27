# Phase 4.4 Week 0: Security Hardening - Implementation Plan

**Week**: Week 0 (Before Core Implementation)
**Focus**: All 4 P0 Critical Security Fixes
**Duration**: 1 week (~30 hours)
**Priority**: CRITICAL - Must complete before any other work

---

## Overview

Week 0 implements the four critical security/compliance fixes identified in QA review:

1. **P0.1: Seed Management** (4 hours) - Move secrets from YAML to environment
2. **P0.2: Audit Logging** (12 hours) - Immutable audit trail for compliance
3. **P0.3: Foreign Key Consistency** (6 hours) - Global seed parameter
4. **P0.4: YAML Security** (8 hours) - Safe loading + schema validation

All code is **tested** and **production-ready** before moving to Week 1.

---

## Daily Breakdown

### Day 1: Foundation & P0.1 (Seed Management)
**Hours**: 8 (4 development + 4 testing/review)

**Tasks**:
- [ ] Create `python/confiture/core/anonymization/` directory structure
- [ ] Implement base `AnonymizationStrategy` abstract class
- [ ] Create `StrategyConfig` dataclass with seed management
- [ ] Add `seed_env_var` support to all strategy configs
- [ ] Create environment variable loader utility
- [ ] Write unit tests for seed loading (env var fallback)
- [ ] Test: Seed from environment variable works
- [ ] Test: Fallback to default seed if env var not set

**Deliverable**: Core strategy interface + seed management working

---

### Day 2: P0.4 (YAML Security) + P0.2 Setup (Audit Logging Foundation)
**Hours**: 8 (6 YAML security + 2 audit setup)

**Tasks**:
- [ ] Create `StrategyType` enum (whitelist allowed types)
- [ ] Create Pydantic `AnonymizationProfile` schema class
- [ ] Implement `yaml.safe_load()` for profile loading
- [ ] Add Pydantic validation for profile schema
- [ ] Create strategy type whitelist validation
- [ ] Add `confiture validate-profile` CLI command
- [ ] Test YAML injection attack (should fail safely)
- [ ] Setup: Create `AuditEntry` dataclass
- [ ] Setup: Create audit logging module structure

**Deliverable**: YAML profiles are secure + validation working

---

### Day 3: P0.2 (Audit Logging - Core Implementation)
**Hours**: 8 (6 development + 2 testing)

**Tasks**:
- [ ] Create `AuditEntry` dataclass with all fields
- [ ] Create `AuditLogger` class with database table schema
- [ ] Implement `_ensure_audit_table()` to create table if needed
- [ ] Implement `log_sync()` to append audit entries
- [ ] Add entry signing (HMAC-based)
- [ ] Add serialization (to_json)
- [ ] Test: Audit table creation works
- [ ] Test: Audit entries are appended correctly
- [ ] Test: Entries cannot be modified (append-only)

**Deliverable**: Audit logging system fully functional

---

### Day 4: P0.3 (Foreign Key Consistency) + Integration
**Hours**: 8 (4 development + 4 integration/testing)

**Tasks**:
- [ ] Add `global_seed` field to `AnonymizationProfile`
- [ ] Implement seed resolution logic (column → global → default)
- [ ] Update rule resolution to use global_seed
- [ ] Create test: Same value different tables = same hash
- [ ] Create test: Different seeds override global_seed
- [ ] Integrate audit logging with ProductionSyncer
- [ ] Update Syncer to log sync operations
- [ ] Test: End-to-end audit logging in sync

**Deliverable**: Foreign key consistency + audit integration working

---

### Day 5: Testing, Documentation, Review
**Hours**: 8 (2 final testing + 2 docs + 2 security review + 2 cleanup)

**Tasks**:
- [ ] Run full test suite: `pytest tests/ -v`
- [ ] Verify coverage: `pytest --cov=confiture`
- [ ] Run security tests: YAML injection, seed exposure
- [ ] Create docs/security/threat-model.md
- [ ] Create docs/security/seed-management.md
- [ ] Create example `.env` file for seed management
- [ ] Update PHASE_4_4_PLAN.md with Week 0 fixes
- [ ] Code review: Security + DPO approval
- [ ] Merge Week 0 code to main branch

**Deliverable**: All P0 fixes complete, tested, documented, approved

---

## Detailed Implementation Tasks

### P0.1: Seed Management Implementation

**File**: `python/confiture/core/anonymization/strategy.py`

```python
# Current (VULNERABLE):
@dataclass
class StrategyConfig:
    seed: int | None = None  # Hardcoded in YAML!

# Fixed (SECURE):
@dataclass
class StrategyConfig:
    seed: int | None = None
    seed_env_var: str | None = None  # NEW: Load from environment

def resolve_seed(config: StrategyConfig) -> int:
    """Resolve seed from env var, config, or default."""
    if config.seed_env_var:
        # Try to load from environment variable
        env_value = os.getenv(config.seed_env_var)
        if env_value:
            try:
                return int(env_value)
            except ValueError:
                raise ValueError(f"Invalid seed in {config.seed_env_var}: {env_value}")

    # Fallback to hardcoded seed (if provided, e.g., for testing)
    if config.seed is not None:
        return config.seed

    # Default seed
    return 0
```

**YAML Usage**:
```yaml
# db/anonymization-profiles/production.yaml
strategies:
  email_mask:
    type: email
    config:
      seed_env_var: ANONYMIZATION_SEED  # Load from environment
      # Actual seed: export ANONYMIZATION_SEED=12345

  # OR hardcoded (testing only):
  # seed: 12345  # ❌ NEVER in production YAML
```

**Tests**:
```python
def test_seed_from_environment_variable():
    """Seed loaded from environment variable."""
    os.environ['TEST_SEED'] = '54321'
    config = StrategyConfig(seed_env_var='TEST_SEED')
    assert resolve_seed(config) == 54321

def test_seed_fallback_to_hardcoded():
    """Fallback to hardcoded seed if env var not set."""
    config = StrategyConfig(seed=99999, seed_env_var='NONEXISTENT_VAR')
    assert resolve_seed(config) == 99999

def test_seed_default():
    """Default seed if nothing provided."""
    config = StrategyConfig()
    assert resolve_seed(config) == 0
```

---

### P0.4: YAML Security Implementation

**File**: `python/confiture/core/anonymization/profile.py`

```python
# Current (VULNERABLE):
def load_profile(path: Path) -> dict:
    with open(path) as f:
        return yaml.load(f)  # ❌ UNSAFE! Can execute code!

# Fixed (SECURE):
from enum import Enum
from pydantic import BaseModel, validator
import yaml

class StrategyType(str, Enum):
    """Whitelist of allowed strategy types."""
    HASH = "hash"
    EMAIL = "email"
    PHONE = "phone"
    REDACT = "redact"
    # Note: Pattern and Conditional excluded (too complex/dangerous)

class StrategyDefinition(BaseModel):
    """Pydantic validates strategy structure."""
    type: str
    config: dict | None = None

    @validator('type')
    def validate_type(cls, v):
        allowed = {st.value for st in StrategyType}
        if v not in allowed:
            raise ValueError(f"Strategy type '{v}' not allowed. Allowed: {allowed}")
        return v

class AnonymizationProfile(BaseModel):
    """Profile with strict schema validation."""
    name: str
    version: str
    global_seed: int | None = None
    strategies: dict[str, StrategyDefinition]
    tables: dict[str, list[dict]]

    @classmethod
    def load(cls, path: Path) -> "AnonymizationProfile":
        """Load profile with safe YAML + schema validation."""
        with open(path) as f:
            # ✅ SAFE: Use safe_load, not load
            raw_data = yaml.safe_load(f)

        # ✅ SAFE: Pydantic validates structure
        try:
            profile = cls(**raw_data)
        except Exception as e:
            raise ValueError(f"Invalid profile {path}: {e}")

        return profile
```

**CLI Command**:
```python
@app.command()
def validate_profile(path: Path = typer.Argument(...)):
    """Validate anonymization profile YAML."""
    try:
        profile = AnonymizationProfile.load(path)
        console.print(f"✅ Valid profile: {profile.name} v{profile.version}")
        console.print(f"   Strategies: {list(profile.strategies.keys())}")
        console.print(f"   Tables: {list(profile.tables.keys())}")
    except ValueError as e:
        console.print(f"❌ Invalid profile: {e}", style="red")
        raise typer.Exit(1)
```

**Tests**:
```python
def test_yaml_safe_load_prevents_injection():
    """YAML injection attack is prevented."""
    malicious_yaml = """
    strategies:
      evil:
        type: !!python/object/apply:os.system
        args: ['rm -rf /']
    """
    with pytest.raises(Exception):  # Should fail, not execute
        AnonymizationProfile.load(malicious_yaml)

def test_yaml_whitelist_validation():
    """Unknown strategy types are rejected."""
    invalid_yaml = """
    name: test
    version: 1.0
    strategies:
      fake:
        type: unknown_strategy
    """
    with pytest.raises(ValueError, match="not allowed"):
        AnonymizationProfile.load(invalid_yaml)

def test_valid_profile_loads():
    """Valid profile loads successfully."""
    valid_yaml = """
    name: test
    version: 1.0
    strategies:
      email:
        type: email
    tables:
      users:
        - column: email
          strategy: email
    """
    profile = AnonymizationProfile.load(valid_yaml)
    assert profile.name == "test"
    assert "email" in profile.strategies
```

---

### P0.2: Audit Logging Implementation

**File**: `python/confiture/core/anonymization/audit.py`

```python
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from uuid import UUID, uuid4
import hashlib
import hmac
import json
import socket
import os
import psycopg

@dataclass
class AuditEntry:
    """Immutable audit log entry for compliance."""
    # Identifiers
    id: UUID
    timestamp: datetime

    # Who & Where
    user: str
    hostname: str
    source_database: str
    target_database: str

    # What
    profile_name: str
    profile_version: str
    profile_hash: str

    # Impact
    tables_synced: list[str]
    rows_anonymized: dict[str, int]
    strategies_applied: dict[str, int]

    # Verification
    verification_passed: bool
    verification_report: str

    # Signature
    signature: str

    def to_json(self) -> str:
        """Serialize to JSON for storage."""
        data = asdict(self)
        data['id'] = str(self.id)
        data['timestamp'] = self.timestamp.isoformat()
        return json.dumps(data)

class AuditLogger:
    """Append-only audit log (immutable)."""

    def __init__(self, target_conn: psycopg.Connection):
        self.conn = target_conn
        self._ensure_audit_table()

    def _ensure_audit_table(self):
        """Create audit table if not exists (idempotent)."""
        with self.conn.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS confiture_audit_log (
                    id UUID PRIMARY KEY,
                    timestamp TIMESTAMPTZ NOT NULL,
                    user TEXT NOT NULL,
                    hostname TEXT NOT NULL,
                    source_database TEXT NOT NULL,
                    target_database TEXT NOT NULL,
                    profile_name TEXT NOT NULL,
                    profile_version TEXT NOT NULL,
                    profile_hash TEXT NOT NULL,
                    tables_synced TEXT[] NOT NULL,
                    rows_anonymized JSONB NOT NULL,
                    strategies_applied JSONB NOT NULL,
                    verification_passed BOOLEAN NOT NULL,
                    verification_report TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );

                -- Make table append-only (no UPDATE/DELETE)
                ALTER TABLE confiture_audit_log
                    OWNER TO CURRENT_USER;
                REVOKE UPDATE, DELETE ON confiture_audit_log FROM PUBLIC;
            """)
            self.conn.commit()

    def log_sync(self, entry: AuditEntry):
        """Append entry to audit log (immutable append-only)."""
        with self.conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO confiture_audit_log (
                    id, timestamp, user, hostname,
                    source_database, target_database,
                    profile_name, profile_version, profile_hash,
                    tables_synced, rows_anonymized, strategies_applied,
                    verification_passed, verification_report, signature
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                str(entry.id),
                entry.timestamp,
                entry.user,
                entry.hostname,
                entry.source_database,
                entry.target_database,
                entry.profile_name,
                entry.profile_version,
                entry.profile_hash,
                entry.tables_synced,
                json.dumps(entry.rows_anonymized),
                json.dumps(entry.strategies_applied),
                entry.verification_passed,
                entry.verification_report,
                entry.signature,
            ))
            self.conn.commit()

    def get_audit_log(self, limit: int = 100) -> list[AuditEntry]:
        """Get recent audit log entries (for reporting)."""
        with self.conn.cursor() as cursor:
            cursor.execute("""
                SELECT * FROM confiture_audit_log
                ORDER BY timestamp DESC
                LIMIT %s
            """, (limit,))

            entries = []
            for row in cursor.fetchall():
                entries.append(AuditEntry(
                    id=UUID(row[0]),
                    timestamp=row[1],
                    user=row[2],
                    hostname=row[3],
                    source_database=row[4],
                    target_database=row[5],
                    profile_name=row[6],
                    profile_version=row[7],
                    profile_hash=row[8],
                    tables_synced=row[9],
                    rows_anonymized=row[10],
                    strategies_applied=row[11],
                    verification_passed=row[12],
                    verification_report=row[13],
                    signature=row[14],
                ))

            return entries

def sign_audit_entry(entry: AuditEntry, secret: str | None = None) -> str:
    """Create HMAC signature for audit entry (prevents tampering)."""
    if secret is None:
        secret = os.getenv('AUDIT_LOG_SECRET', 'default-secret')

    # Create deterministic JSON for signing
    data = {
        'id': str(entry.id),
        'timestamp': entry.timestamp.isoformat(),
        'user': entry.user,
        'hostname': entry.hostname,
        'source_database': entry.source_database,
        'target_database': entry.target_database,
        'profile_name': entry.profile_name,
        'profile_hash': entry.profile_hash,
        'tables_synced': ','.join(sorted(entry.tables_synced)),
        'rows_anonymized': sum(entry.rows_anonymized.values()),
        'verification_passed': entry.verification_passed,
    }

    json_str = json.dumps(data, sort_keys=True)
    signature = hmac.new(
        secret.encode(),
        json_str.encode(),
        hashlib.sha256
    ).hexdigest()

    return signature
```

**Tests**:
```python
def test_audit_table_creation():
    """Audit table is created on first use."""
    logger = AuditLogger(test_conn)

    # Check table exists
    with test_conn.cursor() as cursor:
        cursor.execute("""
            SELECT EXISTS(
                SELECT FROM information_schema.tables
                WHERE table_name = 'confiture_audit_log'
            )
        """)
        assert cursor.fetchone()[0] is True

def test_audit_entry_append_only():
    """Audit entries cannot be deleted (append-only)."""
    logger = AuditLogger(test_conn)

    # Create entry
    entry = AuditEntry(
        id=uuid4(),
        timestamp=datetime.now(timezone.utc),
        user='test_user',
        hostname='localhost',
        source_database='prod',
        target_database='staging',
        profile_name='test',
        profile_version='1.0',
        profile_hash='abc123',
        tables_synced=['users'],
        rows_anonymized={'users': 100},
        strategies_applied={'email': 100},
        verification_passed=True,
        verification_report='{}',
        signature='sig123'
    )

    logger.log_sync(entry)

    # Try to delete (should fail with permissions error)
    with pytest.raises(Exception):  # psycopg.Error
        with test_conn.cursor() as cursor:
            cursor.execute("DELETE FROM confiture_audit_log WHERE id = %s", (str(entry.id),))
            test_conn.commit()

def test_audit_entry_signature():
    """Audit entry signature prevents tampering."""
    entry = AuditEntry(...)
    sig1 = sign_audit_entry(entry)

    # Change something
    entry.verification_passed = False
    sig2 = sign_audit_entry(entry)

    assert sig1 != sig2  # Signature changed
```

---

### P0.3: Foreign Key Consistency Implementation

**File**: `python/confiture/core/anonymization/profile.py` (update)

```python
@dataclass
class AnonymizationRule:
    """Rule for anonymizing a specific column."""
    column: str
    strategy: str
    seed: int | None = None  # Column-specific seed (overrides global)
    options: dict[str, Any] | None = None

class AnonymizationProfile(BaseModel):
    """Profile with global seed for consistency."""
    name: str
    version: str
    global_seed: int | None = None  # NEW: Applied to all columns
    strategies: dict[str, StrategyDefinition]
    tables: dict[str, list[AnonymizationRule]]

def resolve_seed_for_column(
    rule: AnonymizationRule,
    profile: AnonymizationProfile
) -> int:
    """Resolve seed with proper precedence:
    1. Column-specific seed (highest priority)
    2. Global profile seed
    3. Default (0)
    """
    # Column-specific seed takes precedence
    if rule.seed is not None:
        return rule.seed

    # Global seed applies to all columns
    if profile.global_seed is not None:
        return profile.global_seed

    # Default seed
    return 0
```

**YAML Usage**:
```yaml
# production.yaml
name: production
version: 1.0
global_seed: 12345  # ALL columns use this seed unless overridden

strategies:
  email_mask:
    type: email
  phone_mask:
    type: phone

tables:
  users:
    rules:
      - column: email
        strategy: email_mask
        # Uses global_seed (12345)

      - column: phone
        strategy: phone_mask
        # Uses global_seed (12345)

  orders:
    rules:
      - column: user_email
        strategy: email_mask
        # Uses global_seed (12345) - SAME AS users.email!
        # ✅ Same email = same hash across tables

      - column: special_code
        strategy: email_mask
        seed: 99999  # Override with column-specific seed
        # ✅ Different hash for this column
```

**Tests**:
```python
def test_global_seed_consistency():
    """Same PII values hash to same output with global_seed."""
    profile = AnonymizationProfile(
        name='test',
        version='1.0',
        global_seed=12345,
        strategies={...},
        tables={
            'users': [...],
            'orders': [...]
        }
    )

    # Get rules for same email in different tables
    users_rule = profile.tables['users'][0]  # email column
    orders_rule = profile.tables['orders'][0]  # user_email column

    # Both should use same seed
    assert resolve_seed_for_column(users_rule, profile) == 12345
    assert resolve_seed_for_column(orders_rule, profile) == 12345

def test_column_seed_overrides_global():
    """Column-specific seed overrides global_seed."""
    profile = AnonymizationProfile(
        name='test',
        version='1.0',
        global_seed=12345,
        tables={
            'data': [
                AnonymizationRule(column='col1', strategy='email', seed=99999)
            ]
        }
    )

    rule = profile.tables['data'][0]
    assert resolve_seed_for_column(rule, profile) == 99999  # Not 12345!
```

---

## File Structure After Week 0

```
python/confiture/core/anonymization/
├── __init__.py
├── strategy.py              # Base + seed management
├── profile.py               # Pydantic schema + YAML loading
├── audit.py                 # Audit logging system
├── manager.py               # Profile manager (existing, will update)
└── strategies/
    ├── __init__.py
    ├── hash.py              # DeterministicHashStrategy
    ├── email.py             # EmailMaskingStrategy
    ├── phone.py             # PhoneMaskingStrategy
    └── redact.py            # SimpleRedactStrategy

tests/
├── unit/
│   ├── test_anonymization_strategy.py
│   ├── test_anonymization_profile.py
│   ├── test_anonymization_audit.py
│   └── test_yaml_security.py
└── integration/
    └── test_audit_logging.py
```

---

## Verification Checklist

After each day, verify:

- [ ] Code compiles without errors
- [ ] Type hints pass: `ty check python/confiture/`
- [ ] Linting passes: `ruff check python/confiture/`
- [ ] Unit tests pass: `pytest tests/unit/ -v`
- [ ] Integration tests pass: `pytest tests/integration/ -v`
- [ ] Coverage maintained: `pytest --cov=confiture` (>80%)
- [ ] No security warnings (test injection, env var handling)
- [ ] Documentation updated (docstrings, type hints)

---

## Success Criteria for Week 0

✅ **All 4 P0 Fixes Implemented**:
- [ ] Seed management (env vars working)
- [ ] Audit logging (immutable table, entries logged)
- [ ] Foreign key consistency (global_seed parameter)
- [ ] YAML security (safe_load + schema validation)

✅ **All Code Tested**:
- [ ] >80% test coverage
- [ ] All critical paths tested
- [ ] Security tests included (YAML injection, seed exposure)
- [ ] All tests passing

✅ **Documentation Complete**:
- [ ] docs/security/threat-model.md created
- [ ] docs/security/seed-management.md created
- [ ] All docstrings added
- [ ] Type hints complete

✅ **Approval & Merge**:
- [ ] Security review passed
- [ ] DPO approval obtained
- [ ] Code merged to main branch
- [ ] Ready for Week 1

---

## Daily Status Template

Use this for daily updates:

```
## Day X Status

### Completed
- [ ] Task 1
- [ ] Task 2

### In Progress
- [ ] Task 3

### Blockers
- None

### Code Stats
- Lines of code added: XXX
- Tests added: XXX
- Coverage: XX%

### Next Day
- [ ] Task 4
- [ ] Task 5
```

---

## Emergency Rollback Plan

If critical issue found during Week 0:

1. **Identify**: Document the issue
2. **Isolate**: Revert the problematic code
3. **Investigate**: Root cause analysis
4. **Fix**: Address and add test
5. **Re-test**: Full test suite
6. **Re-review**: Security/DPO approval
7. **Continue**: Resume Week 0 plan

No rollback to original unpatched architecture.

---

## Week 0 Complete Checklist

When all tasks done:

- [ ] All 4 P0 fixes implemented
- [ ] All tests passing (>80% coverage)
- [ ] Security review passed
- [ ] DPO approval obtained
- [ ] Documentation complete
- [ ] Code merged to main
- [ ] WEEK_0_SUMMARY.md created
- [ ] Ready for Week 1: Core Strategies

**Then**: Move to Week 1 implementation

