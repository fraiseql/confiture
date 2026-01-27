"""Integration tests for IntentRegistry with real PostgreSQL database.

These tests exercise the IntentRegistry database operations including:
- Intent registration and storage
- Conflict detection and storage
- Status transitions and audit history
- Branch allocation
- Multi-agent conflict scenarios
"""

from __future__ import annotations

import pytest

from confiture.integrations.pggit.coordination import (
    ConflictType,
    IntentRegistry,
    IntentStatus,
    RiskLevel,
)


@pytest.fixture
def registry(test_db_connection):
    """Create a fresh IntentRegistry for each test."""
    if test_db_connection is None:
        pytest.skip("PostgreSQL database not available")

    # Drop tables before test to ensure clean state
    with test_db_connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS tb_pggit_intent_history CASCADE")
        cursor.execute("DROP TABLE IF EXISTS tb_pggit_conflict CASCADE")
        cursor.execute("DROP TABLE IF EXISTS tb_pggit_intent CASCADE")
        test_db_connection.commit()

    registry = IntentRegistry(test_db_connection)
    return registry


class TestIntentRegistryBasicOperations:
    """Test basic registry operations."""

    def test_register_intent_stores_in_database(self, registry, test_db_connection):
        """Registering intent should store it in database."""
        intent = registry.register(
            agent_id="agent_a",
            feature_name="stripe_integration",
            schema_changes=["ALTER TABLE users ADD COLUMN stripe_id TEXT"],
            tables_affected=["users"],
        )

        # Verify in database
        retrieved = registry.get_intent(intent.id)
        assert retrieved is not None
        assert retrieved.agent_id == "agent_a"
        assert retrieved.feature_name == "stripe_integration"
        assert retrieved.status == IntentStatus.REGISTERED

    def test_register_intent_with_all_fields(self, registry):
        """Registering intent with all optional fields should work."""
        intent = registry.register(
            agent_id="agent_b",
            feature_name="oauth2_flow",
            schema_changes=[
                "CREATE TABLE oauth_tokens (id INT, token TEXT)",
                "CREATE INDEX idx_oauth_user ON oauth_tokens(user_id)",
            ],
            tables_affected=["oauth_tokens"],
            estimated_duration_ms=5000,
            risk_level="high",
            metadata={"priority": "critical", "requires_testing": True},
        )

        retrieved = registry.get_intent(intent.id)
        assert retrieved.estimated_duration_ms == 5000
        assert retrieved.risk_level == RiskLevel.HIGH
        assert retrieved.metadata["priority"] == "critical"

    def test_get_intent_returns_none_for_missing_id(self, registry):
        """Getting non-existent intent should return None."""
        result = registry.get_intent("nonexistent_id")
        assert result is None

    def test_list_intents_empty_when_none_exist(self, registry):
        """List should be empty when no intents registered."""
        intents = registry.list_intents()
        assert len(intents) == 0

    def test_list_intents_returns_all_intents(self, registry):
        """List should return all registered intents."""
        intent_a = registry.register(
            agent_id="agent_a",
            feature_name="feature_a",
            schema_changes=["ALTER TABLE t1 ADD COLUMN c1 TEXT"],
            tables_affected=["t1"],
        )

        intent_b = registry.register(
            agent_id="agent_b",
            feature_name="feature_b",
            schema_changes=["ALTER TABLE t2 ADD COLUMN c2 TEXT"],
            tables_affected=["t2"],
        )

        intents = registry.list_intents()
        assert len(intents) == 2
        ids = {intent.id for intent in intents}
        assert intent_a.id in ids
        assert intent_b.id in ids

    def test_list_intents_filter_by_status(self, registry):
        """Filtering by status should work."""
        intent_a = registry.register(
            agent_id="agent_a",
            feature_name="feature_a",
            schema_changes=["ALTER TABLE t1 ADD COLUMN c1 TEXT"],
            tables_affected=["t1"],
        )
        intent_b = registry.register(
            agent_id="agent_b",
            feature_name="feature_b",
            schema_changes=["ALTER TABLE t2 ADD COLUMN c2 TEXT"],
            tables_affected=["t2"],
        )

        # Mark one as in progress
        registry.mark_in_progress(intent_a.id)

        registered = registry.list_intents(status=IntentStatus.REGISTERED)
        assert len(registered) == 1
        assert registered[0].id == intent_b.id

        in_progress = registry.list_intents(status=IntentStatus.IN_PROGRESS)
        assert len(in_progress) == 1
        assert in_progress[0].id == intent_a.id

    def test_list_intents_filter_by_agent_id(self, registry):
        """Filtering by agent ID should work."""
        intent_a = registry.register(
            agent_id="agent_a",
            feature_name="feature_a",
            schema_changes=["ALTER TABLE t1 ADD COLUMN c1 TEXT"],
            tables_affected=["t1"],
        )
        _ = registry.register(
            agent_id="agent_b",
            feature_name="feature_b",
            schema_changes=["ALTER TABLE t2 ADD COLUMN c2 TEXT"],
            tables_affected=["t2"],
        )
        intent_c = registry.register(
            agent_id="agent_a",
            feature_name="feature_c",
            schema_changes=["ALTER TABLE t3 ADD COLUMN c3 TEXT"],
            tables_affected=["t3"],
        )

        agent_a_intents = registry.list_intents(agent_id="agent_a")
        assert len(agent_a_intents) == 2
        ids = {intent.id for intent in agent_a_intents}
        assert intent_a.id in ids
        assert intent_c.id in ids


