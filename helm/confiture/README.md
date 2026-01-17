# Confiture Helm Chart

Helm chart for deploying Confiture PostgreSQL migrations in Kubernetes.

## Installation

```bash
# Add the Confiture Helm repository (when published)
helm repo add confiture https://charts.confiture.io
helm repo update

# Install with default values
helm install my-migrations confiture/confiture \
  --set database.existingSecret=my-db-secret

# Or install from local chart
helm install my-migrations ./helm/confiture \
  --set database.existingSecret=my-db-secret
```

## Quick Start

### Using an Existing Database Secret

```bash
# Create a secret with your DATABASE_URL
kubectl create secret generic db-credentials \
  --from-literal=DATABASE_URL="postgresql://user:pass@host:5432/db"

# Install Confiture
helm install migrations confiture/confiture \
  --set database.existingSecret=db-credentials
```

### Using Migrations from a ConfigMap

```bash
# Create ConfigMap from your migrations directory
kubectl create configmap my-migrations \
  --from-file=db/migrations/

# Install with migrations ConfigMap
helm install migrations confiture/confiture \
  --set database.existingSecret=db-credentials \
  --set migrations.configMap=my-migrations
```

## Configuration

### Image

| Parameter | Description | Default |
|-----------|-------------|---------|
| `image.repository` | Container image repository | `confiture/confiture` |
| `image.tag` | Container image tag | `""` (uses appVersion) |
| `image.pullPolicy` | Image pull policy | `IfNotPresent` |
| `imagePullSecrets` | Image pull secrets | `[]` |

### Migration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `migration.command` | Command to run | `["confiture", "migrate", "up"]` |
| `migration.lockTimeout` | Lock timeout in milliseconds | `30000` |
| `migration.verifyChecksums` | Verify migration checksums | `true` |
| `migration.extraArgs` | Additional arguments | `[]` |
| `migration.environment` | Environment name | `production` |

### Database

| Parameter | Description | Default |
|-----------|-------------|---------|
| `database.existingSecret` | Existing secret with DATABASE_URL | `""` |
| `database.existingSecretKey` | Key in existing secret | `DATABASE_URL` |
| `database.host` | Database host | `postgres` |
| `database.port` | Database port | `5432` |
| `database.name` | Database name | `mydb` |
| `database.user` | Database user | `postgres` |
| `database.passwordSecret` | Secret containing password | `""` |
| `database.passwordSecretKey` | Key in password secret | `password` |
| `database.sslMode` | SSL mode | `require` |

### Migrations Source

| Parameter | Description | Default |
|-----------|-------------|---------|
| `migrations.configMap` | ConfigMap containing migrations | `""` |
| `migrations.persistentVolumeClaim` | PVC containing migrations | `""` |
| `migrations.mountPath` | Mount path for migrations | `/app/db/migrations` |
| `migrations.schemaConfigMap` | ConfigMap for schema files | `""` |
| `migrations.schemaMountPath` | Mount path for schema | `/app/db/schema` |

### Job

| Parameter | Description | Default |
|-----------|-------------|---------|
| `job.backoffLimit` | Number of retries | `3` |
| `job.activeDeadlineSeconds` | Maximum job duration | `900` |
| `job.ttlSecondsAfterFinished` | Cleanup delay | `3600` |
| `job.annotations` | Additional annotations | `{}` |

### Hooks

| Parameter | Description | Default |
|-----------|-------------|---------|
| `hooks.enabled` | Run as Helm hook | `true` |
| `hooks.weight` | Hook weight | `"-5"` |
| `hooks.deletePolicy` | Hook delete policy | `before-hook-creation` |

### Service Account & RBAC

| Parameter | Description | Default |
|-----------|-------------|---------|
| `serviceAccount.create` | Create service account | `true` |
| `serviceAccount.name` | Service account name | `""` |
| `serviceAccount.annotations` | Service account annotations | `{}` |
| `rbac.create` | Create RBAC resources | `true` |

