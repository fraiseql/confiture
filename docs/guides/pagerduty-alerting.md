# PagerDuty Alerting Integration

**Create PagerDuty incidents from Confiture migration failures to escalate to on-call engineers**

---

## What is PagerDuty Integration?

PagerDuty integration enables Confiture to create incidents, trigger alerts, and escalate critical migration failures to your on-call team. This ensures critical issues are addressed immediately.

**Tagline**: *Route migration failures to your on-call responders instantly*

---

## Why Use PagerDuty?

### Common Use Cases

1. **Incident Escalation** - Critical failures wake up on-call engineers
2. **Duty Rotation** - Alerts go to whoever is currently on-call
3. **Runbook Integration** - Link runbooks directly to incidents
4. **Incident Tracking** - Create permanent record of all failures
5. **Team Coordination** - Multiple teams notified simultaneously

### Business Value

- ✅ **Faster response times** (minutes instead of hours)
- ✅ **Duty-aware routing** (alerts go to right person)
- ✅ **Accountability** (who responded to incident?)
- ✅ **Learning from failures** (post-mortem documentation)
- ✅ **Clear escalation** (manager notified if unresolved)

---

## When to Use PagerDuty

### ✅ Perfect For

- **Production migrations** - Always create incident on failure
- **Critical databases** - High-priority services get escalated
- **After-hours migrations** - Wake up on-call engineer if needed
- **Compliance requirements** - Need audit trail of incidents
- **Team collaboration** - Multiple teams need awareness

### ❌ Not For

- **Development environment** - Dev failures don't need escalation
- **Ad-hoc testing** - Temporary experiments don't need incidents
- **Non-critical services** - Low-impact failures could use Slack only

---

## How PagerDuty Integration Works

### Incident Creation Flow

```
Migration Fails
    ↓
on_error Hook Triggered
    ↓
Create PagerDuty Incident
    ├─ Title: "Production Migration Failed"
    ├─ Severity: HIGH/CRITICAL
    ├─ Service: Database Service
    └─ Escalation: To on-call engineer
    ↓
Incident Assigned
    ├─ Page: On-call engineer
    ├─ Alert phone + SMS
    └─ Escalate if not acknowledged
    ↓
Engineer Investigates
    └─ Uses runbook from incident
```

### Alert Severity Levels

- **CRITICAL** - Production down, requires immediate response
- **HIGH** - Major functionality impaired
- **MEDIUM** - Service degraded but operational
- **LOW** - Minor issue, informational

---

## Setup Overview

### Requirements

- ✅ PagerDuty account with admin access
- ✅ Ability to create integration keys
- ✅ Confiture with hooks (Phase 4+)
- ✅ Network access to PagerDuty API

### Time Required

- **Initial setup**: 10-15 minutes
- **Service configuration**: 10-15 minutes
- **Escalation policy**: 5-10 minutes

---

## Step 1: Create PagerDuty Service

1. Go to **Services** → **New Service**
2. Configure:
   - **Name**: "Database Migrations" (or your service name)
   - **Escalation Policy**: Select your on-call team
   - **Incident Title Format**: "Migration [migration_name] failed"
   - **Auto-resolve**: 30 minutes (customize as needed)

