# Command reference

The commands this plugin adds to `confiture`, as `docs/reference/cli.md` in
confiture's repository documented them when they left it (1.16). `confiture <command>
--help` is the live reference once the plugin is installed.

## `confiture branch`

Schema branching commands (requires pgGit)

### `confiture branch checkout`

Switch to a different schema branch.

**Usage**

```bash
confiture branch checkout [OPTIONS] {name}
```

**Arguments**

| Argument | Type | Required | Description |
|---|---|---|---|
| `name` | str | yes | Branch name to checkout |

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file |

### `confiture branch commit`

Commit current schema changes.

**Usage**

```bash
confiture branch commit [OPTIONS] {message}
```

**Arguments**

| Argument | Type | Required | Description |
|---|---|---|---|
| `message` | str | yes | Commit message |

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file |

### `confiture branch create`

Create a new schema branch.

**Usage**

```bash
confiture branch create [OPTIONS] {name}
```

**Arguments**

| Argument | Type | Required | Description |
|---|---|---|---|
| `name` | str | yes | Name of the new branch |

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--from` | `-f` | str | - | Parent branch (default: current branch) |
| `--checkout` / `--no-checkout` | - | Flag | on | Checkout new branch after creation (default: on) |
| `--copy-data` / `--no-copy-data` | - | Flag | on | Copy data from parent branch (default: on) |
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file (default: db/environments/local.yaml) |

### `confiture branch delete`

Delete a schema branch.

**Usage**

```bash
confiture branch delete [OPTIONS] {name}
```

**Arguments**