### Pod Configuration

| Parameter | Description | Default |
|-----------|-------------|---------|
| `podAnnotations` | Pod annotations | `{}` |
| `podLabels` | Pod labels | `{}` |
| `podSecurityContext` | Pod security context | See values.yaml |
| `securityContext` | Container security context | See values.yaml |
| `resources` | Resource limits/requests | See values.yaml |
| `nodeSelector` | Node selector | `{}` |
| `tolerations` | Tolerations | `[]` |
| `affinity` | Affinity rules | `{}` |

### Observability

| Parameter | Description | Default |
|-----------|-------------|---------|
| `observability.tracing.enabled` | Enable OpenTelemetry tracing | `false` |
| `observability.tracing.endpoint` | OTLP endpoint | `""` |
| `observability.metrics.enabled` | Enable Prometheus metrics | `false` |
| `observability.metrics.port` | Metrics port | `9090` |

## Usage Patterns

### 1. Helm Hook (Default)

By default, the chart runs as a Helm pre-install/pre-upgrade hook:

```bash
helm install myapp ./myapp-chart \
  --set confiture.database.existingSecret=db-creds
```

Migrations run automatically before your application deploys.

### 2. Init Container

Use Confiture as an init container in your application deployment:

```yaml
initContainers:
  - name: migrate
    image: confiture/confiture:0.5.0
    command: ["confiture", "migrate", "up"]
    env:
      - name: DATABASE_URL
        valueFrom:
          secretKeyRef:
            name: db-credentials
            key: DATABASE_URL
```

See `examples/init-container.yaml` for a complete example.

### 3. Standalone Job

Disable hooks to manage the job lifecycle yourself:

```bash
helm install migrations confiture/confiture \
  --set hooks.enabled=false \
  --set database.existingSecret=db-creds
```

### 4. ArgoCD Integration

Configure ArgoCD to run migrations before your application:

```yaml
metadata:
  annotations:
    argocd.argoproj.io/sync-wave: "-1"
```

See `examples/argocd-application.yaml` for a complete example.

## Security

The chart follows security best practices:

- **Non-root user**: Runs as UID 1000
- **Read-only filesystem**: Root filesystem is read-only
- **No privilege escalation**: Disabled by default
- **Minimal RBAC**: Only permissions needed for secrets/configmaps
- **No service account token**: automountServiceAccountToken is false

### Secret Management

For production, use one of these approaches:

1. **External Secrets Operator**:
   ```yaml
   database:
     existingSecret: my-external-secret
   ```

2. **Vault Agent Injector**:
   ```yaml
   podAnnotations:
     vault.hashicorp.com/agent-inject: "true"
     vault.hashicorp.com/agent-inject-secret-db: "secret/data/myapp/db"
   ```

3. **AWS Secrets Manager**:
   Use the Secrets Store CSI Driver with AWS provider.

## Troubleshooting

### Migration job fails

1. Check job status:
   ```bash
   kubectl describe job <release-name>-confiture
   ```

2. View logs:
   ```bash
   kubectl logs -l job-name=<release-name>-confiture
   ```

3. Common issues:
   - Database connection timeout: Increase `migration.lockTimeout`
   - Lock conflict: Another migration is running
   - Checksum mismatch: Migration file was modified

### Hook not running

If the hook isn't running during upgrade:

1. Verify hook annotations:
   ```bash
   kubectl get job -o yaml | grep helm.sh/hook
   ```

2. Check for previous hook:
   ```bash
   kubectl get jobs -l app.kubernetes.io/managed-by=Helm
   ```

3. Delete stale hooks:
   ```bash
   kubectl delete job <old-hook-job>
   ```

## Examples

See the `examples/` directory for:

- `init-container.yaml` - Using as init container
- `cronjob.yaml` - Scheduled drift detection
- `argocd-application.yaml` - ArgoCD integration

## License

MIT License - See [LICENSE](../../LICENSE) for details.
