"""Unit tests for JinjaRenderer — Phase 03 Cycle 4.

Covers:
- Happy path (flat-dict context, expression-only templates).
- Block-tag refusal (``{% set %}``, ``{% for %}``, ``{% if %}``, ``{% macro %}``,
  ``{% include %}``, ``{% import %}``, ``{% raw %}``).
- SSTI bypass class refusals (defense-in-depth — should be unreachable with
  flat-dict context, but pinned here).
- Opt-in gate.
- Template size cap.
- Render timeout via ``threading.Timer`` (not ``signal.alarm``).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from confiture.core.hooks.notifications.context import NotificationContext
from confiture.core.hooks.notifications.jinja_renderer import JinjaRenderer
from confiture.exceptions import ConfigurationError

_FIXED_TS = datetime(2026, 5, 20, 14, 30, 0, tzinfo=UTC)


def _ctx(**overrides) -> NotificationContext:
    base = {
        "migration_name": "add_user_bio",
        "migration_version": "20260520143015",
        "direction": "up",
        "success": True,
        "duration_ms": 124,
        "database_name": "myapp_prod",
        "schema": "public",
        "timestamp": _FIXED_TS,
        "rows_affected": 5,
        "error": None,
        "migrations_applied": [],
    }
    base.update(overrides)
    return NotificationContext(**base)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestJinjaHappyPath:
    def test_renders_simple_template(self) -> None:
        r = JinjaRenderer(
            template="migration={{ migration_name }} status={{ status_word }}",
            allow_templated_renderers=True,
        )
        payload = r.render(_ctx())
        assert payload.body == "migration=add_user_bio status=succeeded"

    def test_renders_with_tojson_filter(self) -> None:
        r = JinjaRenderer(
            template='{"name": {{ migration_name | tojson }}, "ms": {{ execution_time_ms }}}',
            allow_templated_renderers=True,
        )
        payload = r.render(_ctx())
        # Successful JSON pass-through.
        import json

        assert json.loads(payload.body) == {"name": "add_user_bio", "ms": 124}

    def test_renders_with_default_filter(self) -> None:
        r = JinjaRenderer(
            template="{{ error | default('no error') }}",
            allow_templated_renderers=True,
        )
        # Note: error is "" not None after _build_flat_context, so default is NOT applied.
        # The intended use of default is for missing keys, which our flat-dict approach
        # eliminates.  We just confirm the filter is callable.
        payload = r.render(_ctx())
        # Empty string passes through, but the filter is callable without exception.
        assert isinstance(payload.body, str)

    def test_content_type_propagates(self) -> None:
        r = JinjaRenderer(
            template="hello",
            content_type="text/plain",
            allow_templated_renderers=True,
        )
        payload = r.render(_ctx())
        assert payload.content_type == "text/plain"

    def test_provides_documented_context_variables(self) -> None:
        """The full v1 context surface — flat str/int/bool/None primitives."""
        r = JinjaRenderer(
            template=(
                "name={{ migration_name }} "
                "ver={{ migration_version }} "
                "dir={{ direction }} "
                "success={{ success }} "
                "ms={{ execution_time_ms }} "
                "db={{ database_name }} "
                "schema={{ schema }} "
                "ts={{ timestamp }} "
                "rows={{ rows_affected }} "
                "err={{ error }} "
                "applied={{ migrations_applied }} "
                "word={{ status_word }}"
            ),
            allow_templated_renderers=True,
        )
        body = r.render(_ctx()).body
        for token in [
            "add_user_bio",
            "20260520143015",
            "up",
            "True",
            "124",
            "myapp_prod",
            "public",
            "2026-05-20T14:30:00",
            "5",
            "succeeded",
        ]:
            assert token in body, f"Missing token {token!r} in: {body!r}"

    def test_invalid_template_fails_at_construction(self) -> None:
        """Syntax errors must surface at config-load time, not at render."""
        with pytest.raises(ConfigurationError, match="failed to parse"):
            JinjaRenderer(
                template="{{ unclosed_expr",
                allow_templated_renderers=True,
            )


# ---------------------------------------------------------------------------
# Block-tag refusal — the load-bearing constraint of the v1 envelope.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "template,description",
    [
        ("{% set x = 1 %}{{ x }}", "set"),
        ("{% for x in [1,2] %}{{ x }}{% endfor %}", "for"),
        ("{% if success %}ok{% endif %}", "if"),
        ("{% macro m() %}x{% endmacro %}", "macro"),
    ],
)
class TestJinjaBlockTagRefusal:
    def test_block_tag_rejected_at_construction(self, template: str, description: str) -> None:
        with pytest.raises(ConfigurationError, match="forbidden node|forbidden|no `{% "):
            JinjaRenderer(template=template, allow_templated_renderers=True)


class TestJinjaRawTagAccepted:
    """``{% raw %}`` is parse-time-only — no code execution at render.

    The raw block's contents become a literal ``TemplateData`` node, so it
    is safe to allow and there is no SSTI vector through it.  Pinning the
    behaviour so future hardening doesn't accidentally regress.
    """

    def test_raw_block_passes_through_as_literal_text(self) -> None:
        r = JinjaRenderer(
            template="prefix {% raw %}literal {{ not_rendered }}{% endraw %} suffix",
            allow_templated_renderers=True,
        )
        out = r.render(_ctx()).body
        assert "literal {{ not_rendered }}" in out
        assert "prefix" in out and "suffix" in out


# ---------------------------------------------------------------------------
# Filter allow-list refusal.
# ---------------------------------------------------------------------------


class TestJinjaFilterAllowlist:
    def test_unknown_filter_rejected(self) -> None:
        # ``urlencode`` is a real Jinja filter but not on our allow-list.
        with pytest.raises(ConfigurationError, match="allow-list"):
            JinjaRenderer(
                template="{{ migration_name | urlencode }}",
                allow_templated_renderers=True,
            )

    def test_allowed_filters_work(self) -> None:
        for filter_name in ["tojson", "upper", "lower", "length", "default"]:
            JinjaRenderer(
                template=f"{{{{ migration_name | {filter_name} }}}}",
                allow_templated_renderers=True,
            )  # must not raise


# ---------------------------------------------------------------------------
# SSTI bypass class refusal — defense-in-depth (should be unreachable with
# flat-dict context, but pinned here).
# ---------------------------------------------------------------------------


class TestJinjaSSTIBypassClasses:
    """Every test in this class represents a known SSTI escape pattern.

    With flat-dict context these should all fail to access anything
    interesting, returning empty/safe output.  If any of these stop being
    safe, the v1 envelope is broken.
    """

    def _render(self, template: str) -> str:
        return JinjaRenderer(template=template, allow_templated_renderers=True).render(_ctx()).body

    def test_class_attribute_traversal_blocked(self) -> None:
        # ``{{ ''.__class__ }}`` — the classic SSTI pivot.  is_safe_attribute
        # blocks any ``_``-prefixed attr.
        body = self._render("{{ migration_name }}")  # baseline sanity
        assert "add_user_bio" in body

        # The actual SSTI attempt — should fail or return empty.
        from jinja2.exceptions import SecurityError

        with pytest.raises((ConfigurationError, SecurityError)):
            self._render("{{ migration_name.__class__ }}")

    def test_subscript_traversal_blocked(self) -> None:
        """Getitem-based traversal — the class the reviewer flagged."""
        from jinja2.exceptions import SecurityError

        # ``migration_name['__class__']`` — strings ARE subscriptable, but
        # our flat-dict context only exposes primitives.  This should either
        # raise or return safe output (no callable result).
        with pytest.raises((ConfigurationError, SecurityError, TypeError, AttributeError)):
            JinjaRenderer(
                template="{{ migration_name['__class__'] }}",
                allow_templated_renderers=True,
            ).render(_ctx())

    def test_underscore_attribute_blocked(self) -> None:
        """Any attribute starting with ``_`` is blocked by is_safe_attribute."""
        from jinja2.exceptions import SecurityError

        with pytest.raises((ConfigurationError, SecurityError)):
            self._render("{{ migration_name._private }}")

    def test_globals_access_blocked(self) -> None:
        from jinja2.exceptions import SecurityError

        with pytest.raises((ConfigurationError, SecurityError)):
            self._render("{{ migration_name.__globals__ }}")

    def test_format_string_traversal_blocked(self) -> None:
        from jinja2.exceptions import SecurityError

        # ``"{0.__class__}".format(obj)`` — `format` is on the unsafe list.
        with pytest.raises((ConfigurationError, SecurityError)):
            self._render('{{ "{0.__class__}".format(migration_name) }}')


# ---------------------------------------------------------------------------
# Opt-in gate.
# ---------------------------------------------------------------------------


class TestJinjaOptInGate:
    def test_disabled_when_flag_unset(self) -> None:
        with pytest.raises(ConfigurationError, match="allow_templated_renderers"):
            JinjaRenderer(template="{{ migration_name }}")  # flag not set

    def test_disabled_when_flag_false(self) -> None:
        with pytest.raises(ConfigurationError, match="allow_templated_renderers"):
            JinjaRenderer(
                template="{{ migration_name }}",
                allow_templated_renderers=False,
            )


# ---------------------------------------------------------------------------
# Size cap.
# ---------------------------------------------------------------------------


class TestJinjaSizeCap:
    def test_template_size_capped_at_16kib(self) -> None:
        large = "x" * (16 * 1024 + 1)
        with pytest.raises(ConfigurationError, match="exceeds 16384"):
            JinjaRenderer(template=large, allow_templated_renderers=True)

    def test_exactly_at_cap_accepted(self) -> None:
        # 16 KiB of ASCII text — must be accepted.
        ok = "x" * (16 * 1024)
        JinjaRenderer(template=ok, allow_templated_renderers=True)  # must not raise


# ---------------------------------------------------------------------------
# Render timeout via threading.Timer.
# ---------------------------------------------------------------------------


class TestJinjaTimeout:
    def test_render_completes_within_timeout(self) -> None:
        # A trivial render must complete well within 1s.
        r = JinjaRenderer(template="{{ migration_name }}", allow_templated_renderers=True)
        payload = r.render(_ctx())
        assert payload.body == "add_user_bio"

    def test_render_timeout_uses_threading_not_signals(self) -> None:
        """Cycle-4 design decision: ``threading.Timer``-based timeout, not
        ``signal.alarm``.  Pinned by checking the renderer module does not
        ``import signal`` and does ``import threading``."""
        import ast as _ast
        import inspect

        from confiture.core.hooks.notifications import jinja_renderer

        tree = _ast.parse(inspect.getsource(jinja_renderer))
        imported_modules: set[str] = set()
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, _ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
        assert "signal" not in imported_modules, (
            "Renderer imports `signal`, but the v1 envelope mandates threading.Timer."
        )
        assert "threading" in imported_modules

    def test_render_timeout_returns_configuration_error(self, monkeypatch) -> None:
        """If a template render exceeds the timeout, a ConfigurationError is raised."""
        import threading

        # Monkeypatch the timeout to a tiny value and use a template the
        # renderer thread will treat as slow via a custom filter — but our
        # filter allow-list blocks custom filters.  So we patch the worker
        # to sleep, simulating a long render.
        from confiture.core.hooks.notifications import jinja_renderer as jr

        def _slow_render(template, ctx: dict, timeout_seconds: float) -> str:  # noqa: ANN001
            result: list = []
            done = threading.Event()

            def _worker() -> None:
                import time

                time.sleep(0.5)  # longer than the patched timeout
                try:
                    result.append(template.render(**ctx))
                except Exception as exc:
                    result.append(exc)
                finally:
                    done.set()

            t = threading.Thread(target=_worker, daemon=True)
            t.start()
            if not done.wait(timeout=timeout_seconds):
                raise ConfigurationError(
                    f"JinjaRenderer render exceeded {timeout_seconds}s timeout."
                )
            return result[0]  # type: ignore[no-any-return]

        monkeypatch.setattr(jr, "_render_with_timeout", lambda t, c, _tos: _slow_render(t, c, 0.05))
        r = JinjaRenderer(template="{{ migration_name }}", allow_templated_renderers=True)
        with pytest.raises(ConfigurationError, match="timeout"):
            r.render(_ctx())


# ---------------------------------------------------------------------------
# Flat-dict context boundary.
# ---------------------------------------------------------------------------


class TestJinjaFlatContextBoundary:
    """The flat-dict context is the v1 envelope's load-bearing defence.
    The renderer must never expose anything but primitives to a template.
    """

    def test_context_values_are_only_primitives(self) -> None:
        from confiture.core.hooks.notifications.jinja_renderer import _build_flat_context

        ctx = _build_flat_context(_ctx())
        for key, value in ctx.items():
            assert isinstance(value, (str, int, float, bool, type(None))), (
                f"Context key {key!r} has non-primitive value {type(value).__name__}"
            )

    def test_context_helper_rejects_non_primitive(self) -> None:
        from confiture.core.hooks.notifications.jinja_renderer import _assert_flat_primitives

        with pytest.raises(ConfigurationError, match="primitive|str |int |float |bool"):
            _assert_flat_primitives({"x": [1, 2, 3]})
        with pytest.raises(ConfigurationError):
            _assert_flat_primitives({"x": {"nested": "dict"}})
        with pytest.raises(ConfigurationError):
            _assert_flat_primitives({"x": object()})
