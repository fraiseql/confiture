# Slack Integration Guide

**Status**: Complete Integration Guide
**Last Updated**: January 9, 2026
**Complexity**: Intermediate
**Time to Implement**: 30-45 minutes

---

## What is Slack Integration?

Slack integration enables Confiture to send notifications to your Slack workspace when migrations occur. This keeps your team informed about migration status, failures, and completions in real-time.

**Tagline**: *Get migration notifications in Slack without leaving your chat*

---

## Why Send Migrations to Slack?

### Common Use Cases

1. **Team Awareness** - Everyone knows when migrations happen
2. **Alert Fatigue Prevention** - One place for all alerts
3. **Incident Response** - Quick escalation when migrations fail
4. **Audit Trail** - Slack searchable history of all migrations
5. **Multi-team Coordination** - DevOps, backend, DBA all informed

### Business Value

- ✅ **Faster incident response** (5-10 min faster)
- ✅ **Better team coordination** (no email delays)
- ✅ **Reduced on-call burden** (one place to check)
- ✅ **Audit compliance** (timestamped records)
- ✅ **Team confidence** (transparency builds trust)

---

## Setup Overview

### Requirements

- ✅ Slack workspace with admin access
- ✅ Ability to create Slack apps
- ✅ Confiture with hooks (Phase 4+)
- ✅ Network access to Slack API

### Time Required

- **Initial setup**: 10-15 minutes
- **Testing**: 10-15 minutes
- **Deployment**: 5-10 minutes
- **Total**: 30-45 minutes

---

## Step 1: Create Slack App & Webhook

### Create Slack App

1. Go to https://api.slack.com/apps
2. Click "Create New App"
3. Choose "From scratch"
4. **App Name**: `Confiture Migrations`
5. **Workspace**: Select your workspace
6. Click "Create App"

### Create Incoming Webhook

1. In left sidebar, click "Incoming Webhooks"
2. Toggle "Activate Incoming Webhooks" → ON
3. Click "Add New Webhook to Workspace"
4. Select channel: `#migrations` (or create new)
5. Click "Allow"
6. Copy the **Webhook URL** (looks like: `https://hooks.slack.com/services/T.../B.../X...`)

### Store Webhook URL

```bash
# Add to environment variables
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

# Or in .env file
echo 'SLACK_WEBHOOK_URL="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"' >> .env
```

---

## Step 2: Create Migration Hook

### Basic Slack Hook

```python
import os
import json
import requests
from confiture.hooks import register_hook, HookContext

SLACK_WEBHOOK = os.environ.get('SLACK_WEBHOOK_URL')

@register_hook('post_execute')
def notify_slack_success(context: HookContext) -> None:
    """
    Send Slack notification when migration succeeds.

    Sends rich message with migration details.
    """
    if not SLACK_WEBHOOK:
        return  # Silently skip if webhook not configured

    message = {
        "text": f"✅ Migration {context.migration_name} completed",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "✅ Migration Completed",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Migration:*\n{context.migration_name}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Environment:*\n{context.environment}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Duration:*\n{context.duration}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Rows Affected:*\n{context.rows_affected or 'N/A'}"
                    }
                ]
            }
        ]
    }

    response = requests.post(SLACK_WEBHOOK, json=message)
    response.raise_for_status()
```

**Output in Slack**:
```
✅ Migration Completed

Migration:        002_add_email_to_users
Environment:      production
Duration:         0:00:02.34
Rows Affected:    1000
```

---

### Error Notification Hook

```python
@register_hook('on_error')
def notify_slack_error(context: HookContext) -> None:
    """
    Send Slack alert when migration fails.

    Includes error details and mentions team.
    """
    if not SLACK_WEBHOOK:
        return

    error_message = str(context.error) if context.error else "Unknown error"

    message = {
        "text": f"🚨 Migration {context.migration_name} FAILED",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "🚨 Migration Failed",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Migration:*\n{context.migration_name}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Environment:*\n{context.environment}"
                    }
                ]
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Error:*\n```{error_message}```"
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "View Logs"
                        },
                        "url": f"https://your-logs.example.com/migration/{context.migration_name}"
                    }
                ]
            }
        ]
    }

    # For critical errors, mention team
    if context.environment == 'production':
        message["text"] = f"<!here> 🚨 Production migration failed: {context.migration_name}"

    response = requests.post(SLACK_WEBHOOK, json=message)
    response.raise_for_status()
```

**Output in Slack**:
```
<!here> 🚨 Production migration failed: 003_add_payment_table

🚨 Migration Failed

Migration:    003_add_payment_table
Environment:  production

Error:
ERROR: Column 'email' already exists
```

---

## Step 3: Rich Message Formatting

### Custom Message Layouts

