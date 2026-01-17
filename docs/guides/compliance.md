# Compliance Guide

[← Back to Guides](../index.md) · [Anonymization](anonymization.md) · [Integrations →](integrations.md)

Industry-specific compliance for database migrations: HIPAA, SOX, GDPR, PCI-DSS.

---

## Quick Reference

| Regulation | Industry | Key Requirements |
|-----------|----------|------------------|
| **HIPAA** | Healthcare | Audit logs, PHI encryption, access control |
| **SOX** | Finance | Segregation of duties, GL reconciliation |
| **GDPR/CCPA** | All (EU/CA) | Data minimization, right to erasure |
| **PCI-DSS** | Payments | Card masking, encryption |

---

## HIPAA (Healthcare)

**Protected Health Information (PHI)** includes: names, SSNs, medical records, insurance info, lab results, appointments.

### Requirements

1. **Encryption**: TLS for transit, AES-256 at rest
2. **Audit Logging**: All PHI access logged with 6+ year retention
3. **Access Control**: RBAC with minimum necessary principle
4. **Breach Notification**: 60-day notification requirement

### Configuration

```yaml
# confiture.yaml
database:
  ssl_mode: require
  ssl_cert: /etc/ssl/certs/client.crt

audit:
  enabled: true
  retention_years: 6
  log_path: /var/log/confiture/hipaa_audit.log
```

### Audit Hook Example

```python
@register_hook('post_execute')
def hipaa_audit_log(context: HookContext) -> None:
    audit_event = {
        'event_type': 'migration_success',
        'migration': context.migration_name,
        'user_id': os.environ.get('USER'),
        'timestamp': datetime.utcnow().isoformat(),
        'tables_modified': [t.name for t in context.tables] if context.tables else [],
    }
    audit_logger.info(json.dumps(audit_event))
```

### Compliance Checklist

- [ ] Risk assessment completed
- [ ] Business Associate Agreement signed
- [ ] Encryption enabled (at rest and in transit)
- [ ] Audit logging configured
- [ ] Access control policies defined
- [ ] Incident response plan documented

---

## SOX (Finance)

**Sarbanes-Oxley** requires documented procedures, audit trails, and segregation of duties for financial data.

### Segregation of Duties

```
           | Initiate | Approve | Execute | Audit |
-----------|----------|---------|---------|-------|
DBA        |    -     |    -    |    X    |   -   |
Finance    |    X     |    X    |    -    |   X   |
CFO        |    -     |    X    |    -    |   -   |
Auditor    |    -     |    -    |    -    |   X   |
```

### Requirements

1. **Change Management**: Formal approval before production changes
2. **Segregation**: Different people for request/approve/execute
3. **GL Reconciliation**: Verify balances pre/post migration
4. **Audit Trail**: Immutable logs of all changes

### Reconciliation Hook

```python
@register_hook('post_execute')
def sox_reconcile_gl(context: HookContext) -> None:
    source_balance = float(os.environ.get('SOURCE_GL_BALANCE', 0))

    with psycopg.connect(context.database_url) as conn:
        cursor = conn.execute("""
            SELECT SUM(CASE WHEN entry_type = 'debit' THEN amount ELSE -amount END)
            FROM general_ledger WHERE fiscal_year = EXTRACT(YEAR FROM CURRENT_DATE)
        """)
        target_balance = cursor.fetchone()[0] or 0

    if abs(source_balance - target_balance) > 0.01:
        raise ValueError(f"GL mismatch: ${source_balance} vs ${target_balance}")
```

### Compliance Checklist

- [ ] Change request documented
- [ ] Finance manager approval
- [ ] Segregation of duties verified
- [ ] GL balance captured pre-migration
- [ ] Reconciliation completed post-migration
- [ ] Audit trail preserved

---

## GDPR/CCPA (Privacy)

**General Data Protection Regulation** (EU) and **California Consumer Privacy Act** require data protection and right to erasure.

### Data Classification

```
PERSONAL DATA (mask in non-production):
- Names, email, phone
- IP addresses, device IDs
- Location data
- Purchase history

NON-PERSONAL (keep as-is):
- Product catalogs
- Pricing information
- Aggregate statistics
```

### Anonymization Profile

```python
profile = StrategyProfile(
    name="gdpr_compliant",
    seed=42,
    columns={
        "customer_id": "preserve",      # Keep for tracking
        "name": "name",                 # Anonymize
        "email": "text_redaction",      # Anonymize
        "phone": "text_redaction",      # Anonymize
        "ip_address": "ip_address",     # Anonymize
        "order_total": "preserve",      # Business metric
    },
    defaults="preserve"
)
```

### Right to Erasure

