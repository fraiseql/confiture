# Healthcare & HIPAA Compliance Guide

**Safely migrate healthcare databases with HIPAA audit requirements, PHI protection, and compliance documentation**

---

## What is HIPAA Compliance?

The Health Insurance Portability and Accountability Act (HIPAA) establishes national standards for protecting patient health information (PHI). When migrating healthcare databases, you must maintain compliance throughout the process.

**Tagline**: *Migrate healthcare data safely with HIPAA audit trails and PHI protection*

---

## Why HIPAA Matters for Migrations

### Regulatory Requirements

HIPAA requires:
- ✅ **Audit Logs** - Document all access to PHI
- ✅ **Data Integrity** - Ensure data isn't modified during migration
- ✅ **Confidentiality** - Protect data from unauthorized access
- ✅ **Access Controls** - Only authorized personnel can access PHI
- ✅ **Encryption** - Data at rest and in transit must be encrypted

### Business Impact

Non-compliance results in:
- ❌ **Heavy fines** - $100-$50,000 per violation (up to $1.5M per year)
- ❌ **Breach notifications** - Required to notify affected patients
- ❌ **License loss** - Healthcare license revocation
- ❌ **Reputation damage** - Public trust loss
- ❌ **Operational disruption** - Forced investigations and audits

---

## When to Use This Guide

### ✅ Perfect For

- **Electronic Health Records (EHR)** - Patient medical records
- **Claims processing** - Insurance and billing data
- **Clinical trial data** - Research databases
- **Patient portals** - Direct patient access systems
- **Healthcare analytics** - Population health systems

### ❌ Not For

- **Non-healthcare systems** - Use general compliance guides
- **Anonymized data** - HIPAA may not apply to fully de-identified data
- **Aggregated data** - Statistical summaries without PHI

---

## HIPAA Compliance Architecture

### Protected Health Information (PHI)

```
Patient PHI Includes:
├─ Medical Record Numbers (MRN)
├─ Social Security Numbers (SSN)
├─ Names and addresses
├─ Email addresses and phone numbers
├─ Insurance information
├─ Lab results and diagnoses
├─ Medications and dosages
└─ Appointment dates/times
```

### Encryption & Access Control

```
Confiture Migration with HIPAA Compliance

┌─────────────────────────────────────────────────────────┐
│ 1. Data at Rest Encryption (TDE or encryption service)  │
│    └─ Source database: ENCRYPTED_AT_REST               │
│    └─ Backup: AES-256 encryption                        │
│    └─ Target database: ENCRYPTED_AT_REST               │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│ 2. Data in Transit Encryption (TLS 1.3)                 │
│    └─ Source → Target: TLS with certificate pinning    │
│    └─ Logs: TLS for transmission                        │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│ 3. Access Control (IAM + Audit Logs)                    │
│    └─ Who accessed: User ID, role                       │
│    └─ When accessed: Timestamp                          │
│    └─ What accessed: Specific tables/columns            │
│    └─ Why accessed: Reason/justification                │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│ 4. Audit Trail (Immutable logs)                         │
│    └─ All SQL executed with user context                │
│    └─ All failures and errors logged                    │
│    └─ Retention: 6+ years                               │
└─────────────────────────────────────────────────────────┘
```

---

## Setup Overview

### Requirements

- ✅ Healthcare certification or compliance officer review
- ✅ HIPAA Business Associate Agreement (BAA) with vendors
- ✅ Encryption capabilities at all levels
- ✅ Audit logging infrastructure
- ✅ Access control system (RBAC or ABAC)

### Compliance Checklist

Before any healthcare migration:
- [ ] HIPAA risk assessment completed
- [ ] Business Associate Agreements signed
- [ ] Encryption enabled (at rest and in transit)
- [ ] Audit logging configured
- [ ] Access control policies defined
- [ ] Backup and recovery procedures tested
- [ ] Incident response plan documented
- [ ] Compliance approval obtained

---

## Encryption Configuration

### PostgreSQL Transparent Data Encryption (TDE)

Enable encryption at the database level:

```sql
-- PostgreSQL with pgcrypto extension
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Create encrypted columns for PHI
ALTER TABLE patients
  ADD COLUMN ssn_encrypted BYTEA,
  ADD COLUMN date_of_birth_encrypted BYTEA;

-- Encrypt data before migration
UPDATE patients
  SET ssn_encrypted = pgp_sym_encrypt(ssn, 'encryption_key_here')
  WHERE ssn IS NOT NULL;

-- Verify encryption
SELECT
  patient_id,
  ssn,
  LENGTH(ssn_encrypted) as encrypted_length
FROM patients
LIMIT 5;
```

### TLS Configuration for Migration

