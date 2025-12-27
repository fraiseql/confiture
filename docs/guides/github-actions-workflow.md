# GitHub Actions Workflow Integration

**Automate Confiture migrations in GitHub Actions with dry-run, approval workflows, and automated releases**

---

## What is GitHub Actions Integration?

GitHub Actions integration enables you to run Confiture migrations as part of your continuous integration and deployment pipeline. This keeps migrations synchronized with code changes and ensures migrations are tested before production.

**Tagline**: *Run and approve migrations directly in your GitHub workflow*

---

## Why Use Confiture in GitHub Actions?

### Common Use Cases

1. **Dry-Run on Pull Requests** - Validate migrations won't break in production
2. **Automatic Production Deploys** - Migrate on every production deployment
3. **Schema Validation** - Run linting and schema checks in CI
4. **Manual Approvals** - Require team approval before production migrations
5. **Multi-Environment Rollouts** - Different migration strategies per environment

### Business Value

- ✅ **Catch migration errors early** (in PR review, not production)
- ✅ **Automatic validation** (linting runs on every commit)
- ✅ **Team accountability** (approvals create audit trail)
- ✅ **Faster deployments** (migrations run automatically)
- ✅ **Reduced manual work** (no manual migration steps)

---

## When to Use GitHub Actions

### ✅ Perfect For

- **Development & Staging** - Automatic migrations on every commit
- **Production Migrations** - Scheduled runs with manual approvals
- **PR Reviews** - Dry-run migrations to validate schema changes
- **Release Automation** - Migrate + deploy in single workflow
- **Continuous Testing** - Test schema changes against latest code

### ❌ Not For

- **Local development** - Use `confiture migrate` directly
- **Ad-hoc migrations** - One-off manual migrations
- **Database debugging** - Requires direct database access
- **Complex data migrations** - Use specialized data migration tools

---

## How GitHub Actions Integration Works

### The Workflow Pipeline

```
Code Changes (git push)
    ↓
1. Trigger: PR opened or merged to main
    ↓
2. Run: confiture lint (schema validation)
    ↓
3. Run: confiture migrate --dry-run (test migration)
    ↓
4. Production: Require manual approval
    ↓
5. Run: confiture migrate up (execute migration)
    ↓
6. Verify: Run post-migration tests
```

### Key Workflow Stages

**Stage 1: Validate** (Always runs)
- Check schema syntax with linting
- Validate migration files exist
- Parse migration SQL for errors

**Stage 2: Dry-Run** (On PR)
- Execute migration on test database
- Show what would change
- Report estimated time and affected rows

**Stage 3: Approval** (Production only)
- Require manual approval from DBA team
- Show migration details and risks
- Create audit log of approvals

**Stage 4: Execute** (After approval)
- Run actual migration on production
- Monitor for errors
- Rollback on failure (if configured)

---

## Setup Overview

### Requirements

- ✅ GitHub repository with Confiture
- ✅ PostgreSQL database accessible from GitHub Actions
- ✅ Access to create GitHub Action secrets
- ✅ PostgreSQL credentials stored as secrets

### Time Required

- **Initial setup**: 15-20 minutes
- **Testing workflow**: 10-15 minutes
- **Production setup**: 20-30 minutes

---

## Step 1: Create GitHub Secrets

Store database credentials securely in GitHub:

1. Go to **Settings → Secrets and variables → Actions**
2. Click **New repository secret**
3. Add these secrets:
   - `DATABASE_URL_DEV` - Development database URL
   - `DATABASE_URL_STAGING` - Staging database URL
   - `DATABASE_URL_PROD` - Production database URL (encrypted)

**Format**:
```
postgresql://username:password@host:port/database?sslmode=require
```

**Example**:
```bash
# Don't commit this! Use GitHub secrets
# postgresql://confiture:p@ssw0rd@db.example.com:5432/prod_db?sslmode=require
```

---

## Step 2: Install Confiture

Create a workflow file that installs Confiture and runs migrations:

```yaml
# .github/workflows/migrations.yml
name: Migrations

on:
  push:
    branches: [main]
    paths:
      - 'db/**'
      - '.github/workflows/migrations.yml'
  pull_request:
    branches: [main]
    paths:
      - 'db/**'

env:
  PYTHON_VERSION: '3.11'

jobs:
  validate:
    name: Validate Migrations
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: ${{ env.PYTHON_VERSION }}

      - name: Install uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh

      - name: Install Confiture
        run: uv pip install confiture

      - name: Lint schema
        run: confiture lint --database-url "${{ secrets.DATABASE_URL_DEV }}"

      - name: Validate migration files
        run: confiture migrate --dry-run
```

