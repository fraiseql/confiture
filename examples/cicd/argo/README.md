# Argo Workflows Templates for Confiture

Kubernetes-native migration workflows using Argo Workflows.

## Quick Start

```bash
# Install Argo Workflows (if not already installed)
kubectl create namespace argo
kubectl apply -n argo -f https://github.com/argoproj/argo-workflows/releases/download/v3.5.0/install.yaml

# Create migrations namespace
kubectl create namespace migrations

# Create secrets
kubectl create secret generic db-credentials \
  --namespace migrations \
  --from-literal=test-url="postgresql://user:pass@test-db:5432/app" \
  --from-literal=staging-url="postgresql://user:pass@staging-db:5432/app" \
  --from-literal=production-url="postgresql://user:pass@prod-db:5432/app"

# Apply workflow templates
kubectl apply -f migration-workflow.yaml
```

## Components

### WorkflowTemplate
Reusable templates for common migration operations:
- `lint-migrations` - Validate migration syntax
- `dry-run-migration` - Test migrations without applying
- `deploy-migration` - Apply migrations with health checks
- `rollback-migration` - Rollback specified number of migrations

### Workflow
Main migration pipeline with DAG steps:
1. Clone repository
2. Lint migrations
3. Dry run against test database
4. Deploy to target environment

### CronWorkflow
Scheduled drift detection running every 6 hours.

### EventSource & Sensor
GitOps integration for automatic workflow triggering on Git push.

## Required Secrets

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: db-credentials
  namespace: migrations
type: Opaque
stringData:
  test-url: "postgresql://user:pass@test-db:5432/app"
  staging-url: "postgresql://user:pass@staging-db:5432/app"
  production-url: "postgresql://user:pass@prod-db:5432/app"
```

## Running Workflows

### Manual Trigger

```bash
# Submit workflow with default parameters
argo submit -n migrations migration-workflow.yaml

# Submit with custom parameters
argo submit -n migrations migration-workflow.yaml \
  -p git-repo=https://github.com/your-org/your-app.git \
  -p git-branch=feature/new-migration \
  -p environment=staging

# Watch workflow progress
argo watch -n migrations @latest

# Get workflow logs
argo logs -n migrations @latest
```

### GitOps Trigger

Configure webhook in your Git provider:
- URL: `http://<argo-events-service>:12000/migrations`
- Content type: `application/json`
- Events: Push events

## Customization

### Different PostgreSQL Image

```yaml
container:
  image: postgres:16-alpine  # Include psql for debugging
```

### Custom Resource Limits

```yaml
resources:
  requests:
    memory: "512Mi"
    cpu: "200m"
  limits:
    memory: "1Gi"
    cpu: "1"
```

### Add Slack Notifications

```yaml
- name: notify-slack
  container:
    image: curlimages/curl:latest
    command: ["/bin/sh", "-c"]
    args:
      - |
        curl -X POST $SLACK_WEBHOOK \
          -H 'Content-Type: application/json' \
          -d '{"text":"Migration completed successfully"}'
    env:
      - name: SLACK_WEBHOOK
        valueFrom:
          secretKeyRef:
            name: slack-credentials
            key: webhook-url
```

### Multi-Environment Pipeline

```yaml
dag:
  tasks:
    - name: deploy-staging
      template: deploy-migration
      arguments:
        parameters:
          - name: database-key
            value: "staging-url"
          - name: environment
            value: "staging"

    - name: wait-for-approval
      template: approval
      dependencies: [deploy-staging]

    - name: deploy-production
      template: deploy-migration
      dependencies: [wait-for-approval]
      arguments:
        parameters:
          - name: database-key
            value: "production-url"
          - name: environment
            value: "production"
```

## Service Account Setup

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: argo-workflow
  namespace: migrations

---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: argo-workflow-role
  namespace: migrations
rules:
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get"]
  - apiGroups: [""]
    resources: ["pods", "pods/log"]
    verbs: ["get", "list", "watch"]

---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: argo-workflow-binding
  namespace: migrations
subjects:
  - kind: ServiceAccount
    name: argo-workflow
    namespace: migrations
roleRef:
  kind: Role
  name: argo-workflow-role
  apiGroup: rbac.authorization.k8s.io
```

## Troubleshooting

### Workflow stuck in Pending

1. Check service account permissions
2. Verify secrets exist: `kubectl get secrets -n migrations`
3. Check pod events: `kubectl describe pod <pod-name> -n migrations`

### Database connection failed

1. Verify secret values are correct
2. Check network policies allow connection
3. Test connectivity: `kubectl run -it --rm pg-test --image=postgres:15 -- psql $DATABASE_URL`

### Artifact storage errors

Configure artifact repository:
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: artifact-repositories
  namespace: migrations
data:
  default-v1: |
    archiveLogs: true
    s3:
      bucket: argo-artifacts
      endpoint: minio:9000
      insecure: true
      accessKeySecret:
        name: minio-credentials
        key: accesskey
      secretKeySecret:
        name: minio-credentials
        key: secretkey
```

## Best Practices

1. **Use WorkflowTemplates** for reusable components
2. **Set resource limits** to prevent resource exhaustion
3. **Configure retries** for transient failures
4. **Use DAG** for complex dependencies
5. **Enable archiving** for audit trail
6. **Set up monitoring** with Prometheus metrics