| Argument | Type | Required | Description |
|---|---|---|---|
| `name` | str | yes | Branch name to delete |

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--force` | `-f` | Flag | off | Force delete even if branch has unmerged commits |
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file |

### `confiture branch diff`

Show differences between branches.

**Usage**

```bash
confiture branch diff [OPTIONS] [source] [target]
```

**Arguments**

| Argument | Type | Required | Description |
|---|---|---|---|
| `source` | str | no | Source branch (default: current branch) |
| `target` | str | no | Target branch to compare against |

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file |

### `confiture branch list`

List all schema branches.

**Usage**

```bash
confiture branch list [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file (default: db/environments/local.yaml) |
| `--format` | `-f` | str | `table` | Output format: table or json (default: table) |

### `confiture branch log`

Show commit history for current branch.

**Usage**

```bash
confiture branch log [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--limit` | `-n` | int | `10` | Maximum number of commits to show |
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file |

### `confiture branch merge`

Merge one branch into another.

**Usage**

```bash
confiture branch merge [OPTIONS] {source}
```

**Arguments**

| Argument | Type | Required | Description |
|---|---|---|---|
| `source` | str | yes | Source branch to merge from |

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--into` | - | str | - | Target branch (default: current branch) |
| `--dry-run` | - | Flag | off | Show what would be merged without making changes |
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file |

### `confiture branch merge-abort`

Abort an in-progress merge.

**Usage**

```bash
confiture branch merge-abort [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file |

### `confiture branch status`

Show current branch status and uncommitted changes.

**Usage**

```bash
confiture branch status [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file |


## `confiture coordinate`

Multi-agent coordination for schema changes

### `confiture coordinate abandon`

Abandon an intention before completion.

**Usage**

```bash
confiture coordinate abandon [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--intent-id` | - | str | - | Intention ID |
| `--reason` | - | str | - | Reason for abandonment |
| `--database-url` | - | str | - | Database URL |
| `--format` | `-f` | str | `text` | Output format: text or json (default: text) |

### `confiture coordinate check`

Check for conflicts with a proposed set of schema changes.

**Usage**

```bash
confiture coordinate check [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--agent-id` | - | str | - | Agent ID |
| `--feature-name` | - | str | - | Feature name |
| `--schema-changes` | - | str | - | DDL statements or SQL file path |
| `--tables-affected` | - | str | - | Comma-separated table names |
| `--database-url` | - | str | - | Database URL |
| `--format` | `-f` | str | `text` | Output format: text or json (default: text) |

### `confiture coordinate conflicts`

List all detected conflicts between intentions.

**Usage**

```bash
confiture coordinate conflicts [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--database-url` | - | str | - | Database URL |
| `--format` | `-f` | str | `text` | Output format: text or json (default: text) |

### `confiture coordinate list-intents`

List all registered intentions with optional filtering.

**Usage**

```bash
confiture coordinate list-intents [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--status-filter` | - | str | - | Filter by status (registered, in_progress, completed, merged, abandoned, conflicted) |
| `--agent-filter` | - | str | - | Filter by agent ID |
| `--database-url` | - | str | - | Database URL |
| `--format` | `-f` | str | `text` | Output format: text or json (default: text) |

### `confiture coordinate register`

Register a new agent intention for schema changes.

**Usage**

```bash
confiture coordinate register [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--agent-id` | - | str | - | Identifier for the agent, e.g. claude-payments (required) |
| `--feature-name` | - | str | - | Human-readable feature name (required) |
| `--schema-changes` | - | str | - | DDL statements or path to SQL file (required) |
| `--tables-affected` | - | str | - | Comma-separated table names affected (default: none) |
| `--risk-level` | - | str | `low` | Risk assessment: low, medium, high (default: low) |
| `--estimated-hours` | - | float | `0` | Estimated hours to complete (default: 0) |
| `--database-url` | - | str | - | Database URL (default: from config) |
| `--metadata` | - | str | - | JSON metadata string (default: none) |
| `--format` | `-f` | str | `text` | Output format: text or json (default: text) |

### `confiture coordinate resolve`

Mark a conflict as reviewed and provide resolution notes.

**Usage**

```bash
confiture coordinate resolve [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--conflict-id` | - | int | - | Conflict ID |
| `--notes` | - | str | - | Resolution notes |
| `--database-url` | - | str | - | Database URL |
| `--format` | `-f` | str | `text` | Output format: text or json (default: text) |

### `confiture coordinate status`

Show detailed status of a specific intention.

**Usage**

```bash
confiture coordinate status [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--intent-id` | - | str | - | Intention ID |
| `--database-url` | - | str | - | Database URL |
| `--format` | `-f` | str | `text` | Output format: text or json (default: text) |

### `confiture coordinate complete`

Record that an intention's changes are finished.

**Usage**

```bash
confiture coordinate complete [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--intent-id` | - | str | - | Intention ID |
| `--notes` | - | str | `Changes completed` | Why the status changed |
| `--database-url` | - | str | - | Database URL |
| `--format` | `-f` | str | `text` | Output format: text or json (default: text) |

### `confiture coordinate merge`

Record that an intention's changes have reached the main line.

**Usage**

```bash
confiture coordinate merge [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--intent-id` | - | str | - | Intention ID |
| `--notes` | - | str | `Changes merged to main` | Why the status changed |
| `--database-url` | - | str | - | Database URL |
| `--format` | `-f` | str | `text` | Output format: text or json (default: text) |

### `confiture coordinate start`

Record that work on an intention has begun.

**Usage**

```bash
confiture coordinate start [OPTIONS]
```

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--intent-id` | - | str | - | Intention ID |
| `--notes` | - | str | `Agent started work` | Why the status changed |
| `--database-url` | - | str | - | Database URL |
| `--format` | `-f` | str | `text` | Output format: text or json (default: text) |


### `confiture generate diff`

Show detailed diff between branches.

**Usage**

```bash
confiture generate diff [OPTIONS] {branch}
```

**Arguments**

| Argument | Type | Required | Description |
|---|---|---|---|
| `branch` | str | yes | Branch name to diff |

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--base` | `-b` | str | `main` | Base branch to compare against (default: main) |
| `--show-sql` | `-s` | Flag | off | Show the actual SQL for each change (default: off) |
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file (default: db/environments/local.yaml) |


### `confiture generate from-branch`

Generate migrations from a pgGit branch.

**Usage**

```bash
confiture generate from-branch [OPTIONS] {branch}
```

**Arguments**

| Argument | Type | Required | Description |
|---|---|---|---|
| `branch` | str | yes | Branch name to generate migrations from |

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--base` | `-b` | str | `main` | Base branch to compare against (default: main) |
| `--output` | `-o` | path | `db/migrations` | Output directory for migration files (default: db/migrations) |
| `--combined` | `-c` | Flag | off | Generate single combined migration (default: off) |
| `--config` | - | path | `db/environments/local.yaml` | Configuration file (default: db/environments/local.yaml) |


### `confiture generate preview`

Preview what migrations would be generated.

**Usage**

```bash
confiture generate preview [OPTIONS] {branch}
```

**Arguments**

| Argument | Type | Required | Description |
|---|---|---|---|
| `branch` | str | yes | Branch name to preview |

**Options**

| Option | Short | Type | Default | Description |
|---|---|---|---|---|
| `--base` | `-b` | str | `main` | Base branch to compare against (default: main) |
| `--config` | `-c` | path | `db/environments/local.yaml` | Configuration file (default: db/environments/local.yaml) |
