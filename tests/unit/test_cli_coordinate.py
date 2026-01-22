"""Tests for coordinate CLI commands.

These tests verify the coordinate command integrates properly with the CLI framework,
including command parsing, validation, output formatting, and error handling.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from typer.testing import CliRunner

from confiture.cli.main import app
from confiture.integrations.pggit.coordination import (
    ConflictReport,
    ConflictSeverity,
    ConflictType,
    Intent,
    IntentStatus,
    RiskLevel,
)

# Create test runner
runner = CliRunner()


class TestCoordinateRegisterCommand:
    """Tests for 'confiture coordinate register' command."""

    @patch("confiture.cli.coordinate._get_connection")
    @patch("confiture.cli.coordinate.IntentRegistry")
    def test_register_basic(self, mock_registry_class, mock_get_connection):
        """Should register an intention with required options."""
        # Mock connection
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        # Mock registry
        mock_registry = MagicMock()
        mock_registry_class.return_value = mock_registry

        # Mock registered intent
        intent_id = str(uuid4())
        mock_intent = Intent(
            id=intent_id,
            agent_id="claude-test",
            feature_name="test_feature",
            branch_name="feature/test_feature_001",
            schema_changes=["ALTER TABLE users ADD COLUMN test TEXT"],
            tables_affected=["users"],
            status=IntentStatus.REGISTERED,
            risk_level=RiskLevel.LOW,
        )
        mock_registry.register.return_value = mock_intent
        mock_registry.get_conflicts.return_value = []

        # Run command
        result = runner.invoke(
            app,
            [
                "coordinate",
                "register",
                "--agent-id",
                "claude-test",
                "--feature-name",
                "test_feature",
                "--schema-changes",
                "ALTER TABLE users ADD COLUMN test TEXT",
            ],
        )

        # Should succeed
        assert result.exit_code == 0
        assert "Intention Registered" in result.stdout
        assert "claude-test" in result.stdout
        assert "test_feature" in result.stdout
        assert mock_registry.register.called

    @patch("confiture.cli.coordinate._get_connection")
    @patch("confiture.cli.coordinate.IntentRegistry")
    def test_register_with_all_options(self, mock_registry_class, mock_get_connection):
        """Should register intention with all optional parameters."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_registry = MagicMock()
        mock_registry_class.return_value = mock_registry

        intent_id = str(uuid4())
        mock_intent = Intent(
            id=intent_id,
            agent_id="claude-payments",
            feature_name="stripe_integration",
            branch_name="feature/stripe_integration_001",
            schema_changes=["ALTER TABLE users ADD COLUMN stripe_id TEXT"],
            tables_affected=["users", "payments"],
            status=IntentStatus.REGISTERED,
            risk_level=RiskLevel.MEDIUM,
        )
        mock_registry.register.return_value = mock_intent
        mock_registry.get_conflicts.return_value = []

        result = runner.invoke(
            app,
            [
                "coordinate",
                "register",
                "--agent-id",
                "claude-payments",
                "--feature-name",
                "stripe_integration",
                "--schema-changes",
                "ALTER TABLE users ADD COLUMN stripe_id TEXT",
                "--tables-affected",
                "users,payments",
                "--risk-level",
                "medium",
                "--estimated-hours",
                "2.5",
            ],
        )

        assert result.exit_code == 0
        assert "stripe_integration" in result.stdout
        assert mock_registry.register.called

        # Verify register was called with correct parameters
        call_kwargs = mock_registry.register.call_args[1]
        assert call_kwargs["agent_id"] == "claude-payments"
        assert call_kwargs["feature_name"] == "stripe_integration"
        assert call_kwargs["risk_level"] == "medium"
        assert call_kwargs["estimated_duration_ms"] == int(2.5 * 3600 * 1000)

    @patch("confiture.cli.coordinate._get_connection")
    @patch("confiture.cli.coordinate.IntentRegistry")
    def test_register_with_conflicts(self, mock_registry_class, mock_get_connection):
        """Should display conflicts if detected during registration."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_registry = MagicMock()
        mock_registry_class.return_value = mock_registry

        intent_id = str(uuid4())
        mock_intent = Intent(
            id=intent_id,
            agent_id="claude-test",
            feature_name="test_feature",
            branch_name="feature/test_feature_001",
            schema_changes=["ALTER TABLE users ADD COLUMN test TEXT"],
            tables_affected=["users"],
            status=IntentStatus.REGISTERED,
            risk_level=RiskLevel.LOW,
        )
        mock_registry.register.return_value = mock_intent

        # Mock conflicts
        conflict = ConflictReport(
            intent_a=intent_id,
            intent_b=str(uuid4()),
            conflict_type=ConflictType.TABLE,
            affected_objects=["users"],
            severity=ConflictSeverity.WARNING,
            resolution_suggestions=["Coordinate column naming"],
        )
        mock_registry.get_conflicts.return_value = [conflict]

        result = runner.invoke(
            app,
            [
                "coordinate",
                "register",
                "--agent-id",
                "claude-test",
                "--feature-name",
                "test_feature",
                "--schema-changes",
                "ALTER TABLE users ADD COLUMN test TEXT",
            ],
        )

        assert result.exit_code == 0
        assert "Warning" in result.stdout
        assert "conflict" in result.stdout.lower()
        assert "table" in result.stdout.lower()

    @patch("confiture.cli.coordinate._get_connection")
    def test_register_missing_required_option(self, mock_get_connection):
        """Should fail when required option is missing."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        # Missing --feature-name
        result = runner.invoke(
            app,
            [
                "coordinate",
                "register",
                "--agent-id",
                "claude-test",
                "--schema-changes",
                "ALTER TABLE users ADD COLUMN test TEXT",
            ],
        )

        assert result.exit_code != 0