```sql
-- Support data deletion requests
DELETE FROM customers WHERE customer_id = :customer_id;
DELETE FROM orders WHERE customer_id = :customer_id;
DELETE FROM audit_logs WHERE customer_id = :customer_id;
```

---

## PCI-DSS (Payments)

**Payment Card Industry Data Security Standard** requires secure handling of credit card data.

### Card Masking

```python
@register_strategy('credit_card')
def mask_credit_card(value, field_name, row_context=None):
    if not value:
        return None

    card = re.sub(r'\D', '', value)
    # Keep first 6 (BIN) and last 4 (PCI-DSS compliant)
    return f"{card[:6]}******{card[-4:]}"
```

### Requirements

1. **Never store CVV** after authorization
2. **Mask card numbers** (show first 6 + last 4 only)
3. **Encrypt** cardholder data at rest
4. **Log access** to card data

### PCI-DSS Masking Config

```yaml
anonymization:
  columns:
    card_number: credit_card
    cvv: null_value  # Never sync CVV
    card_expiry: mask_expiry
    cardholder_name: name
```

---

## Multi-Tenant SaaS

Multi-tenant systems must maintain **tenant isolation** during migrations.

### Tenant Isolation

```python
class TenantMigration:
    def migrate_tenant(self, tenant_id: str, context: HookContext):
        with psycopg.connect(context.database_url) as conn:
            with conn.transaction():
                # Verify tenant exists
                cursor = conn.execute(
                    "SELECT id FROM accounts WHERE id = %s", (tenant_id,)
                )
                if not cursor.fetchone():
                    return False

                # Execute tenant-specific migration
                conn.execute(
                    "UPDATE users SET migrated = true WHERE tenant_id = %s",
                    (tenant_id,)
                )
                return True
```

### Per-Tenant Rollback

```python
def rollback_tenant(tenant_id: str, context: HookContext):
    """Rollback single tenant without affecting others."""
    with psycopg.connect(context.database_url) as conn:
        cursor = conn.execute("""
            SELECT rollback_sql FROM migration_audit
            WHERE tenant_id = %s AND migration = %s
            ORDER BY executed_at DESC
        """, (tenant_id, context.migration_name))

        for row in cursor.fetchall():
            conn.execute(row[0])
```

### Canary Rollout

```
Stage 1:  1% of tenants  (2 hours monitoring)
Stage 2:  5% of tenants  (4 hours monitoring)
Stage 3: 25% of tenants  (8 hours monitoring)
Stage 4: 100% of tenants (24 hours monitoring)
```

---

## E-Commerce Data Masking

Protect customer data when syncing to dev/staging.

### Data Classification

```
CRITICAL (mask always):
- Credit card numbers
- CVV codes
- Social security numbers

HIGH (mask in dev):
- Email addresses
- Phone numbers
- Shipping addresses

LOW (keep as-is):
- Product names
- Prices
- Stock levels
```

### Masking Strategies

```python
@register_strategy('customer_name')
def mask_name(value, field_name, row_context=None):
    if not value:
        return None
    customer_id = row_context.get('customer_id') if row_context else None
    hash_val = hashlib.md5(str(customer_id).encode()).hexdigest()[:4]
    return f"Customer_{hash_val.upper()}"

@register_strategy('email')
def mask_email(value, field_name, row_context=None):
    if not value or '@' not in value:
        return "customer@example.com"
    local, domain = value.rsplit('@', 1)
    hash_val = hashlib.sha256(local.encode()).hexdigest()[:8]
    return f"user_{hash_val}@{domain}"
```

---

## Multi-Region Compliance

Different regions have different requirements.

| Region | Regulation | Key Requirement |
|--------|-----------|-----------------|
| EU | GDPR | Consent, right to erasure |
| California | CCPA | Disclosure, opt-out |
| Brazil | LGPD | Similar to GDPR |
| China | PIPL | Data localization |

### Region-Aware Anonymization

```python
def get_compliance_profile(region: str) -> StrategyProfile:
    if region in ['EU', 'UK', 'BR']:
        return gdpr_strict_profile
    elif region == 'CA':
        return ccpa_profile
    else:
        return standard_profile
```

---

## Best Practices

### Always

1. **Enable audit logging** for all production migrations
2. **Encrypt data** at rest and in transit
3. **Verify compliance** before and after migrations
4. **Document everything** for audit reviews

### Never

1. **Skip approval workflows** for production
2. **Store credentials** in code or logs
3. **Sync sensitive data** without anonymization
4. **Modify audit logs** after creation

---

## See Also

- [Anonymization Guide](./anonymization.md)
- [Production Sync](./03-production-sync.md)
- [Hooks Guide](./hooks.md)
