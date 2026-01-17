# GitLab CI Template for Confiture

Ready-to-use GitLab CI/CD pipeline for automated migration management.

## Quick Start

```bash
# Copy configuration to your repository root
cp .gitlab-ci.yml /path/to/your/project/
```

## Pipeline Stages

### 1. lint
- **lint-migrations**: Validates migration syntax and checksums

### 2. test
- **dry-run-migrations**: Tests migrations against fresh PostgreSQL
- **schema-diff-check**: Detects schema drift (informational)

### 3. deploy-staging
- **deploy-staging**: Automatically deploys to staging on main branch

### 4. deploy-production
- **deploy-production**: Manual trigger required for production

## Required Variables

Configure in Settings → CI/CD → Variables:

| Variable | Description | Protected | Masked |
|----------|-------------|-----------|--------|
| `STAGING_DATABASE_URL` | PostgreSQL URL for staging | Yes | Yes |
| `PRODUCTION_DATABASE_URL` | PostgreSQL URL for production | Yes | Yes |
| `SLACK_WEBHOOK` | Slack webhook for notifications | Yes | Yes |

## Environment Configuration

Create environments in Deployments → Environments:

### staging
- Auto-deploy on merge to main
- No approval required

### production
- Manual trigger only
- Consider adding protected branch rules

## Scheduled Drift Detection

Set up scheduled pipelines (CI/CD → Schedules):

1. Create new schedule
2. Interval pattern: `0 */6 * * *` (every 6 hours)
3. Target branch: `main`
4. Variables: None needed (uses existing CI variables)

This runs the `drift-detection` job to alert on schema drift.

## Customization

### Different PostgreSQL Versions

```yaml
services:
  - name: postgres:16  # Change version here
    alias: postgres
```

### Custom Lock Timeout

```yaml
script:
  - confiture migrate up --lock-timeout 120000  # 2 minutes
```

### Additional Environments

```yaml
deploy-qa:
  extends: .migration-base
  stage: deploy-staging
  environment:
    name: qa
  variables:
    DATABASE_URL: ${QA_DATABASE_URL}
  rules:
    - if: $CI_COMMIT_BRANCH == "develop"
```

### Skip Migrations for Specific Commits

```yaml
rules:
  - if: $CI_COMMIT_MESSAGE =~ /\[skip-migrations\]/
    when: never
  - if: $CI_COMMIT_BRANCH == "main"
```

## Troubleshooting

### Pipeline stuck on production deploy

Production deploys require manual trigger - click "Play" button.

### Database connection timeout

1. Check variable is correctly set and masked
2. Verify network connectivity (firewall, VPN)
3. Increase timeout: `--lock-timeout 120000`

### Drift detection always failing

Drift detection compares current schema to DDL files:
1. Run `confiture build` to regenerate schema
2. Check if DDL files match actual schema
3. Consider ignoring specific objects in config

## Best Practices

1. **Use protected variables** for database URLs
2. **Mask sensitive variables** to prevent log exposure
3. **Set up environments** for deployment tracking
4. **Configure notifications** for failure alerts
5. **Schedule drift checks** to catch manual changes