class TestCoordinateListCommand:
    """Tests for 'confiture coordinate list-intents' command."""

    @patch("confiture.cli.coordinate._get_connection")
    @patch("confiture.cli.coordinate.IntentRegistry")
    def test_list_all_intents(self, mock_registry_class, mock_get_connection):
        """Should list all intentions without filters."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_registry = MagicMock()
        mock_registry_class.return_value = mock_registry

        # Mock intents
        intents = [
            Intent(
                id=str(uuid4()),
                agent_id="claude-auth",
                feature_name="oauth2",
                branch_name="feature/oauth2_001",
                schema_changes=["ALTER TABLE users ADD COLUMN oauth_provider TEXT"],
                tables_affected=["users"],
                status=IntentStatus.IN_PROGRESS,
                risk_level=RiskLevel.MEDIUM,
            ),
            Intent(
                id=str(uuid4()),
                agent_id="claude-payments",
                feature_name="stripe",
                branch_name="feature/stripe_001",
                schema_changes=["CREATE TABLE payments (id UUID PRIMARY KEY)"],
                tables_affected=["payments"],
                status=IntentStatus.REGISTERED,
                risk_level=RiskLevel.LOW,
            ),
        ]
        mock_registry.list_intents.return_value = intents

        result = runner.invoke(app, ["coordinate", "list-intents"])

        assert result.exit_code == 0
        assert "oauth2" in result.stdout
        assert "stripe" in result.stdout
        assert "2 total" in result.stdout

    @patch("confiture.cli.coordinate._get_connection")
    @patch("confiture.cli.coordinate.IntentRegistry")
    def test_list_with_status_filter(self, mock_registry_class, mock_get_connection):
        """Should filter intentions by status."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_registry = MagicMock()
        mock_registry_class.return_value = mock_registry

        intents = [
            Intent(
                id=str(uuid4()),
                agent_id="claude-test",
                feature_name="test",
                branch_name="feature/test_001",
                schema_changes=[],
                tables_affected=[],
                status=IntentStatus.IN_PROGRESS,
                risk_level=RiskLevel.LOW,
            )
        ]
        mock_registry.list_intents.return_value = intents

        result = runner.invoke(
            app, ["coordinate", "list-intents", "--status-filter", "in_progress"]
        )

        assert result.exit_code == 0
        assert "test" in result.stdout
        mock_registry.list_intents.assert_called_with(
            status=IntentStatus.IN_PROGRESS, agent_id=None
        )

    @patch("confiture.cli.coordinate._get_connection")
    @patch("confiture.cli.coordinate.IntentRegistry")
    def test_list_with_agent_filter(self, mock_registry_class, mock_get_connection):
        """Should filter intentions by agent ID."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_registry = MagicMock()
        mock_registry_class.return_value = mock_registry

        intents = []
        mock_registry.list_intents.return_value = intents

        result = runner.invoke(
            app, ["coordinate", "list-intents", "--agent-filter", "claude-payments"]
        )

        assert result.exit_code == 0
        assert "No intentions found" in result.stdout

    @patch("confiture.cli.coordinate._get_connection")
    @patch("confiture.cli.coordinate.IntentRegistry")
    def test_list_empty(self, mock_registry_class, mock_get_connection):
        """Should handle empty intent list gracefully."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_registry = MagicMock()
        mock_registry_class.return_value = mock_registry
        mock_registry.list_intents.return_value = []

        result = runner.invoke(app, ["coordinate", "list-intents"])

        assert result.exit_code == 0
        assert "No intentions found" in result.stdout

    @patch("confiture.cli.coordinate._get_connection")
    def test_list_invalid_status_filter(self, mock_get_connection):
        """Should fail with invalid status filter."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        result = runner.invoke(
            app, ["coordinate", "list-intents", "--status-filter", "invalid_status"]
        )

        assert result.exit_code == 1
        assert "Invalid status" in result.stdout


class TestCoordinateCheckCommand:
    """Tests for 'confiture coordinate check' command."""

    @patch("confiture.cli.coordinate._get_connection")
    @patch("confiture.cli.coordinate.IntentRegistry")
    def test_check_no_conflicts(self, mock_registry_class, mock_get_connection):
        """Should report no conflicts when none exist."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_registry = MagicMock()
        mock_registry_class.return_value = mock_registry
        mock_registry.list_intents.return_value = []

        result = runner.invoke(
            app,
            [
                "coordinate",
                "check",
                "--agent-id",
                "claude-test",
                "--feature-name",
                "test_feature",
                "--schema-changes",
                "CREATE TABLE test_table (id UUID PRIMARY KEY)",
            ],
        )

        assert result.exit_code == 0
        assert "No conflicts detected" in result.stdout

    @patch("confiture.cli.coordinate._get_connection")
    @patch("confiture.cli.coordinate.IntentRegistry")
    def test_check_with_conflicts(self, mock_registry_class, mock_get_connection):
        """Should report conflicts when detected."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_registry = MagicMock()
        mock_registry_class.return_value = mock_registry

        # Mock existing intent
        existing_intent = Intent(
            id=str(uuid4()),
            agent_id="claude-other",
            feature_name="other_feature",
            branch_name="feature/other_feature_001",
            schema_changes=["ALTER TABLE users ADD COLUMN other_col TEXT"],
            tables_affected=["users"],
            status=IntentStatus.IN_PROGRESS,
            risk_level=RiskLevel.LOW,
        )
        mock_registry.list_intents.return_value = [existing_intent]

        # Mock detector to return conflicts
        mock_detector = MagicMock()
        conflict = ConflictReport(
            intent_a=str(uuid4()),
            intent_b=existing_intent.id,
            conflict_type=ConflictType.TABLE,
            affected_objects=["users"],
            severity=ConflictSeverity.WARNING,
            resolution_suggestions=["Coordinate with other agent"],
        )
        mock_detector.detect_conflicts.return_value = [conflict]
        mock_registry._detector = mock_detector

        result = runner.invoke(
            app,
            [
                "coordinate",
                "check",
                "--agent-id",
                "claude-test",
                "--feature-name",
                "test_feature",
                "--schema-changes",
                "ALTER TABLE users ADD COLUMN test_col TEXT",
                "--tables-affected",
                "users",
            ],
        )

        assert result.exit_code == 0
        assert "Found" in result.stdout
        assert "conflict" in result.stdout.lower()


class TestCoordinateStatusCommand:
    """Tests for 'confiture coordinate status' command."""

    @patch("confiture.cli.coordinate._get_connection")
    @patch("confiture.cli.coordinate.IntentRegistry")
    def test_status_existing_intent(self, mock_registry_class, mock_get_connection):
        """Should display status of an existing intention."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_registry = MagicMock()
        mock_registry_class.return_value = mock_registry

        intent_id = str(uuid4())
        intent = Intent(
            id=intent_id,
            agent_id="claude-test",
            feature_name="test_feature",
            branch_name="feature/test_feature_001",
            schema_changes=["ALTER TABLE users ADD COLUMN test TEXT"],
            tables_affected=["users"],
            status=IntentStatus.IN_PROGRESS,
            risk_level=RiskLevel.MEDIUM,
        )
        mock_registry.get_intent.return_value = intent
        mock_registry.get_conflicts.return_value = []

        result = runner.invoke(
            app, ["coordinate", "status", "--intent-id", intent_id]
        )

        assert result.exit_code == 0
        assert "test_feature" in result.stdout
        assert "claude-test" in result.stdout
        assert "in_progress" in result.stdout

    @patch("confiture.cli.coordinate._get_connection")
    @patch("confiture.cli.coordinate.IntentRegistry")
    def test_status_nonexistent_intent(self, mock_registry_class, mock_get_connection):
        """Should fail when intention doesn't exist."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_registry = MagicMock()
        mock_registry_class.return_value = mock_registry
        mock_registry.get_intent.return_value = None

        intent_id = str(uuid4())
        result = runner.invoke(
            app, ["coordinate", "status", "--intent-id", intent_id]
        )

        assert result.exit_code == 1
        assert "not found" in result.stdout

    @patch("confiture.cli.coordinate._get_connection")
    @patch("confiture.cli.coordinate.IntentRegistry")
    def test_status_with_conflicts(self, mock_registry_class, mock_get_connection):
        """Should display conflicts if they exist."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_registry = MagicMock()
        mock_registry_class.return_value = mock_registry

        intent_id = str(uuid4())
        intent = Intent(
            id=intent_id,
            agent_id="claude-test",
            feature_name="test_feature",
            branch_name="feature/test_feature_001",
            schema_changes=["ALTER TABLE users ADD COLUMN test TEXT"],
            tables_affected=["users"],
            status=IntentStatus.CONFLICTED,
            risk_level=RiskLevel.MEDIUM,
        )
        mock_registry.get_intent.return_value = intent

        # Mock conflicts
        conflict = ConflictReport(
            intent_a=intent_id,
            intent_b=str(uuid4()),
            conflict_type=ConflictType.COLUMN,
            affected_objects=["users.test"],
            severity=ConflictSeverity.ERROR,
            resolution_suggestions=["Rename column"],
        )
        mock_registry.get_conflicts.return_value = [conflict]

        result = runner.invoke(
            app, ["coordinate", "status", "--intent-id", intent_id]
        )

        assert result.exit_code == 0
        assert "Conflict" in result.stdout
        assert "column" in result.stdout.lower()


