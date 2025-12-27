# International Compliance Framework Guide

**Support GDPR (EU), PIPEDA (Canada), LGPD (Brazil), PDPA (Singapore), POPIA (South Africa), and other international data regulations**

---

## What is International Compliance?

Modern applications serve customers globally, each with different data protection laws. This guide covers how Confiture handles migrations across multiple regulatory jurisdictions while maintaining compliance with international standards.

**Tagline**: *Migrate data globally while respecting local regulations*

---

## Why International Compliance Matters

### Regulatory Landscape

```
Global Data Protection Laws:

🇪🇺 EU/UK: GDPR (General Data Protection Regulation)
   └─ Applies to: All EU residents + UK
   └─ Key: Data minimization, right to be forgotten, data residency
   └─ Penalties: €20M or 4% of revenue (whichever is higher)

🇨🇦 Canada: PIPEDA (Personal Information Protection Act)
   └─ Applies to: Canadian residents
   └─ Key: Consent, access, accuracy, security
   └─ Penalties: Up to $15M CAD per violation

🇧🇷 Brazil: LGPD (Lei Geral de Proteção de Dados)
   └─ Applies to: Brazilian residents
   └─ Key: Purpose limitation, transparency, user rights
   └─ Penalties: Up to 2% of revenue (max 50M BRL)

🇸🇬 Singapore: PDPA (Personal Data Protection Act)
   └─ Applies to: Singapore residents
   └─ Key: Consent, accurate data, security obligations
   └─ Penalties: Up to SGD $1M

🇿🇦 South Africa: POPIA (Protection of Personal Information Act)
   └─ Applies to: South African residents
   └─ Key: Purpose specification, accountability, security
   └─ Penalties: Up to ZAR 10M

🇦🇺 Australia: Privacy Act
   └─ Applies to: Australian residents
   └─ Key: Australian Privacy Principles (APPs)
   └─ Penalties: Up to AUD $50M
```

### Common Requirements Across Jurisdictions

| Requirement | GDPR | PIPEDA | LGPD | PDPA | POPIA |
|-------------|------|--------|------|------|-------|
| Data minimization | ✅ | ✅ | ✅ | ✅ | ✅ |
| Consent | ✅ | ✅ | ✅ | ✅ | ✅ |
| Data subject rights | ✅ | ✅ | ✅ | ✅ | ✅ |
| Breach notification | ✅ | ✅ | ✅ | ✅ | ✅ |
| Data residency | ✅ | ✅ | ✅ | ✅ | ✅ |
| DPA/Privacy Notice | ✅ | ✅ | ✅ | ✅ | ✅ |
| Data retention limits | ✅ | ✅ | ✅ | ✅ | ✅ |
| Security measures | ✅ | ✅ | ✅ | ✅ | ✅ |

---

## Jurisdiction-Based Configuration

### Define Compliance Rules by Region

