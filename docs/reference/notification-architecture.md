# Notification Architecture Reference

[← Reference](../index.md) · [Notifications Guide](../guides/notifications.md) · [Notification Context →](notification-context.md)

The design behind `confiture.core.hooks.notifications` — why the three layers, where they meet, and what each owns.

---

## Layers

```
┌────────────────────────────────────────────────┐
│  NotificationHook                              │  ← single Hook subclass
│  • holds: Transport, Renderer                  │
│  • implements: execute() → render → send       │
└────────────────────────────────────────────────┘
             │                       │
             ▼                       ▼
┌──────────────────┐     ┌──────────────────────┐
│  Renderer        │     │  Transport           │
│  (pure function) │     │  (IO)                │
│  context → bytes │     │  bytes → None        │
└──────────────────┘     └──────────────────────┘
```

Three modules under `python/confiture/core/hooks/notifications/`:

| Module | Layer | Responsibility |
|--------|-------|----------------|
| `hook.py` | NotificationHook | Convert live `ExecutionContext` → `NotificationContext`, hand to renderer, hand bytes to transport, swallow transport errors. |
| `renderer.py` | Renderer | Pure mapping from `NotificationContext` → `TransportPayload`. No I/O. No clock reads. No `os.environ` lookups. |
| `transport.py` | Transport | Push the rendered bytes to their destination. Owns retry, timeout, TLS verification, credential handling. |

Plus three support modules:

| Module | Role |
|--------|------|
| `context.py` | `NotificationContext` frozen dataclass — the value object renderers consume. |
| `config.py` | Pydantic discriminated-union models — the YAML surface. |
| `factory.py` | `from_config(NotificationConfig)` — builds a `NotificationHook` from validated config. |
| `jinja_renderer.py` | `JinjaRenderer` — opt-in templated payloads, isolated from the core renderer module to keep core install lean. |

---

## Why the Split?

### Why separate Renderer from Transport?

- **Code reuse.** All HTTP-based services share retry, timeout, TLS verification, header handling. One transport, six renderers — instead of six copies of an HTTP-send block.
- **Testability.** Renderers stay pure → trivially snapshot-comparable across tests. Transports are mocked once and reused.
- **Audit mode.** A future audit-only deployment swaps `HttpTransport` for a file or stdout transport without touching renderers.

### Why a single `NotificationHook`?

The broader hooks system already supports phases, priorities, and registration. Wrapping every per-service variation in its own `Hook` subclass duplicates the registration logic and produces N+ classes whose only differences live in their `execute()` body. One `NotificationHook` parameterised by (Transport, Renderer) handles everything.

### Why frozen `NotificationContext`?

`ExecutionContext` is mutable and the migration's live state. Renderers must not read past the moment of notification. Projecting into an immutable value object at fire time:

- Makes renderer outputs deterministic given identical inputs.
- Lets the renderer be tested without spinning up a migration.
- Prevents a slow renderer from observing a later context mutation.

---

## YAML Surface

The Pydantic models in `config.py` form a discriminated union on `type:`:

```python
TransportConfig = Annotated[
    HttpTransportConfig | SmtpTransportConfig | StdoutTransportConfig,
    Field(discriminator="type"),
]

RendererConfig = Annotated[
    SlackRendererConfig | DiscordRendererConfig | TeamsRendererConfig |
    EmailRendererConfig | PagerDutyRendererConfig | OpsGenieRendererConfig |
    RawJsonRendererConfig | JinjaRendererConfig,
    Field(discriminator="type"),
]
```

A `model_validator(mode="before")` pre-checks discriminator values against known sets and raises `ConfigurationError` with the valid options on a typo — Pydantic's default discriminator error (`"Input tag X not found in any of the expected tags"`) is replaced with a more actionable message.

`${VAR}` substitution runs at config-load time. Missing env vars raise `ConfigurationError` immediately rather than expanding to empty strings.

---

## Error Handling

`NotificationHook.execute()` swallows every error after logging it at WARNING. The contract: a migration never fails because a notification failed.

The transport classification:

- **2xx** — success, return.
- **4xx** — `_NonRetryableHttpError` → `HttpTransportError` on the **first attempt**. No retry; 4xx is a duplicate-notification risk for non-idempotent receivers.
- **5xx and connection errors** (`OSError`, `socket.gaierror`, `ssl.SSLError`, `ConnectionRefusedError`) — retried up to `retry.attempts` with exponential backoff.

The retry budget is per-attempt; the total wall-clock cap is the calling phase's hook timeout (separate from the transport's per-attempt `timeout_seconds`).

---

## SMTP Password Handling

The password handling in `SmtpTransport` is defense-in-depth:

1. `SmtpConfig.password` is a `pydantic.SecretStr`. `repr()`, `str()`, and `model_dump()` redact.
2. `_login_safely(server, cfg)` wraps `smtplib.SMTP.login(user, password)`. On exception, it walks `__traceback__` and truncates the chain at the first frame whose `f_locals` contains the cleartext password.

Without step 2, the password leaks via:

- `rich.traceback.Traceback.from_exception(..., show_locals=True)`
- Sentry's default exception capture
- `loguru.opt(exception=True)`

All three walk frame locals. `SecretStr` only protects its own `__repr__` — it does not mask the unwrapped string passed into `smtplib.SMTP.login`.

The truncation approach (rather than `f_locals` mutation) is robust: `PyFrame_LocalsToFast` doesn't round-trip for function fastlocals in CPython 3.11+. `tb_next` is settable on traceback objects since PEP 569 (Python 3.7), so we cut the chain at the leaky frame.

---

## Threading Considerations

`HttpTransport` uses stdlib `urllib.request.urlopen`. Caveat: `urllib`'s `timeout` parameter covers socket reads only — DNS resolution can hang independently. For receivers with unreliable DNS, configure the calling phase's hook timeout, not just `transport.timeout_seconds`.

The `JinjaRenderer` uses `threading.Timer` for render timeouts, **not** `signal.alarm`. `signal.alarm` is process-global and collides with parallel hook execution; it also doesn't fire under non-main threads.

---

## What Lives Where

```
python/confiture/core/hooks/notifications/
├── __init__.py             # public re-exports
├── context.py              # NotificationContext (frozen value object)
├── transport.py            # Transport ABC + HttpTransport + SmtpTransport + StdoutTransport
├── renderer.py             # Renderer ABC + Slack/Discord/Teams/Email/PagerDuty/OpsGenie/RawJson
├── jinja_renderer.py       # JinjaRenderer with v1 security envelope
├── config.py               # Pydantic discriminated-union YAML models
├── hook.py                 # NotificationHook itself
└── factory.py              # from_config() — builds hook from validated config
```

CLI surface lives in `python/confiture/cli/commands/hooks.py` — currently exposes `confiture hooks test`.

---

## See Also

- [Notifications Guide](../guides/notifications.md) — user-facing recipes.
- [Notification Context](notification-context.md) — Jinja context vars and security envelope.
- [Migration Hooks](../guides/hooks.md) — the broader hook system.
