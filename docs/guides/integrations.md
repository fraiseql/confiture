# Integrations Guide

[← Back to Guides](../index.md) · [Compliance](compliance.md) · [Dry-Run →](dry-run.md)

Connect Confiture with CI/CD, monitoring, and alerting systems.

---

## Quick Reference

| Integration | Purpose | Key Features |
|------------|---------|--------------|
| **GitHub Actions** | CI/CD | Dry-run validation, auto-deploy |
| **Slack** | Notifications | Migration status, approvals |
| **Prometheus/Grafana** | Monitoring | Metrics, dashboards |
| **PagerDuty** | Alerting | Incident creation, escalation |
| **Webhooks** | Custom | Generic HTTP notifications |

---

## GitHub Actions

### Basic Workflow

```yaml
# .github/workflows/migrations.yml
name: Database Migrations

on:
  push:
    branches: [main]
    paths: ['db/**']
  pull_request:
    paths: ['db/**']

jobs:
  validate:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: test
        ports: ['5432:5432']
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install Confiture
        run: pip install confiture

      - name: Dry-run migrations
        env:
          DATABASE_URL: postgresql://postgres:test@localhost/postgres
        run: |
          confiture migrate up --dry-run --format json --output report.json

      - name: Check for unsafe migrations
        run: |
          unsafe=$(jq '.summary.unsafe_count' report.json)
          if [ "$unsafe" -gt 0 ]; then
            echo "::error::Unsafe migrations detected"
            exit 1
          fi

  deploy:
    needs: validate
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    environment: production

    steps:
      - uses: actions/checkout@v4

      - name: Install Confiture
        run: pip install confiture

      - name: Run migrations
        env:
          DATABASE_URL: ${{ secrets.PRODUCTION_DATABASE_URL }}
        run: confiture migrate up
```

### Matrix Testing

```yaml
jobs:
  test:
    strategy:
      matrix:
        postgres: ['14', '15', '16']
    services:
      postgres:
        image: postgres:${{ matrix.postgres }}
```

### Caching

```yaml
- uses: actions/cache@v4
  with:
    path: ~/.cache/pip
    key: ${{ runner.os }}-pip-confiture
```

---

## Multi-Agent Coordination CI/CD

Integrate coordination checks into your CI/CD pipeline to detect conflicts before merging.

### Pre-Merge Conflict Detection

Automatically check for schema conflicts on pull requests:

```yaml
# .github/workflows/schema-conflicts.yml
name: Check Schema Conflicts

on:
  pull_request:
    paths: ['db/schema/**']

jobs:
  check-conflicts:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install Confiture
        run: pip install confiture

      - name: Extract modified tables
        id: tables
        run: |
          # Get list of modified schema files
          TABLES=$(git diff --name-only origin/${{ github.base_ref }} HEAD \
            | grep 'db/schema' \
            | xargs basename -a \
            | sed 's/\.sql$//' \
            | paste -sd "," -)
          echo "tables=$TABLES" >> $GITHUB_OUTPUT

      - name: Check coordination conflicts
        if: steps.tables.outputs.tables != ''
        env:
          COORDINATION_DB_URL: ${{ secrets.COORDINATION_DB_URL }}
        run: |
          confiture coordinate check \
            --agent-id "github-ci-pr-${{ github.event.pull_request.number }}" \
            --tables-affected "${{ steps.tables.outputs.tables }}" \
            --format json > conflicts.json

          # Fail if conflicts detected
          if jq -e '.conflicts | length > 0' conflicts.json; then
            echo "❌ Schema conflicts detected:"
            jq '.conflicts' conflicts.json
            exit 1
          else
            echo "✅ No schema conflicts detected"
          fi

      - name: Comment on PR
        if: always()
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const conflicts = JSON.parse(fs.readFileSync('conflicts.json'));

            let body = '## Schema Coordination Check\n\n';
            if (conflicts.conflicts.length > 0) {
              body += '⚠️ **Conflicts detected:**\n\n';
              conflicts.conflicts.forEach(c => {
                body += `- **${c.type}**: ${c.suggestion}\n`;
              });
            } else {
              body += '✅ No schema conflicts detected!';
            }

            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: body
            });
```

### Register Intention on Branch Creation

Automatically register coordination intentions when feature branches are created:

```yaml
# .github/workflows/register-intention.yml
name: Register Schema Intention

on:
  create:
    branches:
      - 'feature/**'
      - 'schema/**'

jobs:
  register:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install Confiture
        run: pip install confiture

      - name: Extract feature info
        id: feature
        run: |
          BRANCH_NAME="${{ github.ref_name }}"
          FEATURE_NAME=$(echo "$BRANCH_NAME" | sed 's/^feature\///')
          echo "name=$FEATURE_NAME" >> $GITHUB_OUTPUT

      - name: Register coordination intention
        env:
          COORDINATION_DB_URL: ${{ secrets.COORDINATION_DB_URL }}
        run: |
          confiture coordinate register \
            --agent-id "${{ github.actor }}" \
            --feature-name "${{ steps.feature.outputs.name }}" \
            --risk-level medium \
            --format json > intention.json

          INTENT_ID=$(jq -r '.intent_id' intention.json)
          echo "Registered intention: $INTENT_ID"
```

### Mark Complete on Merge

Automatically mark intentions as complete when PRs are merged:

```yaml
# .github/workflows/complete-intention.yml
name: Complete Schema Intention

on:
  pull_request:
    types: [closed]
    paths: ['db/schema/**']

jobs:
  complete:
    if: github.event.pull_request.merged == true
    runs-on: ubuntu-latest
    steps:
      - name: Find and complete intention
        env:
          COORDINATION_DB_URL: ${{ secrets.COORDINATION_DB_URL }}
        run: |
          # Find intention by agent and branch
          INTENT_ID=$(confiture coordinate list \
            --agent-id "${{ github.event.pull_request.user.login }}" \
            --format json \
            | jq -r ".[0].intent_id")

          # Mark as complete
          confiture coordinate complete \
            --intent-id "$INTENT_ID" \
            --outcome success \
            --notes "Merged via PR #${{ github.event.pull_request.number }}" \
            --merge-commit "${{ github.event.pull_request.merge_commit_sha }}"
```

### Dashboard Integration

Export coordination status for dashboards:

```yaml
# .github/workflows/coordination-dashboard.yml
name: Update Coordination Dashboard

on:
  schedule:
    - cron: '*/15 * * * *'  # Every 15 minutes
  workflow_dispatch:

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - name: Install Confiture
        run: pip install confiture

      - name: Export coordination status
        env:
          COORDINATION_DB_URL: ${{ secrets.COORDINATION_DB_URL }}
        run: |
          confiture coordinate status --format json > status.json
          confiture coordinate conflicts --format json > conflicts.json

      - name: Publish to dashboard
        run: |
          curl -X POST "${{ secrets.DASHBOARD_URL }}/api/coordination" \
            -H "Authorization: Bearer ${{ secrets.DASHBOARD_TOKEN }}" \
            -H "Content-Type: application/json" \
            -d @status.json

          curl -X POST "${{ secrets.DASHBOARD_URL }}/api/conflicts" \
            -H "Authorization: Bearer ${{ secrets.DASHBOARD_TOKEN }}" \
            -H "Content-Type: application/json" \
            -d @conflicts.json
```

### GitLab CI Example

```yaml
# .gitlab-ci.yml
schema-conflict-check:
  stage: test
  image: python:3.11
  services:
    - postgres:15
  variables:
    COORDINATION_DB_URL: $COORDINATION_DB_URL
  before_script:
    - pip install confiture
  script:
    - |
      # Extract modified tables
      TABLES=$(git diff --name-only $CI_MERGE_REQUEST_TARGET_BRANCH_SHA HEAD \
        | grep 'db/schema' \
        | xargs basename -a \
        | sed 's/\.sql$//' \
        | paste -sd "," -)

      if [ -n "$TABLES" ]; then
        confiture coordinate check \
          --agent-id "gitlab-ci-mr-${CI_MERGE_REQUEST_IID}" \
          --tables-affected "$TABLES" \
          --format json > conflicts.json

        if jq -e '.conflicts | length > 0' conflicts.json; then
          echo "❌ Schema conflicts detected!"
          exit 1
        fi
      fi
  only:
    - merge_requests
  when: always
```

**[→ Full Multi-Agent Coordination Guide](multi-agent-coordination.md)**

---

## Slack Integration

### Webhook Notifications