class TestCoordinateConflictsCommand:
    """Tests for 'confiture coordinate conflicts' command."""

    @patch("confiture.cli.coordinate._get_connection")
    @patch("confiture.cli.coordinate.IntentRegistry")
    def test_conflicts_none(self, mock_registry_class, mock_get_connection):
        """Should report no conflicts when none exist."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_registry = MagicMock()
        mock_registry_class.return_value = mock_registry
        mock_registry.list_intents.return_value = []

        result = runner.invoke(app, ["coordinate", "conflicts"])

        assert result.exit_code == 0
        assert "No conflicts" in result.stdout

    @patch("confiture.cli.coordinate._get_connection")
    @patch("confiture.cli.coordinate.IntentRegistry")
    def test_conflicts_exist(self, mock_registry_class, mock_get_connection):
        """Should list all conflicted intentions."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_registry = MagicMock()
        mock_registry_class.return_value = mock_registry

        intent_id = str(uuid4())
        conflicted_intent = Intent(
            id=intent_id,
            agent_id="claude-test",
            feature_name="test_feature",
            branch_name="feature/test_feature_001",
            schema_changes=["ALTER TABLE users ADD COLUMN test TEXT"],
            tables_affected=["users"],
            status=IntentStatus.CONFLICTED,
            risk_level=RiskLevel.HIGH,
        )
        mock_registry.list_intents.return_value = [conflicted_intent]

        conflict = ConflictReport(
            intent_a=intent_id,
            intent_b=str(uuid4()),
            conflict_type=ConflictType.TABLE,
            affected_objects=["users"],
            severity=ConflictSeverity.ERROR,
            resolution_suggestions=[],
        )
        mock_registry.get_conflicts.return_value = [conflict]

        result = runner.invoke(app, ["coordinate", "conflicts"])

        assert result.exit_code == 0
        assert "test_feature" in result.stdout
        assert "claude-test" in result.stdout


