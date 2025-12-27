# Phase 4.4 Architecture - Multi-Specialist QA Review Summary

**Date**: 2025-12-27
**Status**: ⚠️ REQUIRES CRITICAL FIXES BEFORE IMPLEMENTATION
**Review Verdict**: 🟡 **PROCEED WITH CHANGES** (after addressing P0 issues)

---

## Executive Summary

The Phase 4.4 architecture has **strong foundational design** (strategy pattern, YAML configuration, verification system) but contains **4 critical security/compliance gaps** that MUST be fixed before any implementation begins.

**DO NOT START CODING** until these P0 issues are resolved.

---

## Critical Issues (P0 - MUST FIX)

### 1. 🔴 Seed Management Security Vulnerability

**Issue**: Seeds stored in plaintext YAML files committed to Git
- Enables **rainbow table attacks** if seed is compromised
- Seeds can be extracted from Git history
- Violates security best practice (secrets in code)

**Current Implementation**:
```yaml
# db/anonymization-profiles/production.yaml
strategies:
  email_mask:
    type: email
    config:
      seed: 12345  # ❌ UNSAFE: In plaintext in version control
```

**Why It's Critical**:
- If attacker knows seed (from Git), can reverse hashes
- Example attack:
  ```python
  # Attacker has seed from leaked profile
  import hashlib
  for email in common_emails:
      hashed = hashlib.sha256(f"12345:{email}".encode()).hexdigest()[:8]
      if hashed == "a1b2c3d4":  # From anonymized DB
          print(f"Found: {email}")  # Re-identified!
  ```

**Required Fix**:
```python
# Strategy 1: Environment Variables (Recommended)
@dataclass
class DeterministicHashConfig(StrategyConfig):
    algorithm: str = "sha256"
    seed: int | None = None
    seed_env_var: str | None = None  # NEW

def load_seed(config: DeterministicHashConfig) -> int:
    """Load seed from env var, with fallback."""
    if config.seed_env_var:
        return int(os.getenv(config.seed_env_var, config.seed or 0))
    return config.seed or 0

# Usage in YAML:
strategies:
  email_mask:
    type: email
    config:
      seed_env_var: ANONYMIZATION_SEED  # ✅ SAFE
      # Actual value: export ANONYMIZATION_SEED=12345
```

**Alternative Fix**: HMAC-based hashing (prevents rainbow tables):
```python
import hmac

def _hmac_hash(value: str, seed: int, secret: str) -> str:
    """HMAC prevents rainbow table attacks even if seed is known."""
    key = f"{seed}{secret}".encode()
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()
```

**Action Items**:
- [ ] Remove all plaintext seeds from YAML profiles
- [ ] Add `seed_env_var` field to all strategy configs
- [ ] Update ProfileManager to load seeds from environment
- [ ] Document required environment variables for each environment
- [ ] Add validation: Fail if seed is hardcoded in profiles
- [ ] Update CI/CD to inject seeds via secrets

---

### 2. 🔴 Missing Audit Trail (GDPR Article 30 Violation)

**Issue**: No log of who anonymized what data, when, or under what authority
- Cannot prove GDPR compliance (Article 30: Record of Processing Activities)
- Regulators can request: "Prove email X was anonymized"
- No accountability trail for data access

**Why It's Critical**:
- GDPR requires documentation of all data processing
- Without audit log, cannot demonstrate compliance
- Could result in fines up to 4% of global revenue
- Required for SOC 2, ISO 27001 compliance