```python
import requests
from confiture.hooks import register_hook, HookContext

SLACK_WEBHOOK = os.environ.get('SLACK_WEBHOOK_URL')

@register_hook('post_execute')
def notify_slack(context: HookContext) -> None:
    if context.environment != "production":
        return

    message = {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "Migration Completed"}
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Migration:*\n{context.migration.name}"},
                    {"type": "mrkdwn", "text": f"*Duration:*\n{context.duration_ms}ms"},
                    {"type": "mrkdwn", "text": f"*Environment:*\n{context.environment}"},
                    {"type": "mrkdwn", "text": f"*Status:*\n:white_check_mark: Success"}
                ]
            }
        ]
    }

    requests.post(SLACK_WEBHOOK, json=message, timeout=10)
```

### Error Notifications

```python
@register_hook('on_error')
def notify_slack_error(context: HookContext, error: Exception) -> None:
    message = {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": ":x: Migration Failed"}
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"```{str(error)[:500]}```"}
            },
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"Migration: {context.migration.name}"}
                ]
            }
        ]
    }

    requests.post(SLACK_WEBHOOK, json=message, timeout=10)
```

### Approval Workflow

```python
from slack_sdk import WebClient

client = WebClient(token=os.environ['SLACK_BOT_TOKEN'])

def request_approval(migration_name: str, channel: str) -> str:
    """Request migration approval via Slack."""
    response = client.chat_postMessage(
        channel=channel,
        blocks=[
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Migration Approval Required*\n`{migration_name}`"}
            },
            {
                "type": "actions",
                "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "Approve"}, "style": "primary", "action_id": "approve"},
                    {"type": "button", "text": {"type": "plain_text", "text": "Reject"}, "style": "danger", "action_id": "reject"}
                ]
            }
        ]
    )
    return response['ts']
```

---

## Monitoring (Prometheus/Grafana)

### Prometheus Metrics

```python
from prometheus_client import Counter, Histogram, Gauge, start_http_server
from confiture.hooks import register_hook, HookContext

# Metrics
MIGRATIONS_TOTAL = Counter(
    'tb_confiture_total',
    'Total migrations executed',
    ['environment', 'status']
)

MIGRATION_DURATION = Histogram(
    'confiture_migration_duration_seconds',
    'Migration execution time',
    ['migration_name'],
    buckets=[0.1, 0.5, 1, 5, 10, 30, 60, 120, 300]
)

PENDING_MIGRATIONS = Gauge(
    'confiture_pending_migrations',
    'Number of pending migrations',
    ['environment']
)

# Start metrics server
start_http_server(9090)

@register_hook('post_execute')
def record_metrics(context: HookContext) -> None:
    MIGRATIONS_TOTAL.labels(
        environment=context.environment,
        status='success'
    ).inc()

    MIGRATION_DURATION.labels(
        migration_name=context.migration.name
    ).observe(context.duration_ms / 1000)

@register_hook('on_error')
def record_failure(context: HookContext, error: Exception) -> None:
    MIGRATIONS_TOTAL.labels(
        environment=context.environment,
        status='failure'
    ).inc()
```

### Grafana Dashboard

```json
{
  "dashboard": {
    "title": "Confiture Migrations",
    "panels": [
      {
        "title": "Migration Success Rate",
        "type": "stat",
        "targets": [{
          "expr": "sum(rate(tb_confiture_total{status='success'}[1h])) / sum(rate(tb_confiture_total[1h])) * 100"
        }]
      },
      {
        "title": "Migration Duration (p95)",
        "type": "graph",
        "targets": [{
          "expr": "histogram_quantile(0.95, rate(confiture_migration_duration_seconds_bucket[5m]))"
        }]
      },
      {
        "title": "Pending Migrations",
        "type": "stat",
        "targets": [{
          "expr": "confiture_pending_migrations"
        }]
      }
    ]
  }
}
```

### Datadog Integration

```python
from datadog import statsd

@register_hook('post_execute')
def datadog_metrics(context: HookContext) -> None:
    statsd.increment(
        'confiture.migrations.completed',
        tags=[f'env:{context.environment}', f'migration:{context.migration.name}']
    )
    statsd.histogram(
        'confiture.migrations.duration',
        context.duration_ms,
        tags=[f'env:{context.environment}']
    )
```

### AWS CloudWatch

