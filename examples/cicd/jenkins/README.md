# Jenkins Pipeline for Confiture

Ready-to-use Jenkins pipeline for automated migration management.

## Quick Start

```bash
# Copy Jenkinsfile to your repository root
cp Jenkinsfile /path/to/your/project/
```

Then configure a Multibranch Pipeline job in Jenkins pointing to your repository.

## Pipeline Stages

### 1. Setup
Installs Confiture and dependencies.

### 2. Lint Migrations
Validates migration syntax and checksums.
- Triggered by changes to `db/migrations/**` or `db/schema/**`

### 3. Dry Run
Tests migrations against test database.
- Triggered by changes to `db/migrations/**`

### 4. Test Rollback
Verifies rollback scripts work correctly.
- Triggered by changes to `db/migrations/**`

### 5. Deploy Staging
Automatically deploys to staging on main branch.
- Includes health checks before and after

### 6. Deploy Production
Manual approval required for production deployment.
- Confirmation checkbox required
- Automatic rollback on failure

## Required Credentials

Configure in Jenkins → Credentials:

| Credential ID | Type | Description |
|---------------|------|-------------|
| `test-database-url` | Secret text | PostgreSQL URL for testing |
| `staging-database-url` | Secret text | PostgreSQL URL for staging |
| `production-database-url` | Secret text | PostgreSQL URL for production |

## Required Plugins

- **Pipeline** (workflow-aggregator)
- **Pipeline: Declarative** (pipeline-model-definition)
- **Slack Notification** (slack)
- **Email Extension** (email-ext)
- **Credentials Binding** (credentials-binding)

## Slack Integration

1. Create Slack app with incoming webhook
2. Configure in Jenkins → Configure System → Slack
3. Set workspace, credential, and default channel

## Job Configuration

### Multibranch Pipeline Setup

1. New Item → Multibranch Pipeline
2. Branch Sources → Add → Git
3. Project Repository: Your repo URL
4. Behaviors: Discover branches, filter by name if needed
5. Build Configuration: by Jenkinsfile

### Pipeline Options

The Jenkinsfile includes:
- `disableConcurrentBuilds()` - Prevents parallel migration runs
- `timeout(time: 30, unit: 'MINUTES')` - Overall timeout
- `buildDiscarder(logRotator(numToKeepStr: '20'))` - Log retention

## Customization

### Different Approval Groups

```groovy
input {
    submitter 'dba-team,platform-team'  // Change approvers
}
```

### Custom Lock Timeout

```groovy
sh '''
    confiture migrate up \
        --lock-timeout 120000  # 2 minutes
'''
```

### Additional Environments

```groovy
stage('Deploy QA') {
    when {
        branch 'develop'
    }
    environment {
        DATABASE_URL = credentials('qa-database-url')
    }
    steps {
        // Same as staging
    }
}
```

### Skip Migrations via Commit Message

```groovy
when {
    allOf {
        branch 'main'
        changeset 'db/migrations/**'
        not {
            changelog '.*\\[skip-migrations\\].*'
        }
    }
}
```

## Troubleshooting

### Credentials not found

1. Verify credential ID matches exactly
2. Check credential scope (global vs folder)
3. Ensure pipeline has access to credential

### Slack notifications not sending

1. Check Slack plugin configuration
2. Verify webhook URL is correct
3. Check Jenkins → Manage Jenkins → System Log

### Pipeline timeout

Increase timeout in pipeline options:
```groovy
options {
    timeout(time: 60, unit: 'MINUTES')
}
```

### Manual approval stuck

1. Check submitter list includes current user
2. Verify user has appropriate permissions
3. Check for typos in submitter parameter

## Best Practices

1. **Use credential binding** for all database URLs
2. **Require confirmation** for production deployments
3. **Set up email notifications** for failures
4. **Configure Slack** for team visibility
5. **Use shared library** for common functions across pipelines