**Required Fix**:
```python
# confiture/core/anonymization/audit.py (NEW)

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4
import hashlib

@dataclass
class AuditEntry:
    """Immutable audit log entry."""
    id: UUID
    timestamp: datetime

    # Who & Where
    user: str  # OS user who ran sync
    hostname: str

    # What
    source_database: str
    target_database: str
    profile_name: str
    profile_version: str
    profile_hash: str  # SHA256 of YAML to detect changes

    # Impact
    tables_synced: list[str]
    rows_anonymized: dict[str, int]  # table -> row count
    strategies_applied: dict[str, int]  # strategy -> count

    # Proof
    verification_passed: bool
    verification_report: str  # JSON with PII detection results

    # Signature
    signature: str  # HMAC of all above fields

    def to_json(self) -> str:
        """Serialize for storage."""
        return json.dumps({
            "id": str(self.id),
            "timestamp": self.timestamp.isoformat(),
            "user": self.user,
            "hostname": self.hostname,
            "source_database": self.source_database,
            "target_database": self.target_database,
            "profile_name": self.profile_name,
            "profile_version": self.profile_version,
            "profile_hash": self.profile_hash,
            "tables_synced": self.tables_synced,
            "rows_anonymized": self.rows_anonymized,
            "strategies_applied": self.strategies_applied,
            "verification_passed": self.verification_passed,
            "verification_report": self.verification_report,
            "signature": self.signature,
        })

class AuditLogger:
    """Append-only audit log (immutable)."""

    def __init__(self, target_conn: psycopg.Connection):
        self.conn = target_conn
        self._ensure_audit_table()

    def _ensure_audit_table(self):
        """Create audit table if not exists (runs once)."""
        self.conn.execute("""
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

            -- Make table append-only
            ALTER TABLE confiture_audit_log OWNER TO CURRENT_USER;
            REVOKE UPDATE, DELETE ON confiture_audit_log FROM PUBLIC;
        """)

    def log_sync(self, entry: AuditEntry):
        """Append entry to audit log."""
        self.conn.execute("""
            INSERT INTO confiture_audit_log (
                id, timestamp, user, hostname, source_database, target_database,
                profile_name, profile_version, profile_hash, tables_synced,
                rows_anonymized, strategies_applied, verification_passed,
                verification_report, signature
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
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

# Usage in ProductionSyncer:
class ProductionSyncer:
    def __init__(self, source, target, profile):
        # ... existing code ...
        self.audit_logger = AuditLogger(self._target_conn)

    def sync(self):
        entry = AuditEntry(
            id=uuid4(),
            timestamp=datetime.now(timezone.utc),
            user=os.getenv("USER", "unknown"),
            hostname=socket.gethostname(),
            source_database=self.source_config.database,
            target_database=self.target_config.database,
            profile_name=self.profile.name,
            profile_version=self.profile.version,
            profile_hash=hashlib.sha256(self.profile.to_yaml().encode()).hexdigest(),
            tables_synced=self.synced_tables,
            rows_anonymized=self.metrics,
            strategies_applied=self._count_strategies(),
            verification_passed=self.verification_result.passed,
            verification_report=self.verification_result.to_json(),
            signature=self._sign_entry(entry),
        )

        self.audit_logger.log_sync(entry)
```

**Action Items**:
- [ ] Create `AuditEntry` and `AuditLogger` classes
- [ ] Create `confiture_audit_log` table in target database
- [ ] Log every sync operation with full details
- [ ] Generate audit reports: `confiture audit report --days=90`
- [ ] Prevent audit log tampering (append-only permissions)
- [ ] Export audit log for compliance (PDF, CSV)

---

### 3. 🔴 Foreign Key Anonymization Inconsistency

**Issue**: Different seeds for related columns break database joins
- Example: `users.email` and `orders.user_email` hash to different values
- Causes data inconsistency and query failures
- **CRITICAL for referential integrity**

**Current Problem**:
```yaml
# production.yaml
tables:
  users:
    rules:
      - column: email
        strategy: email_mask
        seed: 12345  # Seed A

  orders:
    rules:
      - column: user_email
        strategy: email_mask
        seed: 67890  # Seed B - DIFFERENT!
```

**Result**:
```sql
-- Same user, different hashes:
SELECT * FROM users WHERE email = "user_a1b2c3d4@example.com";  -- 1 row

SELECT * FROM orders WHERE user_email = "user_x9y8z7w6@example.com";  -- Same user, different hash!

-- Join breaks:
SELECT * FROM users u
JOIN orders o ON u.email = o.user_email;  -- Returns 0 rows!
```

