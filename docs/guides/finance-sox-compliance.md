# Finance & SOX Compliance Guide

**Migrate financial databases with Sarbanes-Oxley (SOX) audit requirements, segregation of duties, and financial controls**

---

## What is SOX Compliance?

The Sarbanes-Oxley Act (SOX) established requirements for financial reporting, internal controls, and audit trails. For financial database migrations, SOX requires documented procedures, audit trails, and segregation of duties.

**Tagline**: *Migrate financial data with SOX audit trails and segregation of duties*

---

## Why SOX Matters for Migrations

### Regulatory Requirements

SOX requires:
- ✅ **Segregation of Duties (SoD)** - No one person can initiate, approve, and execute
- ✅ **Audit Trails** - Document all changes with user and timestamp
- ✅ **Change Management** - Approval before production changes
- ✅ **Financial Control** - Ensure data accuracy and completeness
- ✅ **Reconciliation** - Verify data matches between systems
- ✅ **Access Controls** - Only authorized personnel can change financial data

### Business Impact

Non-compliance results in:
- ❌ **Executive penalties** - CEO/CFO criminal liability
- ❌ **Company fines** - Up to $5 million per violation
- ❌ **Stock delisting** - Removal from exchanges
- ❌ **Auditor suspension** - Prevents financial statement certification
- ❌ **Operational disruption** - Forced investigation and remediation

---

## When to Use This Guide

### ✅ Perfect For

- **General ledger (GL)** - Chart of accounts and transactions
- **Accounts payable (AP)** - Vendor invoices and payments
- **Accounts receivable (AR)** - Customer invoices and collections
- **Fixed assets** - Depreciation and asset tracking
- **Payroll** - Employee compensation and taxes

### ❌ Not For

- **Non-financial systems** - Use general compliance guides
- **Development/test databases** - Lighter SOX controls acceptable
- **Internal metrics** - Non-GAAP measures may have reduced controls

---

## SOX Compliance Architecture

### Segregation of Duties Matrix

```
           | Initiate | Approve | Execute | Audit |
-----------|----------|---------|---------|-------|
DBA        |    ✓     |    ✗    |    ✓    |   ✗   |
Finance    |    ✓     |    ✓    |    ✗    |   ✓   |
CFO        |    ✗     |    ✓    |    ✗    |   ✗   |
Auditor    |    ✗     |    ✗    |    ✗    |   ✓   |

✓ = Can perform this role
✗ = Cannot perform this role (conflict of interest)
```

### Control Framework

```
Financial Migration Control Flow

┌─────────────────────────────────────────────────────────┐
│ 1. Initiate: Document change request and business case  │
│    └─ Who: Finance team or application owner            │
│    └─ What: Migration scope and business justification  │
│    └─ Audit: Recorded with timestamp and approver       │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│ 2. Approve: CFO/Finance director reviews and approves   │
│    └─ Who: CFO or finance director (different from init)│
│    └─ Review: Business justification and risk assessment│
│    └─ Audit: Approval recorded with signature           │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│ 3. Execute: DBA performs migration (not finance)        │
│    └─ Who: Database administrator or DevOps            │
│    └─ Access: Time-limited elevated privileges         │
│    └─ Audit: All SQL logged with execution details     │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│ 4. Verify: Finance reconciles pre and post-migration   │
│    └─ Who: Finance team (not who initiated change)     │
│    └─ Reconciliation: GL balance verification          │
│    └─ Audit: Reconciliation report signed              │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│ 5. Audit: Independent auditor reviews audit trail      │
│    └─ Who: Internal audit or external auditor          │
│    └─ Review: Complete documentation and logs          │
│    └─ Certification: Sign-off on migration compliance  │
└─────────────────────────────────────────────────────────┘
```

---

## Setup Overview

### Requirements

- ✅ Change management system (Jira, ServiceNow, etc.)
- ✅ Financial reconciliation team
- ✅ Audit logging infrastructure
- ✅ Role-based access control (RBAC)
- ✅ Time-limited elevated access (PAM system)

### Compliance Checklist

