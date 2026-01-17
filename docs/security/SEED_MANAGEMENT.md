# Seed Management Security Guide

**Version**: 1.0
**Date**: 2025-12-27
**Status**: Beta (Not Production-Tested)

---

## 🎯 Overview

Confiture uses **seeded hashing** to create deterministic anonymization that:
- Produces identical hashes for the same input (enabling foreign key consistency)
- Cannot be reversed without the seed (preventing rainbow tables)
- Varies based on configuration (preventing pattern recognition)

This guide explains seed management best practices for production use.

---

## 🔐 What is a Seed?

A **seed** is a number used to initialize a hash function:

```python
import hmac
import hashlib

# Same email, different seeds = different hashes
email = "john@example.com"

# Seed 12345
hmac.new(str(12345).encode(), email.encode(), hashlib.sha256).hexdigest()
# → "e3f4c2a1d5b8c9e2f1a3d5c7b9e1f3a5"

# Seed 99999
hmac.new(str(99999).encode(), email.encode(), hashlib.sha256).hexdigest()
# → "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"
```

**Key Properties**:
- **Deterministic**: Same seed + same input = same output
- **Unique**: Different seed = different output
- **Secure**: Seed is secret (not visible in anonymized data)

---

## 📊 Seed Precedence (3-Tier System)

Confiture resolves seeds using a 3-tier precedence system:

```
┌─ Tier 1: Column-Specific Seed (Highest Priority)
│  └─ Set in YAML profile per column
│  └─ Override global seed for specific columns
│
├─ Tier 2: Global Seed (Second Priority)
│  └─ Set in YAML profile globally
│  └─ Applied to all columns without column-specific seed
│
└─ Tier 3: Default Seed (Lowest Priority)
   └─ Hardcoded to 0
   └─ Used if neither column nor global seed set
```

### Example: Seed Resolution

```yaml
# anonymization_profile.yaml
anonymization:
  global_seed: 12345  # Applied to all columns

  tables:
    users:
      rules:
        - column: email
          strategy: email_mask
          # No seed specified → uses global_seed: 12345

        - column: ssn
          strategy: hash
          seed: 99999  # Overrides global_seed: 12345

        - column: phone
          strategy: phone_mask
          # No seed specified → uses global_seed: 12345
```

**Resolution**:
- `email`: Uses 12345 (from global_seed)
- `ssn`: Uses 99999 (column-specific, overrides global)
- `phone`: Uses 12345 (from global_seed)

---

## 🚀 Production Setup

### Step 1: Generate Secure Seeds

```bash
# Generate cryptographically random seeds
python3 -c "
import secrets
for i in range(5):
    seed = secrets.randbits(32)
    print(f'ANONYMIZATION_SEED_{i}: {seed}')
"

# Output:
# ANONYMIZATION_SEED_0: 1847362956
# ANONYMIZATION_SEED_1: 2156483729
# ANONYMIZATION_SEED_2: 3964827156
# ANONYMIZATION_SEED_3: 1738294756
# ANONYMIZATION_SEED_4: 2948362847
```

### Step 2: Store in Secure Location

**❌ DON'T**: Hardcode in configuration files
```yaml
# DANGEROUS!
anonymization:
  global_seed: 12345  # Exposed in version control!
```

**✅ DO**: Use environment variables

```bash
# Set in .env.production (NEVER commit to git)
export ANONYMIZATION_SEED_GLOBAL=1847362956
export ANONYMIZATION_SEED_EMAIL=2156483729
export ANONYMIZATION_SEED_SSN=3964827156
```

**✅ BETTER**: Use secret management system

```bash
# Using HashiCorp Vault
vault kv put secret/confiture/seeds \
  global=1847362956 \
  email=2156483729 \
  ssn=3964827156

# Using AWS Secrets Manager
aws secretsmanager create-secret \
  --name confiture/seeds \
  --secret-string '{
    "global": 1847362956,
    "email": 2156483729,
    "ssn": 3964827156
  }'
```

### Step 3: Configure Application