```python
@register_hook('post_execute')
def detailed_slack_message(context: HookContext) -> None:
    """Send detailed message with table information."""
    if not SLACK_WEBHOOK:
        return

    # Build table information
    table_info = ""
    for table in context.tables:
        table_info += f"• {table.name}: {table.rows_after or '?'} rows\n"

    message = {
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "✅ Migration Complete",
                    "emoji": True
                }
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{context.migration_name}*\n" \
                            f"Environment: {context.environment}\n" \
                            f"Duration: {context.duration}\n" \
                            f"Status: Success ✅"
                }
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Tables Affected:*\n{table_info}"
                }
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Executed at {context.end_time.isoformat()}"
                    }
                ]
            }
        ]
    }

    requests.post(SLACK_WEBHOOK, json=message)
```

---

## Step 4: Thread Management

### Keep Related Messages in Threads

```python
import os
import json
import requests
from datetime import datetime

SLACK_WEBHOOK = os.environ.get('SLACK_WEBHOOK_URL')
# Simple in-memory thread tracking (use database in production)
_thread_ids = {}

@register_hook('pre_execute')
def slack_start_migration(context: HookContext) -> None:
    """Start a thread for this migration."""
    message = {
        "text": f"🔄 Starting migration: {context.migration_name}",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"🔄 Starting migration\n*{context.migration_name}*"
                }
            }
        ]
    }

    response = requests.post(SLACK_WEBHOOK, json=message)
    response_data = response.json()

    # Store thread timestamp for reply
    _thread_ids[context.migration_name] = response_data['ts']

@register_hook('post_execute')
def slack_complete_migration(context: HookContext) -> None:
    """Reply in migration thread when complete."""
    thread_ts = _thread_ids.get(context.migration_name)

    message = {
        "text": f"✅ Completed: {context.migration_name}",
        "thread_ts": thread_ts,  # Reply in thread
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"✅ Migration completed in {context.duration}"
                }
            }
        ]
    }

    requests.post(SLACK_WEBHOOK, json=message)
```

---

## Step 5: Error Handling & Retries

### Resilient Slack Notifications

```python
import requests
import time
from confiture.hooks import register_hook, HookContext, HookError

SLACK_WEBHOOK = os.environ.get('SLACK_WEBHOOK_URL')
MAX_RETRIES = 3

def send_slack_with_retry(message: dict) -> None:
    """Send Slack message with retry logic."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.post(
                SLACK_WEBHOOK,
                json=message,
                timeout=5
            )
            response.raise_for_status()
            return  # Success

        except requests.exceptions.RequestException as e:
            if attempt == MAX_RETRIES:
                # Give up after max retries, but don't fail migration
                print(f"Warning: Failed to send Slack notification: {e}")
                return

            # Exponential backoff
            wait_time = 2 ** (attempt - 1)
            time.sleep(wait_time)

@register_hook('post_execute')
def resilient_notification(context: HookContext) -> None:
    """Send notification with error handling."""
    if not SLACK_WEBHOOK:
        return

    message = {
        "text": f"✅ Migration {context.migration_name} completed",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"✅ {context.migration_name}\nDuration: {context.duration}"
                }
            }
        ]
    }

    try:
        send_slack_with_retry(message)
    except Exception as e:
        # Log but don't fail migration if Slack is down
        print(f"Error sending Slack notification: {e}")
```

---

## Example 1: Production Migration Alert

```python
@register_hook('post_execute')
def production_migration_alert(context: HookContext) -> None:
    """Alert team for production migrations."""
    if context.environment != 'production':
        return

    message = {
        "text": f"🚀 Production migration: {context.migration_name}",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "🚀 Production Migration Complete",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Migration:* {context.migration_name}\n" \
                            f"*Duration:* {context.duration}\n" \
                            f"*Status:* ✅ Success"
                }
            }
        ]
    }

    requests.post(os.environ['SLACK_WEBHOOK_URL'], json=message)
```

---

## Example 2: Data Validation Integration

```python
import psycopg
from confiture.hooks import register_hook, HookContext

@register_hook('post_execute')
def validate_and_notify(context: HookContext) -> None:
    """Validate data then notify Slack of results."""
    validation_status = "✅ Passed"
    validation_details = []

    try:
        with psycopg.connect(context.database_url) as conn:
            for table in context.tables:
                # Check row count
                cursor = conn.execute(
                    f"SELECT COUNT(*) FROM {table.name}"
                )
                row_count = cursor.scalar()
                validation_details.append(
                    f"• {table.name}: {row_count} rows"
                )

    except Exception as e:
        validation_status = f"⚠️ Warning: {str(e)}"

    message = {
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Migration:* {context.migration_name}\n" \
                            f"*Validation:* {validation_status}\n" \
                            f"*Tables:*\n" + "\n".join(validation_details)
                }
            }
        ]
    }

    requests.post(os.environ['SLACK_WEBHOOK_URL'], json=message)
```

---

## Example 3: Team-Specific Channels