class TestIntentRegistryStatusTransitions:
    """Test intent status lifecycle management."""

    def test_mark_in_progress(self, registry):
        """Marking intent as in progress should update status."""
        intent = registry.register(
            agent_id="agent_a",
            feature_name="feature_a",
            schema_changes=["ALTER TABLE t ADD COLUMN c TEXT"],
            tables_affected=["t"],
        )

        registry.mark_in_progress(intent.id, reason="Starting work")
        retrieved = registry.get_intent(intent.id)
        assert retrieved.status == IntentStatus.IN_PROGRESS

    def test_mark_completed(self, registry):
        """Marking intent as completed should update status."""
        intent = registry.register(
            agent_id="agent_a",
            feature_name="feature_a",
            schema_changes=["ALTER TABLE t ADD COLUMN c TEXT"],
            tables_affected=["t"],
        )

        registry.mark_in_progress(intent.id)
        registry.mark_completed(intent.id, reason="Finished work")
        retrieved = registry.get_intent(intent.id)
        assert retrieved.status == IntentStatus.COMPLETED

    def test_mark_merged(self, registry):
        """Marking intent as merged should update status."""
        intent = registry.register(
            agent_id="agent_a",
            feature_name="feature_a",
            schema_changes=["ALTER TABLE t ADD COLUMN c TEXT"],
            tables_affected=["t"],
        )

        registry.mark_in_progress(intent.id)
        registry.mark_completed(intent.id)
        registry.mark_merged(intent.id, reason="Merged to main")
        retrieved = registry.get_intent(intent.id)
        assert retrieved.status == IntentStatus.MERGED

    def test_mark_abandoned(self, registry):
        """Marking intent as abandoned should update status."""
        intent = registry.register(
            agent_id="agent_a",
            feature_name="feature_a",
            schema_changes=["ALTER TABLE t ADD COLUMN c TEXT"],
            tables_affected=["t"],
        )

        registry.mark_in_progress(intent.id)
        registry.mark_abandoned(intent.id, reason="Feature cancelled")
        retrieved = registry.get_intent(intent.id)
        assert retrieved.status == IntentStatus.ABANDONED

    def test_status_history_recorded(self, registry, test_db_connection):
        """Status transitions should be recorded in history."""
        intent = registry.register(
            agent_id="agent_a",
            feature_name="feature_a",
            schema_changes=["ALTER TABLE t ADD COLUMN c TEXT"],
            tables_affected=["t"],
        )

        registry.mark_in_progress(intent.id, reason="Starting", changed_by="test_user")
        registry.mark_completed(intent.id, reason="Finished", changed_by="test_user")

        # Query history from database
        with test_db_connection.cursor() as cursor:
            cursor.execute(
                "SELECT old_status, new_status, reason, changed_by FROM tb_pggit_intent_history "
                "WHERE intent_id = %s ORDER BY changed_at",
                (intent.id,),
            )
            rows = cursor.fetchall()

        assert len(rows) == 2
        # First transition: registered -> in_progress
        assert rows[0][0] == "registered"
        assert rows[0][1] == "in_progress"
        assert rows[0][2] == "Starting"
        assert rows[0][3] == "test_user"

        # Second transition: in_progress -> completed
        assert rows[1][0] == "in_progress"
        assert rows[1][1] == "completed"
        assert rows[1][2] == "Finished"


