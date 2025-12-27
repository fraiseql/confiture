# Generic Webhook Integration

**Send Confiture migration events to any webhook endpoint for custom integrations**

---

## What is Webhook Integration?

Generic webhook integration enables Confiture to send HTTP POST requests to any webhook endpoint when migrations occur. This allows integration with custom systems, less common platforms, or internal tools.

**Tagline**: *Integrate migrations with any system via webhooks*

---

## Why Use Generic Webhooks?

### Common Use Cases

1. **Custom Integrations** - Connect to internal tools or APIs
2. **Multiple Platforms** - Send to Slack AND your custom dashboard
3. **Analytics** - Track migration events in custom analytics platform
4. **Automation** - Trigger scripts or workflows on migration events
5. **Team Tools** - Integrate with team-specific communication platforms

### Business Value

- ✅ **Flexibility** - Works with any webhook-capable system
- ✅ **No vendor lock-in** - Not tied to specific platforms
- ✅ **Custom workflows** - Implement exactly what your team needs
- ✅ **Real-time events** - Instant notification to your systems
- ✅ **Easy to test** - Use simple HTTP endpoints

---

## When to Use Webhooks

### ✅ Perfect For

- **Custom internal tools** - Your own dashboard or alerting system
- **Multiple integrations** - Need Slack AND email AND analytics
- **Testing** - Verify hooks work before production
- **Prototyping** - Quick integration without waiting for SDK
- **Non-standard platforms** - Systems without dedicated integrations

### ❌ Not For

- **Long-running operations** - Webhooks timeout after 30 seconds
- **Complex authentication** - Use native SDKs for OAuth/mTLS
- **Batch processing** - Only for real-time events
- **Sensitive data** - Consider security implications of HTTP

---

## How Webhooks Work

### Webhook Event Flow

```
Migration Event Occurs
    ↓
Hook Triggered (post_execute or on_error)
    ↓
Format Event Payload (JSON)
    ├─ migration_name: "005_add_payment_table"
    ├─ status: "success"
    ├─ duration: 2.34
    └─ rows_affected: 50000
    ↓
Send HTTP POST to Webhook URL
    ├─ URL: https://your-system.example.com/webhooks/migrations
    ├─ Method: POST
    ├─ Headers: {"Content-Type": "application/json"}
    └─ Body: JSON payload
    ↓
Your System Receives Event
    └─ Process, log, or act on event
```

---

## Setup Overview

### Requirements

- ✅ Confiture with hooks (Phase 4+)
- ✅ Webhook endpoint to send to (HTTP server)
- ✅ Network access from your migration server
- ✅ HTTPS endpoint (for production)

### Time Required

- **Basic setup**: 5-10 minutes
- **Testing**: 5-10 minutes
- **Production setup**: 10-15 minutes

---

## Simple Webhook Integration

### Basic Webhook Hook

```python
# confiture_hooks/webhooks.py
import os
import json
import requests
from datetime import datetime
from confiture.hooks import register_hook, HookContext

WEBHOOK_URL = os.environ.get('CONFITURE_WEBHOOK_URL')
WEBHOOK_SECRET = os.environ.get('CONFITURE_WEBHOOK_SECRET')

def send_webhook(event_type: str, context: HookContext) -> None:
    """Send webhook event to configured endpoint."""
    if not WEBHOOK_URL:
        print("⚠️ CONFITURE_WEBHOOK_URL not set")
        return

    payload = {
        'event_type': event_type,
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'migration': {
            'name': context.migration_name,
            'version': context.migration_version,
            'environment': context.environment,
        },
        'execution': {
            'start_time': context.start_time.isoformat() if context.start_time else None,
            'end_time': context.end_time.isoformat() if context.end_time else None,
            'duration_seconds': context.duration.total_seconds() if context.duration else None,
            'rows_affected': context.rows_affected,
        },
        'database': {
            'host': context.database_url.split('@')[-1].split('/')[0],
            'schema': context.schema_name,
        }
    }

    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'Confiture/1.0'
    }

    # Add secret header if configured
    if WEBHOOK_SECRET:
        headers['X-Confiture-Secret'] = WEBHOOK_SECRET

    try:
        response = requests.post(
            WEBHOOK_URL,
            json=payload,
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        print(f"✅ Webhook sent: {event_type}")

    except requests.exceptions.Timeout:
        print(f"⚠️ Webhook timeout (10s)")
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Webhook failed: {e}")

@register_hook('post_execute')
def webhook_on_success(context: HookContext) -> None:
    """Send success event to webhook."""
    send_webhook('migration_success', context)

@register_hook('on_error')
def webhook_on_error(context: HookContext) -> None:
    """Send error event to webhook."""
    payload = {
        'event_type': 'migration_error',
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'migration': {
            'name': context.migration_name,
            'version': context.migration_version,
            'environment': context.environment,
        },
        'error': {
            'type': type(context.error).__name__,
            'message': str(context.error),
        }
    }

    headers = {'Content-Type': 'application/json'}
    if WEBHOOK_SECRET:
        headers['X-Confiture-Secret'] = WEBHOOK_SECRET

    try:
        requests.post(
            WEBHOOK_URL,
            json=payload,
            headers=headers,
            timeout=10
        )
        print(f"✅ Error webhook sent")
    except Exception as e:
        print(f"⚠️ Error webhook failed: {e}")
```