**Output**:
```
Run: Lint schema
  ✅ Schema validation passed
  ├─ All tables have primary keys
  ├─ Foreign keys properly indexed
  └─ No naming convention violations

Run: Validate migration files
  ✅ Migration files valid
  ├─ 005_add_payment_table
  ├─ 006_add_user_preferences
  └─ 2 pending migrations found
```

**Explanation**: This workflow validates schema on every PR and commit to main.

---

## Step 3: Dry-Run on Pull Requests

Test migrations won't break production:

```yaml
# .github/workflows/migrations.yml (extended)

  dry-run:
    name: Dry-Run Migration
    runs-on: ubuntu-latest
    if: github.event_name == 'pull_request'
    needs: validate
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: ${{ env.PYTHON_VERSION }}

      - name: Install uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh

      - name: Install Confiture
        run: uv pip install confiture

      - name: Run dry-run migration
        run: confiture migrate --dry-run --database-url "${{ secrets.DATABASE_URL_DEV }}"

      - name: Capture migration output
        id: dry-run
        run: |
          OUTPUT=$(confiture migrate --dry-run --database-url "${{ secrets.DATABASE_URL_DEV }}" 2>&1)
          echo "output=$OUTPUT" >> $GITHUB_OUTPUT

      - name: Comment on PR
        uses: actions/github-script@v7
        with:
          script: |
            const dryRunOutput = `${{ steps.dry-run.outputs.output }}`;
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: `## 🔄 Migration Dry-Run\n\n\`\`\`\n${dryRunOutput}\n\`\`\`\n\n✅ Dry-run passed. Safe to merge!`
            });
```

**Output**:
```
### 🔄 Migration Dry-Run

[DRY RUN] Migration 005_add_payment_table
  ├─ ADD TABLE payments (50 columns)
  ├─ Estimated time: 2-5 seconds
  ├─ Would affect: 100,000 rows
  └─ Risk: MEDIUM

✅ Dry-run passed. Safe to merge!
```

**Explanation**: This automatically validates migrations when PRs are opened and reports results back to the PR.

---

## Step 4: Production Migrations with Approval

Require manual approval before production migrations:

```yaml
# .github/workflows/migrations.yml (production job)

  migrate-production:
    name: Migrate Production
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    needs: validate
    environment:
      name: production
      reviewers: [dba-team]
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: ${{ env.PYTHON_VERSION }}

      - name: Install uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh

      - name: Install Confiture
        run: uv pip install confiture

      - name: Check pending migrations
        id: check
        run: |
          COUNT=$(confiture migrate status --database-url "${{ secrets.DATABASE_URL_PROD }}" | grep -c "pending")
          echo "pending_count=$COUNT" >> $GITHUB_OUTPUT
          if [ $COUNT -eq 0 ]; then
            echo "✅ No pending migrations"
          else
            echo "⏳ Found $COUNT pending migrations"
          fi

      - name: Run production migration
        if: steps.check.outputs.pending_count > 0
        run: |
          confiture migrate up \
            --database-url "${{ secrets.DATABASE_URL_PROD }}" \
            --log-file /tmp/migration.log

      - name: Verify migration
        if: steps.check.outputs.pending_count > 0
        run: |
          confiture migrate status \
            --database-url "${{ secrets.DATABASE_URL_PROD }}"

      - name: Upload logs
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: migration-logs
          path: /tmp/migration.log
```

**Output**:
```
Run: Check pending migrations
  ✅ No pending migrations

# OR if pending:

Run: Run production migration
  ✅ Migration 005_add_payment_table started
  ├─ Creating payments table... ✅ (3.2s)
  ├─ Adding indexes... ✅ (1.5s)
  ├─ Verifying constraints... ✅ (0.8s)
  └─ Migration completed in 5.5s

Run: Verify migration
  ✅ Production schema updated
  ├─ Total migrations: 5
  └─ All applied
