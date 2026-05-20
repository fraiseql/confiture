# Notification Hooks

[← Back to Guides](../index.md) · [Migration Hooks](hooks.md) · [Architecture Reference →](../reference/notification-architecture.md)

Send migration outcomes to Slack, Discord, Microsoft Teams, email, PagerDuty, OpsGenie, or any HTTP webhook — declaratively, via the environment YAML.

---

## Quick Start

```yaml
# db/environments/production.yaml
notifications:
  hooks:
    - id: prod-slack
      phase: after_execute
      transport:
        type: http
        url: ${SLACK_WEBHOOK_URL}
      renderer:
        type: slack
        channel: "#migrations"
        mention_on_failure: "@oncall"
```

That's the whole setup. The `notifications:` block is loaded by every command that fires hooks (`migrate up`, `migrate down`, `build`, `migrate preflight`).

To verify the configuration before a real migration:

```bash
confiture hooks test --env production
```

The command fires a synthetic event through the configured hook with `StdoutTransport` swapped in by default — you see exactly what would be sent, with no external service contacted. Pass `--no-dry-run` once you trust the setup.

---

## The Three Layers

```
NotificationHook
  ├── Renderer  (pure function: context → payload)
  └── Transport (IO: payload → wire)
```

- **Transports** are how the payload gets delivered: `http`, `smtp`, or `stdout`.
- **Renderers** are how the payload is shaped: `slack`, `discord`, `teams`, `email`, `pagerduty`, `opsgenie`, `raw_json`, `jinja`.

You compose them. The same `http` transport ships every webhook-based renderer; the `smtp` transport drives the email renderer.

See [Notification Architecture](../reference/notification-architecture.md) for the design rationale.

---

## Configuration Surface

### Transports

#### `http`

```yaml
transport:
  type: http
  url: https://hooks.example.com/...
  timeout_seconds: 10      # default: 10
  verify_tls: true         # default: true
  retry:
    attempts: 3            # default: 1 (no retry)
    backoff_seconds: 2     # default: 0 — multiplied by 2 each retry
```

- Retries fire on **5xx and connection errors only**. 4xx is final to avoid duplicate notifications on non-idempotent receivers.
- For receivers that cannot tolerate duplicates, set `attempts: 1`.

#### `smtp`

```yaml
transport:
  type: smtp
  host: smtp.example.com
  port: 587                # default: 587
  username: notify
  password: ${SMTP_PASSWORD}   # SecretStr — never logged
  use_tls: true            # default: true
  timeout_seconds: 10
```

Passwords are stored as `pydantic.SecretStr`; `repr()` and `confiture validate` output both redact, and traceback frames are scrubbed if `login()` raises.

#### `stdout`

```yaml
transport:
  type: stdout
```

Writes the rendered payload to stdout. Useful for `--dry-run`, audit pipes, or testing.

---

### Renderers

#### `slack`

```yaml
renderer:
  type: slack
  channel: "#migrations"           # optional — overrides webhook default
  mention_on_failure: "@oncall"    # optional — appended to failure text
```

Slack incoming-webhook attachments format. Green attachment on success, red on failure.

#### `discord`

```yaml
renderer:
  type: discord
  username: Confiture              # optional — overrides webhook default
  mention_on_failure: "<@USER_ID>" # optional — `<@&ROLE_ID>` also works
```

Discord webhook embed format. Failure embeds include the error in a dedicated field.

#### `teams`

```yaml
renderer:
  type: teams
  mention_on_failure: "@team"      # optional — plain text in the activity title
```

Microsoft Teams MessageCard format. For richer `<at>username</at>` mentions, configure per-tenant Teams settings.

#### `email`

```yaml
renderer:
  type: email
  from: db-migrations@example.com
  to: [team@example.com]
  cc: [audit@example.com]                                  # optional
  subject_template: "[Migration] {database_name} — {status}"   # default
  include_html: true                                       # default
```

Sends a multipart HTML+plaintext message. The subject template uses Python `str.format()` keys: `database_name`, `status`, `migration_name`, `direction`. Plain string formatting — **not Jinja** — keeps SMTP free of sandbox concerns.

#### `pagerduty`

