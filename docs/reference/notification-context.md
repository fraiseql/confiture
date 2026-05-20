# Notification Context Reference

[← Reference](../index.md) · [Notifications Guide](../guides/notifications.md) · [Architecture](notification-architecture.md)

The `NotificationContext` value object renderers consume, plus the Jinja sandbox envelope for the templated renderer.

---

## NotificationContext

```python
@dataclass(frozen=True)
class NotificationContext:
    migration_name: str = "unknown"
    migration_version: str = ""
    direction: str = "up"           # "up" or "down"
    success: bool = True
    duration_ms: int = 0
    database_name: str = ""
    schema: str = "public"
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    rows_affected: int = 0
    error: str | None = None
    migrations_applied: list[str] = field(default_factory=list)

    @property
    def status_word(self) -> str: ...          # "succeeded" | "FAILED"
    @property
    def timestamp_iso(self) -> str: ...        # ISO 8601, seconds resolution
    @property
    def timestamp_human(self) -> str: ...      # "YYYY-MM-DD HH:MM UTC"
```

Renderers receive a `NotificationContext` and return a `TransportPayload`. Both are immutable; renderers stay pure.

---

## Jinja Renderer — v1 Security Envelope

Jinja templates execute config-driven code. `jinja2.sandbox.SandboxedEnvironment` has a known history of escape bypasses (class-attribute traversal, format-string tricks, `getitem`-chain traversal). The v1 strategy is to shrink the attack surface to what we can confidently defend.

### Opt-in by default off

```yaml
notifications:
  allow_templated_renderers: true   # required to use type: jinja
```

A project that never sets this flag cannot be exploited through this path. The opt-in is the **load-bearing defence**; everything below is defence-in-depth.

### Allowed context

Only flat-dict values. Validated at config-load time:

```python
context: dict[str, str | int | float | bool | None]
```

Nested dicts, lists of objects, dataclasses, or any other type fail validation with a clear error pointing at the offending key. This removes the objects that `{{ x.__class__ }}` and friends would traverse.

### Allowed context keys

| Key | Type | Notes |
|-----|------|-------|
| `migration_name` | str | |
| `migration_version` | str | empty when unknown |
| `direction` | str | `up` or `down` |
| `success` | bool | |
| `execution_time_ms` | int | alias for `duration_ms` |
| `duration_ms` | int | |
| `database_name` | str | |
| `database` | str | alias for `database_name` |
| `schema` | str | |
| `rows_affected` | int | |
| `error` | str / None | populated only on failure |
| `timestamp` | str | ISO 8601 |
| `status` | str | `succeeded` or `FAILED` |

### No block tags

Templates may contain only `{{ expr }}` expressions and `{# comment #}` comments. Block tags are rejected at config-load time:

- `{% set %}`
- `{% for %}`
- `{% if %}`
- `{% macro %}`
- `{% include %}`
- `{% import %}`
- `{% raw %}`

The check parses the template's AST after compile and refuses anything that is not `Output`, `TemplateData`, `Name`, `Getattr`, `Filter`, or `Const`. Block tags would let an attacker chain object walks across statements; refusing them at parse time eliminates the class.

### Allow-listed filters only

```
tojson, upper, lower, length, default
```

No `attr`, no `eval`, no custom filters. A template that references any other filter is rejected at compile time.

### Underscore-attribute block

The sandbox subclass overrides `is_safe_attribute()` to refuse:

- Any attribute starting with `_`
- `format`, `__class__`, `__mro__`, `__subclasses__`, `__globals__`, `__init__`, `__getattribute__`

With the flat-dict context restriction above, these should be unreachable — but the check is cheap, so it stays as belt-and-braces.

### Size and time caps

- **Template max length: 16 KiB.** Templates longer than this are rejected at config-load.
- **Render timeout via `threading.Timer` + cancellation token.** Not `signal.alarm` — process-global signals collide with parallel hook execution and don't fire under threads.

### Compile-at-load

Templates compile at config-load time. Syntax errors surface during startup, not during a migration.

---

## Worked Example

```yaml
notifications:
  allow_templated_renderers: true

  hooks:
    - id: metrics-ingest
      phase: after_execute
      transport:
        type: http
        url: https://metrics.example.com/ingest
      renderer:
        type: jinja
        content_type: application/json
        template: |
          {
            "service": "db-migration",
            "name": "{{ migration_name }}",
            "version": "{{ migration_version }}",
            "success": {{ success | tojson }},
            "duration_ms": {{ duration_ms }},
            "rows": {{ rows_affected }},
            "error": {{ error | default("") | tojson }}
          }
```

Note the use of `| tojson` to produce valid JSON literals for booleans and strings; raw `{{ success }}` would render `True` (Python repr) rather than `true` (JSON).

---

## Deferred to a Future Version

Items flagged by review that are out of scope for v1:

- **Sandboxed objects in the context** — nested attribute access like `{{ migration.version }}`.
- **Block tags** — conditional output via `{% if %}` / `{% for %}`.
- **Custom filter registration.**
- **Process-isolated render workers** for projects that need full Jinja with hard security guarantees.

Operators who need richer templates today can pre-render their payload in application code and pass the result through `RawJsonRenderer`.

---

## See Also

- [Notifications Guide](../guides/notifications.md) — user-facing recipes.
- [Notification Architecture](notification-architecture.md) — design rationale.