**Setup**:
```bash
# Set webhook URL
export CONFITURE_WEBHOOK_URL="https://your-system.example.com/webhooks/migrations"

# Optional: Set secret for verification
export CONFITURE_WEBHOOK_SECRET="your_secret_key_here"
```

**Webhook Payload Example**:
```json
{
  "event_type": "migration_success",
  "timestamp": "2026-01-09T14:23:45.123Z",
  "migration": {
    "name": "005_add_payment_table",
    "version": "005",
    "environment": "production"
  },
  "execution": {
    "start_time": "2026-01-09T14:23:43.000Z",
    "end_time": "2026-01-09T14:23:45.123Z",
    "duration_seconds": 2.123,
    "rows_affected": 50000
  },
  "database": {
    "host": "db.production.internal",
    "schema": "public"
  }
}
```

---

## Multiple Webhooks

### Send to Multiple Endpoints

```python
# confiture_hooks/multi_webhooks.py
import os
import requests
from confiture.hooks import register_hook, HookContext

# Configure multiple webhooks
WEBHOOKS = {
    'analytics': os.environ.get('WEBHOOK_ANALYTICS'),
    'dashboard': os.environ.get('WEBHOOK_DASHBOARD'),
    'slack': os.environ.get('WEBHOOK_SLACK'),
}

@register_hook('post_execute')
def send_to_all_webhooks(context: HookContext) -> None:
    """Send to multiple webhook endpoints."""
    for webhook_name, webhook_url in WEBHOOKS.items():
        if not webhook_url:
            continue

        payload = {
            'event_type': 'migration_success',
            'webhook_target': webhook_name,
            'migration': context.migration_name,
            'duration': context.duration.total_seconds(),
            'rows_affected': context.rows_affected,
            'environment': context.environment,
        }

        try:
            requests.post(webhook_url, json=payload, timeout=5)
            print(f"✅ Webhook sent to {webhook_name}")
        except Exception as e:
            print(f"⚠️ Webhook {webhook_name} failed: {e}")
            # Continue to next webhook even if one fails
```

**Setup**:
```bash
export WEBHOOK_ANALYTICS="https://analytics.example.com/events"
export WEBHOOK_DASHBOARD="https://dashboard.example.com/migrations"
export WEBHOOK_SLACK="https://hooks.slack.com/services/YOUR/WEBHOOK"
```

---

## Webhook Signature Verification

### HMAC Verification for Security

```python
# confiture_hooks/secure_webhooks.py
import os
import json
import hmac
import hashlib
import requests
from confiture.hooks import register_hook, HookContext

WEBHOOK_URL = os.environ.get('CONFITURE_WEBHOOK_URL')
WEBHOOK_SECRET = os.environ.get('CONFITURE_WEBHOOK_SECRET')

def create_signature(payload: dict) -> str:
    """Create HMAC signature for webhook verification."""
    payload_json = json.dumps(payload, sort_keys=True)
    signature = hmac.new(
        WEBHOOK_SECRET.encode(),
        payload_json.encode(),
        hashlib.sha256
    ).hexdigest()
    return f"sha256={signature}"

@register_hook('post_execute')
def send_signed_webhook(context: HookContext) -> None:
    """Send webhook with HMAC signature."""
    if not WEBHOOK_URL or not WEBHOOK_SECRET:
        return

    payload = {
        'event_type': 'migration_success',
        'migration': context.migration_name,
        'duration': context.duration.total_seconds(),
        'timestamp': context.end_time.isoformat() if context.end_time else None,
    }

    signature = create_signature(payload)

    headers = {
        'Content-Type': 'application/json',
        'X-Confiture-Signature': signature,
    }

    try:
        response = requests.post(
            WEBHOOK_URL,
            json=payload,
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        print(f"✅ Signed webhook sent")

    except Exception as e:
        print(f"⚠️ Webhook failed: {e}")
```