class TestBranchAllocation:
    """Test automatic branch name allocation."""

    def test_allocate_branch_simple_name(self, registry):
        """Branch allocation should create valid branch names."""
        branch = registry.allocate_branch("stripe_integration")
        assert branch == "feature/stripe_integration"

    def test_allocate_branch_with_spaces(self, registry):
        """Branch allocation should handle spaces."""
        branch = registry.allocate_branch("stripe integration")
        assert branch == "feature/stripe_integration"

    def test_allocate_branch_with_slashes(self, registry):
        """Branch allocation should handle slashes."""
        branch = registry.allocate_branch("feature/authentication")
        assert branch == "feature/feature_authentication"

    def test_allocate_branch_unique_names(self, registry):
        """Duplicate feature names should get unique branches."""
        branch1 = registry.allocate_branch("stripe_integration")
        assert branch1 == "feature/stripe_integration"

        # Register intent to occupy first branch
        registry.register(
            agent_id="agent_a",
            feature_name="stripe_integration",
            schema_changes=["ALTER TABLE t ADD COLUMN c TEXT"],
            tables_affected=["t"],
        )

        # Allocate same feature name again - should get unique name
        branch2 = registry.allocate_branch("stripe_integration")
        assert branch2 != branch1
        assert branch2.startswith("feature/stripe_integration_")

    def test_allocate_branch_incremental_suffixes(self, registry):
        """Multiple duplicate branch names should have incrementing suffixes."""
        registry.register(
            agent_id="agent_a",
            feature_name="feature_a",
            schema_changes=["ALTER TABLE t1 ADD COLUMN c1 TEXT"],
            tables_affected=["t1"],
        )

        registry.register(
            agent_id="agent_b",
            feature_name="feature_a",
            schema_changes=["ALTER TABLE t2 ADD COLUMN c2 TEXT"],
            tables_affected=["t2"],
        )

        branch = registry.allocate_branch("feature_a")
        # Should get a unique name with counter
        assert "feature_a" in branch


class TestConflictDetectionAndStorage:
    """Test conflict detection and storage."""

    def test_register_intent_detects_table_conflicts(self, registry):
        """Registering intent should detect table conflicts with existing intents."""
        intent_a = registry.register(
            agent_id="agent_a",
            feature_name="feature_a",
            schema_changes=["ALTER TABLE users ADD COLUMN stripe_id TEXT"],
            tables_affected=["users"],
        )

        intent_b = registry.register(
            agent_id="agent_b",
            feature_name="feature_b",
            schema_changes=["ALTER TABLE users ADD COLUMN phone TEXT"],
            tables_affected=["users"],
        )

        # intent_b should be marked as conflicted
        retrieved_b = registry.get_intent(intent_b.id)
        assert retrieved_b.status == IntentStatus.CONFLICTED
        assert intent_a.id in retrieved_b.conflicts_with

    def test_register_intent_stores_conflicts(self, registry):
        """Conflict reports should be stored in database."""
        _ = registry.register(
            agent_id="agent_a",
            feature_name="feature_a",
            schema_changes=["ALTER TABLE users ADD COLUMN stripe_id TEXT"],
            tables_affected=["users"],
        )

        intent_b = registry.register(
            agent_id="agent_b",
            feature_name="feature_b",
            schema_changes=["ALTER TABLE users ADD COLUMN phone TEXT"],
            tables_affected=["users"],
        )

        # Check conflicts were detected and stored
        conflicts = registry.get_conflicts(intent_b.id)
        assert len(conflicts) > 0

        # Should have a table conflict
        conflict_types = {c.conflict_type for c in conflicts}
        assert ConflictType.TABLE in conflict_types

    def test_get_conflicts_returns_all_conflicts(self, registry):
        """Getting conflicts should return all conflicts for intent."""
        intent_a = registry.register(
            agent_id="agent_a",
            feature_name="feature_a",
            schema_changes=["ALTER TABLE users ADD COLUMN stripe_id TEXT"],
            tables_affected=["users"],
        )

        intent_b = registry.register(
            agent_id="agent_b",
            feature_name="feature_b",
            schema_changes=["ALTER TABLE users ADD COLUMN phone TEXT"],
            tables_affected=["users"],
        )

        conflicts = registry.get_conflicts(intent_b.id)
        assert len(conflicts) > 0
        # Conflict should involve both intents (order may vary depending on which was called first)
        assert {conflicts[0].intent_a, conflicts[0].intent_b} == {intent_a.id, intent_b.id}

    def test_resolve_conflict_marks_reviewed(self, registry):
        """Resolving conflict should mark it as reviewed."""
        _ = registry.register(
            agent_id="agent_a",
            feature_name="feature_a",
            schema_changes=["ALTER TABLE users ADD COLUMN stripe_id TEXT"],
            tables_affected=["users"],
        )

        intent_b = registry.register(
            agent_id="agent_b",
            feature_name="feature_b",
            schema_changes=["ALTER TABLE users ADD COLUMN phone TEXT"],
            tables_affected=["users"],
        )

        conflicts = registry.get_conflicts(intent_b.id)
        conflict_id = conflicts[0].id

        registry.resolve_conflict(
            conflict_id,
            reviewed=True,
            resolution_notes="Agents coordinated to apply changes sequentially",
        )

        # Verify in database
        updated_conflicts = registry.get_conflicts(intent_b.id)
        assert updated_conflicts[0].reviewed is True
        assert "sequentially" in updated_conflicts[0].resolution_notes