Before any financial migration:
- [ ] Change request submitted and documented
- [ ] Business justification reviewed
- [ ] Risk assessment completed
- [ ] Finance manager approval obtained
- [ ] Segregation of duties verified
- [ ] Audit logging configured
- [ ] Time windows defined (blackout dates identified)
- [ ] Reconciliation procedures prepared
- [ ] Rollback plan documented
- [ ] Auditor notification sent

---

## Change Management & Approval

### Change Request Workflow

```python
# confiture_hooks/sox_change_management.py
import os
import json
from datetime import datetime
from confiture.hooks import register_hook, HookContext

class ChangeRequest:
    def __init__(self, migration_name: str, business_case: str):
        self.id = f"CHG-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        self.migration_name = migration_name
        self.business_case = business_case
        self.requested_by = os.environ.get('USER_ID')
        self.requested_date = datetime.utcnow().isoformat()
        self.approval_status = 'PENDING'
        self.approved_by = None
        self.approved_date = None

    def to_dict(self):
        return {
            'change_id': self.id,
            'migration': self.migration_name,
            'business_case': self.business_case,
            'requested_by': self.requested_by,
            'requested_date': self.requested_date,
            'status': self.approval_status,
            'approved_by': self.approved_by,
            'approved_date': self.approved_date,
        }

def create_change_request(migration_name: str) -> ChangeRequest:
    """Create SOX change request for financial migration."""
    business_case = os.environ.get('BUSINESS_CASE', 'Not provided')

    request = ChangeRequest(migration_name, business_case)

    # Log to change management system
    with open('/var/log/confiture/change_requests.log', 'a') as f:
        f.write(json.dumps(request.to_dict()) + '\n')

    print(f"📝 Change request created: {request.id}")
    return request

@register_hook('pre_validate')
def log_change_request(context: HookContext) -> None:
    """Log change request before validation."""
    create_change_request(context.migration_name)
```

---

## Segregation of Duties Enforcement

### Role-Based Access Control

```python
# confiture_hooks/sox_segregation.py
import os
from typing import List
from confiture.hooks import register_hook, HookContext, HookError

class Role:
    def __init__(self, name: str, permissions: List[str]):
        self.name = name
        self.permissions = permissions

# Define SOX roles
ROLES = {
    'dba': Role('DBA', ['execute_migration', 'view_audit_logs']),
    'finance_initiator': Role('Finance Initiator', ['request_migration', 'view_status']),
    'finance_approver': Role('Finance Approver', ['approve_migration', 'view_requests']),
    'auditor': Role('Internal Auditor', ['view_audit_logs', 'view_reconciliation']),
    'cfo': Role('CFO', ['approve_migration', 'view_all_logs']),
}

class MigrationState:
    """Track SOX segregation of duties."""
    def __init__(self):
        self.requested_by = None
        self.approved_by = None
        self.executed_by = None
        self.verified_by = None

    def record_request(self, user_id: str):
        self.requested_by = user_id
        print(f"📝 Migration requested by: {user_id}")

    def record_approval(self, user_id: str):
        if user_id == self.requested_by:
            raise HookError("Segregation of duties violation: Same person cannot request and approve")
        self.approved_by = user_id
        print(f"✅ Migration approved by: {user_id}")

    def record_execution(self, user_id: str):
        if user_id in [self.requested_by, self.approved_by]:
            raise HookError("Segregation of duties violation: Executor cannot be requester or approver")
        self.executed_by = user_id
        print(f"⚙️ Migration executed by: {user_id}")

    def record_verification(self, user_id: str):
        if user_id == self.requested_by:
            raise HookError("Segregation of duties violation: Verifier cannot be requester")
        self.verified_by = user_id
        print(f"🔍 Migration verified by: {user_id}")

migration_state = MigrationState()

@register_hook('pre_execute')
def verify_segregation_of_duties(context: HookContext) -> None:
    """Ensure segregation of duties compliance."""
    user_id = os.environ.get('USER_ID')
    user_role = os.environ.get('USER_ROLE')

    # Get approval status
    approval_status = os.environ.get('APPROVAL_STATUS')
    if approval_status != 'APPROVED':
        raise HookError(f"Migration not approved. Status: {approval_status}")

    # Verify executor has permission
    role = ROLES.get(user_role)
    if not role or 'execute_migration' not in role.permissions:
        raise HookError(f"User role {user_role} cannot execute migrations")

    # Record execution for audit
    migration_state.record_execution(user_id)
    print("✅ Segregation of duties verified")
```