class TestCoordinateResolveCommand:
    """Tests for 'confiture coordinate resolve' command."""

    @patch("confiture.cli.coordinate._get_connection")
    @patch("confiture.cli.coordinate.IntentRegistry")
    def test_resolve_conflict(self, mock_registry_class, mock_get_connection):
        """Should mark conflict as resolved with notes."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_registry = MagicMock()
        mock_registry_class.return_value = mock_registry

        result = runner.invoke(
            app,
            [
                "coordinate",
                "resolve",
                "--conflict-id",
                "42",
                "--notes",
                "Agents coordinated",
            ],
        )

        assert result.exit_code == 0
        assert "resolved" in result.stdout
        assert "Agents coordinated" in result.stdout
        mock_registry.resolve_conflict.assert_called_once_with(
            42, reviewed=True, resolution_notes="Agents coordinated"
        )


class TestCoordinateAbandonCommand:
    """Tests for 'confiture coordinate abandon' command."""

    @patch("confiture.cli.coordinate._get_connection")
    @patch("confiture.cli.coordinate.IntentRegistry")
    def test_abandon_existing_intent(self, mock_registry_class, mock_get_connection):
        """Should abandon an existing intention."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_registry = MagicMock()
        mock_registry_class.return_value = mock_registry

        intent_id = str(uuid4())
        intent = Intent(
            id=intent_id,
            agent_id="claude-test",
            feature_name="test_feature",
            branch_name="feature/test_feature_001",
            schema_changes=[],
            tables_affected=[],
            status=IntentStatus.REGISTERED,
            risk_level=RiskLevel.LOW,
        )
        mock_registry.get_intent.return_value = intent

        result = runner.invoke(
            app,
            [
                "coordinate",
                "abandon",
                "--intent-id",
                intent_id,
                "--reason",
                "Feature cancelled",
            ],
        )

        assert result.exit_code == 0
        assert "abandoned" in result.stdout
        assert "Feature cancelled" in result.stdout
        mock_registry.mark_abandoned.assert_called_once()

    @patch("confiture.cli.coordinate._get_connection")
    @patch("confiture.cli.coordinate.IntentRegistry")
    def test_abandon_nonexistent_intent(self, mock_registry_class, mock_get_connection):
        """Should fail when intention doesn't exist."""
        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_registry = MagicMock()
        mock_registry_class.return_value = mock_registry
        mock_registry.get_intent.return_value = None

        intent_id = str(uuid4())
        result = runner.invoke(
            app,
            [
                "coordinate",
                "abandon",
                "--intent-id",
                intent_id,
                "--reason",
                "Feature cancelled",
            ],
        )

        assert result.exit_code == 1
        assert "not found" in result.stdout