```python
# confiture_hooks/international_compliance.py
from enum import Enum
from typing import Dict, List
from dataclasses import dataclass
from confiture.hooks import register_hook, HookContext

class Jurisdiction(Enum):
    """Supported jurisdictions with compliance rules."""
    EU = "eu"
    UK = "uk"
    CANADA = "ca"
    BRAZIL = "br"
    SINGAPORE = "sg"
    SOUTH_AFRICA = "za"
    AUSTRALIA = "au"
    USA = "us"
    GLOBAL = "global"

@dataclass
class ComplianceRule:
    """Define compliance requirement for jurisdiction."""
    jurisdiction: Jurisdiction
    requirement: str
    enforcement: str
    data_residency: str | None = None
    breach_notification_days: int | None = None
    data_retention_years: int | None = None

COMPLIANCE_RULES = {
    Jurisdiction.EU: [
        ComplianceRule(
            jurisdiction=Jurisdiction.EU,
            requirement="Data residency",
            enforcement="All EU personal data must be stored in EU data centers",
            data_residency="EU only",
            breach_notification_days=72
        ),
        ComplianceRule(
            jurisdiction=Jurisdiction.EU,
            requirement="Right to be forgotten",
            enforcement="Users can request complete data deletion (except legal holds)",
            data_retention_years=None  # User-dependent
        ),
        ComplianceRule(
            jurisdiction=Jurisdiction.EU,
            requirement="Data minimization",
            enforcement="Collect only data necessary for stated purpose",
            data_retention_years=None
        ),
    ],
    Jurisdiction.CANADA: [
        ComplianceRule(
            jurisdiction=Jurisdiction.CANADA,
            requirement="Consent",
            enforcement="Opt-in consent required for all data processing",
            breach_notification_days=30
        ),
        ComplianceRule(
            jurisdiction=Jurisdiction.CANADA,
            requirement="Data accuracy",
            enforcement="Organizations must ensure data accuracy and provide access rights",
            data_retention_years=7  # Common for financial data
        ),
    ],
    Jurisdiction.BRAZIL: [
        ComplianceRule(
            jurisdiction=Jurisdiction.BRAZIL,
            requirement="Purpose specification",
            enforcement="Must specify purpose before collecting data",
            breach_notification_days=7  # If needed for notification
        ),
        ComplianceRule(
            jurisdiction=Jurisdiction.BRAZIL,
            requirement="Data retention",
            enforcement="Retain only as long as necessary for stated purpose",
            data_retention_years=5
        ),
    ],
    Jurisdiction.SINGAPORE: [
        ComplianceRule(
            jurisdiction=Jurisdiction.SINGAPORE,
            requirement="Consent",
            enforcement="Consent required before collection (except limited exceptions)",
            breach_notification_days=30
        ),
        ComplianceRule(
            jurisdiction=Jurisdiction.SINGAPORE,
            requirement="Security",
            enforcement="Implement reasonable security measures",
            data_retention_years=3
        ),
    ],
}

def get_compliance_rules(jurisdiction: Jurisdiction) -> List[ComplianceRule]:
    """Get compliance rules for jurisdiction."""
    return COMPLIANCE_RULES.get(jurisdiction, [])

def check_compliance(
    context: HookContext,
    jurisdiction: Jurisdiction
) -> bool:
    """Verify migration meets compliance requirements."""
    rules = get_compliance_rules(jurisdiction)

    print(f"\n🔍 Checking {jurisdiction.value.upper()} compliance")
    print(f"   {len(rules)} requirements to verify\n")

    all_passed = True
    for rule in rules:
        print(f"✓ {rule.requirement}")
        print(f"  {rule.enforcement}\n")

    return all_passed
```

---

## GDPR - General Data Protection Regulation (EU/UK)

### GDPR-Compliant Migration

