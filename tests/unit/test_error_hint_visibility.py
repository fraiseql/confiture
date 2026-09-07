"""Issue #211: a resolution_hint must survive rendering by ``str()``.

``ConfiturError`` computes actionable guidance at 200+ raise sites. Before
#211 it reached a human only through the CLI's Rich renderer or the JSON
envelope, so every library consumer — pytest fixtures, orchestration code,
plain logging — dropped it.

The hint now rides on ``__str__``. That makes a hint-free accessor mandatory:
the in-tree renderers print the hint from the attribute (printing it twice
otherwise) and two classifiers keyword-match the message (matching hint text
otherwise). Both read :attr:`ConfiturError.message`.
"""

from __future__ import annotations

import json

from confiture.cli.error_json import coerce_to_confiture_error, emit_error_json
from confiture.core.error_handler import (
    _detect_error_context,
    format_error_for_cli,
    get_error_context,
)
from confiture.exceptions import ConfigurationError, ConfiturError, SQLError


class TestStrCarriesTheHint:
    """``str(exc)`` is the only surface most library consumers ever see."""

    def test_str_appends_the_hint(self) -> None:
        error = ConfigurationError(
            "Refusing to replace database 'x': it exists and is not confiture-managed.",
            error_code="CONFIG_010",
            resolution_hint="Choose a different --template name, or pass --force.",
        )

        rendered = str(error)

        assert rendered.startswith(
            "Refusing to replace database 'x': it exists and is not confiture-managed."
        )
        assert "Choose a different --template name, or pass --force." in rendered

    def test_hint_is_on_its_own_line(self) -> None:
        error = ConfiturError("boom", resolution_hint="do the thing")

        assert str(error).splitlines() == ["boom", "Hint: do the thing"]

    def test_str_unchanged_without_a_hint(self) -> None:
        assert str(ConfiturError("boom")) == "boom"
        assert str(ConfigurationError("Config error")) == "Config error"

    def test_empty_hint_is_not_rendered(self) -> None:
        assert str(ConfiturError("boom", resolution_hint="")) == "boom"

    def test_hint_survives_a_computed_subclass_message(self) -> None:
        """SQLError builds its own message; the hint still lands after it."""
        error = SQLError(
            "SELECT 1",
            None,
            RuntimeError("db error"),
            resolution_hint="Check the statement syntax.",
        )

        assert str(error).startswith("SQL execution failed | SQL: SELECT 1")
        assert str(error).endswith("Hint: Check the statement syntax.")

    def test_pytest_raises_match_still_works(self) -> None:
        """``match=`` searches ``str(exc)``; a suffix must not break it."""
        import pytest

        with pytest.raises(ConfiturError, match=r"^boom"):
            raise ConfiturError("boom", resolution_hint="try harder")


class TestMessageIsHintFree:
    """The base message stays reachable for renderers and classifiers."""

    def test_message_excludes_the_hint(self) -> None:
        error = ConfiturError("boom", resolution_hint="do the thing")

        assert error.message == "boom"

    def test_message_without_a_hint(self) -> None:
        assert ConfiturError("boom").message == "boom"

    def test_message_of_a_computed_subclass(self) -> None:
        error = SQLError("SELECT 1", None, RuntimeError("db error"))

        assert error.message.startswith("SQL execution failed")
        assert "Hint:" not in error.message


class TestRenderersDoNotDuplicate:
    """CLI and JSON already render the hint from the attribute."""

    def test_cli_renders_the_hint_once(self) -> None:
        error = ConfigurationError(
            "Missing field",
            error_code="CONFIG_001",
            resolution_hint="Add the field to config",
        )

        output = format_error_for_cli(error)

        assert output.count("Add the field to config") == 1
        assert "💡 Add the field to config" in output

    def test_json_envelope_message_is_hint_free(self) -> None:
        error = ConfigurationError(
            "Missing field",
            error_code="CONFIG_001",
            resolution_hint="Add the field to config",
        )

        envelope = emit_error_json(error)

        assert envelope["error"]["message"] == "Missing field"
        assert envelope["error"]["actionable"] == "Add the field to config"
        json.dumps(envelope)

    def test_to_dict_message_is_hint_free(self) -> None:
        error = ConfiturError("boom", resolution_hint="do the thing")

        payload = error.to_dict()

        assert payload["message"] == "boom"
        assert payload["resolution_hint"] == "do the thing"

    def test_coerced_foreign_exception_is_unaffected(self) -> None:
        coerced = coerce_to_confiture_error(RuntimeError("kaboom"))

        assert coerced.message == "kaboom"
        assert str(coerced) == "kaboom"

    def test_get_error_context_of_a_plain_exception(self) -> None:
        assert get_error_context(RuntimeError("kaboom")) == {"message": "kaboom"}


class TestClassifiersReadTheBaseMessage:
    """Keyword classifiers must not match on hint text."""

    def test_hint_keywords_do_not_retarget_the_context_template(self) -> None:
        """A seed-file error whose hint mentions the database URL is not a
        connection failure."""
        error = ConfigurationError(
            "Seed file not found: db/seeds/010_users.sql",
            resolution_hint="Check the database URL in local.yaml if this looks wrong.",
        )

        assert _detect_error_context(error) != "DB_CONNECTION_FAILED"

    def test_hint_keywords_do_not_escalate_to_permission_denied(self) -> None:
        error = ConfigurationError(
            "Could not connect to the database.",
            resolution_hint="Permission denied usually means a bad role; check pg_hba.conf.",
        )

        assert _detect_error_context(error) == "DB_CONNECTION_FAILED"

    def test_genuine_message_keywords_still_classify(self) -> None:
        error = ConfigurationError("Database connection failed: timeout")

        assert _detect_error_context(error) == "DB_CONNECTION_FAILED"