class TestCoordinateConnectionHandling:
    """Tests for database connection handling."""

    def test_missing_database_url(self):
        """Should fail gracefully when database URL is missing."""
        # Ensure no DATABASE_URL or CONFITURE_DB_URL in environment
        import os

        old_db_url = os.environ.pop("DATABASE_URL", None)
        old_confiture_url = os.environ.pop("CONFITURE_DB_URL", None)

        try:
            result = runner.invoke(
                app,
                [
                    "coordinate",
                    "register",
                    "--agent-id",
                    "test",
                    "--feature-name",
                    "test",
                    "--schema-changes",
                    "SELECT 1",
                ],
            )

            assert result.exit_code == 1
            assert "database url" in result.stdout.lower()
        finally:
            # Restore environment
            if old_db_url:
                os.environ["DATABASE_URL"] = old_db_url
            if old_confiture_url:
                os.environ["CONFITURE_DB_URL"] = old_confiture_url


class TestCoordinateJSONOutput:
    """Tests for JSON output format in all coordinate commands."""

    @patch("confiture.cli.coordinate._get_connection")
    @patch("confiture.cli.coordinate.IntentRegistry")
    def test_register_json_output(self, mock_registry_class, mock_get_connection):
        """Should output JSON when --format json is specified."""
        import json

        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_registry = MagicMock()
        mock_registry_class.return_value = mock_registry

        intent_id = str(uuid4())
        mock_intent = Intent(
            id=intent_id,
            agent_id="claude-test",
            feature_name="test_feature",
            branch_name="feature/test_feature_001",
            schema_changes=["ALTER TABLE users ADD COLUMN test TEXT"],
            tables_affected=["users"],
            status=IntentStatus.REGISTERED,
            risk_level=RiskLevel.LOW,
        )
        mock_registry.register.return_value = mock_intent
        mock_registry.get_conflicts.return_value = []

        result = runner.invoke(
            app,
            [
                "coordinate",
                "register",
                "--agent-id",
                "claude-test",
                "--feature-name",
                "test_feature",
                "--schema-changes",
                "ALTER TABLE users ADD COLUMN test TEXT",
                "--format",
                "json",
            ],
        )

        assert result.exit_code == 0
        output = json.loads(result.stdout)
        assert "intent" in output
        assert "conflicts" in output
        assert output["intent"]["agent_id"] == "claude-test"
        assert output["intent"]["feature_name"] == "test_feature"
        assert len(output["conflicts"]) == 0

    @patch("confiture.cli.coordinate._get_connection")
    @patch("confiture.cli.coordinate.IntentRegistry")
    def test_list_intents_json_output(self, mock_registry_class, mock_get_connection):
        """Should output JSON list of intents."""
        import json

        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_registry = MagicMock()
        mock_registry_class.return_value = mock_registry

        mock_intents = [
            Intent(
                id=str(uuid4()),
                agent_id="claude-1",
                feature_name="feature_1",
                branch_name="feature/feature_1_001",
                status=IntentStatus.REGISTERED,
            ),
            Intent(
                id=str(uuid4()),
                agent_id="claude-2",
                feature_name="feature_2",
                branch_name="feature/feature_2_001",
                status=IntentStatus.IN_PROGRESS,
            ),
        ]
        mock_registry.list_intents.return_value = mock_intents

        result = runner.invoke(
            app,
            [
                "coordinate",
                "list-intents",
                "--format",
                "json",
            ],
        )

        assert result.exit_code == 0
        output = json.loads(result.stdout)
        assert "total" in output
        assert "intents" in output
        assert output["total"] == 2
        assert len(output["intents"]) == 2
        assert output["intents"][0]["agent_id"] == "claude-1"
        assert output["intents"][1]["agent_id"] == "claude-2"

    @patch("confiture.cli.coordinate._get_connection")
    @patch("confiture.cli.coordinate.IntentRegistry")
    def test_status_json_output(self, mock_registry_class, mock_get_connection):
        """Should output JSON status for an intent."""
        import json

        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_registry = MagicMock()
        mock_registry_class.return_value = mock_registry

        intent_id = str(uuid4())
        mock_intent = Intent(
            id=intent_id,
            agent_id="claude-test",
            feature_name="test_feature",
            branch_name="feature/test_feature_001",
            status=IntentStatus.IN_PROGRESS,
        )
        mock_registry.get_intent.return_value = mock_intent
        mock_registry.get_conflicts.return_value = []

        result = runner.invoke(
            app,
            [
                "coordinate",
                "status",
                "--intent-id",
                intent_id,
                "--format",
                "json",
            ],
        )

        assert result.exit_code == 0
        output = json.loads(result.stdout)
        assert "intent" in output
        assert "conflicts" in output
        assert output["intent"]["id"] == intent_id
        assert output["intent"]["status"] == "in_progress"

    @patch("confiture.cli.coordinate._get_connection")
    @patch("confiture.cli.coordinate.IntentRegistry")
    def test_check_json_output_no_conflicts(self, mock_registry_class, mock_get_connection):
        """Should output JSON check result with no conflicts."""
        import json

        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_registry = MagicMock()
        mock_registry_class.return_value = mock_registry

        mock_registry.list_intents.return_value = []
        mock_detector = MagicMock()
        mock_detector.detect_conflicts.return_value = []
        mock_registry._detector = mock_detector

        result = runner.invoke(
            app,
            [
                "coordinate",
                "check",
                "--agent-id",
                "claude-test",
                "--feature-name",
                "test_feature",
                "--schema-changes",
                "ALTER TABLE users ADD COLUMN test TEXT",
                "--format",
                "json",
            ],
        )

        assert result.exit_code == 0
        output = json.loads(result.stdout)
        assert "conflicts_detected" in output
        assert "conflicts" in output
        assert output["conflicts_detected"] == 0
        assert len(output["conflicts"]) == 0

    @patch("confiture.cli.coordinate._get_connection")
    @patch("confiture.cli.coordinate.IntentRegistry")
    def test_check_json_output_with_conflicts(self, mock_registry_class, mock_get_connection):
        """Should output JSON check result with conflicts."""
        import json

        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_registry = MagicMock()
        mock_registry_class.return_value = mock_registry

        existing_intent = Intent(
            id=str(uuid4()),
            agent_id="claude-existing",
            feature_name="existing_feature",
            branch_name="feature/existing_001",
            status=IntentStatus.IN_PROGRESS,
        )
        # Mock list_intents to return the intent once for IN_PROGRESS, empty for REGISTERED
        mock_registry.list_intents.side_effect = [[], [existing_intent]]

        mock_conflict = ConflictReport(
            intent_a=str(uuid4()),
            intent_b=str(uuid4()),
            conflict_type=ConflictType.TABLE,
            affected_objects=["users"],
            severity=ConflictSeverity.WARNING,
            resolution_suggestions=["Coordinate with other agent"],
        )

        mock_detector = MagicMock()
        mock_detector.detect_conflicts.return_value = [mock_conflict]
        mock_registry._detector = mock_detector

        result = runner.invoke(
            app,
            [
                "coordinate",
                "check",
                "--agent-id",
                "claude-test",
                "--feature-name",
                "test_feature",
                "--schema-changes",
                "ALTER TABLE users ADD COLUMN test TEXT",
                "--format",
                "json",
            ],
        )

        assert result.exit_code == 0
        output = json.loads(result.stdout)
        assert output["conflicts_detected"] == 1
        assert len(output["conflicts"]) == 1
        assert output["conflicts"][0]["conflict_type"] == "table"
        assert output["conflicts"][0]["severity"] == "warning"

    @patch("confiture.cli.coordinate._get_connection")
    @patch("confiture.cli.coordinate.IntentRegistry")
    def test_conflicts_json_output(self, mock_registry_class, mock_get_connection):
        """Should output JSON list of conflicted intents."""
        import json

        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_registry = MagicMock()
        mock_registry_class.return_value = mock_registry

        intent_id = str(uuid4())
        mock_intent = Intent(
            id=intent_id,
            agent_id="claude-test",
            feature_name="test_feature",
            branch_name="feature/test_feature_001",
            status=IntentStatus.CONFLICTED,
        )
        mock_registry.list_intents.return_value = [mock_intent]

        mock_conflict = ConflictReport(
            intent_a=intent_id,
            intent_b=str(uuid4()),
            conflict_type=ConflictType.COLUMN,
            affected_objects=["users.email"],
            severity=ConflictSeverity.ERROR,
        )
        mock_registry.get_conflicts.return_value = [mock_conflict]

        result = runner.invoke(
            app,
            [
                "coordinate",
                "conflicts",
                "--format",
                "json",
            ],
        )

        assert result.exit_code == 0
        output = json.loads(result.stdout)
        assert "total_conflicted_intents" in output
        assert "conflicted_intents" in output
        assert output["total_conflicted_intents"] == 1
        assert len(output["conflicted_intents"]) == 1
        assert output["conflicted_intents"][0]["intent"]["id"] == intent_id

    @patch("confiture.cli.coordinate._get_connection")
    @patch("confiture.cli.coordinate.IntentRegistry")
    def test_resolve_json_output(self, mock_registry_class, mock_get_connection):
        """Should output JSON confirmation of conflict resolution."""
        import json

        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_registry = MagicMock()
        mock_registry_class.return_value = mock_registry

        conflict_id = 42
        notes = "Coordinated with team, applying changes sequentially"

        result = runner.invoke(
            app,
            [
                "coordinate",
                "resolve",
                "--conflict-id",
                str(conflict_id),
                "--notes",
                notes,
                "--format",
                "json",
            ],
        )

        assert result.exit_code == 0
        output = json.loads(result.stdout)
        assert "conflict_id" in output
        assert "resolved" in output
        assert "resolution_notes" in output
        assert output["conflict_id"] == conflict_id
        assert output["resolved"] is True
        assert output["resolution_notes"] == notes

    @patch("confiture.cli.coordinate._get_connection")
    @patch("confiture.cli.coordinate.IntentRegistry")
    def test_abandon_json_output(self, mock_registry_class, mock_get_connection):
        """Should output JSON confirmation of intent abandonment."""
        import json

        mock_conn = MagicMock()
        mock_get_connection.return_value = mock_conn

        mock_registry = MagicMock()
        mock_registry_class.return_value = mock_registry

        intent_id = str(uuid4())
        mock_intent = Intent(
            id=intent_id,
            agent_id="claude-test",
            feature_name="test_feature",
            branch_name="feature/test_feature_001",
            status=IntentStatus.REGISTERED,
        )
        mock_registry.get_intent.return_value = mock_intent

        # Mock updated intent with abandoned status
        abandoned_intent = Intent(
            id=intent_id,
            agent_id="claude-test",
            feature_name="test_feature",
            branch_name="feature/test_feature_001",
            status=IntentStatus.ABANDONED,
        )
        mock_registry.get_intent.side_effect = [mock_intent, abandoned_intent]

        reason = "Feature cancelled by product team"

        result = runner.invoke(
            app,
            [
                "coordinate",
                "abandon",
                "--intent-id",
                intent_id,
                "--reason",
                reason,
                "--format",
                "json",
            ],
        )

        assert result.exit_code == 0
        output = json.loads(result.stdout)
        assert "intent_id" in output
        assert "feature_name" in output
        assert "status" in output
        assert "reason" in output
        assert output["intent_id"] == intent_id
        assert output["feature_name"] == "test_feature"
        assert output["status"] == "abandoned"
        assert output["reason"] == reason
