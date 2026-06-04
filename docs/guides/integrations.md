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

## Hook-based integrations

The notification and monitoring integrations below are all **migration hooks**:
a class subclassing `Hook[ExecutionContext]` that you register on a `Migrator`
(see the [Hook API Reference](../api/hooks.md)). Each reads run data from the
context and posts it somewhere. The shared shape:

```python
from confiture.core.hooks import Hook, HookContext, HookResult
from confiture.core.hooks.context import ExecutionContext


class MyIntegration(Hook[ExecutionContext]):
    def __init__(self) -> None:
        super().__init__(hook_id="my.integration", name="My Integration", priority=7)

    async def execute(self, context: HookContext[ExecutionContext]) -> HookResult:
        data = context.get_data()
        name = data.metadata.get("migration_name")
        ok = data.metadata.get("success")
        error = data.metadata.get("error")
        # ... post to the external system ...
        return HookResult(success=True)  # best-effort: don't fail the migration
```

Register it once on `HookPhase.AFTER_EXECUTE` — it fires on both success and
failure, so branch on `data.metadata["success"]` rather than relying on a
separate error phase.

## Slack Integration

```python
import requests

from confiture.core.hooks import Hook, HookContext, HookResult
from confiture.core.hooks.context import ExecutionContext


class SlackNotify(Hook[ExecutionContext]):
    def __init__(self, webhook_url: str, environment: str = "production") -> None:
        super().__init__(hook_id="slack.notify", name="Slack Notify", priority=7)
        self._webhook = webhook_url
        self._environment = environment

    async def execute(self, context: HookContext[ExecutionContext]) -> HookResult:
        data = context.get_data()
        ok = data.metadata.get("success")
        name = data.metadata.get("migration_name")
        if ok:
            header = "Migration Completed"
            body = {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*Migration:*\n{name}"},
                {"type": "mrkdwn", "text": f"*Duration:*\n{data.elapsed_time_ms}ms"},
                {"type": "mrkdwn", "text": "*Status:*\n:white_check_mark: Success"},
            ]}
        else:
            header = ":x: Migration Failed"
            body = {"type": "section", "text": {
                "type": "mrkdwn",
                "text": f"```{str(data.metadata.get('error'))[:500]}```",
            }}
        message = {"blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": header}},
            body,
        ]}
        try:
            requests.post(self._webhook, json=message, timeout=10)
        except requests.RequestException:
            pass  # never let a notification failure abort the migration
        return HookResult(success=True)
```

Register: `m.register_hook(HookPhase.AFTER_EXECUTE, SlackNotify(webhook_url))`.

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

from confiture.core.hooks import Hook, HookContext, HookResult
from confiture.core.hooks.context import ExecutionContext

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


class PrometheusMetrics(Hook[ExecutionContext]):
    def __init__(self, environment: str = "production") -> None:
        super().__init__(hook_id="prometheus.metrics", name="Prometheus", priority=8)
        self._environment = environment

    async def execute(self, context: HookContext[ExecutionContext]) -> HookResult:
        data = context.get_data()
        status = "success" if data.metadata.get("success") else "failure"
        MIGRATIONS_TOTAL.labels(environment=self._environment, status=status).inc()
        MIGRATION_DURATION.labels(
            migration_name=data.metadata.get("migration_name")
        ).observe(data.elapsed_time_ms / 1000)
        return HookResult(success=True)
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

from confiture.core.hooks import Hook, HookContext, HookResult
from confiture.core.hooks.context import ExecutionContext


class DatadogMetrics(Hook[ExecutionContext]):
    def __init__(self, environment: str = "production") -> None:
        super().__init__(hook_id="datadog.metrics", name="Datadog", priority=8)
        self._environment = environment

    async def execute(self, context: HookContext[ExecutionContext]) -> HookResult:
        data = context.get_data()
        tags = [f"env:{self._environment}", f"migration:{data.metadata.get('migration_name')}"]
        statsd.increment("confiture.migrations.completed", tags=tags)
        statsd.histogram("confiture.migrations.duration", data.elapsed_time_ms, tags=tags)
        return HookResult(success=True)
```

### AWS CloudWatch

```python
import boto3

from confiture.core.hooks import Hook, HookContext, HookResult
from confiture.core.hooks.context import ExecutionContext

cloudwatch = boto3.client('cloudwatch')


