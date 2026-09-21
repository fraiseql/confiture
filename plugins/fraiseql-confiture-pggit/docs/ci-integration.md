# Coordination in CI/CD

Coordination checks in a CI/CD pipeline, so a conflict is reported on the pull
request rather than at merge time. Every `confiture coordinate` command takes
`--format json`; the payloads are described in the
[coordination guide](multi-agent-coordination.md#json-output-format).

These workflows moved here from confiture's own documentation when pgGit support
became this plugin (1.16).

**Installing the plugin in CI.** The workflows install it by name,
`fraiseql-confiture-pggit`. It is not published on PyPI yet; until it is, replace
that step with an install from a checkout of confiture's repository, as the
[README](../README.md) shows.

**The database.** The commands read the coordination database from
`--database-url`, or from `DATABASE_URL` / `CONFITURE_DB_URL`. The workflows set
`DATABASE_URL` from a `COORDINATION_DB_URL` secret. The coordination tables are
created there on first use; there is no separate init step.

**One agent per pull request.** An intent never conflicts with another intent of the
same agent, so the workflows use one agent ID per pull request,
`github-pr-<number>`: the check does not report the pull request's own registered
intent as a conflict, and the merge step finds that intent again by its agent.

---

## Pre-Merge Conflict Detection

Check the schema files a pull request changes against every registered or
in-progress intent:

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
        with:
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install confiture and the pgGit plugin
        run: pip install fraiseql-confiture fraiseql-confiture-pggit

      - name: Collect the changed schema files
        id: changes
        run: |
          FILES=$(git diff --name-only --diff-filter=AM \
            origin/${{ github.base_ref }} HEAD -- 'db/schema/*.sql')
          if [ -n "$FILES" ]; then
            cat $FILES > changes.sql
            echo "found=true" >> $GITHUB_OUTPUT
          fi

      - name: Check coordination conflicts
        if: steps.changes.outputs.found == 'true'
        env:
          DATABASE_URL: ${{ secrets.COORDINATION_DB_URL }}
        run: |
          confiture coordinate check \
            --agent-id "github-pr-${{ github.event.pull_request.number }}" \
            --feature-name "${{ github.head_ref }}" \
            --schema-changes changes.sql \
            --format json > conflicts.json

          if jq -e '.conflicts_detected > 0' conflicts.json > /dev/null; then
            echo "Schema conflicts detected:"
            jq '.conflicts' conflicts.json
            exit 1
          fi
          echo "No schema conflicts detected"

      - name: Comment on PR
        if: always() && steps.changes.outputs.found == 'true'
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const report = JSON.parse(fs.readFileSync('conflicts.json'));

            let body = '## Schema Coordination Check\n\n';
            if (report.conflicts_detected > 0) {
              body += '**Conflicts detected:**\n\n';
              report.conflicts.forEach(c => {
                body += `- **${c.conflict_type}** (${c.severity}) on ` +
                  `${c.affected_objects.join(', ')}: ` +
                  `${c.resolution_suggestions.join('; ')}\n`;
              });
            } else {
              body += 'No schema conflicts detected.';
            }

            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: body
            });
```

`check` needs `--feature-name` and `--schema-changes`; `--schema-changes` takes
DDL statements or the path of one `.sql` file, which is why the changed files are
concatenated into `changes.sql` first. When `--tables-affected` is omitted, the
tables are read from the DDL.

## Register an Intention When a Pull Request Opens

```yaml
# .github/workflows/register-intention.yml
name: Register Schema Intention

on:
  pull_request:
    types: [opened]
    paths: ['db/schema/**']

jobs:
  register:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Install confiture and the pgGit plugin
        run: pip install fraiseql-confiture fraiseql-confiture-pggit

      - name: Register coordination intention
        env:
          DATABASE_URL: ${{ secrets.COORDINATION_DB_URL }}
        run: |
          FILES=$(git diff --name-only --diff-filter=AM \
            origin/${{ github.base_ref }} HEAD -- 'db/schema/*.sql')
          [ -n "$FILES" ] || exit 0
          cat $FILES > changes.sql

          confiture coordinate register \
            --agent-id "github-pr-${{ github.event.pull_request.number }}" \
            --feature-name "${{ github.head_ref }}" \
            --schema-changes changes.sql \
            --risk-level medium \
            --format json > intention.json

          echo "Registered intention: $(jq -r '.intent.id' intention.json)"