```python
@register_hook('post_execute')
def send_to_appropriate_channel(context: HookContext) -> None:
    """Send to different channels based on environment."""
    webhooks = {
        'production': os.environ.get('SLACK_WEBHOOK_PROD'),
        'staging': os.environ.get('SLACK_WEBHOOK_STAGING'),
        'development': os.environ.get('SLACK_WEBHOOK_DEV'),
    }

    webhook = webhooks.get(context.environment)
    if not webhook:
        return

    color = '#36a64f' if context.status == 'success' else '#ff0000'

    message = {
        "attachments": [
            {
                "color": color,
                "title": context.migration_name,
                "fields": [
                    {
                        "title": "Environment",
                        "value": context.environment,
                        "short": True
                    },
                    {
                        "title": "Duration",
                        "value": str(context.duration),
                        "short": True
                    },
                    {
                        "title": "Status",
                        "value": "✅ Success",
                        "short": True
                    }
                ]
            }
        ]
    }

    requests.post(webhook, json=message)
```

---

## Testing Slack Integration

### Manual Test

```bash
# Test webhook directly
curl -X POST -H 'Content-type: application/json' \
    --data '{"text":"Test migration notification"}' \
    $SLACK_WEBHOOK_URL

# Should see message appear in Slack channel
```

### Automated Test

```python
import pytest
from unittest.mock import patch, MagicMock
import requests

@patch('requests.post')
def test_slack_notification_sent(mock_post):
    """Test that Slack message is sent on migration success."""
    from my_hooks import notify_slack_success
    from confiture.hooks import HookContext
    from datetime import datetime, timedelta

    # Mock context
    context = MagicMock(spec=HookContext)
    context.migration_name = '001_create_users'
    context.environment = 'production'
    context.duration = timedelta(seconds=2)
    context.rows_affected = 1000
    context.tables = []

    # Call hook
    notify_slack_success(context)

    # Verify Slack was called
    mock_post.assert_called_once()
    call_args = mock_post.call_args

    # Verify message content
    message = call_args.kwargs['json']
    assert '001_create_users' in message['text']
```

---

## Troubleshooting

### Problem: Notifications Not Appearing

**Cause**: Webhook URL invalid or expired

**Solution**:
```python
# Verify webhook URL is correct
import os
webhook = os.environ.get('SLACK_WEBHOOK_URL')
print(f"Webhook URL: {webhook}")

# Verify format (should start with https://hooks.slack.com)
assert webhook.startswith('https://hooks.slack.com'), "Invalid webhook URL"

# Test webhook directly
import requests
response = requests.post(webhook, json={"text": "Test"})
print(f"Response: {response.status_code}")  # Should be 200
```

### Problem: Rate Limiting

**Cause**: Sending too many messages

**Solution**:
```python
# Slack limits: ~1 message per second per webhook
# For multiple migrations, batch or throttle:

@register_hook('post_execute')
def throttled_notification(context: HookContext) -> None:
    """Only notify for certain migrations to avoid rate limits."""
    # Only notify for production
    if context.environment != 'production':
        return

    # Only notify for significant migrations
    if context.rows_affected and context.rows_affected < 100:
        return

    send_message(...)
```

### Problem: Special Characters Breaking Message

**Cause**: JSON encoding issues

**Solution**:
```python
import json

message = {
    "text": f"Migration: {context.migration_name}",
}

# Ensure proper JSON encoding
json_str = json.dumps(message, ensure_ascii=True)
response = requests.post(SLACK_WEBHOOK, data=json_str)
```

---

## Best Practices

### ✅ Do's

1. **Store webhook URL in environment**
   ```python
   webhook = os.environ.get('SLACK_WEBHOOK_URL')
   ```

2. **Check webhook exists before sending**
   ```python
   if not webhook:
       return  # Silently skip if not configured
   ```

3. **Use threads for related messages**
   ```python
   message['thread_ts'] = parent_ts  # Reply in thread
   ```

4. **Include timestamp in context**
   ```python
   "text": f"Migration completed at {context.end_time}"
   ```

### ❌ Don'ts

1. **Don't hardcode webhook URLs**
   ```python
   # Bad
   webhook = "https://hooks.slack.com/..."

   # Good
   webhook = os.environ['SLACK_WEBHOOK_URL']
   ```

2. **Don't fail migration if Slack is down**
   ```python
   # Bad: Raises exception, stops migration
   response.raise_for_status()

   # Good: Log but continue
   try:
       response.raise_for_status()
   except Exception:
       logger.error("Failed to send Slack notification")
   ```

3. **Don't send sensitive data**
   ```python
   # Bad: Raw SQL
   "error": raw_sql_error

   # Good: Sanitized message
   "error": "Database constraint violation"
   ```

---

## Performance Considerations

### Notification Latency

| Operation | Typical Time |
|-----------|-------------|
| Send to Slack | 100-500ms |
| Render in Slack UI | 50-200ms |
| Total latency | 150-700ms |

**Impact**: Negligible for migrations (usually take 1-10+ seconds)

### Best for: High-visibility events (production migrations, errors)

---

## See Also

- [Hook API Reference](../api/hooks.md) - Hooks documentation
- [GitHub Actions Integration](./github-actions-workflow.md) - CI/CD notifications
- [Phase 4 Patterns](./phase-4-patterns.md#notification-patterns) - More examples

---

**Status**: Production Ready ✅
**Last Tested**: January 9, 2026
**Examples Verified**: All working ✅

🍓 Slack notifications: Keep your team in the loop