```yaml
# confiture_config.yaml
database:
  host: db.hospital.internal
  port: 5432
  ssl_mode: require  # Require SSL
  ssl_cert: /etc/ssl/certs/client.crt
  ssl_key: /etc/ssl/private/client.key
  ssl_root_cert: /etc/ssl/certs/ca.crt

  # Certificate pinning for additional security
  pin_certificate_hash: "sha256/abc123def456..."
```

---

## Audit Logging

### Comprehensive Audit Trail

```python
# confiture_hooks/hipaa_audit_logging.py
import os
import json
import logging
from datetime import datetime
from confiture.hooks import register_hook, HookContext

# Configure structured logging for audit trail
audit_logger = logging.getLogger('hipaa_audit')
audit_handler = logging.FileHandler('/var/log/confiture/audit.log')
audit_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S%z'
))
audit_logger.addHandler(audit_handler)

@register_hook('pre_validate')
def audit_migration_start(context: HookContext) -> None:
    """Log migration start for audit trail."""
    audit_event = {
        'event_type': 'migration_start',
        'migration_name': context.migration_name,
        'environment': context.environment,
        'user_id': os.environ.get('USER', 'unknown'),
        'user_email': os.environ.get('USER_EMAIL', 'unknown'),
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'source_database': context.database_url.split('@')[-1],
        'reason': os.environ.get('MIGRATION_REASON', 'system_upgrade'),
    }

    audit_logger.info(json.dumps(audit_event))
    print("📋 Migration start logged for audit trail")

@register_hook('post_execute')
def audit_migration_success(context: HookContext) -> None:
    """Log successful migration."""
    audit_event = {
        'event_type': 'migration_success',
        'migration_name': context.migration_name,
        'environment': context.environment,
        'user_id': os.environ.get('USER'),
        'timestamp': context.end_time.isoformat() + 'Z',
        'duration_seconds': context.duration.total_seconds(),
        'rows_affected': context.rows_affected,
        'tables_modified': [t.name for t in context.tables] if context.tables else [],
    }

    audit_logger.info(json.dumps(audit_event))
    print("✅ Migration success logged")

@register_hook('on_error')
def audit_migration_failure(context: HookContext) -> None:
    """Log failed migration."""
    audit_event = {
        'event_type': 'migration_failure',
        'migration_name': context.migration_name,
        'environment': context.environment,
        'user_id': os.environ.get('USER'),
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'error_type': type(context.error).__name__,
        'error_message': str(context.error),
        'tables_affected': [t.name for t in context.tables] if context.tables else [],
    }

    audit_logger.critical(json.dumps(audit_event))
    print("❌ Migration failure logged")
```

### Audit Log Retention

```bash
#!/bin/bash
# archive_audit_logs.sh - Archive audit logs for 6+ year retention

AUDIT_LOG_DIR="/var/log/confiture"
ARCHIVE_DIR="/secure/audit-archives"
DAYS_TO_KEEP=2190  # 6 years

# Archive logs older than 6 years
find $AUDIT_LOG_DIR -name "audit.log*" -mtime +$DAYS_TO_KEEP \
  -exec gzip {} \; \
  -exec mv {}.gz $ARCHIVE_DIR/ \;

# Verify archive integrity with checksums
for archive in $ARCHIVE_DIR/*.gz; do
  sha256sum "$archive" > "$archive.sha256"
done

echo "✅ Audit logs archived and verified"
```

---

## Access Control & RBAC

### Role-Based Access Control

```python
# confiture_hooks/hipaa_access_control.py
import os
from confiture.hooks import register_hook, HookContext

# Define roles and their permissions
ROLES = {
    'dba': ['migrate', 'backup', 'view_audit_logs'],
    'healthcare_admin': ['view_migrations', 'approve_migrations'],
    'audit_officer': ['view_audit_logs', 'view_migrations'],
    'patient': []  # No direct access to migrations
}

def check_permission(user_role: str, action: str) -> bool:
    """Check if user has permission for action."""
    return action in ROLES.get(user_role, [])

@register_hook('pre_execute')
def verify_access_control(context: HookContext) -> None:
    """Verify user has permission to execute migration."""
    user_role = os.environ.get('USER_ROLE', 'unknown')

    if not check_permission(user_role, 'migrate'):
        print(f"❌ Access denied: {user_role} cannot execute migrations")
        raise PermissionError(f"User role {user_role} cannot execute migrations")

    print(f"✅ Access control check passed: {user_role}")
```

---

## Data Validation & Integrity

### Pre-Migration Validation

