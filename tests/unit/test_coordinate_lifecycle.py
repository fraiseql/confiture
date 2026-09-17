"""Every documented intent status is reachable from the CLI (issue #286).

`coordinate list-intents --status-filter` documents six statuses. Three of them
could not be produced by anything a user could run:

    registered    set by `coordinate register`
    conflicted    set by the registry during `coordinate check`
    abandoned     set by `coordinate abandon`
    in_progress   IntentRegistry.mark_in_progress — no caller but a docstring
    completed     IntentRegistry.mark_completed   — no caller at all
    merged        IntentRegistry.mark_merged      — no caller at all

The issue named `completed` and `merged`. `in_progress` is the same gap and was
not reported: an agent could neither say it had started nor that it had
finished, and the only terminal transition it had, `abandon`, records the
opposite outcome and demands a `--reason` for it.

The registry has had all four `mark_*` methods since it was written. What was
missing was three commands.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.integrations.pggit.coordination import Intent, IntentStatus, RiskLevel

runner = CliRunner()

#: Which registry call each new command must make. The CLI's whole job here is
#: to reach the right transition, so that is what the test asserts.
TRANSITIONS = {
    "start": ("mark_in_progress", IntentStatus.IN_PROGRESS),
    "complete": ("mark_completed", IntentStatus.COMPLETED),
    "merge": ("mark_merged", IntentStatus.MERGED),
    "abandon": ("mark_abandoned", IntentStatus.ABANDONED),
}

#: Statuses no transition command sets, and what sets them instead. An entry
#: that stops being true fails `test_every_status_is_accounted_for`.
SET_ELSEWHERE = {
    IntentStatus.REGISTERED: "coordinate register, when the intent is created",
    IntentStatus.CONFLICTED: "the registry itself, during coordinate check",
}


def _intent(intent_id: str) -> Intent:
    return Intent(
        id=intent_id,
        agent_id="claude-test",
        feature_name="test_feature",
        branch_name="feature/test_feature_001",
        schema_changes=[],
        tables_affected=[],
        status=IntentStatus.REGISTERED,
        risk_level=RiskLevel.LOW,
    )


def _run(command: str, *extra: str):
    intent_id = str(uuid4())
    with (
        patch("confiture.cli.coordinate._get_connection") as get_conn,
        patch("confiture.cli.coordinate.IntentRegistry") as registry_class,
    ):
        get_conn.return_value = MagicMock()
        registry = MagicMock()
        registry_class.return_value = registry
        registry.get_intent.return_value = _intent(intent_id)
        result = runner.invoke(app, ["coordinate", command, "--intent-id", intent_id, *extra])
    return result, registry, intent_id


class TestEveryStatusIsReachable:
    def test_every_status_is_accounted_for(self):
        """No documented status is left without a way to produce it."""
        produced = {status for _, status in TRANSITIONS.values()}
        unreachable = sorted(
            s.value for s in IntentStatus if s not in produced and s not in SET_ELSEWHERE
        )
        assert unreachable == [], (
            f"{unreachable} can be filtered for but nothing sets them. Add a "
            f"coordinate command, or record what sets it in SET_ELSEWHERE."
        )

    def test_no_stale_entry_in_the_elsewhere_table(self):
        """A reason cannot outlive the status it explains."""
        assert set(SET_ELSEWHERE) <= set(IntentStatus)

    @pytest.mark.parametrize("command", sorted(TRANSITIONS))
    def test_the_command_exists(self, command: str):
        result = runner.invoke(app, ["coordinate", command, "--help"])
        assert result.exit_code == 0, result.output


class TestTheTransitionsAreRecorded:
    @pytest.mark.parametrize("command", ["start", "complete", "merge"])
    def test_the_command_calls_its_registry_transition(self, command: str):
        method, _status = TRANSITIONS[command]
        result, registry, intent_id = _run(command)
        assert result.exit_code == 0, result.output
        getattr(registry, method).assert_called_once()
        assert getattr(registry, method).call_args.args[0] == intent_id

    @pytest.mark.parametrize("command", ["start", "complete", "merge"])
    def test_no_other_transition_is_called(self, command: str):
        """`complete` must not abandon the intent, which is what it replaced."""
        _result, registry, _ = _run(command)
        for other, (method, _) in TRANSITIONS.items():
            if other != command:
                getattr(registry, method).assert_not_called()

    @pytest.mark.parametrize("command", ["start", "complete", "merge"])
    def test_a_missing_intent_is_an_error(self, command: str):
        with (
            patch("confiture.cli.coordinate._get_connection") as get_conn,
            patch("confiture.cli.coordinate.IntentRegistry") as registry_class,
        ):
            get_conn.return_value = MagicMock()
            registry = MagicMock()
            registry_class.return_value = registry
            registry.get_intent.return_value = None
            result = runner.invoke(app, ["coordinate", command, "--intent-id", "nope"])
        assert result.exit_code != 0
        getattr(registry, TRANSITIONS[command][0]).assert_not_called()

    @pytest.mark.parametrize("command", ["start", "complete", "merge"])
    def test_notes_reach_the_registry_as_the_reason(self, command: str):
        method, _ = TRANSITIONS[command]
        _result, registry, _ = _run(command, "--notes", "ship it")
        assert "ship it" in str(getattr(registry, method).call_args)

    @pytest.mark.parametrize("command", ["start", "complete", "merge"])
    def test_json_output_names_the_new_status(self, command: str):
        import json

        _method, status = TRANSITIONS[command]
        result, registry, intent_id = _run(command, "--format", "json")
        registry.get_intent.return_value = _intent(intent_id)
        payload = json.loads(result.output)
        assert payload["intent_id"] == intent_id
        assert payload["status"] == status.value


class TestCompleteIsNotAbandon:
    """The repair the docs campaign refused to make: `abandon` is the opposite."""

    def test_complete_does_not_require_a_reason(self):
        result, _registry, _ = _run("complete")
        assert result.exit_code == 0, result.output

    def test_abandon_still_requires_one(self):
        intent_id = str(uuid4())
        result = runner.invoke(app, ["coordinate", "abandon", "--intent-id", intent_id])
        assert result.exit_code != 0