```

## Record the Merge

When the pull request is merged, find its intent by agent and record that its
changes reached the main line:

```yaml
# .github/workflows/merge-intention.yml
name: Record Schema Intention Merge

on:
  pull_request:
    types: [closed]
    paths: ['db/schema/**']

jobs:
  merge:
    if: github.event.pull_request.merged == true
    runs-on: ubuntu-latest
    steps:
      - name: Install confiture and the pgGit plugin
        run: pip install fraiseql-confiture fraiseql-confiture-pggit

      - name: Find and record the intention
        env:
          DATABASE_URL: ${{ secrets.COORDINATION_DB_URL }}
        run: |
          INTENT_ID=$(confiture coordinate list-intents \
            --agent-filter "github-pr-${{ github.event.pull_request.number }}" \
            --format json \
            | jq -r '.intents[0].id // empty')
          [ -n "$INTENT_ID" ] || exit 0

          # `coordinate complete` is the step before this one, for when the
          # changes are finished but not yet landed.
          confiture coordinate merge \
            --intent-id "$INTENT_ID" \
            --notes "Merged in PR #${{ github.event.pull_request.number }}"
```

## Dashboard Export

Export the intents and the conflicts for a dashboard on a schedule:

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
      - name: Install confiture and the pgGit plugin
        run: pip install fraiseql-confiture fraiseql-confiture-pggit

      - name: Export coordination state
        env:
          DATABASE_URL: ${{ secrets.COORDINATION_DB_URL }}
        run: |
          confiture coordinate list-intents --format json > intents.json
          confiture coordinate conflicts --format json > conflicts.json

      - name: Publish to dashboard
        run: |
          curl -X POST "${{ secrets.DASHBOARD_URL }}/api/coordination" \
            -H "Authorization: Bearer ${{ secrets.DASHBOARD_TOKEN }}" \
            -H "Content-Type: application/json" \
            -d @intents.json

          curl -X POST "${{ secrets.DASHBOARD_URL }}/api/conflicts" \
            -H "Authorization: Bearer ${{ secrets.DASHBOARD_TOKEN }}" \
            -H "Content-Type: application/json" \
            -d @conflicts.json
```

`coordinate status` reports one intent and needs `--intent-id`; `list-intents` is
the command that lists them all.

## GitLab CI

```yaml
# .gitlab-ci.yml
schema-conflict-check:
  stage: test
  image: python:3.11
  variables:
    DATABASE_URL: $COORDINATION_DB_URL
  before_script:
    - pip install fraiseql-confiture fraiseql-confiture-pggit
  script:
    - |
      FILES=$(git diff --name-only --diff-filter=AM \
        $CI_MERGE_REQUEST_DIFF_BASE_SHA HEAD -- 'db/schema/*.sql')

      if [ -n "$FILES" ]; then
        cat $FILES > changes.sql
        confiture coordinate check \
          --agent-id "gitlab-mr-${CI_MERGE_REQUEST_IID}" \
          --feature-name "$CI_MERGE_REQUEST_SOURCE_BRANCH_NAME" \
          --schema-changes changes.sql \
          --format json > conflicts.json

        if jq -e '.conflicts_detected > 0' conflicts.json > /dev/null; then
          echo "Schema conflicts detected!"
          exit 1
        fi
      fi
  only:
    - merge_requests
```

---

**Related:**
- [Multi-agent coordination guide](multi-agent-coordination.md)
- [Command reference](cli.md#confiture-coordinate)
- [confiture's integrations guide](../../../docs/guides/integrations.md) — CI/CD,
  notification and monitoring integrations for confiture itself