class CloudWatchMetrics(Hook[ExecutionContext]):
    def __init__(self, environment: str = "production") -> None:
        super().__init__(hook_id="cloudwatch.metrics", name="CloudWatch", priority=8)
        self._environment = environment

    async def execute(self, context: HookContext[ExecutionContext]) -> HookResult:
        data = context.get_data()
        cloudwatch.put_metric_data(
            Namespace="Confiture",
            MetricData=[{
                "MetricName": "MigrationDuration",
                "Value": data.elapsed_time_ms,
                "Unit": "Milliseconds",
                "Dimensions": [
                    {"Name": "Environment", "Value": self._environment},
                    {"Name": "Migration", "Value": data.metadata.get("migration_name")},
                ],
            }],
        )
        return HookResult(success=True)
```

---

## PagerDuty Alerting

### Events API v2 (trigger on failure, resolve on success)

A single `AFTER_EXECUTE` hook triggers an incident when a migration fails and
auto-resolves it on success — keyed on a stable `dedup_key`:

```python
import requests

from confiture.core.hooks import Hook, HookContext, HookResult
from confiture.core.hooks.context import ExecutionContext

PAGERDUTY_URL = "https://events.pagerduty.com/v2/enqueue"


class PagerDutyAlert(Hook[ExecutionContext]):
    def __init__(self, routing_key: str, environment: str = "production") -> None:
        super().__init__(hook_id="pagerduty.alert", name="PagerDuty", priority=8)
        self._routing_key = routing_key
        self._environment = environment

    async def execute(self, context: HookContext[ExecutionContext]) -> HookResult:
        data = context.get_data()
        name = data.metadata.get("migration_name")
        dedup_key = f"confiture-{name}"
        if data.metadata.get("success"):
            payload = {
                "routing_key": self._routing_key,
                "event_action": "resolve",
                "dedup_key": dedup_key,
            }
        else:
            payload = {
                "routing_key": self._routing_key,
                "event_action": "trigger",
                "dedup_key": dedup_key,
                "payload": {
                    "summary": f"Migration failed: {name}",
                    "severity": "critical",
                    "source": "confiture",
                    "custom_details": {
                        "migration": name,
                        "error": str(data.metadata.get("error"))[:1000],
                        "environment": self._environment,
                    },
                },
            }
        try:
            requests.post(PAGERDUTY_URL, json=payload, timeout=10)
        except requests.RequestException:
            pass
        return HookResult(success=True)
```

---

## Generic Webhooks

### Basic Webhook

```python
import requests

from confiture.core.hooks import Hook, HookContext, HookResult
from confiture.core.hooks.context import ExecutionContext


class WebhookNotify(Hook[ExecutionContext]):
    def __init__(self, webhook_url: str, environment: str = "production") -> None:
        super().__init__(hook_id="webhook.notify", name="Webhook", priority=7)
        self._url = webhook_url
        self._environment = environment

    async def execute(self, context: HookContext[ExecutionContext]) -> HookResult:
        data = context.get_data()
        payload = {
            "event": "migration.completed" if data.metadata.get("success")
            else "migration.failed",
            "timestamp": context.timestamp.isoformat(),
            "data": {
                "migration": data.metadata.get("migration_name"),
                "version": data.metadata.get("migration_version"),
                "environment": self._environment,
                "duration_ms": data.elapsed_time_ms,
            },
        }
        try:
            requests.post(self._url, json=payload, timeout=30)
        except requests.RequestException:
            pass
        return HookResult(success=True)
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

> There is no YAML webhook configuration — webhooks (and every integration on
> this page) are registered as hooks in Python via `Migrator.register_hook`.

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

Best-effort hooks should swallow their own errors and still return
`HookResult(success=True)` — a flaky webhook must not abort the migration:

```python
async def execute(self, context: HookContext[ExecutionContext]) -> HookResult:
    try:
        await send_notification(context)
    except Exception as exc:  # log, but don't fail the migration
        logging.getLogger(__name__).warning("notification failed: %s", exc)
    return HookResult(success=True)
```

(Conversely, a real post-condition check should return
`HookResult(success=False, error=...)` to stop the run.)

### 4. Filter by Environment

`ExecutionContext` carries no environment field — pass it to the hook's
constructor and branch on `self._environment`:

```python
def __init__(self, environment: str = "production") -> None:
    super().__init__(hook_id="notify", name="Notify", priority=7)
    self._environment = environment
    # ... in execute(): if self._environment != "production": return HookResult(success=True)
```

### 5. Deduplicate Alerts

```python
# Use a stable dedup key (the migration name from context metadata)
dedup_key = f"confiture-{context.get_data().metadata.get('migration_name')}"
```

---

## See Also

- [Hooks Guide](./hooks.md)
- [CLI Reference](../reference/cli.md)
- [Dry-Run Guide](./dry-run.md)