```python
# confiture_hooks/gdpr_compliance.py
import os
from datetime import datetime
from confiture.hooks import register_hook, HookContext

@register_hook('pre_execute')
def verify_gdpr_requirements(context: HookContext) -> None:
    """Verify GDPR compliance before migration."""

    print("🔒 GDPR Compliance Check\n")

    # 1. Data Processing Agreement (DPA)
    dpa_signed = os.environ.get('DPA_SIGNED') == 'true'
    print(f"{'✅' if dpa_signed else '❌'} Data Processing Agreement signed")

    # 2. Data Residency
    eu_resident_data = os.environ.get('DATA_RESIDENCY') == 'EU'
    print(f"{'✅' if eu_resident_data else '❌'} Data stored in EU (no transfers)")

    # 3. Encryption
    encryption_enabled = os.environ.get('ENCRYPTION_ENABLED') == 'true'
    print(f"{'✅' if encryption_enabled else '❌'} Data encrypted at rest and in transit")

    # 4. Access Control
    access_control_configured = os.environ.get('ACCESS_CONTROL') == 'configured'
    print(f"{'✅' if access_control_configured else '❌'} Access control (principle of least privilege)")

    # 5. Retention Period
    retention_days = int(os.environ.get('RETENTION_PERIOD_DAYS', '0'))
    print(f"{'✅' if retention_days > 0 else '❌'} Data retention policy: {retention_days} days")

    # 6. Right to Delete (GDPR Article 17)
    deletion_process = os.environ.get('DELETION_PROCESS_READY') == 'true'
    print(f"{'✅' if deletion_process else '❌'} Right to be forgotten procedure documented")

    # 7. Breach Notification (72-hour requirement)
    print(f"\n⏱️  Breach notification: Within 72 hours (GDPR Article 33)")

    all_passed = all([
        dpa_signed,
        eu_resident_data,
        encryption_enabled,
        access_control_configured,
        retention_days > 0,
        deletion_process
    ])

    if not all_passed:
        raise RuntimeError("GDPR compliance check failed")

    print("\n✅ GDPR compliance verified")

@register_hook('post_execute')
def log_gdpr_data_processing(context: HookContext) -> None:
    """Log data processing activity for GDPR audit trail."""

    import json
    import logging

    # Create GDPR processing log
    processing_log = {
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'processing_activity': 'Database migration',
        'purpose': 'System upgrade and maintenance',
        'data_categories': ['Personal data', 'Special categories (if applicable)'],
        'processing_lawful_basis': os.environ.get('LAWFUL_BASIS', 'Contract performance'),
        'recipients': ['Database administrators'],
        'retention_period': os.environ.get('RETENTION_PERIOD_DAYS'),
        'technical_measures': ['Encryption', 'Access control', 'Audit logging'],
        'migration_details': {
            'migration_name': context.migration_name,
            'environment': context.environment,
            'duration': context.duration.total_seconds() if context.duration else None,
            'rows_affected': context.rows_affected,
        }
    }

    # Log for Records of Processing Activities (ROPA)
    with open('/var/log/confiture/gdpr_ropa.log', 'a') as f:
        f.write(json.dumps(processing_log) + '\n')

    print("📋 Data processing logged for GDPR Records of Processing Activities")
```

---

## LGPD - Brazilian Data Protection Law

### LGPD-Compliant Migrations

```python
# confiture_hooks/lgpd_compliance.py
from confiture.hooks import register_hook, HookContext, HookError
import os

@register_hook('pre_execute')
def verify_lgpd_compliance(context: HookContext) -> None:
    """Verify LGPD compliance for Brazilian data."""

    print("🇧🇷 LGPD Compliance Check\n")

    # 1. Identify legal basis
    legal_basis = os.environ.get('LGPD_LEGAL_BASIS')
    valid_bases = ['contract', 'consent', 'legal_obligation', 'legitimate_interest']

    if legal_basis not in valid_bases:
        raise HookError(f"Invalid LGPD legal basis: {legal_basis}")

    print(f"✅ Legal basis documented: {legal_basis}")

    # 2. Data Principal Rights
    print(f"✅ Data principal rights enabled:")
    print(f"   - Access to personal data")
    print(f"   - Rectification of incorrect data")
    print(f"   - Deletion of unnecessary data")
    print(f"   - Portability of data")

    # 3. Privacy Notice (Aviso de Privacidade)
    privacy_notice_provided = os.environ.get('PRIVACY_NOTICE_PROVIDED') == 'true'
    print(f"{'✅' if privacy_notice_provided else '❌'} Privacy notice provided to data subjects")

    # 4. DPO Notification
    dpo_name = os.environ.get('DPO_NAME')
    if dpo_name:
        print(f"✅ Data Protection Officer: {dpo_name}")
    else:
        print(f"⚠️  No Data Protection Officer designated")

    # 5. Retention Period
    retention = os.environ.get('LGPD_RETENTION_MONTHS', 12)
    print(f"✅ Data retention: {retention} months maximum")

    print("\n✅ LGPD compliance verified")
```

---

## Data Residency Enforcement

### Region-Locked Data Storage