```python
import boto3

cloudwatch = boto3.client('cloudwatch')

@register_hook('post_execute')
def cloudwatch_metrics(context: HookContext) -> None:
    cloudwatch.put_metric_data(
        Namespace='Confiture',
        MetricData=[
            {
                'MetricName': 'MigrationDuration',
                'Value': context.duration_ms,
                'Unit': 'Milliseconds',
                'Dimensions': [
                    {'Name': 'Environment', 'Value': context.environment},
                    {'Name': 'Migration', 'Value': context.migration.name}
                ]
            }
        ]
    )
```

---

## PagerDuty Alerting

### Events API v2

```python
import requests
from confiture.hooks import register_hook, HookContext

PAGERDUTY_KEY = os.environ.get('PAGERDUTY_ROUTING_KEY')

@register_hook('on_error')
def pagerduty_alert(context: HookContext, error: Exception) -> None:
    if context.environment != "production":
        return

    payload = {
        "routing_key": PAGERDUTY_KEY,
        "event_action": "trigger",
        "dedup_key": f"confiture-{context.migration.name}",
        "payload": {
            "summary": f"Migration failed: {context.migration.name}",
            "severity": "critical",
            "source": "confiture",
            "custom_details": {
                "migration": context.migration.name,
                "error": str(error)[:1000],
                "environment": context.environment
            }
        }
    }

    requests.post(
        "https://events.pagerduty.com/v2/enqueue",
        json=payload,
        timeout=10
    )
```

### Auto-Resolve on Success

```python
@register_hook('post_execute')
def pagerduty_resolve(context: HookContext) -> None:
    payload = {
        "routing_key": PAGERDUTY_KEY,
        "event_action": "resolve",
        "dedup_key": f"confiture-{context.migration.name}"
    }

    requests.post(
        "https://events.pagerduty.com/v2/enqueue",
        json=payload,
        timeout=10
    )
```

---

## Generic Webhooks

### Basic Webhook

```python
import requests
from confiture.hooks import register_hook, HookContext

@register_hook('post_execute')
def send_webhook(context: HookContext) -> None:
    webhook_url = os.environ.get('WEBHOOK_URL')
    if not webhook_url:
        return

    payload = {
        "event": "migration.completed",
        "timestamp": datetime.utcnow().isoformat(),
        "data": {
            "migration": context.migration.name,
            "version": context.migration.version,
            "environment": context.environment,
            "duration_ms": context.duration_ms
        }
    }

    requests.post(webhook_url, json=payload, timeout=30)
```

### Signed Webhooks

```python
import hmac
import hashlib

def send_signed_webhook(url: str, payload: dict, secret: str) -> None:
    body = json.dumps(payload)
    signature = hmac.new(
        secret.encode(),
        body.encode(),
        hashlib.sha256
    ).hexdigest()

    requests.post(
        url,
        data=body,
        headers={
            'Content-Type': 'application/json',
            'X-Signature': f'sha256={signature}'
        },
        timeout=30
    )
```

### Webhook Configuration

```yaml
# confiture.yaml
webhooks:
  - url: https://api.example.com/migrations
    events: [post_execute, on_error]
    secret: ${WEBHOOK_SECRET}
    timeout: 30
    retry:
      max_attempts: 3
      backoff: exponential
```

---

## Best Practices

### 1. Use Environment Variables

```python
# Never hardcode secrets
SLACK_WEBHOOK = os.environ.get('SLACK_WEBHOOK_URL')  # Good
SLACK_WEBHOOK = "https://hooks.slack.com/..."        # Bad
```

### 2. Add Timeouts

```python
# Always set timeouts for external calls
requests.post(url, json=data, timeout=10)  # Good
requests.post(url, json=data)              # Bad - can hang forever
```

### 3. Handle Failures Gracefully

```python
@register_hook('post_execute')
def safe_notification(context: HookContext) -> None:
    try:
        send_notification(context)
    except Exception as e:
        # Log but don't fail the migration
        logger.warning(f"Notification failed: {e}")
```

### 4. Filter by Environment

```python
@register_hook('post_execute')
def production_only(context: HookContext) -> None:
    if context.environment != "production":
        return  # Skip for dev/staging
    # ... send notification
```

### 5. Deduplicate Alerts

```python
# Use consistent dedup keys to prevent alert storms
"dedup_key": f"confiture-{context.migration.name}"
```

---

## See Also

- [Hooks Guide](./hooks.md)
- [CLI Reference](../reference/cli.md)
- [Dry-Run Guide](./dry-run.md)