---

## Audit Logging & Trails

### Comprehensive Financial Audit Log

```python
# confiture_hooks/sox_audit_logging.py
import os
import json
import logging
from datetime import datetime
from confiture.hooks import register_hook, HookContext

# Configure financial audit logging
audit_logger = logging.getLogger('sox_audit')
handler = logging.FileHandler('/var/log/confiture/sox_audit.log')
formatter = logging.Formatter('%(asctime)s - %(message)s')
audit_logger.addHandler(handler)

def log_audit_event(event_type: str, details: dict) -> None:
    """Log SOX-compliant audit event with immutable timestamp."""
    event = {
        'event_type': event_type,
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'user_id': os.environ.get('USER_ID'),
        'user_role': os.environ.get('USER_ROLE'),
        'ip_address': os.environ.get('SOURCE_IP'),
        'details': details,
    }

    # Write immutably (append-only)
    audit_logger.info(json.dumps(event))

@register_hook('pre_validate')
def audit_migration_request(context: HookContext) -> None:
    """Log migration request initiation."""
    log_audit_event('MIGRATION_REQUESTED', {
        'migration': context.migration_name,
        'environment': context.environment,
        'business_case': os.environ.get('BUSINESS_CASE'),
    })

@register_hook('post_execute')
def audit_migration_execution(context: HookContext) -> None:
    """Log successful migration execution."""
    log_audit_event('MIGRATION_EXECUTED', {
        'migration': context.migration_name,
        'environment': context.environment,
        'duration_seconds': context.duration.total_seconds(),
        'rows_affected': context.rows_affected,
        'start_time': context.start_time.isoformat(),
        'end_time': context.end_time.isoformat(),
    })

@register_hook('on_error')
def audit_migration_failure(context: HookContext) -> None:
    """Log migration failure."""
    log_audit_event('MIGRATION_FAILED', {
        'migration': context.migration_name,
        'environment': context.environment,
        'error_type': type(context.error).__name__,
        'error_message': str(context.error),
    })
```

### Audit Log Protection

```bash
#!/bin/bash
# protect_audit_logs.sh - Make audit logs immutable

AUDIT_LOG="/var/log/confiture/sox_audit.log"

# Set immutable flag (Linux)
chattr +a "$AUDIT_LOG"  # Append-only, cannot modify

# Set permissions
chmod 640 "$AUDIT_LOG"
chown confiture:audit "$AUDIT_LOG"

# Verify protection
lsattr "$AUDIT_LOG"
# Output: -----a---------- /var/log/confiture/sox_audit.log

echo "✅ Audit log protected (append-only)"
```

---

## Financial Reconciliation

### GL Balance Verification

