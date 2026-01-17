# Confiture Security Model

This document describes the security architecture and controls implemented in Confiture.

## Table of Contents

- [Overview](#overview)
- [Threat Model](#threat-model)
- [Security Controls](#security-controls)
- [Secure Deployment](#secure-deployment)
- [Compliance Guidance](#compliance-guidance)
- [Security Checklist](#security-checklist)

---

## Overview

Confiture handles sensitive database operations including schema modifications,
data migrations, and access to production databases. Security is built into
every layer of the system.

### Security Principles

1. **Defense in Depth**: Multiple layers of security controls
2. **Least Privilege**: Minimum necessary access
3. **Secure by Default**: Safe configurations out of the box
4. **Audit Trail**: Complete logging of all operations
5. **Fail Secure**: Errors result in safe state

---

## Threat Model

### Assets

| Asset | Sensitivity | Description |
|-------|-------------|-------------|
| Database credentials | Critical | Connection strings, passwords |
| Database schema | High | Structure of production databases |
| Migration files | High | SQL that can modify databases |
| Application data | High | Business data in tables |
| Audit logs | Medium | Record of changes |
| Configuration | Medium | System settings |

### Threats

#### T1: SQL Injection

**Attack Vector**: Malicious SQL in migration files or inputs

**Impact**: Data theft, data corruption, privilege escalation

**Mitigations**:
- Input validation for all identifiers
- Parameterized queries (required by framework)
- SQL pattern detection
- Code review requirements

#### T2: Credential Exposure

**Attack Vector**: Secrets in logs, config files, or version control

**Impact**: Unauthorized database access

**Mitigations**:
- Automatic log redaction
- Environment variable configuration
- KMS integration for sensitive data
- Pre-commit secret scanning

#### T3: Unauthorized Access

**Attack Vector**: Running migrations without permission

**Impact**: Schema changes by unauthorized users

**Mitigations**:
- Database role separation
- Advisory locking
- Audit logging
- Environment-based controls

#### T4: Data Corruption

**Attack Vector**: Bugs or errors in migrations

**Impact**: Data loss, application downtime

**Mitigations**:
- Checksum verification
- Dry-run mode
- Transactional migrations (default)
- Automatic rollback on failure

#### T5: Path Traversal

**Attack Vector**: Malicious file paths to access unauthorized files

**Impact**: Reading/writing unauthorized files

**Mitigations**:
- Path validation with traversal prevention
- Base directory enforcement
- Resolved path checking

---

## Security Controls

### 1. Input Validation

All external inputs are validated before use:

```python
from confiture.core.security.validation import (
    validate_identifier,
    validate_path,
    validate_sql,
)

# Table names validated against pattern and reserved words
validate_identifier("users")  # OK
validate_identifier("'; DROP TABLE users; --")  # Raises ValidationError

# Paths validated for traversal attacks
validate_path("migrations/001.py", base_dir=Path("migrations"))  # OK
validate_path("../../../etc/passwd", base_dir=Path("migrations"))  # Raises

# SQL validated for dangerous patterns
validate_sql("SELECT * FROM users")  # OK
validate_sql("SELECT 1; DROP TABLE users")  # Raises
```

### 2. Parameterized Queries

All database operations MUST use parameterized queries:

```python
# CORRECT - Parameterized query
cursor.execute(
    "SELECT * FROM users WHERE id = %s",
    (user_id,)
)

# WRONG - String interpolation (NEVER DO THIS)
cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
```

Confiture's internal operations all use parameterized queries. Migration
authors are responsible for following this pattern in their migration files.

### 3. Secret Management

#### Environment Variables

```bash
# Recommended: Use environment variables
export DATABASE_URL="postgresql://user:pass@host:5432/db?sslmode=require"
export CONFITURE_KMS_KEY_ID="arn:aws:kms:..."
```

#### KMS Integration

```python
from confiture.core.anonymization.security.kms_manager import KMSManager

# Encrypt sensitive data
kms = KMSManager(provider="aws", key_id=os.environ["KMS_KEY_ID"])
encrypted = kms.encrypt(sensitive_data)

# Decrypt when needed
decrypted = kms.decrypt(encrypted)
```

#### Never Commit Secrets

```gitignore
# .gitignore
.env
*.pem
*.key
credentials.json
```

Use pre-commit hooks to prevent accidental commits:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.0
    hooks:
      - id: gitleaks
```

### 4. Secure Logging

Sensitive data is automatically redacted from logs:

```python
from confiture.core.security.logging import configure_secure_logging

# Configure secure logging
configure_secure_logging()

# Passwords automatically redacted
logger.info("Connecting to postgresql://user:secret@host/db")
# Output: Connecting to postgresql://***@host/db

logger.info("Using token=abc123xyz")
# Output: Using token=***
```

### 5. Least Privilege Database Access

Recommended database role setup:

```sql
-- Create migration role (elevated privileges)
CREATE ROLE confiture_migrate WITH LOGIN PASSWORD '...';
GRANT CREATE ON SCHEMA public TO confiture_migrate;
GRANT ALL ON ALL TABLES IN SCHEMA public TO confiture_migrate;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO confiture_migrate;

-- Create application role (limited privileges)
CREATE ROLE app_user WITH LOGIN PASSWORD '...';
GRANT USAGE ON SCHEMA public TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO app_user;

-- Restrict direct schema modifications for app role
REVOKE CREATE ON SCHEMA public FROM app_user;
```

### 6. Audit Trail

All migrations are logged in the `confiture_migrations` table:

```sql
SELECT
    version,
    applied_at,
    checksum,
    applied_by,
    execution_time_ms
FROM confiture_migrations
ORDER BY applied_at DESC;
```

Enable PostgreSQL audit logging for additional visibility:

```ini
# postgresql.conf
log_statement = 'ddl'
log_connections = on
log_disconnections = on
```

### 7. Distributed Locking

Advisory locks prevent concurrent migrations:

```python
from confiture.core.locking import MigrationLock

with MigrationLock(connection, timeout=30000) as lock:
    # Only one migration can run at a time
    apply_migrations()
```

---

## Secure Deployment

### Kubernetes

```yaml
# Helm values for secure deployment
securityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  runAsNonRoot: true
  runAsUser: 1000
  capabilities:
    drop:
      - ALL

# Use secrets for credentials
database:
  existingSecret: db-credentials
  existingSecretKey: DATABASE_URL
```

### Docker

```dockerfile
# Run as non-root user
FROM python:3.11-slim
RUN useradd -m confiture
USER confiture

# Read-only filesystem
# Mount migrations as volume
```

### CI/CD

```yaml
# Secure CI/CD practices
- Store DATABASE_URL in CI secrets
- Use separate credentials for each environment
- Enable audit logging
- Require approval for production deployments
```

---

## Compliance Guidance

### SOC 2

| Control | Confiture Feature |
|---------|-------------------|
| CC6.1 Logical Access | Database role separation, advisory locks |
| CC6.6 Audit Logging | Migration history, secure logging |
| CC6.7 Change Management | Version-controlled migrations, checksums |
| CC7.1 Configuration Management | confiture.yaml, environment controls |
| CC7.2 Infrastructure Security | Kubernetes security context |

### GDPR

| Article | Confiture Feature |
|---------|-------------------|
| Article 25 (Privacy by Design) | Anonymization strategies |
| Article 32 (Security) | KMS encryption, secure logging |
| Article 33 (Breach Notification) | Audit trail for investigation |

### HIPAA

| Requirement | Confiture Feature |
|-------------|-------------------|
| 164.312(a) Access Control | Role separation, locking |
| 164.312(b) Audit Controls | Migration history, logging |
| 164.312(c) Integrity | Checksums, transactional migrations |
| 164.312(e) Transmission Security | SSL/TLS database connections |

### PCI DSS

| Requirement | Confiture Feature |
|-------------|-------------------|
| 2.2 Configuration Standards | Secure defaults |
| 6.5 Secure Development | Input validation, parameterized queries |
| 8.2 Authentication | Database role credentials |
| 10.2 Audit Trail | Migration logging |

---

## Security Checklist

### Before Deployment

- [ ] DATABASE_URL uses SSL (`?sslmode=require` or higher)
- [ ] Migration role has minimum required privileges
- [ ] Application role cannot modify schema
- [ ] Secrets not in version control
- [ ] Pre-commit hooks check for secrets
- [ ] Audit logging enabled in PostgreSQL
- [ ] Secure logging configured in Confiture

### Before Production Migration

- [ ] Migration reviewed by second developer
- [ ] Dry-run completed successfully
- [ ] Rollback script tested
- [ ] Checksum verification enabled
- [ ] Maintenance window scheduled
- [ ] Rollback plan documented
- [ ] Monitoring alerts configured

### After Migration

- [ ] Verify migration completed
- [ ] Check audit logs
- [ ] Verify no sensitive data in logs
- [ ] Confirm application health
- [ ] Update documentation

### Regular Audits

- [ ] Review database role permissions (monthly)
- [ ] Rotate credentials (quarterly)
- [ ] Audit migration history (quarterly)
- [ ] Review access logs (monthly)
- [ ] Update security dependencies (monthly)

---

## Reporting Security Issues

If you discover a security vulnerability in Confiture, please report it
responsibly:

1. **Do not** open a public GitHub issue
2. Email security@confiture.io with details
3. Include steps to reproduce
4. Allow 90 days for fix before disclosure

We appreciate responsible disclosure and will credit reporters (with permission)
in release notes.

---

*Last updated: January 2026*
*Security contact: security@confiture.io*
