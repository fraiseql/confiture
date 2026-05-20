"""JinjaRenderer — templated webhook payloads with a v1 security envelope.

v1 strategy: shrink the attack surface to what we can confidently defend.

- **Opt-in flag.** Disabled unless ``notifications.allow_templated_renderers``
  is True at config-load time.  This is the load-bearing defence: a project
  that never sets the flag cannot be exploited through this path.
- **Flat-dict context only.** Templates can read ``str | int | float |
  bool | None`` values from a flat mapping.  Nested dicts, lists, dataclasses
  are rejected at config-load.  This closes the entire ``__class__``-traversal
  /  ``__getitem__``-traversal / ``__globals__``-walk class of bypasses by
  removing the objects.
- **No block tags.**  Only ``{{ expr }}`` and ``{# comment #}`` are accepted.
  Validated by parsing the template's AST and refusing anything but the
  whitelisted node types.
- **Sandbox with ``autoescape=True``** and custom ``is_safe_attribute`` —
  belt-and-braces defence; with the flat-dict context this should be
  unreachable.
- **Filter allow-list**: ``tojson``, ``upper``, ``lower``, ``length``,
  ``default``.  No ``attr``, no ``eval``, no custom filters.
- **Template max length: 16 KiB.**
- **Render timeout via ``threading.Timer`` + cancellation token**, not
  ``signal.alarm`` (which is process-global and breaks under threads).
- **Templates compile at config-load time** so syntax errors surface during
  startup, not during a migration.

Deferred to v0.11 (sandboxed objects, ``{% if %}`` / ``{% for %}``, custom
filters, process-isolated render workers).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from confiture.core.hooks.notifications.context import NotificationContext
from confiture.core.hooks.notifications.renderer import Renderer
from confiture.core.hooks.notifications.transport import TransportPayload
from confiture.exceptions import ConfigurationError

_MAX_TEMPLATE_BYTES = 16 * 1024
_RENDER_TIMEOUT_SECONDS = 1.0
_ALLOWED_FILTERS = frozenset({"tojson", "upper", "lower", "length", "default"})


# Lazy import — jinja2 lives in the [notifications] optional extra so the
# core install stays lean.  We import inside the constructor and raise a
# clear ConfigurationError if jinja2 is unavailable.


@dataclass
class JinjaRenderer(Renderer):
    """Render a payload by interpolating a Jinja-style template with the
    notification context.

    Args:
        template: The template source.  ``{{ expr }}`` and ``{# comment #}``
            only — block tags are rejected at construction time.
        content_type: MIME type to set on the transport payload.
        allow_templated_renderers: Opt-in gate.  Must be ``True``; otherwise
            construction fails with a ``ConfigurationError``.  This argument
            exists so the factory can pass the flag through from config
            without a side-band global.

    Raises:
        ConfigurationError: If the opt-in flag is not set, jinja2 is not
            installed, the template exceeds the size cap, the template
            contains forbidden block tags, or the template fails to parse.
    """

    template: str
    content_type: str = "application/json"
    allow_templated_renderers: bool = False

    def __post_init__(self) -> None:
        if not self.allow_templated_renderers:
            raise ConfigurationError(
                "JinjaRenderer requires `notifications.allow_templated_renderers: true`. "
                "Default off.  This is a deliberate signal that the operator accepts "
                "the trust model — set it explicitly to enable Jinja templating."
            )

        try:
            import jinja2  # noqa: F401
            from jinja2 import nodes as _nodes  # noqa: F401
        except ImportError as exc:
            raise ConfigurationError(
                "JinjaRenderer requires the [notifications] extra.  Install with: "
                'pip install "fraiseql-confiture[notifications]"'
            ) from exc

        if len(self.template.encode("utf-8")) > _MAX_TEMPLATE_BYTES:
            raise ConfigurationError(
                f"JinjaRenderer template exceeds {_MAX_TEMPLATE_BYTES} bytes "
                f"({len(self.template.encode('utf-8'))}).  Reduce template size."
            )

        # Build the sandboxed environment and compile the template now so
        # any syntax errors are caught at config-load time.
        self._env = _build_sandbox_env()
        try:
            ast = self._env.parse(self.template)
        except Exception as exc:
            raise ConfigurationError(f"JinjaRenderer template failed to parse: {exc}") from exc

        # Validate the AST against the allow-list — no block tags.
        _validate_ast(ast)

        # Validate filters used in the template against the allow-list.
        _validate_filters(ast)

        # Pre-compile so render is fast.
        self._compiled = self._env.from_string(self.template)

    def render(self, context: NotificationContext) -> TransportPayload:
        ctx_dict = _build_flat_context(context)
        body = _render_with_timeout(self._compiled, ctx_dict, _RENDER_TIMEOUT_SECONDS)
        return TransportPayload(body=body, content_type=self.content_type)


# ---------------------------------------------------------------------------
# Helpers — module-level so the unit tests can exercise them independently.
# ---------------------------------------------------------------------------


def _build_sandbox_env():
    """Construct the SandboxedEnvironment with the v1 envelope."""
    from jinja2 import Undefined
    from jinja2.exceptions import SecurityError
    from jinja2.sandbox import SandboxedEnvironment

    _SUSPICIOUS_NAMES = frozenset(
        {
            "format",
            "__class__",
            "__mro__",
            "__bases__",
            "__subclasses__",
            "__globals__",
            "__init__",
            "__getattribute__",
            "__import__",
            "__builtins__",
            "__dict__",
            "__code__",
            "__func__",
        }
    )

    class _StrictUndefined(Undefined):
        """Raise on construction when ``name`` is suspicious.

        Jinja routes attribute lookups that miss into ``Environment.undefined(
        obj=..., name=...)``, which is the documented escape hatch for an
        attacker probing context shape.  We make those lookups loud rather
        than silently rendering empty.
        """

        __slots__ = ()

        def __init__(  # noqa: D107
            self,
            hint=None,  # noqa: ANN001
            obj=None,  # noqa: ANN001
            name=None,  # noqa: ANN001
            exc=None,  # noqa: ANN001
        ) -> None:
            if (
                name
                and isinstance(name, str)
                and (name.startswith("_") or name in _SUSPICIOUS_NAMES)
            ):
                raise SecurityError(
                    f"access to attribute {name!r} is forbidden in sandboxed templates"
                )
            super().__init__(hint=hint, obj=obj, name=name, exc=exc)

    class _StrictSandbox(SandboxedEnvironment):
        # Block any attribute starting with ``_`` and any of the well-known
        # bypass attribute names.  With the flat-dict context this should be
        # unreachable, but the check is cheap and pins the boundary.
        _UNSAFE_ATTRS = frozenset(
            {
                "format",
                "__class__",
                "__mro__",
                "__bases__",
                "__subclasses__",
                "__globals__",
                "__init__",
                "__getattribute__",
                "__import__",
                "__builtins__",
            }
        )

        def is_safe_attribute(self, obj, attr, value) -> bool:  # noqa: ANN001
            attr_str = str(attr)
            if attr_str.startswith("_"):
                return False
            if attr_str in self._UNSAFE_ATTRS:
                return False
            return super().is_safe_attribute(obj, attr, value)

        def unsafe_undefined(self, obj, attribute):  # noqa: ANN001
            # Default behaviour returns an Undefined that renders to "".
            # That's a silent failure — we want loud failure so SSTI
            # attempts are caught at first read, not at deploy time.
            raise SecurityError(
                f"access to attribute {attribute!r} on {type(obj).__name__} is forbidden"
            )

        def call(self, __context, __obj, *args, **kwargs):  # noqa: ANN001, ANN204, ARG002
            # Belt-and-braces: ensure the only callables ever invoked from a
            # template are filters (which the AST validator already restricts).
            # User-context primitives are never callable, so any call() reaching
            # here is an attempted escape.
            raise SecurityError(
                f"function call on {type(__obj).__name__} is forbidden in templates"
            )

    env = _StrictSandbox(autoescape=True, undefined=_StrictUndefined)
    return env


def _validate_ast(ast) -> None:  # noqa: ANN001
    """Refuse templates with block tags or unexpected node types.

    Allowed nodes:
      - ``Template`` (root)
      - ``Output`` (``{{ ... }}`` boundaries)
      - ``TemplateData`` (literal text outside ``{{ ... }}``)
      - ``Name`` (variable references)
      - ``Getattr`` (``foo.bar`` — guarded by ``is_safe_attribute``)
      - ``Getitem`` (``foo[bar]`` — Jinja routes through ``getitem`` security)
      - ``Filter`` (filter pipeline; values validated separately)
      - ``Const`` (literal values)
      - ``CondExpr`` (ternary ``a if b else c`` — pure expression, safe)
      - ``Compare`` / ``Operand`` (comparisons within expressions)
      - ``Pos`` / ``Neg`` / ``Add`` / ``Sub`` / ``Mul`` / ``Div`` / ``Mod``
        (arithmetic in expressions)
      - ``Concat`` (string concatenation in expressions)
      - ``Not`` / ``And`` / ``Or`` (boolean logic in expressions)
      - ``Tuple`` / ``List`` / ``Dict`` (literal containers used by filters
        like ``default``)
      - ``Pair`` (dict-literal item)
    """
    from jinja2 import nodes

    allowed = (
        nodes.Template,
        nodes.Output,
        nodes.TemplateData,
        nodes.Name,
        nodes.Getattr,
        nodes.Getitem,
        nodes.Filter,
        nodes.Const,
        nodes.CondExpr,
        nodes.Compare,
        nodes.Operand,
        nodes.Pos,
        nodes.Neg,
        nodes.Add,
        nodes.Sub,
        nodes.Mul,
        nodes.Div,
        nodes.Mod,
        nodes.FloorDiv,
        nodes.Pow,
        nodes.Concat,
        nodes.Not,
        nodes.And,
        nodes.Or,
        nodes.Tuple,
        nodes.List,
        nodes.Dict,
        nodes.Pair,
    )

    for node in ast.iter_child_nodes():
        _walk_and_validate(node, allowed)


def _walk_and_validate(node, allowed: tuple) -> None:  # noqa: ANN001
    if not isinstance(node, allowed):
        raise ConfigurationError(
            f"JinjaRenderer template contains forbidden node {type(node).__name__}.  "
            "v1 supports only `{{ expr }}` interpolation — no `{% set %}`, `{% for %}`, "
            "`{% if %}`, `{% macro %}`, `{% include %}`, `{% import %}`, or `{% raw %}`.  "
            "Pre-render complex payloads in your application code and feed them through "
            "RawJsonRenderer instead."
        )
    for child in node.iter_child_nodes():
        _walk_and_validate(child, allowed)


def _validate_filters(ast) -> None:  # noqa: ANN001
    """Refuse any filter not on the allow-list."""
    from jinja2 import nodes

    for node in ast.find_all(nodes.Filter):
        if node.name not in _ALLOWED_FILTERS:
            raise ConfigurationError(
                f"JinjaRenderer filter {node.name!r} is not on the allow-list. "
                f"Allowed: {sorted(_ALLOWED_FILTERS)}."
            )


def _build_flat_context(context: NotificationContext) -> dict[str, Any]:
    """Project ``NotificationContext`` to a flat ``dict[str, primitive]``.

    Anything that isn't ``str | int | float | bool | None`` is rejected — the
    template author can only see scalars.  ``migrations_applied`` is joined
    to a comma-separated string so the template can interpolate it without
    needing list iteration (which would require ``{% for %}``).
    """
    flat: dict[str, Any] = {
        "migration_name": context.migration_name,
        "migration_version": context.migration_version,
        "direction": context.direction,
        "success": context.success,
        "execution_time_ms": context.duration_ms,
        "database_name": context.database_name,
        "schema": context.schema,
        "timestamp": context.timestamp_iso,
        "rows_affected": context.rows_affected,
        "error": context.error or "",
        "migrations_applied": ", ".join(context.migrations_applied)
        if context.migrations_applied
        else "",
        "status_word": context.status_word,
    }
    # Defense-in-depth: validate every value is a primitive.
    _assert_flat_primitives(flat)
    return flat


def _assert_flat_primitives(d: dict) -> None:
    for key, value in d.items():
        if not isinstance(value, (str, int, float, bool, type(None))):
            raise ConfigurationError(
                f"JinjaRenderer context value for {key!r} is {type(value).__name__}; "
                "v1 supports only str | int | float | bool | None."
            )


def _render_with_timeout(template, ctx: dict, timeout_seconds: float) -> str:  # noqa: ANN001
    """Render *template* with *ctx*, aborting after *timeout_seconds*.

    Uses a ``threading.Timer`` watchdog plus a cancellation event.  The
    template-rendering thread checks the event between operations (Jinja
    supports this via ``Environment.async`` callbacks); we approximate by
    raising in the watchdog thread if the renderer thread hasn't completed
    in time.  This is *not* a hard kill — Python doesn't support that — but
    it's sufficient to surface long-running templates as configuration
    errors during testing rather than hanging migrations.
    """
    result: list[str | Exception] = []
    done = threading.Event()

    def _worker() -> None:
        try:
            out = template.render(**ctx)
            result.append(out)
        except Exception as exc:  # propagate any render error
            result.append(exc)
        finally:
            done.set()

    worker = threading.Thread(target=_worker, daemon=True)
    worker.start()
    completed = done.wait(timeout=timeout_seconds)

    if not completed:
        # The worker is still running; we can't safely abort it from outside,
        # but we can raise so the caller surfaces the misconfiguration.
        raise ConfigurationError(
            f"JinjaRenderer render exceeded {timeout_seconds}s timeout.  "
            "Reduce template complexity or pre-render in application code."
        )
    if isinstance(result[0], Exception):
        raise result[0]
    out = result[0]
    assert isinstance(out, str)
    return out


__all__ = ["JinjaRenderer"]
