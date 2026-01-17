# Confiture CI/CD Templates

Ready-to-use pipeline templates for common CI/CD systems.

## Quick Start

Choose your CI/CD platform and copy the templates:

### GitHub Actions

```bash
mkdir -p .github/workflows
cp examples/cicd/github-actions/migration-check.yml .github/workflows/
cp examples/cicd/github-actions/migration-deploy.yml .github/workflows/
```

Configure secrets in GitHub repository settings:
- `STAGING_DATABASE_URL`
- `PRODUCTION_DATABASE_URL`
- `SLACK_WEBHOOK` (optional)

### GitLab CI

```bash
cp examples/cicd/gitlab-ci/.gitlab-ci.yml .
```

Configure variables in GitLab CI/CD settings.

### Jenkins

```bash
cp examples/cicd/jenkins/Jenkinsfile .
```

Configure credentials in Jenkins.

### Argo Workflows (Kubernetes)

```bash
kubectl apply -f examples/cicd/argo/migration-workflow.yaml
```

Configure secrets in Kubernetes.

## Template Features

All templates include:

| Feature | GitHub | GitLab | Jenkins | Argo |
|---------|--------|--------|---------|------|
| Migration linting | ✅ | ✅ | ✅ | ✅ |
| Checksum verification | ✅ | ✅ | ✅ | ✅ |
| Dry-run testing | ✅ | ✅ | ✅ | ✅ |
| Rollback testing | ✅ | ✅ | ✅ | ✅ |
| Staging deployment | ✅ | ✅ | ✅ | ✅ |
| Production deployment | ✅ | ✅ | ✅ | ✅ |
| Manual approval | ✅ | ✅ | ✅ | ✅ |
| Health checks | ✅ | ✅ | ✅ | ✅ |
| Slack notifications | ✅ | ✅ | ✅ | ✅* |
| Automatic rollback | ✅ | ❌ | ✅ | ❌ |
| Drift detection | ✅ | ✅ | ❌ | ✅ |
| Concurrency control | ✅ | ✅ | ✅ | ✅ |

*Requires additional configuration

## Pipeline Stages

All templates follow the same logical flow:

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│    Lint     │────▶│  Dry Run    │────▶│   Staging   │
│ Migrations  │     │   Testing   │     │   Deploy    │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                               │
                                               ▼
                                        ┌─────────────┐
                                        │  Approval   │
                                        │  Required   │
                                        └──────┬──────┘
                                               │
                                               ▼
                                        ┌─────────────┐
                                        │ Production  │
                                        │   Deploy    │
                                        └─────────────┘
```

## Security Best Practices

### 1. Secret Management

**Never** commit database URLs or credentials:
- Use platform-specific secret storage
- Rotate credentials regularly
- Use read-only credentials for dry-run stages

### 2. Network Security

- Restrict database access to CI/CD runners only
- Use SSL/TLS for database connections
- Consider using private runners for production

### 3. Access Control

- Require approval for production deployments
- Limit who can approve (DBAs, leads)
- Log all deployment activities

### 4. Rollback Safety

- Test rollback scripts in CI
- Keep rollback window reasonable
- Document manual rollback procedures

## Customization Guide

### Adding Custom Lint Rules

Create `.confiture/lint.yaml`:

```yaml
rules:
  require_down_migration: true
  max_statements_per_migration: 10
  banned_operations:
    - DROP TABLE
    - TRUNCATE
```

### Custom Health Checks

Add application-specific checks:

```yaml
- name: Application health check
  run: curl --fail https://your-app/health
```

### Multi-Region Deployments

Extend templates for multi-region:

```yaml
deploy-us-east:
  ...
deploy-eu-west:
  needs: deploy-us-east
  ...
```

### Blue-Green Deployments

Use Confiture's blue-green orchestration:

```yaml
- name: Blue-green migration
  run: confiture migrate blue-green --source public --target public_new
```

## Troubleshooting

### Common Issues

1. **"Lock timeout" errors**
   - Increase `--lock-timeout` value
   - Check for long-running transactions
   - Consider using `statement_timeout`

2. **"Checksum mismatch" errors**
   - Someone modified a migration after it ran
   - Use `--skip-checksum` if intentional
   - Reset checksums: `confiture migrate reset-checksums`

3. **"Connection refused" errors**
   - Verify DATABASE_URL format
   - Check firewall/security groups
   - Ensure PostgreSQL service is running

4. **Migrations succeed but app fails**
   - Check application compatibility
   - Review migration for breaking changes
   - Consider blue-green deployment

### Getting Help

- Check individual README files in each directory
- Review [Confiture documentation](https://confiture.readthedocs.io)
- Open an issue on GitHub

## Contributing

We welcome contributions! To add templates for other CI/CD systems:

1. Create a new directory under `examples/cicd/`
2. Include the main configuration file
3. Add a comprehensive README
4. Submit a pull request

## License

MIT License - See [LICENSE](../../LICENSE) for details.