**Receiver Implementation (Python)**:
```python
# Your webhook receiver
import hmac
import hashlib
import json
from flask import Flask, request

WEBHOOK_SECRET = "your_secret_key"

app = Flask(__name__)

@app.route('/webhooks/migrations', methods=['POST'])
def handle_migration_webhook():
    # Get signature from header
    signature = request.headers.get('X-Confiture-Signature')
    if not signature:
        return {'error': 'Missing signature'}, 401

    # Get payload
    payload = request.get_json()
    payload_json = json.dumps(payload, sort_keys=True)

    # Verify signature
    expected_signature = hmac.new(
        WEBHOOK_SECRET.encode(),
        payload_json.encode(),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(signature.split('=')[1], expected_signature):
        return {'error': 'Invalid signature'}, 401

    # Process event
    event_type = payload.get('event_type')
    migration_name = payload.get('migration')
    print(f"✅ Valid webhook received: {event_type} for {migration_name}")

    return {'status': 'received'}, 200
```

---

## Webhook Retry Logic

### Handle Failed Deliveries

```python
# confiture_hooks/webhook_retry.py
import os
import requests
import time
from confiture.hooks import register_hook, HookContext

WEBHOOK_URL = os.environ.get('CONFITURE_WEBHOOK_URL')

def send_webhook_with_retry(payload: dict, max_retries: int = 3) -> bool:
    """Send webhook with exponential backoff retry."""
    for attempt in range(max_retries):
        try:
            response = requests.post(
                WEBHOOK_URL,
                json=payload,
                timeout=10
            )
            response.raise_for_status()
            return True

        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                # Calculate backoff: 2s, 4s, 8s
                wait_time = 2 ** (attempt + 1)
                print(f"⚠️ Webhook failed, retry in {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"❌ Webhook failed after {max_retries} attempts")
                return False

@register_hook('post_execute')
def webhook_with_retry(context: HookContext) -> None:
    """Send webhook with automatic retry."""
    payload = {
        'event_type': 'migration_success',
        'migration': context.migration_name,
        'duration': context.duration.total_seconds(),
    }

    success = send_webhook_with_retry(payload)
    if success:
        print(f"✅ Webhook delivered successfully")
```

---

## Testing Webhooks

### Using RequestBin for Testing

```bash
# 1. Create a temporary webhook endpoint
# Visit https://requestbin.com and create a new bin
# You'll get a URL like: https://requestbin.com/abc123xyz

# 2. Configure Confiture to use it
export CONFITURE_WEBHOOK_URL="https://requestbin.com/abc123xyz"

# 3. Run a migration
confiture migrate up --database-url postgresql://...

# 4. Check RequestBin to see the webhook payload
# Visit https://requestbin.com/abc123xyz to view all received requests
```

### Local Testing with Python

```python
# test_webhooks.py
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import threading

class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        payload = json.loads(body.decode())

        print(f"✅ Webhook received!")
        print(f"   Event: {payload.get('event_type')}")
        print(f"   Migration: {payload.get('migration', {}).get('name')}")
        print(f"   Duration: {payload.get('execution', {}).get('duration_seconds')}s")

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({'status': 'received'}).encode())

    def log_message(self, format, *args):
        pass  # Suppress default logging

def start_test_server(port=8000):
    """Start local test webhook server."""
    server = HTTPServer(('0.0.0.0', port), WebhookHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    print(f"🧪 Test webhook server listening on port {port}")
    print(f"   Set: CONFITURE_WEBHOOK_URL=http://localhost:{port}/webhooks")
    return server

if __name__ == '__main__':
    server = start_test_server(8000)
    try:
        while True:
            pass
    except KeyboardInterrupt:
        server.shutdown()
```

**Usage**:
```bash
# Terminal 1: Start test server
python test_webhooks.py

# Terminal 2: Run migration
export CONFITURE_WEBHOOK_URL="http://localhost:8000/webhooks"
confiture migrate up --database-url postgresql://...

# Terminal 1 output:
# ✅ Webhook received!
#    Event: migration_success
#    Migration: 005_add_payment_table
#    Duration: 2.34s
```

---

## Advanced: Webhook with Custom Headers