**Required Fix**:
```python
# Option 1: Global Seed (Recommended)

@dataclass
class AnonymizationProfile:
    name: str
    version: str
    global_seed: int | None = None  # NEW: Applied to all columns
    strategies: dict[str, AnonymizationStrategy]
    tables: dict[str, list[AnonymizationRule]]

class AnonymizationRule:
    column: str
    strategy: str
    seed: int | None = None  # Column-specific seed (overrides global_seed)

def resolve_seed(rule: AnonymizationRule, profile: AnonymizationProfile) -> int:
    """Column seed > global seed > strategy default."""
    if rule.seed is not None:
        return rule.seed
    return profile.global_seed or 0  # Default to 0

# Usage in YAML:
strategies:
  email_mask:
    type: email

tables:
  users:
    rules:
      - column: email
        strategy: email_mask
        # Seed inherited from global_seed

  orders:
    rules:
      - column: user_email
        strategy: email_mask
        # Seed inherited from global_seed (same as users.email!)

# In profile YAML:
production:
  global_seed: 12345  # All email columns hash consistently
```

**Option 2: Referential Integrity Keys** (Advanced):
```yaml
# production.yaml
global_seed: 12345

referential_integrity:
  - source: users.email
    targets:
      - orders.user_email
      - invoices.customer_email
    # Ensures all three columns hash to same value
```

**Action Items**:
- [ ] Add `global_seed` field to AnonymizationProfile
- [ ] Modify rule resolution to check global_seed before column seed
- [ ] Add referential integrity validation to verifier
- [ ] Test: Same email in different tables must hash to same value
- [ ] Document that changing global_seed breaks existing anonymized data

---

### 4. 🔴 YAML Injection Attack Surface

**Issue**: YAML parsing could enable arbitrary code execution
- `yaml.load()` (unsafe) could execute Python code
- Malicious profile could run `os.system()`, delete files, exfiltrate data
- Even with `safe_load()`, no schema validation

**Why It's Critical**:
```yaml
# Malicious profile (if using yaml.load without restrictions)
strategies:
  evil:
    type: !!python/object/apply:os.system
    args: ['rm -rf /']
    # This would execute on profile load!
```

**Required Fix**:
```python
# confiture/core/anonymization/profile.py (UPDATED)

import yaml
from pydantic import BaseModel, validator
from enum import Enum

class StrategyType(str, Enum):
    """Allowed strategy types (whitelist)."""
    HASH = "hash"
    EMAIL = "email"
    PHONE = "phone"
    REDACT = "redact"
    PATTERN = "pattern"
    # CONDITIONAL deliberately EXCLUDED (too dangerous)

class StrategyConfig(BaseModel):
    """Pydantic validates all config fields."""
    pass

class DeterministicHashConfig(StrategyConfig):
    algorithm: str  # Only allow: sha256, sha1, md5
    length: int | None = None
    prefix: str = ""

    @validator("algorithm")
    def validate_algorithm(cls, v):
        allowed = {"sha256", "sha1", "md5"}
        if v not in allowed:
            raise ValueError(f"Algorithm must be one of {allowed}, got {v}")
        return v

class AnonymizationProfile(BaseModel):
    """Strict schema validation with Pydantic."""
    name: str
    version: str
    global_seed: int | None = None

    strategies: dict[str, dict[str, Any]]
    tables: dict[str, list[dict[str, Any]]]

    @classmethod
    def load(cls, path: Path) -> "AnonymizationProfile":
        """Load and validate profile with strict schema."""
        with open(path) as f:
            # ✅ SAFE: Use safe_load
            raw_data = yaml.safe_load(f)

        # Validate with Pydantic (strict schema)
        try:
            profile = cls(**raw_data)
        except Exception as e:
            raise ValueError(f"Invalid profile {path}: {e}")

        # Additional validation
        cls._validate_strategies(profile)
        cls._validate_table_rules(profile)

        return profile

    @classmethod
    def _validate_strategies(cls, profile: "AnonymizationProfile"):
        """Whitelist allowed strategies."""
        allowed_types = {st.value for st in StrategyType}

        for name, strategy_def in profile.strategies.items():
            strategy_type = strategy_def.get("type")

            if strategy_type not in allowed_types:
                raise ValueError(
                    f"Unknown strategy type: {strategy_type}. "
                    f"Allowed: {allowed_types}"
                )

    @classmethod
    def _validate_table_rules(cls, profile: "AnonymizationProfile"):
        """Validate table rules reference existing strategies."""
        for table_name, rules in profile.tables.items():
            for rule in rules:
                strategy_ref = rule.get("strategy")
                if strategy_ref not in profile.strategies:
                    raise ValueError(
                        f"Table {table_name}: Strategy '{strategy_ref}' "
                        f"not defined in strategies section"
                    )

# CLI validation command:
@app.command()
def validate_profile(path: Path = typer.Argument(...)):
    """Validate anonymization profile YAML."""
    try:
        profile = AnonymizationProfile.load(path)
        console.print(f"✅ Valid profile: {profile.name} v{profile.version}")
        console.print(f"   Strategies: {len(profile.strategies)}")
        console.print(f"   Tables: {len(profile.tables)}")
    except ValueError as e:
        console.print(f"❌ Invalid profile: {e}", style="red")
        raise typer.Exit(1)
```