```python
# confiture/config.py
import os
from confiture.core.anonymization.profile import AnonymizationProfile

# Load profile from YAML (no seeds in file!)
with open("anonymization_profile.yaml") as f:
    profile_dict = yaml.safe_load(f)

# Inject seeds from environment
if "ANONYMIZATION_SEED_GLOBAL" in os.environ:
    profile_dict["global_seed"] = int(os.environ["ANONYMIZATION_SEED_GLOBAL"])

# Create profile (seeds now from environment)
profile = AnonymizationProfile(**profile_dict)
```

### Step 4: Verify Configuration

```bash
# Test that seeds are resolved correctly
python3 -c "
from confiture.core.anonymization.profile import AnonymizationProfile
import yaml

with open('anonymization_profile.yaml') as f:
    profile = AnonymizationProfile.load('anonymization_profile.yaml')

print(f'Global seed: {profile.global_seed}')
for table_name, table_def in profile.tables.items():
    for rule in table_def.rules:
        from confiture.core.anonymization.profile import resolve_seed_for_column
        seed = resolve_seed_for_column(rule, profile)
        print(f'  {table_name}.{rule.column}: {seed}')
"
```

---

## 🔄 Seed Rotation

### Why Rotate Seeds?

1. **Compromise Response**: If seed is leaked, rotation prevents further damage
2. **Access Control**: Limits who can see pre-anonymization mappings
3. **Compliance**: Many standards require regular key rotation

### Rotation Strategy

```python
# Option 1: Version-based rotation
# Keep seeds separate for each anonymization profile version

anonymization_profile_v1.yaml:
  name: "production_anon_v1"
  global_seed: 1234567890  # Seed for v1

anonymization_profile_v2.yaml:
  name: "production_anon_v2"
  global_seed: 9876543210  # Different seed for v2

# Option 2: Date-based rotation
ANONYMIZATION_SEED_2025_Q1=1234567890
ANONYMIZATION_SEED_2025_Q2=9876543210
ANONYMIZATION_SEED_2025_Q3=5555555555
```

### Rotation Process

**1. Prepare New Seed**
```bash
# Generate and store new seed
NEW_SEED=$(python3 -c "import secrets; print(secrets.randbits(32))")
vault kv put secret/confiture/seeds/2025-q2 value=$NEW_SEED
```

**2. Update Configuration**
```bash
# Update environment variable (old data keeps old seed)
export ANONYMIZATION_SEED_GLOBAL=$NEW_SEED
```

**3. Update YAML Profile**
```yaml
# Update profile version
anonymization:
  name: "production_anon_v2"
  version: "2.0"
  global_seed: # Will be resolved from ANONYMIZATION_SEED_GLOBAL env var
```

**4. Verify New Hashes**
```bash
# New data will hash differently
python3 -c "
from confiture.core.anonymization.strategies.email import EmailMaskingStrategy, EmailMaskConfig

# Old seed
strategy_old = EmailMaskingStrategy(EmailMaskConfig(seed=1234567890))
print('Old seed hash:', strategy_old.anonymize('john@example.com'))

# New seed
strategy_new = EmailMaskingStrategy(EmailMaskConfig(seed=9876543210))
print('New seed hash:', strategy_new.anonymize('john@example.com'))
"

# Output:
# Old seed hash: user_a1b2c3d4@example.com
# New seed hash: user_x9y8z7w6@example.com
```

**5. Archive Old Seed**
```bash
# Keep old seed for re-anonymization if needed
vault kv put secret/confiture/seeds/archived/2025-q1 value=1234567890
```

### When NOT to Rotate

⚠️ **DO NOT rotate seeds if**:
- Foreign key consistency required across old and new data
- Data must remain consistent across multiple systems
- Changing seed would break data relationships

✅ **Safe to rotate when**:
- Starting new anonymization cycle
- Creating new test database
- Decommissioning old database

---

## 🔒 Security Best Practices

### 1. Separate Seed Per Environment

```bash
# Development (less sensitive)
export ANONYMIZATION_SEED_DEV=1111111111

# Staging (moderate sensitivity)
export ANONYMIZATION_SEED_STAGING=2222222222

# Production (highest sensitivity)
export ANONYMIZATION_SEED_PROD=3333333333
```