```yaml
renderer:
  type: pagerduty
  routing_key: ${PAGERDUTY_ROUTING_KEY}
  service_name: production-database
  component: postgres              # optional
  group: infrastructure            # optional
  class: migration                 # optional
  severity: critical               # one of critical, error, warning, info
```

Stateless model: every migration emits one Events API v2 event. Success → `event_action: resolve`. Failure → `event_action: trigger`. `dedup_key` is derived from the migration version so re-runs do not re-page.

If the success notification fails to deliver after a triggered failure, the dashboard may show a phantom incident. This is the documented v1 limitation; mitigate with `attempts: 3` on the transport.

#### `opsgenie`

```yaml
renderer:
  type: opsgenie
  api_key: ${OPSGENIE_API_KEY}
  alias_template: "confiture-{migration_version}"   # default
  tags: [prod, db]
  priority_on_failure: P2          # default P2 on failure, P5 on success
```

Stateless one-alert-per-migration model. `alias` ensures retries dedupe.

#### `raw_json`

```yaml
renderer:
  type: raw_json
```

The canonical confiture migration-event JSON payload. Use this against any generic HTTP webhook receiver; external consumers can validate against `docs/reference/notification-payload-schema.json`.

```json
{
  "event": "migration_completed",
  "timestamp": "2026-05-20T14:30:00+00:00",
  "database": "myapp_prod",
  "schema": "public",
  "success": true,
  "execution_time_ms": 124,
  "migrations_applied": 1,
  "error": null,
  "migration_details": [
    {"version": "...", "name": "...", "direction": "up"}
  ]
}
```

#### `jinja`

```yaml
notifications:
  allow_templated_renderers: true     # opt-in — see security envelope below

  hooks:
    - id: custom-metric
      transport: {type: http, url: https://metrics.example.com/ingest}
      renderer:
        type: jinja
        content_type: application/json
        template: |
          { "service": "db-migration",
            "success": {{ success | tojson }},
            "ms": {{ execution_time_ms }} }
```

Templated payloads via a sandboxed Jinja environment. **Disabled by default.** See [Notification Context Reference](../reference/notification-context.md) for the full security envelope: flat-dict context only, no block tags, allow-listed filters.

---

## Environment Variable Substitution

Any string in the `notifications:` block supports `${VAR}` substitution:

```yaml
transport:
  type: http
  url: ${WEBHOOK_URL}
  retry:
    attempts: ${RETRY_ATTEMPTS}
```

Missing environment variables fail **loud** at config-load time — they never silently expand to empty strings. Validation happens at the entrypoint of every command that fires hooks and via `confiture validate`.

---

## Phase Mapping

The `phase:` field maps onto the `HookPhase` enum already used by the broader hooks system:

| Phase | Fires |
|-------|-------|
| `before_execute` | Before each migration |
| `after_execute` | After each migration (default) |
| `on_failure` | When a migration raises |
| `before_rollback` | Before a rollback |
| `after_rollback` | After a rollback |

Configure separate hooks on different phases to implement filtered behaviour (for example, page only on `on_failure`).

---

## Testing Setup

The `hooks test` command renders a synthetic event end-to-end against the configured hook:

```bash
# Default — dry-run, no external service contacted
confiture hooks test --env production

# Disambiguate when multiple hooks are configured
confiture hooks test --env production --id prod-slack

# Actually send through the real transport
confiture hooks test --env production --id prod-slack --no-dry-run
```

---

## Failure Semantics

Notification failures never block migrations. The hook logs at WARNING and returns `HookResult(success=False)`; the migration completes regardless.

- 4xx HTTP responses are **final** — the transport does not retry.
- 5xx HTTP responses and connection errors are retried up to `retry.attempts`.
- SMTP failures are surfaced via the inner hook; the password is scrubbed from any traceback frame walked by Sentry / `rich.traceback(show_locals=True)`.

---

## See Also

- [Notification Architecture](../reference/notification-architecture.md) — design rationale and the Transport / Renderer / Hook split.
- [Notification Context](../reference/notification-context.md) — Jinja context variables, allowed filters, security envelope.
- [Migration Hooks](hooks.md) — the broader hook lifecycle.