**Action Items**:
- [ ] Replace `yaml.load()` with `yaml.safe_load()` everywhere
- [ ] Add Pydantic schema validation for all config fields
- [ ] Whitelist allowed strategy types (enum)
- [ ] Add `confiture validate-profile` command
- [ ] Test profile loading with malicious YAML
- [ ] Document security model: "What is out of scope?"

---

## High Priority Issues (P1 - SHOULD FIX in Phase 4.4)

### P1.1: No Transaction Management in Sync

**Issue**: Sync failure leaves partial anonymized data in target database

**Current Code**:
```python
def sync_table(self, table_name: str, rules: list[AnonymizationRule]) -> int:
    # No transaction wrapper!
    src_cursor.execute(f"COPY ...")
    # If this fails, partial data remains
    dst_cursor.execute(f"INSERT ...")
```

**Fix**:
```python
def sync_table_with_profile(self, table_name: str, profile: AnonymizationProfile) -> int:
    try:
        with self.target_conn.transaction():
            # All-or-nothing: either fully synced or rolled back
            rows = self._sync_rows(table_name, profile)
            self.target_conn.execute(
                "SAVEPOINT sync_checkpoint"
            )
            return rows
    except Exception as e:
        self.target_conn.execute(
            "ROLLBACK TO SAVEPOINT sync_checkpoint"
        )
        raise SyncError(f"Sync failed for {table_name}: {e}") from e
```

---

### P1.2: HMAC-Based Hashing (Rainbow Table Prevention)

**Issue**: Plain SHA256 is reversible with known seed

**Fix**:
```python
import hmac

class DeterministicHashStrategy(AnonymizationStrategy):
    def anonymize(self, value: Any) -> Any:
        if value is None:
            return None

        # Use HMAC to prevent rainbow tables
        secret = os.getenv("ANONYMIZATION_SECRET", "default-secret")
        seed = self.config.seed or 0

        key = f"{seed}{secret}".encode()
        hash_value = hmac.new(
            key,
            str(value).encode(),
            hashlib.sha256
        ).hexdigest()

        if self.config.length:
            hash_value = hash_value[:self.config.length]

        return f"{self.config.prefix}{hash_value}"
```

---

### P1.3: Profile Validation CLI

**Issue**: Users won't know if profile YAML is broken until runtime

**Fix**:
```bash
# New command
confiture validate-profile db/anonymization-profiles/production.yaml

# Output:
✅ Valid profile: production v1.0
   Strategies: 5
   Tables: 12
   Global seed: [configured]
   Audit log: enabled
   Compliance: GDPR ✅, CCPA ⚠️
```

---

### P1.4: Document Security Model

**Required**:
- [ ] Create `docs/security/threat-model.md`
- [ ] Answer: "What attacks are in-scope vs out-of-scope?"
- [ ] Example:
  ```markdown
  ## In-Scope (We Protect Against)
  - Rainbow table attacks (HMAC + secret)
  - Accidental seed exposure (env vars, not YAML)
  - Plaintext YAML injection (safe_load + schema validation)
  - Partial sync failures (transactions)

  ## Out-of-Scope (Not Protected)
  - Insider threat: DBA with database access can read original data
  - Stolen database credentials: Attacker with DB access can bypass anonymization
  - Quantum computing: Future quantum computers could break SHA256
  ```