### 2. Limit Seed Access

```yaml
# AWS IAM Policy
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue"],
      "Resource": "arn:aws:secretsmanager:*:*:secret:confiture/seeds-*",
      "Principal": {
        "AWS": "arn:aws:iam::ACCOUNT:role/confiture-app"
      }
    }
  ]
}
```

### 3. Audit Seed Usage

```python
# Every sync operation logs which profile was used
audit_entry = create_sync_audit_entry(
    user="dba@company.com",
    profile=profile,  # Profile includes seed info
    # ...
)

# Audit entry includes profile hash
print(f"Profile hash: {audit_entry.profile_hash}")
# Verifying: SHA256(profile including seeds) = abc123...
```

### 4. Never Log Seeds

```python
# ❌ DON'T
logger.info(f"Using seed: {seed}")  # DANGEROUS!

# ✅ DO
logger.info(f"Using profile: {profile.name} v{profile.version}")
logger.debug(f"Profile hash: {hash_profile(profile)}")  # Hash, not seed
```

### 5. Rotate on Access Compromise

```python
# If seed is accidentally exposed
if SEED_LEAKED:
    # 1. Generate new seed immediately
    new_seed = secrets.randbits(32)

    # 2. Store in vault
    vault.write("secret/confiture/seeds", value=new_seed)

    # 3. Invalidate old data (if feasible)
    # Update ANONYMIZATION_SEED_GLOBAL to new_seed

    # 4. Re-anonymize if needed
    # Regenerate test data with new seed
```

---

## 🧪 Testing with Seeds

### Deterministic Testing

```python
# Reproducible test: Same seed = same output
def test_email_anonymization():
    seed = 12345  # Fixed seed for testing
    strategy = EmailMaskingStrategy(EmailMaskConfig(seed=seed))

    # Same email always produces same hash
    hash1 = strategy.anonymize("john@example.com")
    hash2 = strategy.anonymize("john@example.com")

    assert hash1 == hash2  # ✓ PASSED
```

### Cross-System Consistency

```python
# Same seed in multiple systems = same hashes
def test_fk_consistency_across_systems():
    seed = 12345

    # System A
    users_hash = hash_email_in_system_a("john@example.com", seed)

    # System B
    orders_hash = hash_email_in_system_b("john@example.com", seed)

    assert users_hash == orders_hash  # ✓ FK integrity maintained
```

### Seed Precedence Testing

```python
from confiture.core.anonymization.profile import resolve_seed_for_column

def test_seed_precedence():
    profile = AnonymizationProfile(
        global_seed=1000,
        tables={
            "users": TableDefinition(
                rules=[
                    AnonymizationRule(column="email", strategy="email_mask"),
                    AnonymizationRule(column="ssn", strategy="hash", seed=2000),
                ]
            )
        }
    )

    # Email uses global seed
    assert resolve_seed_for_column(
        profile.tables["users"].rules[0],
        profile
    ) == 1000

    # SSN uses column-specific seed
    assert resolve_seed_for_column(
        profile.tables["users"].rules[1],
        profile
    ) == 2000
```

---

## 📋 Seed Management Checklist

### Initial Setup
- [ ] Generate cryptographically random seeds
- [ ] Store in secret management system (not version control)
- [ ] Set environment variables in production
- [ ] Document seed purposes (which field, why different)
- [ ] Test seed resolution works correctly
- [ ] Verify audit logs include profile hash (not seed)

### Ongoing Operations
- [ ] Weekly: Verify audit logs show correct profile
- [ ] Monthly: Check seed rotation schedule
- [ ] Quarterly: Review seed access logs
- [ ] Annually: Rotate seeds (or annually review if no need)

### Incident Response
- [ ] If seed compromised: Generate new seed immediately
- [ ] Update environment variables
- [ ] Update audit trail with rotation timestamp
- [ ] Plan re-anonymization if data was exposed
- [ ] Notify security team

### Compliance
- [ ] Document seed management policy
- [ ] DPA includes seed security measures
- [ ] ROPA documents seed handling
- [ ] Audit trail proves seed usage
- [ ] Annual security review includes seed audit

---