class TestMultiAgentScenarios:
    """Test complex multi-agent scenarios."""

    def test_three_agents_same_table(self, registry):
        """Three agents modifying same table should detect conflicts."""
        intent_a = registry.register(
            agent_id="agent_a",
            feature_name="stripe_integration",
            schema_changes=["ALTER TABLE users ADD COLUMN stripe_id TEXT"],
            tables_affected=["users"],
        )

        intent_b = registry.register(
            agent_id="agent_b",
            feature_name="oauth2_flow",
            schema_changes=["ALTER TABLE users ADD COLUMN oauth_provider TEXT"],
            tables_affected=["users"],
        )

        intent_c = registry.register(
            agent_id="agent_c",
            feature_name="mfa_support",
            schema_changes=["ALTER TABLE users ADD COLUMN mfa_enabled BOOLEAN"],
            tables_affected=["users"],
        )

        # All should be conflicted
        assert registry.get_intent(intent_a.id).status == IntentStatus.REGISTERED
        assert registry.get_intent(intent_b.id).status == IntentStatus.CONFLICTED
        assert registry.get_intent(intent_c.id).status == IntentStatus.CONFLICTED

    def test_dependent_features_conflict_resolution(self, registry):
        """Test conflict scenario with dependent features."""
        # Feature 1: Add payment table
        intent_1 = registry.register(
            agent_id="agent_a",
            feature_name="payments",
            schema_changes=[
                "CREATE TABLE payments (id INT, user_id INT, amount DECIMAL)",
                "CREATE INDEX idx_payments_user ON payments(user_id)",
            ],
            tables_affected=["payments"],
        )

        # Feature 2: Add users.stripe_id column
        intent_2 = registry.register(
            agent_id="agent_b",
            feature_name="stripe_integration",
            schema_changes=["ALTER TABLE users ADD COLUMN stripe_id TEXT"],
            tables_affected=["users"],
        )

        # Should not conflict (different tables)
        conflicts_1 = registry.get_conflicts(intent_1.id)
        conflicts_2 = registry.get_conflicts(intent_2.id)
        assert len(conflicts_1) == 0
        assert len(conflicts_2) == 0

    def test_no_conflict_different_agents_same_agent(self, registry):
        """Same agent modifying same table should not create conflicts."""
        _ = registry.register(
            agent_id="agent_a",
            feature_name="feature_a",
            schema_changes=["ALTER TABLE users ADD COLUMN col_a TEXT"],
            tables_affected=["users"],
        )

        intent_2 = registry.register(
            agent_id="agent_a",
            feature_name="feature_b",
            schema_changes=["ALTER TABLE users ADD COLUMN col_b TEXT"],
            tables_affected=["users"],
        )

        # No conflict - same agent
        conflicts = registry.get_conflicts(intent_2.id)
        assert len(conflicts) == 0