---

## Medium Priority Issues (P2 - Can Defer to Phase 4.5)

| Issue | Why Deferrable | Phase 4.5 Plan |
|-------|---|---|
| Advanced PII detection (ML-based) | Current regex-based is 80% sufficient | Add ML pattern library |
| ConditionalStrategy | Too complex, 95% of users won't need | Remove or redesign |
| PatternBasedStrategy | Can use regex in comments for now | Make it core feature |
| Performance optimization | Current is adequate for most users | Add parallel anonymization |
| Exhaustive verification | Sampling-based is fine for now | Add toggle for compliance audits |

---

## Implementation Checklist - REVISED

### Phase 4.4a: Security Hardening (MUST DO FIRST)

- [ ] **Seed Management**
  - [ ] Remove all hardcoded seeds from example profiles
  - [ ] Add `seed_env_var` to strategy configs
  - [ ] Update ProfileManager to load from environment
  - [ ] Document required env vars for each environment

- [ ] **Audit Logging**
  - [ ] Create `AuditEntry` dataclass
  - [ ] Create `AuditLogger` class
  - [ ] Implement `confiture_audit_log` table schema
  - [ ] Integrate with ProductionSyncer
  - [ ] Add audit report generation

- [ ] **Foreign Key Consistency**
  - [ ] Add `global_seed` to AnonymizationProfile
  - [ ] Update rule resolution to use global_seed
  - [ ] Add test: Same value in different tables = same hash
  - [ ] Document in profile YAML reference

- [ ] **YAML Security**
  - [ ] Audit all yaml.load() calls, change to safe_load()
  - [ ] Add Pydantic schema for all config classes
  - [ ] Create StrategyType enum (whitelist)
  - [ ] Add profile validation tests
  - [ ] Create `confiture validate-profile` command

### Phase 4.4b: Transaction Management

- [ ] Wrap sync in `with target_conn.transaction()`
- [ ] Add savepoint for rollback
- [ ] Test partial failure recovery

### Phase 4.4c: Hashing Improvements

- [ ] Implement HMAC-based hashing
- [ ] Add `ANONYMIZATION_SECRET` environment variable
- [ ] Test rainbow table attack scenario
- [ ] Document in security guide

### Phase 4.4d: Strategy Implementation (4 Core Strategies)

- [ ] DeterministicHashStrategy (HMAC)
- [ ] EmailMaskingStrategy
- [ ] PhoneMaskingStrategy
- [ ] SimpleRedactStrategy
- [ ] ❌ **REMOVE**: PatternBasedStrategy (defer to 4.5)
- [ ] ❌ **REMOVE**: ConditionalStrategy (too complex, re-design needed)

### Phase 4.4e: Profile System & Defaults

- [ ] AnonymizationProfile with schema validation
- [ ] AnonymizationProfileManager with caching
- [ ] 4 default profiles (local, test, staging, production)
- [ ] Profile inheritance (single-level)
- [ ] Profile versioning

### Phase 4.4f: ProductionSyncer Integration

- [ ] Update to use new strategy system
- [ ] Add profile-based anonymization
- [ ] Maintain backward compatibility
- [ ] Integrate audit logging
- [ ] Add transaction management

### Phase 4.4g: Verification System

- [ ] AnonymizationVerifier (regex-based PII detection)
- [ ] Coverage reporting
- [ ] Compliance checking
- [ ] Audit report generation
- [ ] ❌ **Defer**: Exhaustive verification (to 4.5)

### Phase 4.4h: Documentation & Security

- [ ] Update docs/guides/anonymization-strategies.md
- [ ] Create docs/reference/profile-yaml-reference.md
- [ ] Create docs/security/threat-model.md
- [ ] Add example profiles (4)
- [ ] Update CLAUDE.md with Phase 4.4 notes

---

## Revised Architecture Summary

### REMOVED (Simplification)
- ❌ PatternBasedStrategy → Defer to Phase 4.5
- ❌ ConditionalStrategy → Too complex, re-design needed