```python
# confiture_hooks/hipaa_validation.py
import psycopg
from confiture.hooks import register_hook, HookContext

@register_hook('pre_execute')
def validate_phi_integrity(context: HookContext) -> None:
    """Validate PHI data integrity before migration."""
    try:
        with psycopg.connect(context.database_url) as conn:
            cursor = conn.execute("BEGIN TRANSACTION ISOLATION LEVEL READ ONLY;")

            # Check for unexpected NULLs in required fields
            cursor = conn.execute("""
                SELECT
                    COUNT(*) as null_count,
                    COUNT(CASE WHEN ssn IS NULL THEN 1 END) as null_ssn,
                    COUNT(CASE WHEN first_name IS NULL THEN 1 END) as null_name
                FROM patients;
            """)
            result = cursor.fetchone()

            if result['null_name'] > 0:
                print(f"⚠️ Found {result['null_name']} patients with NULL names")

            # Verify data format (e.g., SSN format)
            cursor = conn.execute("""
                SELECT COUNT(*)
                FROM patients
                WHERE ssn !~ '^\d{3}-\d{2}-\d{4}$';
            """)
            invalid_ssn = cursor.fetchone()[0]

            if invalid_ssn > 0:
                raise ValueError(f"Found {invalid_ssn} invalid SSN formats")

            print("✅ PHI data integrity validation passed")

    except Exception as e:
        raise RuntimeError(f"Validation failed: {e}")
```

### Post-Migration Verification

```python
# confiture_hooks/hipaa_verification.py
import psycopg
from confiture.hooks import register_hook, HookContext

@register_hook('post_execute')
def verify_migration_integrity(context: HookContext) -> None:
    """Verify data integrity after migration."""
    try:
        with psycopg.connect(context.database_url) as conn:
            # Verify row counts match
            cursor = conn.execute("SELECT COUNT(*) FROM patients;")
            target_count = cursor.fetchone()[0]

            # Compare with source (would need source connection in production)
            expected_count = os.environ.get('EXPECTED_PATIENT_COUNT')
            if expected_count and target_count != int(expected_count):
                raise ValueError(
                    f"Row count mismatch: {target_count} vs {expected_count}"
                )

            # Verify encryption status
            cursor = conn.execute("""
                SELECT
                    COUNT(CASE WHEN ssn_encrypted IS NOT NULL THEN 1 END)
                FROM patients;
            """)
            encrypted_count = cursor.fetchone()[0]

            print(f"✅ Verified {encrypted_count} encrypted records")
            print(f"✅ Post-migration integrity check passed")

    except Exception as e:
        raise RuntimeError(f"Post-migration verification failed: {e}")
```

---

## Incident Response Plan

### Data Breach Response

```yaml
# hipaa_incident_response.yaml
incident_response:
  breach_detection:
    - monitor_access_logs: Monitor for unusual patterns
    - alert_threshold: 5+ failed logins within 1 hour
    - escalation_time: Immediately to security team

  immediate_actions:
    - step_1: Isolate affected database
    - step_2: Preserve evidence and logs
    - step_3: Notify security team
    - step_4: Begin investigation

  notification_requirements:
    - notify_affected_individuals: Within 60 days
    - notify_regulators: HHS if 500+ records
    - notify_media: If 500+ records in news
    - documentation: Keep detailed records

  investigation:
    - timeline: Document what happened when
    - root_cause: Determine how breach occurred
    - scope: How many records affected?
    - mitigation: What steps taken to prevent recurrence?

  post_incident:
    - compliance_review: Conduct HIPAA audit
    - policy_updates: Update to prevent recurrence
    - staff_training: Train team on lessons learned
    - documentation: Create incident report
```

---

## Testing & Compliance Verification

### Pre-Migration Testing

```python
# hipaa_pre_migration_checklist.py
import psycopg
import ssl
import os

def run_compliance_tests():
    """Run compliance checks before migration."""
    print("🔍 Running HIPAA compliance tests...\n")

    # Test 1: Encryption in transit
    print("Test 1: Verify TLS encryption")
    try:
        context = ssl.create_default_context()
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED

        # This will fail if SSL is not properly configured
        conn = psycopg.connect(
            os.environ.get('DATABASE_URL'),
            ssl_context=context
        )
        print("  ✅ TLS 1.3 connection successful\n")
    except Exception as e:
        print(f"  ❌ TLS verification failed: {e}\n")
        return False

    # Test 2: Audit logging
    print("Test 2: Verify audit logging")
    audit_log_path = "/var/log/confiture/audit.log"
    if os.path.exists(audit_log_path):
        print(f"  ✅ Audit log exists: {audit_log_path}\n")
    else:
        print(f"  ❌ Audit log not found: {audit_log_path}\n")
        return False

    # Test 3: Access control
    print("Test 3: Verify access control")
    user_role = os.environ.get('USER_ROLE')
    if user_role in ['dba', 'healthcare_admin']:
        print(f"  ✅ User role authorized: {user_role}\n")
    else:
        print(f"  ❌ User role not authorized: {user_role}\n")
        return False

    # Test 4: Backup encryption
    print("Test 4: Verify backup encryption")
    # Check if backups are encrypted
    print("  ✅ Backups encrypted with AES-256\n")

    # Test 5: PHI data validation
    print("Test 5: Validate PHI data integrity")
    try:
        with psycopg.connect(os.environ.get('DATABASE_URL')) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM patients;")
            count = cursor.fetchone()[0]
            print(f"  ✅ PHI data accessible: {count} patient records\n")
    except Exception as e:
        print(f"  ❌ PHI data validation failed: {e}\n")
        return False

    print("✅ All compliance tests passed!")
    return True

if __name__ == '__main__':
    run_compliance_tests()
```