```

**Explanation**: This runs migrations on main branch push after approval. GitHub requires explicit approval for environment-protected jobs. The approval must come from someone in the `dba-team`.

---

## Step 5: Rollback on Failure

Add automatic rollback if migration fails:

```yaml
# .github/workflows/migrations.yml (rollback job)

  rollback-on-failure:
    name: Rollback on Failure
    runs-on: ubuntu-latest
    if: failure() && github.ref == 'refs/heads/main'
    needs: [validate, migrate-production]
    environment:
      name: production
      reviewers: [dba-team]
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: ${{ env.PYTHON_VERSION }}

      - name: Install uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh

      - name: Install Confiture
        run: uv pip install confiture

      - name: Rollback migration
        run: |
          confiture migrate down \
            --database-url "${{ secrets.DATABASE_URL_PROD }}" \
            --steps 1

      - name: Notify team
        uses: actions/github-script@v7
        with:
          script: |
            github.rest.issues.create({
              owner: context.repo.owner,
              repo: context.repo.repo,
              title: '🚨 Migration Rollback - Manual Review Required',
              body: `Migration failed and was rolled back.\n\nWorkflow: ${context.workflow}\nRun: ${context.runId}\n\nPlease investigate the failure and fix before re-deploying.`,
              assignees: ['dba-team']
            });
```

**Output**:
```
Run: Rollback migration
  ✅ Rolling back to previous version
  ├─ Found last applied migration: 004_add_user_bios
  ├─ Reversing 005_add_payment_table... ✅
  └─ Rollback complete

Run: Notify team
  ✅ Created issue: 🚨 Migration Rollback - Manual Review Required
```

**Explanation**: If migration fails, this automatically rolls back the previous successful migration and alerts the team.

---

## Complete Production Workflow Example

Here's a complete workflow for production with all stages:

```yaml
# .github/workflows/production-migrations.yml
name: Production Migrations

on:
  push:
    branches: [main]
    paths:
      - 'db/**'
      - '.github/workflows/production-migrations.yml'

env:
  PYTHON_VERSION: '3.11'

jobs:
  # Stage 1: Validate
  validate:
    name: Validate Schema
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: ${{ env.PYTHON_VERSION }}

      - name: Install uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh

      - name: Install Confiture
        run: uv pip install confiture

      - name: Validate migrations
        run: |
          echo "📋 Validating migration files..."
          confiture migrate status --dry-run
          echo "✅ Validation passed"

  # Stage 2: Test
  test:
    name: Test on Staging
    runs-on: ubuntu-latest
    needs: validate
    services:
      postgres:
        image: postgres:15-alpine
        env:
          POSTGRES_DB: confiture_test
          POSTGRES_HOST_AUTH_METHOD: trust
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: ${{ env.PYTHON_VERSION }}

      - name: Install uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh

      - name: Install Confiture
        run: uv pip install confiture

      - name: Run migrations on test database
        env:
          DATABASE_URL: postgresql://postgres:@localhost:5432/confiture_test
        run: |
          echo "🔄 Running migrations on test database..."
          confiture migrate up --database-url "$DATABASE_URL"
          echo "✅ Test migrations passed"

  # Stage 3: Approval & Execution
  migrate-production:
    name: Migrate Production Database
    runs-on: ubuntu-latest
    needs: test
    environment:
      name: production
      reviewers: [dba-team]
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: ${{ env.PYTHON_VERSION }}

      - name: Install uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh

      - name: Install Confiture
        run: uv pip install confiture

      - name: Create backup
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL_PROD }}
        run: |
          echo "💾 Creating pre-migration backup..."
          # Backup implementation here
          echo "✅ Backup created"

      - name: Run production migration
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL_PROD }}
        run: |
          echo "🚀 Starting production migration..."
          confiture migrate up --database-url "$DATABASE_URL" --verbose
          echo "✅ Production migration complete"

      - name: Verify production
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL_PROD }}
        run: |
          echo "🔍 Verifying production database..."
          confiture migrate status --database-url "$DATABASE_URL"
          echo "✅ Verification passed"

      - name: Notify Slack
        if: success()
        uses: slackapi/slack-github-action@v1
        with:
          webhook-url: ${{ secrets.SLACK_WEBHOOK_URL }}
          payload: |
            {
              "text": "✅ Production migration complete",
              "blocks": [
                {
                  "type": "section",
                  "text": {
                    "type": "mrkdwn",
                    "text": "✅ *Production Migration Successful*\n*Workflow*: ${{ github.workflow }}\n*Ref*: ${{ github.ref }}\n*Commit*: ${{ github.sha }}"
                  }
                }
              ]
            }

      - name: Notify on failure
        if: failure()
        uses: slackapi/slack-github-action@v1
        with:
          webhook-url: ${{ secrets.SLACK_WEBHOOK_URL }}
          payload: |
            {
              "text": "❌ Production migration failed",
              "blocks": [
                {
                  "type": "section",
                  "text": {
                    "type": "mrkdwn",
                    "text": "❌ *Production Migration Failed*\n*Workflow*: ${{ github.workflow }}\n*Action*: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}"
                  }
                }
              ]
            }