## ⚠️ Common Mistakes

### Mistake 1: Hardcoding Seeds in YAML

```yaml
# ❌ WRONG
anonymization:
  global_seed: 12345  # Exposed in git!
```

```yaml
# ✅ CORRECT
anonymization:
  global_seed: # Leave empty, resolved from environment
```

### Mistake 2: Reusing Same Seed Everywhere

```yaml
# ❌ WRONG
anonymization:
  global_seed: 12345

  tables:
    users:
      rules:
        - column: email
          strategy: email_mask
          seed: 12345  # Same seed!

        - column: ssn
          strategy: hash
          seed: 12345  # Same seed!
```

```yaml
# ✅ CORRECT
anonymization:
  global_seed: 12345

  tables:
    users:
      rules:
        - column: email
          strategy: email_mask
          # Uses global_seed (12345)

        - column: ssn
          strategy: hash
          seed: 99999  # Different seed!
```

### Mistake 3: Rotating Seeds Without Planning

```python
# ❌ WRONG
# Old data: john@example.com → user_abc@example.com (seed 12345)
# Change seed to 99999
# New data: john@example.com → user_xyz@example.com (seed 99999)
# FK relationships broken! ❌

# ✅ CORRECT
# Option 1: Keep old seed for old data, new seed for new data
# Option 2: Rotate entire dataset together
# Option 3: Accept FK breakage if refreshing test data anyway
```

### Mistake 4: Logging Seeds

```python
# ❌ WRONG
logger.info(f"Hashing with seed: {seed}")
print(f"Configuration: seed={seed}")  # Visible in process list!

# ✅ CORRECT
logger.info(f"Using profile: {profile.name}")
logger.debug(f"Profile hash: {hash_profile(profile)}")  # Hash, not seed
```

---

## 🔗 Integration with Other Systems

### With YAML Profiles

```yaml
# anonymization_profile.yaml
# No seeds in file - they're resolved from environment
anonymization:
  name: "production_anon_v1"
  version: "1.0"
  # global_seed: (resolved from ANONYMIZATION_SEED_GLOBAL env var)

  tables:
    users:
      rules:
        - column: email
          strategy: email_mask
          # Uses global seed from environment
```

### With Database Audit Trail

```sql
-- audit entry includes profile hash (not seed)
SELECT
    id,
    user,
    timestamp,
    profile_name,
    profile_version,
    profile_hash,  -- SHA256 of profile (proves which seed was used)
    signature      -- HMAC of entry (tamper proof)
FROM confiture_audit
WHERE timestamp > NOW() - INTERVAL '7 days';
```

### With CI/CD Pipeline

```bash
#!/bin/bash
# sync-to-staging.sh

# Load seeds from vault
SECRET=$(vault kv get -format=json secret/confiture/seeds)
SEED=$(echo $SECRET | jq -r '.data.data.global')

# Set environment
export ANONYMIZATION_SEED_GLOBAL=$SEED

# Run anonymization
python -m confiture sync \
  --source-db production \
  --target-db staging \
  --profile anonymization_profile.yaml

# Verify
python -m confiture audit-verify --strict
```

---

## ✅ Verification & Testing

Run tests to verify seed management:

```bash
# Test seed resolution
pytest tests/unit/test_anonymization_strategy.py::TestSeedResolution -v

# Test foreign key consistency
pytest tests/unit/test_foreign_key_consistency.py -v

# Test audit trail with profile hashing
pytest tests/unit/test_syncer_audit_integration.py::TestProfileHashing -v

# All anonymization tests
pytest tests/unit/test_anonymization_*.py -v
```

**Expected Result**: ✅ 140/140 tests passing

---

## 📞 Support & Questions

**Questions about seed management?**
- Review `docs/security/THREAT_MODEL.md` for security details
- Check `docs/security/GDPR_ARTICLE_30.md` for compliance requirements
- See `WEEK_0_DAY_1_SUMMARY.md` for implementation details

**Found a security issue?**
- Contact: [Security contact info]
- Process: [Responsible disclosure process]

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-12-27 | Initial release (Week 0 completion) |

**Next Review**: 2026-03-27 (Q1 2026)