```python
# confiture_hooks/sox_reconciliation.py
import os
import psycopg
from datetime import datetime
from confiture.hooks import register_hook, HookContext

@register_hook('post_execute')
def reconcile_gl_balance(context: HookContext) -> None:
    """Reconcile general ledger balance after migration."""

    # Get source balance (captured before migration)
    source_gl_balance = float(os.environ.get('SOURCE_GL_BALANCE', 0))

    try:
        with psycopg.connect(context.database_url) as conn:
            cursor = conn.execute("""
                SELECT
                    SUM(CASE WHEN entry_type = 'debit' THEN amount ELSE -amount END)
                    as gl_balance
                FROM general_ledger
                WHERE fiscal_year = EXTRACT(YEAR FROM CURRENT_DATE);
            """)
            target_gl_balance = cursor.fetchone()[0] or 0

            # Tolerance: Within $0.01 due to rounding
            tolerance = 0.01
            difference = abs(source_gl_balance - target_gl_balance)

            if difference > tolerance:
                print(f"❌ GL reconciliation FAILED")
                print(f"   Source balance: ${source_gl_balance:,.2f}")
                print(f"   Target balance: ${target_gl_balance:,.2f}")
                print(f"   Difference: ${difference:,.2f}")
                raise ValueError(f"GL balance mismatch: ${difference:,.2f}")

            print(f"✅ GL balance reconciled successfully")
            print(f"   Source balance: ${source_gl_balance:,.2f}")
            print(f"   Target balance: ${target_gl_balance:,.2f}")

            # Log reconciliation
            log_reconciliation_result(
                migration=context.migration_name,
                source_balance=source_gl_balance,
                target_balance=target_gl_balance,
                status='PASSED'
            )

    except Exception as e:
        log_reconciliation_result(
            migration=context.migration_name,
            status='FAILED',
            error=str(e)
        )
        raise

def log_reconciliation_result(migration: str, status: str, **details) -> None:
    """Log reconciliation result for audit."""
    with open('/var/log/confiture/reconciliation.log', 'a') as f:
        record = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'migration': migration,
            'status': status,
            'verified_by': os.environ.get('USER_ID'),
            **details
        }
        f.write(json.dumps(record) + '\n')
```

---

## Access Control & PAM Integration

### Time-Limited Elevated Access

```python
# confiture_hooks/sox_pam_integration.py
import os
from datetime import datetime, timedelta
from confiture.hooks import register_hook, HookContext, HookError

class AccessWindow:
    def __init__(self, migration_name: str, approved_window_start: str, duration_minutes: int):
        self.migration = migration_name
        self.window_start = datetime.fromisoformat(approved_window_start)
        self.window_end = self.window_start + timedelta(minutes=duration_minutes)
        self.current_time = datetime.utcnow()

    def is_within_window(self) -> bool:
        return self.window_start <= self.current_time <= self.window_end

    def time_remaining_seconds(self) -> int:
        return int((self.window_end - self.current_time).total_seconds())

@register_hook('pre_execute')
def verify_access_window(context: HookContext) -> None:
    """Verify migration is within approved access window."""

    # Get approved window from change request
    window_start = os.environ.get('APPROVED_WINDOW_START')
    duration = int(os.environ.get('ACCESS_DURATION_MINUTES', 60))

    if not window_start:
        raise HookError("No approved access window found")

    access_window = AccessWindow(context.migration_name, window_start, duration)

    if not access_window.is_within_window():
        raise HookError(
            f"Migration outside approved window. "
            f"Allowed: {access_window.window_start} - {access_window.window_end}"
        )

    remaining = access_window.time_remaining_seconds()
    print(f"✅ Within approved access window ({remaining}s remaining)")
```

---

## Pre-Migration Checklist

### SOX Compliance Verification

```python
# sox_compliance_checklist.py
import os
import json
from datetime import datetime

def verify_sox_compliance() -> bool:
    """Verify SOX compliance before production migration."""

    checklist = {
        'change_request_created': {
            'check': os.path.exists('/var/log/confiture/change_requests.log'),
            'requirement': 'Change request must be documented'
        },
        'approval_obtained': {
            'check': os.environ.get('APPROVAL_STATUS') == 'APPROVED',
            'requirement': 'Finance manager must approve'
        },
        'segregation_verified': {
            'check': os.environ.get('SEGREGATION_VERIFIED') == 'true',
            'requirement': 'Different users for request/approve/execute'
        },
        'access_window_valid': {
            'check': os.environ.get('APPROVED_WINDOW_START') is not None,
            'requirement': 'Access window must be approved'
        },
        'gl_balance_captured': {
            'check': os.environ.get('SOURCE_GL_BALANCE') is not None,
            'requirement': 'Pre-migration GL balance must be captured'
        },
        'reconciliation_plan_ready': {
            'check': os.path.exists('/var/lib/confiture/reconciliation_plan.sql'),
            'requirement': 'Post-migration reconciliation plan must exist'
        },
        'rollback_plan_documented': {
            'check': os.path.exists('/var/lib/confiture/rollback_plan.sql'),
            'requirement': 'Rollback plan must be documented'
        },
        'audit_logging_enabled': {
            'check': os.path.exists('/var/log/confiture/sox_audit.log'),
            'requirement': 'Audit logging must be enabled'
        },
    }

    print("🔍 SOX Compliance Verification\n")

    all_passed = True
    for check_name, check_info in checklist.items():
        status = "✅" if check_info['check'] else "❌"
        print(f"{status} {check_name}")
        print(f"   {check_info['requirement']}")

        if not check_info['check']:
            all_passed = False

    print()
    if all_passed:
        print("✅ All SOX compliance checks PASSED")
    else:
        print("❌ Some compliance checks FAILED")

    return all_passed

if __name__ == '__main__':
    if verify_sox_compliance():
        exit(0)
    else:
        exit(1)
```