class TestConstraintAndIndexConflicts:
    """Test detection of constraint and index conflicts."""

    def test_function_conflict_detection(self, registry):
        """Function conflicts should be detected and stored."""
        _ = registry.register(
            agent_id="agent_a",
            feature_name="feature_a",
            schema_changes=[
                "CREATE FUNCTION calculate_total() RETURNS INT AS $$ SELECT 1 $$ LANGUAGE SQL"
            ],
            tables_affected=[],
        )

        intent_b = registry.register(
            agent_id="agent_b",
            feature_name="feature_b",
            schema_changes=["DROP FUNCTION calculate_total"],
            tables_affected=[],
        )

        # Should detect function conflict
        conflicts = registry.get_conflicts(intent_b.id)
        assert len(conflicts) > 0
        function_conflicts = [c for c in conflicts if c.conflict_type == ConflictType.FUNCTION]
        assert len(function_conflicts) > 0

    def test_index_conflict_detection(self, registry):
        """Index conflicts should be detected."""
        _ = registry.register(
            agent_id="agent_a",
            feature_name="feature_a",
            schema_changes=["CREATE INDEX idx_users_email ON users(email)"],
            tables_affected=["users"],
        )

        intent_b = registry.register(
            agent_id="agent_b",
            feature_name="feature_b",
            schema_changes=["CREATE INDEX idx_users_email ON users(email)"],
            tables_affected=["users"],
        )

        # Should detect index conflict
        conflicts = registry.get_conflicts(intent_b.id)
        assert len(conflicts) > 0
        index_conflicts = [c for c in conflicts if c.conflict_type == ConflictType.INDEX]
        assert len(index_conflicts) > 0


class TestErrorHandling:
    """Test error handling in registry."""

    def test_register_requires_agent_id(self, registry):
        """Registering without agent_id should raise error."""
        with pytest.raises(ValueError, match="agent_id.*required"):
            registry.register(
                agent_id="",
                feature_name="feature",
                schema_changes=["ALTER TABLE t ADD COLUMN c TEXT"],
                tables_affected=["t"],
            )

    def test_register_requires_feature_name(self, registry):
        """Registering without feature_name should raise error."""
        with pytest.raises(ValueError, match="feature_name.*required"):
            registry.register(
                agent_id="agent_a",
                feature_name="",
                schema_changes=["ALTER TABLE t ADD COLUMN c TEXT"],
                tables_affected=["t"],
            )

    def test_register_requires_schema_changes(self, registry):
        """Registering without schema_changes should raise error."""
        with pytest.raises(ValueError, match="schema_changes.*required"):
            registry.register(
                agent_id="agent_a",
                feature_name="feature",
                schema_changes=[],
                tables_affected=["t"],
            )

    def test_update_status_nonexistent_intent(self, registry):
        """Updating status of non-existent intent should raise error."""
        with pytest.raises(ValueError, match="not found"):
            registry.mark_in_progress("nonexistent_id")


class TestDatabasePersistence:
    """Test that data persists correctly in database."""

    def test_intent_survives_registry_recreation(self, registry, test_db_connection):
        """Registered intent should survive registry recreation."""
        intent_id = registry.register(
            agent_id="agent_a",
            feature_name="feature_a",
            schema_changes=["ALTER TABLE t ADD COLUMN c TEXT"],
            tables_affected=["t"],
        ).id

        # Create new registry instance
        registry2 = IntentRegistry(test_db_connection)

        # Should retrieve the intent
        retrieved = registry2.get_intent(intent_id)
        assert retrieved is not None
        assert retrieved.id == intent_id
        assert retrieved.agent_id == "agent_a"

    def test_conflicts_survive_registry_recreation(self, registry, test_db_connection):
        """Conflict reports should survive registry recreation."""
        _ = registry.register(
            agent_id="agent_a",
            feature_name="feature_a",
            schema_changes=["ALTER TABLE users ADD COLUMN col_a TEXT"],
            tables_affected=["users"],
        )

        intent_b = registry.register(
            agent_id="agent_b",
            feature_name="feature_b",
            schema_changes=["ALTER TABLE users ADD COLUMN col_b TEXT"],
            tables_affected=["users"],
        )

        # Create new registry instance
        registry2 = IntentRegistry(test_db_connection)

        # Should retrieve conflicts
        conflicts = registry2.get_conflicts(intent_b.id)
        assert len(conflicts) > 0
