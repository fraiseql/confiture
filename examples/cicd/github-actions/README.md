# GitHub Actions Templates for Confiture

Ready-to-use GitHub Actions workflows for automated migration management.

## Quick Start

```bash
# Copy workflows to your repository
cp migration-check.yml .github/workflows/
cp migration-deploy.yml .github/workflows/
```

## Workflows

### migration-check.yml

Runs on **pull requests** that modify migration or schema files.

**Jobs:**
1. **lint-migrations** - Validates migration syntax and best practices
2. **dry-run** - Tests migrations against a fresh PostgreSQL database
3. **schema-diff** - Checks for schema drift

**Triggers:**
- Pull requests modifying `db/migrations/**` or `db/schema/**`

### migration-deploy.yml

Runs on **pushes to main** that modify migration files.

**Jobs:**
1. **deploy-staging** - Deploys to staging with 30s lock timeout
2. **deploy-production** - Deploys to production (requires manual approval)
3. **rollback-on-failure** - Attempts automatic rollback if production fails

**Features:**
- Concurrency control (never cancels running migrations)
- Health checks before and after migration
- Slack notifications on success/failure
- Automatic rollback attempt on failure

## Required Secrets

Configure these in your repository settings (Settings → Secrets → Actions):

| Secret | Description |
|--------|-------------|
| `STAGING_DATABASE_URL` | PostgreSQL connection URL for staging |
| `PRODUCTION_DATABASE_URL` | PostgreSQL connection URL for production |
| `SLACK_WEBHOOK` | Slack incoming webhook URL for notifications |

## Required Environments

Configure environments (Settings → Environments):

### staging
- No required reviewers
- Deployment branches: `main`

### production
- Required reviewers: Add team members who must approve production deploys
- Deployment branches: `main`
- Wait timer (optional): Add delay before deployment

## Customization

### Different PostgreSQL Versions

Change the service image in `migration-check.yml`:

```yaml
services:
  postgres:
    image: postgres:16  # or postgres:14, postgres:13
```

### Additional Linting Rules

Add custom lint rules to `confiture.yaml`:

```yaml
lint:
  rules:
    require_down_migration: true
    max_migration_size: 10000
    naming_pattern: "^[0-9]{3}_[a-z_]+$"
```

### Custom Health Checks

Extend health checks in deploy workflow:

```yaml
- name: Application health check
  run: |
    curl --fail http://your-app/health || exit 1
```

### Different Notification Services

Replace Slack with Teams, Discord, or email:

```yaml
# Microsoft Teams
- name: Notify Teams
  run: |
    curl -H 'Content-Type: application/json' \
      -d '{"text": "Migration completed"}' \
      ${{ secrets.TEAMS_WEBHOOK }}
```

## Troubleshooting

### Migrations stuck in "pending"

1. Check if another workflow is running (concurrency lock)
2. Verify database connectivity
3. Check migration lock table: `SELECT * FROM confiture_locks`

### Dry run passes but deploy fails

Common causes:
- Different PostgreSQL versions between test and target
- Missing extensions in target database
- Data-dependent migration failures

### Rollback failed

Manual intervention required:
1. Connect to database directly
2. Check `confiture_migrations` table
3. Run rollback manually: `confiture migrate down --steps 1`
4. Fix root cause before re-running

## Best Practices

1. **Never cancel running migrations** - Use `cancel-in-progress: false`
2. **Test rollbacks** - Include rollback tests in PR checks
3. **Use lock timeouts** - Prevent migrations from hanging
4. **Monitor notifications** - Set up alerts for failures
5. **Review production deploys** - Require approvals for production