---

## Best Practices

### ✅ Do's

1. **Always require formal approval**
   ```bash
   APPROVAL_STATUS=APPROVED  # Must be explicitly set
   ```

2. **Enforce segregation of duties**
   ```python
   if requester == approver:
       raise HookError("Cannot request and approve")
   ```

3. **Capture GL balance before migration**
   ```bash
   SOURCE_GL_BALANCE=$(psql -c "SELECT SUM(...) FROM general_ledger")
   export SOURCE_GL_BALANCE
   ```

4. **Verify reconciliation post-migration**
   ```python
   @register_hook('post_execute')
   def reconcile_gl_balance(context):
       # Compare source and target balances
   ```

5. **Log all changes immutably**
   ```bash
   chattr +a /var/log/confiture/sox_audit.log  # Append-only
   ```

### ❌ Don'ts

1. **Don't skip change management**
   ```bash
   # Bad: Direct migration without approval
   confiture migrate up

   # Good: Via approved change request
   CHANGE_REQUEST=CHG-12345 confiture migrate up
   ```

2. **Don't allow same person to request and execute**
   ```python
   # Bad: One person controls the entire process
   # Good: Split between initiator, approver, executor
   ```

3. **Don't migrate outside approved windows**
   ```python
   # Bad: Migration at any time
   # Good: Only within approved maintenance windows
   ```

4. **Don't modify audit logs**
   ```bash
   # Bad: Logs are editable
   chmod 666 sox_audit.log

   # Good: Logs are append-only and protected
   chattr +a sox_audit.log
   ```

---

## Troubleshooting

### ❌ Error: "GL balance mismatch"

**Cause**: Rows lost during migration or rounding issues

**Solution**:
```python
# Capture source before migration
SOURCE_GL_BALANCE=$(psql source_db -c "SELECT SUM(...)")

# Verify row counts match
SOURCE_ROWS=$(psql source_db -c "SELECT COUNT(*) FROM accounts")
TARGET_ROWS=$(psql target_db -c "SELECT COUNT(*) FROM accounts")

if [ "$SOURCE_ROWS" != "$TARGET_ROWS" ]; then
    echo "Row count mismatch!"
fi
```

---

## See Also

- [Finance Data Masking](./finance-data-masking.md) - PCI-DSS for payment data
- [Production Sync Guide](./production-sync-guide.md) - Safe data migration
- [Monitoring Integration](./monitoring-integration.md) - Track migration metrics
- [Hook API Reference](../api/hooks.md) - Audit logging hooks

---

## 🎯 Next Steps

**Ready for SOX-compliant migrations?**
- ✅ You now understand: Change management, segregation of duties, GL reconciliation, audit trails

**What to do next:**

1. **[Create change request](#change-management--approval)** - Document migration business case
2. **[Verify segregation of duties](#segregation-of-duties-enforcement)** - Ensure different users for each step
3. **[Capture GL balance](#financial-reconciliation)** - Record pre-migration state
4. **[Run compliance checklist](#pre-migration-checklist)** - Verify all controls in place

---

**Last Updated**: January 9, 2026
**Status**: Production Ready ✅
**Compliance Framework**: SOX 404, COSO ERM, COBIT

🍓 Migrate financial data with confidence and audit compliance