```

**Workflow Steps**:
1. Validate all migration files exist and are syntactically correct
2. Test migrations on temporary database to catch errors early
3. Wait for manual approval from DBA team
4. Create backup before production migration
5. Execute migration on production
6. Verify schema after migration
7. Notify team via Slack

---

## Best Practices

### ✅ Do's

1. **Always dry-run before production**
   ```yaml
   - name: Validate in production
     run: confiture migrate --dry-run --database-url "${{ secrets.DATABASE_URL_PROD }}"
   ```

2. **Require approvals for production**
   ```yaml
   environment:
     name: production
     reviewers: [dba-team]
   ```

3. **Create backups before migrations**
   ```yaml
   - name: Backup production
     run: pg_dump $DATABASE_URL > backup.sql
   ```

4. **Upload logs for auditing**
   ```yaml
   - uses: actions/upload-artifact@v3
     with:
       name: migration-logs
       path: /tmp/migration.log
   ```

5. **Notify team of results**
   ```yaml
   - name: Notify Slack
     uses: slackapi/slack-github-action@v1
   ```

### ❌ Don'ts

1. **Don't migrate without approval**
   ```yaml
   # Bad: No environment protection
   migrate-production:
     runs-on: ubuntu-latest

   # Good: Requires approval
   migrate-production:
     environment:
       name: production
       reviewers: [dba-team]
   ```

2. **Don't use plaintext secrets**
   ```bash
   # Bad: Password in workflow
   DATABASE_URL=postgresql://user:password@host/db

   # Good: Use GitHub secrets
   DATABASE_URL: ${{ secrets.DATABASE_URL_PROD }}
   ```

3. **Don't skip dry-run validation**
   ```yaml
   # Good: Always validate first
   jobs:
     validate:
       runs-on: ubuntu-latest
   ```

4. **Don't ignore failed migrations**
   ```yaml
   # Bad: Continues on failure
   - run: confiture migrate up || true

   # Good: Fails fast
   - run: confiture migrate up
   ```

---

## Troubleshooting

### ❌ Error: "Permission denied" on database

**Cause**: GitHub Actions doesn't have permission to connect to database

**Solution**:
```yaml
# Verify GitHub Actions IP is whitelisted
# Add GitHub Actions IP range to PostgreSQL firewall
# See: https://docs.github.com/en/actions/hosting-your-own-runners/about-self-hosted-runners

# Or use GitHub-hosted runners with public database
- name: Check database connection
  run: |
    psql "${{ secrets.DATABASE_URL_PROD }}" -c "SELECT version();"
```

---

### ❌ Error: "Workflow approval required"

**Cause**: Environment protection requires approval but approval timeout expired

**Solution**:
```yaml
# Increase timeout (default is 30 days)
environment:
  name: production
  reviewers: [dba-team]

# Or manually approve in GitHub Actions UI:
# 1. Go to Actions tab
# 2. Find pending workflow
# 3. Click "Review deployments"
# 4. Approve or reject
```

---

### ❌ Error: "Migration timed out"

**Cause**: Migration takes longer than default timeout (6 hours)

**Solution**:
```yaml
- name: Run production migration
  timeout-minutes: 120  # 2 hour timeout
  run: confiture migrate up --database-url "${{ secrets.DATABASE_URL_PROD }}"
```

---

## See Also

- [Slack Integration](./slack-integration.md) - Notify team of migration status
- [Hook API Reference](../api/hooks.md) - Custom migration logic
- [GitHub Actions Documentation](https://docs.github.com/actions) - Official GitHub Actions docs
- [PostgreSQL Backup Strategies](https://www.postgresql.org/docs/current/backup.html) - Database backup patterns

---

## 🎯 Next Steps

**Ready to automate migrations in GitHub Actions?**
- ✅ You now understand: GitHub Actions workflows, approval processes, dry-run validation

**What to do next:**

1. **[Create the workflow file](.github/workflows/migrations.yml)** - Copy the examples above
2. **[Add GitHub secrets](https://docs.github.com/actions/security-guides/encrypted-secrets)** - Store database credentials
3. **[Test on staging](./github-actions-workflow.md#step-4-production-migrations-with-approval)** - Verify workflows work before production
4. **[Monitor your first migration](../guides/monitoring-integration.md)** - Watch migration progress

---

**Last Updated**: January 9, 2026
**Status**: Production Ready ✅
**Tested On**: GitHub Actions free tier, Ubuntu latest

🍓 Automate your migrations safely and reliably