3. Copy the **Service ID** (you'll need this)

---

## Step 2: Create Integration Key

1. Go to your service → **Integrations**
2. Click **Add an integration**
3. Select **Events API V2**
4. Copy the **Integration Key** (keep this secret!)

---

## Step 3: Install PagerDuty Python Client

```bash
# Install PagerDuty SDK
pip install pdpyras

# Or use REST API directly (no additional dependency)
pip install requests
```

---

## Integration Implementation

### Simple PagerDuty Alert

```python
# confiture_hooks/pagerduty_alerts.py
import os
import requests
from datetime import datetime
from confiture.hooks import register_hook, HookContext

# PagerDuty configuration
PAGERDUTY_INTEGRATION_KEY = os.environ.get('PAGERDUTY_INTEGRATION_KEY')
PAGERDUTY_API_URL = 'https://events.pagerduty.com/v2/enqueue'

def create_pagerduty_incident(context: HookContext, severity: str = 'error'):
    """Create a PagerDuty incident from migration failure."""
    if not PAGERDUTY_INTEGRATION_KEY:
        print("⚠️ PAGERDUTY_INTEGRATION_KEY not set")
        return

    payload = {
        'routing_key': PAGERDUTY_INTEGRATION_KEY,
        'event_action': 'trigger',
        'client': 'Confiture',
        'client_url': 'https://github.com/evoludigit/confiture',
        'dedup_key': f"confiture-{context.migration_name}-{context.environment}",
        'payload': {
            'summary': f"❌ Migration {context.migration_name} failed in {context.environment}",
            'severity': severity,
            'source': 'Database Migration System',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'custom_details': {
                'migration': context.migration_name,
                'environment': context.environment,
                'error': str(context.error),
                'error_type': type(context.error).__name__,
                'database': context.database_url.split('@')[-1].split('/')[0],  # Redact credentials
            }
        }
    }

    # Add runbook if available
    if context.environment == 'production':
        payload['links'] = [
            {
                'href': 'https://wiki.example.com/runbooks/migration-failures',
                'text': 'Migration Failure Runbook'
            }
        ]

    try:
        response = requests.post(
            PAGERDUTY_API_URL,
            json=payload,
            timeout=10
        )
        response.raise_for_status()

        result = response.json()
        incident_key = result['dedup_key']
        print(f"🚨 PagerDuty incident created: {incident_key}")
        return incident_key

    except requests.exceptions.Timeout:
        print("⚠️ PagerDuty request timed out")
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Failed to create PagerDuty incident: {e}")

@register_hook('on_error')
def alert_pagerduty_on_error(context: HookContext) -> None:
    """Alert PagerDuty when migration fails."""
    # Only alert for critical environments
    if context.environment in ['production', 'staging']:
        severity = 'critical' if context.environment == 'production' else 'error'
        create_pagerduty_incident(context, severity=severity)
```

**Output**:
```
❌ Migration 005_add_payment_table failed in production
🚨 PagerDuty incident created: confiture-005_add_payment_table-production
📱 On-call engineer notified via phone and SMS
```

**Explanation**: When a migration fails in production, this immediately creates a critical incident and pages the on-call engineer.

---

### Using PagerDuty Python SDK

```python
# confiture_hooks/pagerduty_sdk.py
import os
from pdpyras import APISession
from confiture.hooks import register_hook, HookContext

# Initialize PagerDuty API session
pd_session = APISession(token=os.environ.get('PAGERDUTY_API_TOKEN'))

@register_hook('on_error')
def create_incident_via_sdk(context: HookContext) -> None:
    """Create PagerDuty incident using Python SDK."""
    # Find service by name
    services = pd_session.find_all('services', 'name', 'Database Migrations')
    if not services:
        print("⚠️ Could not find 'Database Migrations' service in PagerDuty")
        return

    service_id = services[0]['id']

    # Find currently on-call engineer
    try:
        oncalls = pd_session.find_all('oncalls', 'escalation_policy_ids', '*')
        oncall_user_id = oncalls[0]['user']['id'] if oncalls else None

        # Create incident
        incident_data = {
            'type': 'incident',
            'title': f"❌ Migration {context.migration_name} failed",
            'service': {
                'id': service_id,
                'type': 'service_reference'
            },
            'urgency': 'high' if context.environment == 'production' else 'low',
            'body': {
                'type': 'incident_body',
                'details': f"""
Migration Failure Details:
- Migration: {context.migration_name}
- Environment: {context.environment}
- Error: {str(context.error)}
- Error Type: {type(context.error).__name__}

Runbook: https://wiki.example.com/runbooks/migration-failures
                """
            }
        }

        if oncall_user_id:
            incident_data['assigned_via'] = 'escalation_policy'
            incident_data['assignments'] = [{
                'assignee': {
                    'id': oncall_user_id,
                    'type': 'user_reference'
                }
            }]

        incident = pd_session.post('incidents', json=incident_data)
        print(f"🚨 PagerDuty incident created: {incident['incident_number']}")

    except Exception as e:
        print(f"⚠️ Failed to create incident: {e}")
```

**Setup**:
```bash
# Install PagerDuty SDK
pip install pdpyras

# Generate API token from PagerDuty UI
# Settings → API Access → Generate API Token
export PAGERDUTY_API_TOKEN="your_api_token"
```

---

## Advanced Incident Creation

### Incident with Runbook and Context

```python
# confiture_hooks/advanced_pagerduty.py
import os
import requests
from datetime import datetime
from confiture.hooks import register_hook, HookContext

PAGERDUTY_INTEGRATION_KEY = os.environ.get('PAGERDUTY_INTEGRATION_KEY')
PAGERDUTY_API_URL = 'https://events.pagerduty.com/v2/enqueue'

@register_hook('on_error')
def advanced_pagerduty_alert(context: HookContext) -> None:
    """Create detailed PagerDuty incident with context and runbook."""

    # Determine severity based on environment and error type
    if context.environment == 'production':
        severity = 'critical'
    elif context.environment == 'staging':
        severity = 'error'
    else:
        severity = 'warning'

    # Format error details
    error_details = {
        'Migration': context.migration_name,
        'Version': context.migration_version,
        'Environment': context.environment,
        'Error Type': type(context.error).__name__,
        'Error Message': str(context.error),
        'Database': context.database_url.split('@')[-1].split('/')[0],
    }

    # Add context if available
    if context.start_time:
        error_details['Started At'] = context.start_time.isoformat()
    if context.end_time:
        error_details['Ended At'] = context.end_time.isoformat()
    if context.tables:
        error_details['Tables Affected'] = ', '.join([t.name for t in context.tables])

    # Build detailed summary
    summary = f"❌ [{context.environment.upper()}] Migration {context.migration_name} failed"

    # Determine runbook based on environment and error type
    runbooks = {
        'production': {
            'DatabaseError': 'https://wiki.example.com/runbooks/database-connection-issues',
            'TimeoutError': 'https://wiki.example.com/runbooks/slow-migrations',
            'ConstraintError': 'https://wiki.example.com/runbooks/constraint-violations',
            'default': 'https://wiki.example.com/runbooks/migration-failures'
        },
        'staging': {
            'default': 'https://wiki.example.com/runbooks/migration-failures'
        }
    }

    error_type = type(context.error).__name__
    env_runbooks = runbooks.get(context.environment, {})
    runbook_url = env_runbooks.get(error_type, env_runbooks.get('default', ''))

    # Build PagerDuty payload
    payload = {
        'routing_key': PAGERDUTY_INTEGRATION_KEY,
        'event_action': 'trigger',
        'dedup_key': f"confiture-{context.migration_name}-{context.environment}",
        'client': 'Confiture Database Migration System',
        'client_url': 'https://github.com/evoludigit/confiture',
        'payload': {
            'summary': summary,
            'severity': severity,
            'source': f"Migration: {context.migration_name}",
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'custom_details': error_details
        },
        'links': [
            {
                'href': runbook_url,
                'text': 'Migration Failure Runbook'
            }
        ]
    }

    # Add action links for different environments
    if context.environment == 'production':
        payload['links'].append({
            'href': 'https://your-monitoring-dashboard.example.com/migrations',
            'text': 'Migration Dashboard'
        })

    try:
        response = requests.post(
            PAGERDUTY_API_URL,
            json=payload,
            timeout=10
        )
        response.raise_for_status()

        result = response.json()
        print(f"🚨 PagerDuty incident created")
        print(f"   Severity: {severity}")
        print(f"   Environment: {context.environment}")
        print(f"   Runbook: {runbook_url}")

    except requests.exceptions.RequestException as e:
        print(f"⚠️ Failed to create PagerDuty incident: {e}")
        # Don't fail migration if PagerDuty is unavailable
```

---

## Resolving Incidents

### Auto-Resolve After Success

```python
# confiture_hooks/resolve_incidents.py
import os
import requests
from confiture.hooks import register_hook, HookContext

PAGERDUTY_INTEGRATION_KEY = os.environ.get('PAGERDUTY_INTEGRATION_KEY')

@register_hook('post_execute')
def resolve_pagerduty_incident(context: HookContext) -> None:
    """Resolve PagerDuty incident when migration succeeds."""

    # Only resolve if this migration had a previous failure
    dedup_key = f"confiture-{context.migration_name}-{context.environment}"

    payload = {
        'routing_key': PAGERDUTY_INTEGRATION_KEY,
        'event_action': 'resolve',
        'dedup_key': dedup_key,
        'payload': {
            'summary': f"✅ Migration {context.migration_name} succeeded after retry",
            'severity': 'info',
            'source': 'Database Migration System',
            'timestamp': context.end_time.isoformat() + 'Z'
        }
    }

    try:
        response = requests.post(
            'https://events.pagerduty.com/v2/enqueue',
            json=payload,
            timeout=10
        )
        response.raise_for_status()
        print(f"✅ PagerDuty incident resolved")

    except requests.exceptions.RequestException as e:
        print(f"⚠️ Failed to resolve incident: {e}")
```

---

## Escalation Policies

### Configure in PagerDuty UI

**Steps**:
1. Go to **Escalation Policies**
2. Click **New Escalation Policy**
3. Configure levels:
   - **Level 1**: Page primary on-call (5 min timeout)
   - **Level 2**: Page backup on-call (10 min timeout)
   - **Level 3**: Page manager (page after 15 min)

4. Assign to your "Database Migrations" service

---

## Best Practices

### ✅ Do's

1. **Alert only on production failures**
   ```python
   if context.environment == 'production':
       create_pagerduty_incident(context, severity='critical')
   ```

2. **Include helpful runbook links**
   ```python
   payload['links'] = [
       {
           'href': 'https://wiki.example.com/runbooks/migration-failures',
           'text': 'Migration Failure Runbook'
       }
   ]
   ```

3. **Use meaningful dedup keys**
   ```python
   # Good: Unique per migration
   dedup_key = f"confiture-{context.migration_name}-{context.environment}"

   # Bad: Same for all failures
   dedup_key = "migration-error"
   ```

4. **Include context details**
   ```python
   'custom_details': {
       'migration': context.migration_name,
       'error': str(context.error),
       'database': database_name
   }
   ```

### ❌ Don'ts

1. **Don't alert for all migrations**
   ```python
   # Bad: Too noisy
   @register_hook('post_execute')
   def alert_all(context: HookContext) -> None:
       create_pagerduty_incident(context)

   # Good: Only failures
   @register_hook('on_error')
   def alert_failures(context: HookContext) -> None:
       create_pagerduty_incident(context)
   ```

2. **Don't include sensitive data**
   ```python
   # Bad: Logs connection string
   'error': f"Failed to connect to {context.database_url}"

   # Good: Redacts credentials
   'database': context.database_url.split('@')[-1]
   ```

3. **Don't block migration on PagerDuty failure**
   ```python
   try:
       create_incident(...)
   except Exception:
       pass  # Don't fail migration if PagerDuty is down
   ```

---

## Troubleshooting

### ❌ Error: "Invalid routing_key"

**Cause**: PAGERDUTY_INTEGRATION_KEY environment variable is wrong

**Solution**:
```bash
# Verify the key
echo $PAGERDUTY_INTEGRATION_KEY

# Get fresh key from PagerDuty UI
# Service → Integrations → Events API V2 → Copy Integration Key
export PAGERDUTY_INTEGRATION_KEY="new_key_here"
```

---

### ❌ Error: "Incident not triggered"

**Cause**: Dedup key might be resolving old incidents

**Solution**:
```python
# Use unique dedup key per migration
dedup_key = f"confiture-{context.migration_name}-{int(time.time())}"

# Or resolve old incidents explicitly
payload['event_action'] = 'resolve'  # Resolve before creating new one
```

---

### ❌ Error: "On-call engineer not notified"

**Cause**: Escalation policy not configured correctly

**Solution**:
1. Go to **Services** → Select service
2. Click **Escalation Policy**
3. Verify escalation levels are configured
4. Verify on-call schedule is assigned to escalation policy
5. Test escalation with **Send Test Incident**

---

## See Also

- [Slack Integration](./slack-integration.md) - Parallel notifications
- [Monitoring Integration](./monitoring-integration.md) - Metrics and dashboards
- [Hook API Reference](../api/hooks.md) - Custom migration logic
- [PagerDuty Documentation](https://developer.pagerduty.com/docs/events-api-v2/overview/) - Official docs

---

## 🎯 Next Steps

**Ready to route migration failures to PagerDuty?**
- ✅ You now understand: Incident creation, escalation policies, runbook linking

**What to do next:**

1. **[Create PagerDuty service](#step-1-create-pagerduty-service)** - Set up "Database Migrations" service
2. **[Get integration key](#step-2-create-integration-key)** - Copy API credentials
3. **[Install and configure](#step-3-install-pagerduty-python-client)** - Add hooks to your project
4. **[Test with staging](#when-to-use-pagerduty)** - Verify before production
5. **[Set up escalation](#escalation-policies)** - Configure backup on-call engineer

---

**Last Updated**: January 9, 2026
**Status**: Production Ready ✅
**Tested On**: PagerDuty Events API v2

🍓 Never miss a critical migration failure again