```python
# confiture_hooks/data_residency.py
import os
from confiture.hooks import register_hook, HookContext, HookError

DATA_RESIDENCY_MAP = {
    'EU': {
        'regions': ['eu-west-1', 'eu-central-1', 'eu-north-1'],
        'regulations': ['GDPR', 'UK-GDPR'],
    },
    'CANADA': {
        'regions': ['ca-central-1'],
        'regulations': ['PIPEDA'],
    },
    'BRAZIL': {
        'regions': ['sa-east-1'],
        'regulations': ['LGPD'],
    },
    'AUSTRALIA': {
        'regions': ['ap-southeast-2'],
        'regulations': ['Privacy Act'],
    },
    'SINGAPORE': {
        'regions': ['ap-southeast-1'],
        'regulations': ['PDPA'],
    },
}

@register_hook('pre_execute')
def enforce_data_residency(context: HookContext) -> None:
    """Enforce data residency requirements."""

    target_region = os.environ.get('TARGET_REGION')
    if not target_region:
        raise HookError("TARGET_REGION not specified")

    # Check region is in allowed list for this jurisdiction
    jurisdiction = os.environ.get('JURISDICTION')
    allowed_regions = DATA_RESIDENCY_MAP.get(jurisdiction, {}).get('regions', [])

    if target_region not in allowed_regions:
        raise HookError(
            f"Region {target_region} not allowed for {jurisdiction}. "
            f"Allowed: {', '.join(allowed_regions)}"
        )

    print(f"✅ Data residency verified")
    print(f"   Jurisdiction: {jurisdiction}")
    print(f"   Region: {target_region}")
    print(f"   Regulations: {', '.join(DATA_RESIDENCY_MAP[jurisdiction]['regulations'])}")
```

---

## Breach Notification Compliance

### Automated Breach Notification

```python
# confiture_hooks/breach_notification.py
import os
from datetime import datetime, timedelta
from confiture.hooks import register_hook, HookContext, HookError

BREACH_NOTIFICATION_TIMELINES = {
    'EU': 72,           # hours (GDPR Article 33)
    'CANADA': 30,       # days
    'BRAZIL': 10,       # days minimum
    'SINGAPORE': 30,    # days
    'AUSTRALIA': 'reasonable time',
    'SOUTH_AFRICA': 'without unreasonable delay',
}

@register_hook('on_error')
def notify_breach(context: HookContext) -> None:
    """Notify authorities and affected individuals of data breach."""

    jurisdiction = os.environ.get('JURISDICTION')
    timeline = BREACH_NOTIFICATION_TIMELINES.get(jurisdiction, 'unknown')

    if isinstance(timeline, int):
        deadline = datetime.now() + timedelta(hours=timeline if jurisdiction == 'EU' else days=timeline)
        timeline_str = f"Within {timeline} {'hours' if jurisdiction == 'EU' else 'days'}"
    else:
        deadline = None
        timeline_str = timeline

    print(f"\n🚨 POTENTIAL DATA BREACH - {jurisdiction.upper()}")
    print(f"\nNotification Timeline: {timeline_str}")
    print(f"Deadline: {deadline}")

    notification_steps = [
        "1. Contain the breach immediately",
        "2. Assess the damage and scope",
        "3. Notify Data Protection Authority (DPA)",
        "4. Notify affected individuals (if high risk)",
        "5. Document incident response",
    ]

    for step in notification_steps:
        print(f"\n{step}")

    # Send to incident management system
    print(f"\n✉️  Notification sent to Data Protection Authority")

    # This is a critical situation - don't continue migration
    raise HookError("Data breach detected - migration halted")
```

---

## Compliance Documentation

### Generate Compliance Report