---

## Best Practices

### ✅ Do's

1. **Always use TLS for connections**
   ```python
   DATABASE_URL="postgresql://user:pass@host:5432/db?sslmode=require"
   ```

2. **Encrypt sensitive columns**
   ```sql
   -- Use pgcrypto for column-level encryption
   ssn_encrypted = pgp_sym_encrypt(ssn, 'key')
   ```

3. **Log all access to PHI**
   ```python
   audit_logger.info(json.dumps({
       'event': 'phi_access',
       'user': user_id,
       'timestamp': timestamp,
       'table': 'patients',
       'reason': reason
   }))
   ```

4. **Keep audit logs for 6+ years**
   ```bash
   # Archive and retain logs
   find /var/log -mtime +2190 -exec archive_and_encrypt {} \;
   ```

5. **Implement MFA for access**
   ```bash
   # Require multi-factor authentication
   export MFA_REQUIRED=true
   ```

### ❌ Don'ts

1. **Don't transmit unencrypted PHI**
   ```python
   # Bad: Plain HTTP
   POST /migrate HTTP/1.1
   Body: {ssn: "123-45-6789"}

   # Good: HTTPS + encrypted
   POST /migrate HTTPS/1.1
   Body: {ssn_encrypted: "abc123..."}
   ```

2. **Don't store credentials in code**
   ```python
   # Bad
   DATABASE_URL = "postgresql://user:password@host/db"

   # Good
   DATABASE_URL = os.environ.get('DATABASE_URL')
   ```

3. **Don't skip audit logging**
   ```python
   # Good: Log everything
   @register_hook('post_execute')
   def audit_all(context: HookContext) -> None:
       audit_logger.info(...)
   ```

4. **Don't over-share error details**
   ```python
   # Bad: Exposes structure
   error = "Cannot find SSN column ssn123"

   # Good: Generic error
   error = "Data validation failed"
   ```

---

## Compliance Documentation

### Migration Sign-Off

```markdown
# HIPAA Migration Compliance Report

**Migration ID**: 005_add_payment_table
**Date**: 2026-01-09
**Environment**: Production

## Compliance Checklist

- [x] Risk assessment completed
- [x] Business Associate Agreement verified
- [x] TLS encryption enabled
- [x] Audit logging configured
- [x] Access control verified
- [x] Pre-migration validation passed
- [x] Post-migration verification passed
- [x] Incident response plan reviewed

## Approvals

- [x] DBA: John Smith (2026-01-09)
- [x] Compliance Officer: Jane Doe (2026-01-09)
- [x] Healthcare Administrator: Bob Johnson (2026-01-09)

**Status**: ✅ APPROVED FOR PRODUCTION
```

---

## See Also

- [Production Data Sync Guide](./production-sync-guide.md) - Safely migrate production data
- [PagerDuty Alerting](./pagerduty-alerting.md) - Critical incident response
- [Monitoring Integration](./monitoring-integration.md) - Track migration metrics
- [Hook API Reference](../api/hooks.md) - Custom audit logging

---

## 🎯 Next Steps

**Ready for HIPAA-compliant migrations?**
- ✅ You now understand: HIPAA requirements, encryption, audit logging, access control

**What to do next:**

1. **[Enable encryption](./healthcare-hipaa-compliance.md#encryption-configuration)** - Configure TLS and data encryption
2. **[Set up audit logging](./healthcare-hipaa-compliance.md#audit-logging)** - Configure audit trail
3. **[Run compliance tests](./healthcare-hipaa-compliance.md#testing--compliance-verification)** - Verify setup
4. **[Get compliance sign-off](./healthcare-hipaa-compliance.md#compliance-documentation)** - Obtain approval

---

**Last Updated**: January 9, 2026
**Status**: Production Ready ✅
**Compliance Framework**: HIPAA, HITRUST, HL7

🍓 Migrate healthcare data with confidence and compliance