### MODIFIED (Security Fixes)
- ✅ DeterministicHashStrategy → Now uses HMAC
- ✅ AnonymizationProfile → Added schema validation
- ✅ ProductionSyncer → Added transaction management + audit logging
- ✅ All YAML parsing → Now uses safe_load() + schema validation

### NEW (Compliance Requirements)
- ✅ AuditLogger → Immutable audit trail
- ✅ AuditEntry → Compliance-ready audit data
- ✅ confiture validate-profile → Profile validation CLI
- ✅ Global seed → Foreign key consistency

### CORE FILES (Revised Count)
1. `python/confiture/core/anonymization/strategy.py`
2. `python/confiture/core/anonymization/profile.py` (with validation)
3. `python/confiture/core/anonymization/manager.py`
4. `python/confiture/core/anonymization/audit.py` (NEW)
5. `python/confiture/core/anonymization/verifier.py`
6. `python/confiture/core/anonymization/strategies/hash.py` (HMAC)
7. `python/confiture/core/anonymization/strategies/email.py`
8. `python/confiture/core/anonymization/strategies/phone.py`
9. `python/confiture/core/anonymization/strategies/redact.py`

**Total: 9 core files** (was 12, reduced by removing complex strategies)

---

## Risk Assessment - REVISED

**BEFORE Fixes**: 🟡 Proceed with Changes
**AFTER Fixes**: 🟢 Safe to Proceed

### Remaining Risks
- **Low**: Performance on very large tables (10M+ rows) - mitigated by COPY + batch processing
- **Low**: False positives in PII detection - mitigated by sampling-based approach
- **Medium**: Profile versioning conflicts - mitigated by documentation + CI/CD
- **Medium**: DevOps deployment complexity - mitigated by adding validation CLI + examples

---

## Next Steps

### IMMEDIATE (Before Coding)
1. Review this QA summary with DPO/Security lead
2. Confirm fixes for P0 issues are acceptable
3. Get sign-off on simplified scope (remove Pattern + Conditional strategies)
4. Update PHASE_4_4_PLAN.md with security fixes

### THEN (Week 1)
1. Implement security hardening (seeds, audit, FK consistency, YAML validation)
2. Write tests for P0 issues
3. Create audit table schema
4. Create default profiles with proper seed configuration

### WEEK 2-3
1. Implement 4 core strategies
2. Implement profile system
3. Integrate with ProductionSyncer
4. Implement verifier system
5. Add CLI commands

---

## Questions for User

Before we proceed with revised implementation:

1. **Seed Management**: Environment variables vs secret manager integration?
   - Option A: `ANONYMIZATION_SEED` env var (simple)
   - Option B: AWS Secrets Manager integration (enterprise)
   - **Recommendation**: Start with A, support B later

2. **Audit Log Storage**: In target database vs separate?
   - Option A: Same database (easier, accessible)
   - Option B: Separate audit database (more secure)
   - **Recommendation**: A (users can back it up separately)

3. **HMAC Secret**: Where to store?
   - Option A: `ANONYMIZATION_SECRET` env var
   - Option B: Secret manager
   - Option C: GPG-encrypted file
   - **Recommendation**: A (simple) with option to upgrade to B

4. **PatternBasedStrategy & ConditionalStrategy**: Remove from 4.4?
   - **Recommendation**: Yes, too complex. Redesign for 4.5

5. **Profile Versioning**: Semantic versioning or simple increments?
   - **Recommendation**: Semantic (1.0.0) for clarity

6. **Backward Compatibility**: How long to support old AnonymizationRule?
   - **Recommendation**: Through Phase 4.5, deprecate in Phase 5

---

## Compliance Checklist

Before production use:

- [ ] GDPR Article 32: Encryption, pseudonymization, integrity ✅
- [ ] GDPR Article 30: Record of processing activities ✅ (audit log)
- [ ] GDPR Article 5: Data minimization, retention limits ✅
- [ ] CCPA: Data minimization for CA residents ✅
- [ ] SOC 2: Audit trails, access controls ✅
- [ ] ISO 27001: Information security management ✅
- [ ] HIPAA (if applicable): PHI protection ✅

---

**VERDICT**: 🟢 **SAFE TO PROCEED** (after implementing P0 fixes)

Estimated timeline: 3 weeks for revised scope

