# Monitoring Integration Guide

**Monitor Confiture migrations with CloudWatch, Datadog, or Prometheus metrics and alerts**

---

## What is Monitoring Integration?

Monitoring integration enables Confiture to send migration metrics and events to your observability platform. This gives you visibility into migration performance, failures, and trends across all your databases.

**Tagline**: *Monitor migrations alongside your application metrics*

---

## Why Monitor Migrations?

### Common Use Cases

1. **Performance Tracking** - How long do migrations take?
2. **Failure Alerts** - Know immediately when migrations fail
3. **Trend Analysis** - Are migrations getting faster or slower?
4. **Capacity Planning** - When will your database hit limits?
5. **SLA Compliance** - Document migration history for audits

### Business Value

- ✅ **Faster incident response** (alerts within seconds)
- ✅ **Data-driven decisions** (see actual migration times)
- ✅ **Compliance documentation** (audit trail of all migrations)
- ✅ **Team visibility** (everyone sees migration progress)
- ✅ **Proactive maintenance** (catch issues before they're problems)

---

## When to Use Monitoring

### ✅ Perfect For

- **Production migrations** - Always monitor critical operations
- **Multi-environment deployments** - Compare staging vs production
- **SLA tracking** - Document compliance with agreements
- **Team dashboards** - Real-time visibility for teams
- **Historical analysis** - Understand trends over time

### ❌ Not For

- **Local development** - Overhead outweighs benefit
- **Ad-hoc testing** - One-time experiments don't need monitoring
- **Proof-of-concept work** - PoC projects are temporary

---

## Supported Monitoring Platforms

### Platform Comparison

| Platform | Metrics | Traces | Logs | Cost | Best For |
|----------|---------|--------|------|------|----------|
| **Prometheus** | ✅ | ❌ | Basic | Free | Self-hosted, Kubernetes |
| **Datadog** | ✅ | ✅ | ✅ | $15/host/mo | Comprehensive APM |
| **CloudWatch** | ✅ | ❌ | ✅ | Pay-per-metric | AWS shops |
| **New Relic** | ✅ | ✅ | ✅ | $100/mo base | Enterprise APM |
| **Grafana Cloud** | ✅ | ✅ | ✅ | Free-$300/mo | Observability suite |

---

## Setup Overview

### Requirements

- ✅ Confiture with hooks (Phase 4+)
- ✅ Access to monitoring platform
- ✅ API credentials for your platform
- ✅ Network access from your server

### Time Required

- **Basic setup**: 10-15 minutes
- **Custom metrics**: 15-20 minutes
- **Alerts configuration**: 10-15 minutes

---

## How Monitoring Works

### Metrics Architecture

```
Migration Execution
    ↓
Hook Triggers (post_execute, on_error)
    ↓
Metrics Collector
    ├─ Duration: 2.34 seconds
    ├─ Rows affected: 50,000
    ├─ Status: success
    └─ Environment: production
    ↓
Send to Platform (CloudWatch, Datadog, etc)
    ↓
Dashboards & Alerts
```

### Key Metrics

1. **Duration** - How long did the migration take?
2. **Rows Affected** - How many rows were modified?
3. **Status** - Did the migration succeed or fail?
4. **Risk Level** - Was this low, medium, or high risk?
5. **Timestamp** - When did this happen?

---

## Prometheus Integration

Prometheus is a popular open-source monitoring platform. Perfect for self-hosted setups.

### Setup Prometheus

```bash
# 1. Install Prometheus
docker run -d \
  -p 9090:9090 \
  -v $(pwd)/prometheus.yml:/etc/prometheus/prometheus.yml \
  prom/prometheus

# 2. Verify Prometheus is running
curl http://localhost:9090
```

**prometheus.yml** configuration:
```yaml
# prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'confiture'
    static_configs:
      - targets: ['localhost:8000']  # Your metrics endpoint
```

### Export Metrics to Prometheus

```python
# confiture_hooks/monitoring.py
from prometheus_client import Counter, Histogram, Gauge, generate_latest
from confiture.hooks import register_hook, HookContext
import time

# Define metrics
migration_duration = Histogram(
    'confiture_migration_duration_seconds',
    'Migration execution time in seconds',
    buckets=(0.1, 0.5, 1, 5, 10, 30, 60, 300)
)

migration_rows_affected = Gauge(
    'confiture_migration_rows_affected',
    'Number of rows affected by migration',
    labelnames=['migration', 'environment']
)

migration_errors = Counter(
    'confiture_migration_errors_total',
    'Total number of failed migrations',
    labelnames=['migration', 'error_type']
)

migration_successes = Counter(
    'confiture_migration_successes_total',
    'Total number of successful migrations',
    labelnames=['migration', 'environment']
)

@register_hook('post_execute')
def prometheus_metrics(context: HookContext) -> None:
    """Collect metrics after successful migration."""
    # Record duration
    duration_seconds = context.duration.total_seconds()
    migration_duration.observe(duration_seconds)

    # Record rows affected
    if context.rows_affected:
        migration_rows_affected.labels(
            migration=context.migration_name,
            environment=context.environment
        ).set(context.rows_affected)

    # Record success
    migration_successes.labels(
        migration=context.migration_name,
        environment=context.environment
    ).inc()

    print(f"✅ Prometheus metrics recorded")

@register_hook('on_error')
def prometheus_error_metrics(context: HookContext) -> None:
    """Record failed migrations."""
    error_type = type(context.error).__name__
    migration_errors.labels(
        migration=context.migration_name,
        error_type=error_type
    ).inc()

    print(f"❌ Error recorded: {error_type}")

# Metrics endpoint
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/metrics':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(generate_latest())
        else:
            self.send_response(404)
            self.end_headers()

def start_metrics_server(port=8000):
    """Start Prometheus metrics server."""
    server = HTTPServer(('0.0.0.0', port), MetricsHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    print(f"📊 Prometheus metrics server running on port {port}")
```

**Output**:
```
# HELP confiture_migration_duration_seconds Migration execution time in seconds
# TYPE confiture_migration_duration_seconds histogram
confiture_migration_duration_seconds_bucket{le="0.1"} 0.0
confiture_migration_duration_seconds_bucket{le="0.5"} 1.0
confiture_migration_duration_seconds_bucket{le="1.0"} 2.0
confiture_migration_duration_seconds_bucket{le="5.0"} 5.0
confiture_migration_duration_seconds_bucket{le="+Inf"} 5.0
confiture_migration_duration_seconds_sum 8.34
confiture_migration_duration_seconds_count 5.0

# HELP confiture_migration_rows_affected Number of rows affected by migration
# TYPE confiture_migration_rows_affected gauge
confiture_migration_rows_affected{environment="production",migration="005_add_payment_table"} 50000.0

# HELP confiture_migration_errors_total Total number of failed migrations
# TYPE confiture_migration_errors_total counter
confiture_migration_errors_total{error_type="DatabaseError",migration="004_add_user_bios"} 1.0

# HELP confiture_migration_successes_total Total number of successful migrations
# TYPE confiture_migration_successes_total counter
confiture_migration_successes_total{environment="production",migration="005_add_payment_table"} 1.0
```

**Explanation**: Prometheus stores time-series metrics that can be queried and graphed in Grafana.

---

## Datadog Integration

Datadog is a comprehensive monitoring platform with built-in APM, logs, and traces.

### Send Metrics to Datadog

```python
# confiture_hooks/datadog_monitoring.py
import os
from datadog import initialize, api
from confiture.hooks import register_hook, HookContext
from datetime import datetime

# Initialize Datadog
options = {
    'api_key': os.environ.get('DATADOG_API_KEY'),
    'app_key': os.environ.get('DATADOG_APP_KEY'),
    'api_host': 'https://api.datadoghq.com',
}
initialize(**options)

@register_hook('post_execute')
def send_datadog_metrics(context: HookContext) -> None:
    """Send migration metrics to Datadog."""
    timestamp = int(datetime.now().timestamp())

    # Prepare metrics
    metrics = [
        {
            'metric': 'confiture.migration.duration',
            'points': [(timestamp, context.duration.total_seconds())],
            'type': 'gauge',
            'tags': [
                f'migration:{context.migration_name}',
                f'environment:{context.environment}',
                'status:success'
            ]
        },
        {
            'metric': 'confiture.migration.rows_affected',
            'points': [(timestamp, context.rows_affected or 0)],
            'type': 'gauge',
            'tags': [
                f'migration:{context.migration_name}',
                f'environment:{context.environment}'
            ]
        }
    ]

    # Send to Datadog
    try:
        api.Metric.send(
            metric=metrics[0]['metric'],
            points=metrics[0]['points'],
            type=metrics[0]['type'],
            tags=metrics[0]['tags']
        )
        api.Metric.send(
            metric=metrics[1]['metric'],
            points=metrics[1]['points'],
            type=metrics[1]['type'],
            tags=metrics[1]['tags']
        )

        # Also send event
        api.Event.create(
            title=f"✅ Migration {context.migration_name} completed",
            text=f"Duration: {context.duration.total_seconds():.2f}s\nRows: {context.rows_affected}",
            tags=[f'migration:{context.migration_name}', f'env:{context.environment}'],
            alert_type='success'
        )

        print("📊 Datadog metrics sent")
    except Exception as e:
        print(f"⚠️ Failed to send Datadog metrics: {e}")

@register_hook('on_error')
def send_datadog_error(context: HookContext) -> None:
    """Send error events to Datadog."""
    try:
        api.Event.create(
            title=f"❌ Migration {context.migration_name} failed",
            text=f"Error: {str(context.error)}",
            tags=[f'migration:{context.migration_name}', f'env:{context.environment}'],
            alert_type='error'
        )

        # Send error metric
        timestamp = int(datetime.now().timestamp())
        api.Metric.send(
            metric='confiture.migration.errors',
            points=[(timestamp, 1)],
            type='count',
            tags=[
                f'migration:{context.migration_name}',
                f'error_type:{type(context.error).__name__}'
            ]
        )

        print("📊 Datadog error sent")
    except Exception as e:
        print(f"⚠️ Failed to send error to Datadog: {e}")
```

**Setup**:
```bash
# Install Datadog Python client
pip install datadog

# Set environment variables
export DATADOG_API_KEY="your_api_key"
export DATADOG_APP_KEY="your_app_key"
```

**Output**:
```
📊 Datadog metrics sent
📊 Datadog error sent
```

---

## CloudWatch Integration

AWS CloudWatch is built into AWS and works well for AWS-hosted databases.

### Send Metrics to CloudWatch

```python
# confiture_hooks/cloudwatch_monitoring.py
import os
import boto3
from confiture.hooks import register_hook, HookContext
from datetime import datetime

# Initialize CloudWatch
cloudwatch = boto3.client(
    'cloudwatch',
    region_name=os.environ.get('AWS_REGION', 'us-east-1')
)

@register_hook('post_execute')
def send_cloudwatch_metrics(context: HookContext) -> None:
    """Send migration metrics to CloudWatch."""
    try:
        cloudwatch.put_metric_data(
            Namespace='Confiture',
            MetricData=[
                {
                    'MetricName': 'MigrationDuration',
                    'Value': context.duration.total_seconds(),
                    'Unit': 'Seconds',
                    'Timestamp': datetime.utcnow(),
                    'Dimensions': [
                        {'Name': 'Migration', 'Value': context.migration_name},
                        {'Name': 'Environment', 'Value': context.environment}
                    ]
                },
                {
                    'MetricName': 'RowsAffected',
                    'Value': context.rows_affected or 0,
                    'Unit': 'Count',
                    'Timestamp': datetime.utcnow(),
                    'Dimensions': [
                        {'Name': 'Migration', 'Value': context.migration_name},
                        {'Name': 'Environment', 'Value': context.environment}
                    ]
                },
                {
                    'MetricName': 'MigrationSuccess',
                    'Value': 1,
                    'Unit': 'Count',
                    'Timestamp': datetime.utcnow(),
                    'Dimensions': [
                        {'Name': 'Environment', 'Value': context.environment}
                    ]
                }
            ]
        )
        print("📊 CloudWatch metrics sent")
    except Exception as e:
        print(f"⚠️ Failed to send CloudWatch metrics: {e}")

@register_hook('on_error')
def send_cloudwatch_error(context: HookContext) -> None:
    """Send error metric to CloudWatch."""
    try:
        cloudwatch.put_metric_data(
            Namespace='Confiture',
            MetricData=[
                {
                    'MetricName': 'MigrationErrors',
                    'Value': 1,
                    'Unit': 'Count',
                    'Timestamp': datetime.utcnow(),
                    'Dimensions': [
                        {'Name': 'Migration', 'Value': context.migration_name},
                        {'Name': 'ErrorType', 'Value': type(context.error).__name__},
                        {'Name': 'Environment', 'Value': context.environment}
                    ]
                }
            ]
        )
        print("📊 CloudWatch error sent")
    except Exception as e:
        print(f"⚠️ Failed to send error to CloudWatch: {e}")
```

**Setup**:
```bash
# Install AWS SDK
pip install boto3

# Configure AWS credentials
export AWS_ACCESS_KEY_ID="your_access_key"
export AWS_SECRET_ACCESS_KEY="your_secret_key"
export AWS_REGION="us-east-1"
```

---

## Creating Dashboards

### Prometheus/Grafana Dashboard

Create a Grafana dashboard to visualize migration metrics:

```json
{
  "dashboard": {
    "title": "Confiture Migrations",
    "panels": [
      {
        "title": "Migration Duration",
        "targets": [
          {
            "expr": "rate(confiture_migration_duration_seconds_sum[1m]) / rate(confiture_migration_duration_seconds_count[1m])",
            "refId": "A"
          }
        ],
        "type": "graph"
      },
      {
        "title": "Successful Migrations",
        "targets": [
          {
            "expr": "rate(confiture_migration_successes_total[5m])",
            "refId": "A"
          }
        ],
        "type": "stat"
      },
      {
        "title": "Failed Migrations",
        "targets": [
          {
            "expr": "rate(confiture_migration_errors_total[5m])",
            "refId": "A"
          }
        ],
        "type": "stat"
      },
      {
        "title": "Rows Affected Over Time",
        "targets": [
          {
            "expr": "confiture_migration_rows_affected",
            "refId": "A"
          }
        ],
        "type": "graph"
      }
    ]
  }
}
```

---

## Setting Up Alerts

### Prometheus Alert Rules

```yaml
# prometheus-rules.yml
groups:
  - name: confiture
    rules:
      - alert: MigrationFailed
        expr: increase(confiture_migration_errors_total[5m]) > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Migration failed"
          description: "{{ $labels.migration }} failed in {{ $labels.environment }}"

      - alert: MigrationSlow
        expr: |
          histogram_quantile(0.95, rate(confiture_migration_duration_seconds_bucket[5m])) > 60
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Migration taking longer than expected"
          description: "95th percentile: {{ $value }}s"

      - alert: MigrationLargRowCount
        expr: confiture_migration_rows_affected > 1000000
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Large number of rows affected"
          description: "{{ $value }} rows affected by {{ $labels.migration }}"
```

### Datadog Alert Example

```python
# Create alert programmatically
api.Monitor.create(
    type='metric alert',
    query='avg(last_5m):avg:confiture.migration.duration{*} > 60',
    name='Migration Duration Alert',
    message='Migration took longer than 60 seconds. @slack-devops-alerts',
    tags=['confiture', 'production']
)
```

---

## Best Practices

### ✅ Do's

1. **Record all migrations**
   ```python
   @register_hook('post_execute')
   def record_metric(context: HookContext) -> None:
       # Always record successful migrations
       metrics.record('migration.success', 1, tags={...})
   ```

2. **Include rich context**
   ```python
   metrics.record('migration.duration', duration, tags={
       'migration': context.migration_name,
       'environment': context.environment,
       'status': 'success'
   })
   ```

3. **Alert on failures**
   ```python
   @register_hook('on_error')
   def alert_on_failure(context: HookContext) -> None:
       send_alert(f"Migration {context.migration_name} failed")
   ```

4. **Use meaningful metric names**
   ```python
   # Good
   confiture_migration_duration_seconds

   # Bad
   duration
   ```

### ❌ Don'ts

1. **Don't log passwords or secrets**
   ```python
   # Bad: Logs credentials
   print(f"Connecting to {context.database_url}")

   # Good: Redacts credentials
   print(f"Connecting to database")
   ```

2. **Don't send sensitive data to external services**
   ```python
   # Bad: Sends full error with query
   send_metric('error', str(context.error))

   # Good: Sends only error type
   send_metric('error', type(context.error).__name__)
   ```

3. **Don't slow down migrations with monitoring**
   ```python
   # Bad: Blocks migration on slow API
   requests.post('https://slow-api.example.com', timeout=30)

   # Good: Non-blocking with timeout
   try:
       send_metric(...)
   except timeout:
       pass  # Don't block migration
   ```

---

## Troubleshooting

### ❌ Error: "Failed to authenticate with monitoring service"

**Cause**: API credentials are invalid or expired

**Solution**:
```bash
# Verify credentials are correct
echo $DATADOG_API_KEY
echo $AWS_ACCESS_KEY_ID

# Test connection manually
curl -H "DD-API-KEY: $DATADOG_API_KEY" https://api.datadoghq.com/api/v1/validate
```

---

### ❌ Error: "Metrics not appearing in dashboard"

**Cause**: Metrics are being sent to wrong namespace or with wrong tags

**Solution**:
```python
# Add debug logging
@register_hook('post_execute')
def debug_metrics(context: HookContext) -> None:
    print(f"Recording metric: confiture.migration.duration = {context.duration.total_seconds()}")
    print(f"Tags: migration={context.migration_name}, env={context.environment}")
    # Send metric...
```

---

### ❌ Error: "Alert firing but migration succeeded"

**Cause**: Alert threshold is too sensitive or query is incorrect

**Solution**:
```yaml
# Adjust alert threshold
- alert: MigrationSlow
  expr: |
    histogram_quantile(0.95, rate(confiture_migration_duration_seconds_bucket[5m])) > 120
  # Changed threshold from 60 to 120 seconds
```

---

## See Also

- [Slack Integration](./slack-integration.md) - Notify team of migration status
- [GitHub Actions Workflow](./github-actions-workflow.md) - Run migrations in CI/CD
- [Prometheus Documentation](https://prometheus.io/docs/) - Official Prometheus docs
- [Datadog Documentation](https://docs.datadoghq.com/) - Official Datadog docs
- [Hook API Reference](../api/hooks.md) - Custom migration logic

---

## 🎯 Next Steps

**Ready to monitor migrations?**
- ✅ You now understand: Metrics, dashboards, alerts, monitoring platforms

**What to do next:**

1. **[Choose a monitoring platform](./monitoring-integration.md#supported-monitoring-platforms)** - Pick Prometheus, Datadog, or CloudWatch
2. **[Set up hooks](../api/hooks.md)** - Copy metrics code and register hooks
3. **[Create dashboards](#creating-dashboards)** - Visualize your migration metrics
4. **[Configure alerts](#setting-up-alerts)** - Get notified when things go wrong

---

**Last Updated**: January 9, 2026
**Status**: Production Ready ✅
**Tested On**: Prometheus 2.40+, Datadog US/EU, AWS CloudWatch

🍓 Monitor your migrations with confidence