```python
# confiture_hooks/advanced_webhooks.py
import os
import requests
from confiture.hooks import register_hook, HookContext

WEBHOOK_URL = os.environ.get('CONFITURE_WEBHOOK_URL')
API_KEY = os.environ.get('API_KEY')
CORRELATION_ID = os.environ.get('CORRELATION_ID', 'default')

@register_hook('post_execute')
def webhook_with_custom_headers(context: HookContext) -> None:
    """Send webhook with custom headers for authentication."""
    payload = {
        'event_type': 'migration_success',
        'migration': context.migration_name,
        'duration': context.duration.total_seconds(),
    }

    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {API_KEY}',
        'X-Correlation-ID': CORRELATION_ID,
        'X-Migration-Version': context.migration_version,
        'X-Environment': context.environment,
    }

    try:
        response = requests.post(
            WEBHOOK_URL,
            json=payload,
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        print(f"✅ Webhook sent with custom headers")

    except Exception as e:
        print(f"⚠️ Webhook failed: {e}")
```

---

## Best Practices

### ✅ Do's

1. **Verify webhook signatures**
   ```python
   # Always verify incoming webhooks are legitimate
   signature = request.headers.get('X-Confiture-Signature')
   if not verify_signature(payload, signature):
       return 401  # Reject unsigned requests
   ```

2. **Use HTTPS**
   ```python
   WEBHOOK_URL = "https://your-system.example.com/webhooks"  # Always HTTPS
   ```

3. **Set reasonable timeouts**
   ```python
   requests.post(WEBHOOK_URL, timeout=10)  # 10 second timeout
   ```

4. **Include trace IDs**
   ```python
   headers = {
       'X-Correlation-ID': context.migration_name,
       'X-Environment': context.environment
   }
   ```

5. **Log failed webhooks**
   ```python
   except Exception as e:
       logger.error(f"Webhook failed: {e}", extra={'migration': context.migration_name})
   ```

### ❌ Don'ts

1. **Don't block migration on webhook failure**
   ```python
   # Bad: Migration fails if webhook fails
   requests.post(WEBHOOK_URL).raise_for_status()

   # Good: Webhook failure doesn't affect migration
   try:
       requests.post(WEBHOOK_URL)
   except:
       pass  # Log but don't block
   ```

2. **Don't expose sensitive data**
   ```python
   # Bad: Logs database password
   'database_url': context.database_url

   # Good: Redacts credentials
   'database_host': context.database_url.split('@')[-1].split('/')[0]
   ```

3. **Don't use long timeouts**
   ```python
   # Bad: 5 minute timeout
   requests.post(url, timeout=300)

   # Good: 10 second timeout
   requests.post(url, timeout=10)
   ```

---

## Troubleshooting

### ❌ Error: "Connection refused"

**Cause**: Webhook endpoint not running or wrong URL

**Solution**:
```bash
# Test connectivity
curl -X POST https://your-system.example.com/webhooks/migrations \
  -H "Content-Type: application/json" \
  -d '{"test": true}'

# Check webhook URL
echo $CONFITURE_WEBHOOK_URL
```

---

### ❌ Error: "Request timeout"

**Cause**: Webhook endpoint is slow or not responding

**Solution**:
```python
# Increase timeout to 30 seconds
requests.post(WEBHOOK_URL, timeout=30)

# Or add retry logic
send_webhook_with_retry(payload, max_retries=3)
```

---

### ❌ Error: "Webhook received but not processed"

**Cause**: Signature verification failing

**Solution**:
```python
# Verify signature is being created correctly
payload_json = json.dumps(payload, sort_keys=True)
signature = hmac.new(SECRET, payload_json.encode(), hashlib.sha256).hexdigest()
print(f"Signature: sha256={signature}")

# Verify on receiver side
expected = hmac.new(SECRET, payload_json.encode(), hashlib.sha256).hexdigest()
if not hmac.compare_digest(received, expected):
    print("Signature mismatch!")
```

---

## See Also

- [Slack Integration](./slack-integration.md) - Native Slack integration
- [Monitoring Integration](./monitoring-integration.md) - Metrics and dashboards
- [PagerDuty Alerting](./pagerduty-alerting.md) - Incident management
- [Hook API Reference](../api/hooks.md) - Custom migration logic

---

## 🎯 Next Steps

**Ready to integrate with webhooks?**
- ✅ You now understand: Webhook payloads, signatures, retries, testing

**What to do next:**

1. **[Test with RequestBin](#testing-webhooks)** - Set up temporary endpoint
2. **[Create webhook receiver](#webhook-signature-verification)** - Implement your endpoint
3. **[Deploy hooks to production](#setup-overview)** - Configure environment variables
4. **[Monitor webhook deliveries](#advanced-webhook-with-custom-headers)** - Add logging and alerting

---

**Last Updated**: January 9, 2026
**Status**: Production Ready ✅
**Tested On**: HTTP/HTTPS endpoints, various frameworks

🍓 Connect migrations to any system via webhooks