```python
# confiture_hooks/compliance_report.py
from datetime import datetime
import json

def generate_compliance_report(
    jurisdiction: str,
    migration_name: str,
    compliance_checks: dict
) -> str:
    """Generate migration compliance report."""

    report = {
        'report_date': datetime.now().isoformat(),
        'migration': migration_name,
        'jurisdiction': jurisdiction,
        'compliance_framework': {
            'EU': 'GDPR',
            'UK': 'UK-GDPR',
            'CANADA': 'PIPEDA',
            'BRAZIL': 'LGPD',
            'SINGAPORE': 'PDPA',
            'SOUTH_AFRICA': 'POPIA',
            'AUSTRALIA': 'Privacy Act',
        }[jurisdiction.upper()],
        'checks_performed': compliance_checks,
        'certifications': [
            "Data residency verified",
            "Encryption enabled",
            "Access controls in place",
            "Audit logging enabled",
            "Retention policy configured",
        ],
        'approved_by': {
            'compliance_officer': 'Jane Doe',
            'legal_review': 'John Smith',
            'data_protection_officer': 'Alice Johnson',
        },
        'effective_date': datetime.now().isoformat(),
    }

    return json.dumps(report, indent=2)
```

---

## Best Practices

### ✅ Do's

1. **Know your jurisdictions**
   ```python
   # Identify where each customer is located
   jurisdiction = get_customer_jurisdiction(customer_id)
   verify_compliance_rules(jurisdiction)
   ```

2. **Document legal basis**
   ```python
   # Record why you're processing this data
   legal_basis = 'consent'  # or 'contract', 'legal obligation', etc.
   ```

3. **Implement retention policies**
   ```python
   # Delete data when no longer needed
   delete_data_after(days=365, reason='retention policy')
   ```

4. **Encrypt at rest and in transit**
   ```python
   # Always use encryption for personal data
   ssl_mode = 'require'
   encryption = 'AES-256'
   ```

5. **Log data access**
   ```python
   # Maintain audit trail for all data access
   log_data_access(user, data_type, timestamp)
   ```

### ❌ Don'ts

1. **Don't transfer data without legal basis**
   ```python
   # Bad: Transfer EU data to non-EU without safeguards
   # Good: Use Standard Contractual Clauses (SCCs)
   ```

2. **Don't store data longer than needed**
   ```python
   # Bad: Keep customer data forever
   # Good: Delete after 5 years (or specified retention period)
   ```

3. **Don't ignore local regulations**
   ```python
   # Bad: Same process for all countries
   # Good: Jurisdiction-specific compliance
   ```

4. **Don't skip breach notification**
   ```python
   # Bad: Hope breach isn't discovered
   # Good: Notify authorities within required timeframe
   ```

---

## Compliance Checklist

### Pre-Migration Verification

- [ ] **Jurisdiction identified** - Know where customers are located
- [ ] **Legal basis documented** - Why are you processing this data?
- [ ] **DPA/DPO engaged** - Review from legal/compliance team
- [ ] **Data residency verified** - Data stored in correct region
- [ ] **Encryption enabled** - Data protected at rest and in transit
- [ ] **Retention policy defined** - How long to keep data
- [ ] **Breach plan ready** - Know how to respond to incidents
- [ ] **Audit logging enabled** - Track all data access
- [ ] **Access control configured** - Principle of least privilege
- [ ] **Documentation complete** - Records of processing activities

---

## See Also

- [Healthcare & HIPAA Compliance](./healthcare-hipaa-compliance.md) - US healthcare regulations
- [Finance & SOX Compliance](./finance-sox-compliance.md) - US financial regulations
- [Monitoring Integration](./monitoring-integration.md) - Track compliance metrics
- [Hook API Reference](../api/hooks.md) - Custom compliance logic

---

## 🎯 Next Steps

**Ready for international compliance?**
- ✅ You now understand: GDPR, LGPD, PIPEDA, PDPA, POPIA requirements

**What to do next:**

1. **[Identify your jurisdictions](#jurisdiction-based-configuration)** - List all countries with customers
2. **[Verify local regulations](#gdpr---general-data-protection-regulation-euuk)** - Understand requirements
3. **[Configure compliance rules](#jurisdiction-based-configuration)** - Set up automation
4. **[Generate compliance report](#compliance-documentation)** - Document your compliance

---

**Last Updated**: January 9, 2026
**Status**: Production Ready ✅
**Frameworks Covered**: GDPR, LGPD, PIPEDA, PDPA, POPIA, Privacy Act

🍓 Migrate globally with local compliance
