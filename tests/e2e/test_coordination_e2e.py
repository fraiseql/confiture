"""E2E tests for multi-agent coordination workflows.

These tests exercise complete workflows of multiple agents working in parallel
on database schemas with automatic conflict detection, resolution, and merging.

Scenarios tested:
- Parallel feature development with conflict detection
- Conflict resolution and coordination
- Status lifecycle from registration through merge
- Branch management and allocation
- Complex multi-agent scenarios with dependencies
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


class TestParallelFeatureDevelopment:
    """Test scenarios with multiple agents developing features in parallel."""

    def test_two_agents_independent_features(self, registry):
        """Two agents working on independent features should have no conflicts."""
        # Agent A: Building payment processing
        stripe_intent = registry.register(
            agent_id="claude-payments",
            feature_name="stripe_integration",
            schema_changes=[
                "CREATE TABLE stripe_customers (id TEXT PRIMARY KEY, user_id INT UNIQUE)",
                "CREATE TABLE stripe_charges (id TEXT PRIMARY KEY, customer_id TEXT REFERENCES stripe_customers(id))",
            ],
            tables_affected=["stripe_customers", "stripe_charges"],
            risk_level="medium",
            metadata={"priority": "high", "sla_hours": 24},
        )

        # Agent B: Building authentication
        oauth_intent = registry.register(
            agent_id="claude-auth",
            feature_name="oauth2_flow",
            schema_changes=[
                "CREATE TABLE oauth_tokens (id SERIAL PRIMARY KEY, user_id INT, token TEXT UNIQUE)",
                "CREATE TABLE oauth_providers (id SERIAL PRIMARY KEY, name TEXT UNIQUE)",
            ],
            tables_affected=["oauth_tokens", "oauth_providers"],
            risk_level="medium",
            metadata={"priority": "high", "sla_hours": 24},
        )

        # Verify no conflicts
        assert stripe_intent.status == IntentStatus.REGISTERED
        assert oauth_intent.status == IntentStatus.REGISTERED
        assert len(registry.get_conflicts(stripe_intent.id)) == 0
        assert len(registry.get_conflicts(oauth_intent.id)) == 0

        # Both can proceed independently
        registry.mark_in_progress(stripe_intent.id)
        registry.mark_in_progress(oauth_intent.id)

        stripe_in_progress = registry.get_intent(stripe_intent.id)
        oauth_in_progress = registry.get_intent(oauth_intent.id)
        assert stripe_in_progress.status == IntentStatus.IN_PROGRESS
        assert oauth_in_progress.status == IntentStatus.IN_PROGRESS

    def test_three_agents_same_table_requires_coordination(self, registry):
        """Three agents modifying same table should detect conflicts."""
        # Agent A: Adding payment fields
        intent_a = registry.register(
            agent_id="claude-payments",
            feature_name="stripe_integration",
            schema_changes=["ALTER TABLE users ADD COLUMN stripe_customer_id TEXT"],
            tables_affected=["users"],
            risk_level="high",
        )

        # Agent B: Adding auth fields
        intent_b = registry.register(
            agent_id="claude-auth",
            feature_name="oauth2",
            schema_changes=["ALTER TABLE users ADD COLUMN oauth_provider TEXT"],
            tables_affected=["users"],
            risk_level="high",
        )

        # Agent C: Adding MFA fields
        intent_c = registry.register(
            agent_id="claude-security",
            feature_name="mfa",
            schema_changes=["ALTER TABLE users ADD COLUMN mfa_enabled BOOLEAN"],
            tables_affected=["users"],
            risk_level="high",
        )

        # Verify conflicts detected
        assert intent_a.status == IntentStatus.REGISTERED
        assert intent_b.status == IntentStatus.CONFLICTED  # Conflicts with A
        assert intent_c.status == IntentStatus.CONFLICTED  # Conflicts with A and B

        # All should have conflict reports
        conflicts_b = registry.get_conflicts(intent_b.id)
        conflicts_c = registry.get_conflicts(intent_c.id)
        assert len(conflicts_b) > 0
        assert len(conflicts_c) > 0

        # Verify conflict types
        for conflict in conflicts_b:
            assert conflict.conflict_type == ConflictType.TABLE

    def test_sequential_coordination_workflow(self, registry):
        """Test agents coordinating to resolve conflicts sequentially."""
        # Agent A starts first
        intent_a = registry.register(
            agent_id="claude-payments",
            feature_name="payments",
            schema_changes=["ALTER TABLE users ADD COLUMN stripe_id TEXT"],
            tables_affected=["users"],
        )
        registry.mark_in_progress(intent_a.id)
        registry.mark_completed(intent_a.id, reason="Payment changes completed")
        registry.mark_merged(intent_a.id, reason="Merged to main")

        # Agent B starts after A completes
        intent_b = registry.register(
            agent_id="claude-auth",
            feature_name="auth",
            schema_changes=["ALTER TABLE users ADD COLUMN oauth_provider TEXT"],
            tables_affected=["users"],
        )
        # No conflict because A is already merged
        # (In practice, merging would update the database so B would know)
        registry.mark_in_progress(intent_b.id)
        registry.mark_completed(intent_b.id)
        registry.mark_merged(intent_b.id)

        # Verify final states
        assert registry.get_intent(intent_a.id).status == IntentStatus.MERGED
        assert registry.get_intent(intent_b.id).status == IntentStatus.MERGED


class TestConflictResolution:
    """Test conflict detection, reporting, and resolution workflows."""

    def test_column_conflict_resolution_workflow(self, registry):
        """Test workflow for resolving column conflicts."""
        # Agent A: Add email column
        _ = registry.register(
            agent_id="claude-users",
            feature_name="user_emails",
            schema_changes=["ALTER TABLE users ADD COLUMN email TEXT UNIQUE"],
            tables_affected=["users"],
        )

        # Agent B: Also trying to add email column with different type
        intent_b = registry.register(
            agent_id="claude-auth",
            feature_name="auth_emails",
            schema_changes=["ALTER TABLE users ADD COLUMN email VARCHAR(255) NOT NULL"],
            tables_affected=["users"],
        )

        # Verify conflict detected
        assert intent_b.status == IntentStatus.CONFLICTED
        conflicts = registry.get_conflicts(intent_b.id)
        assert len(conflicts) > 0

        # Get any conflict and mark it as reviewed
        conflict = conflicts[0]
        assert len(conflict.resolution_suggestions) > 0

        # Mark conflict as reviewed with resolution
        conflict_id_to_resolve = conflict.id
        registry.resolve_conflict(
            conflict_id_to_resolve,
            reviewed=True,
            resolution_notes="Agents coordinated: Using TEXT UNIQUE, Agent B will use the column",
        )

        # Verify the specific conflict was marked resolved
        # Re-fetch all conflicts
        updated_conflicts = registry.get_conflicts(intent_b.id)
        resolved_conflict = next(
            (c for c in updated_conflicts if c.id == conflict_id_to_resolve), None
        )
        assert resolved_conflict is not None
        assert resolved_conflict.reviewed is True
        assert "coordinated" in resolved_conflict.resolution_notes.lower()

    def test_risk_escalation_workflow(self, registry):
        """Test that high-risk changes are properly flagged."""
        # High-risk: Modifying critical tables
        critical_intent = registry.register(
            agent_id="claude-system",
            feature_name="system_upgrade",
            schema_changes=[
                "ALTER TABLE users DROP COLUMN deprecated_field",
                "ALTER TABLE users ADD COLUMN new_system_field JSONB",
            ],
            tables_affected=["users"],
            risk_level="high",
            metadata={"requires_approval": True, "requires_backup": True},
        )

        # Medium-risk: Adding new feature
        feature_intent = registry.register(
            agent_id="claude-features",
            feature_name="new_feature",
            schema_changes=[
                "CREATE TABLE feature_data (id INT, data TEXT)",
                "CREATE INDEX idx_feature_data ON feature_data(id)",
            ],
            tables_affected=["feature_data"],
            risk_level="medium",
        )

        assert critical_intent.risk_level == RiskLevel.HIGH
        assert feature_intent.risk_level == RiskLevel.MEDIUM
        assert critical_intent.metadata.get("requires_approval") is True


class TestMultiAgentScenarios:
    """Test complex multi-agent coordination scenarios."""

    def test_diamond_dependency_pattern(self, registry):
        """Test diamond dependency: A and B both depend on C."""
        # Base feature: User authentication
        base = registry.register(
            agent_id="claude-base",
            feature_name="authentication",
            schema_changes=["ALTER TABLE users ADD COLUMN auth_token TEXT"],
            tables_affected=["users"],
        )
        registry.mark_completed(base.id)
        registry.mark_merged(base.id)

        # Feature A: Payment processing (depends on auth)
        feature_a = registry.register(
            agent_id="claude-payments",
            feature_name="payments",
            schema_changes=["ALTER TABLE users ADD COLUMN payment_method TEXT"],
            tables_affected=["users"],
        )

        # Feature B: Notifications (depends on auth)
        feature_b = registry.register(
            agent_id="claude-notifications",
            feature_name="notifications",
            schema_changes=["ALTER TABLE users ADD COLUMN notification_prefs TEXT"],
            tables_affected=["users"],
        )

        # Both should conflict (both modifying users after base merged)
        assert feature_a.status == IntentStatus.REGISTERED
        assert feature_b.status == IntentStatus.CONFLICTED
        assert len(registry.get_conflicts(feature_b.id)) > 0

    def test_schema_reorganization_workflow(self, registry):
        """Test agents handling schema reorganization."""
        # Agent A: Add new organization table
        _ = registry.register(
            agent_id="claude-schema",
            feature_name="org_structure",
            schema_changes=[
                "CREATE TABLE organizations (id SERIAL PRIMARY KEY, name TEXT)",
                "ALTER TABLE users ADD COLUMN org_id INT REFERENCES organizations(id)",
            ],
            tables_affected=["organizations", "users"],
            risk_level="high",
        )

        # Agent B: Add user profile features (also touches users)
        profile_intent = registry.register(
            agent_id="claude-profiles",
            feature_name="user_profiles",
            schema_changes=[
                "ALTER TABLE users ADD COLUMN bio TEXT",
                "ALTER TABLE users ADD COLUMN avatar_url TEXT",
            ],
            tables_affected=["users"],
        )

        # Should detect conflict
        assert profile_intent.status == IntentStatus.CONFLICTED
        conflicts = registry.get_conflicts(profile_intent.id)
        assert len(conflicts) > 0
        assert conflicts[0].conflict_type == ConflictType.TABLE


class TestBranchManagement:
    """Test branch allocation and naming for agents."""

    def test_branch_naming_consistency(self, registry):
        """Branches should have consistent, meaningful names."""
        intent_a = registry.register(
            agent_id="claude-a",
            feature_name="stripe_payments",
            schema_changes=["ALTER TABLE users ADD COLUMN stripe_id TEXT"],
            tables_affected=["users"],
        )

        intent_b = registry.register(
            agent_id="claude-b",
            feature_name="stripe_payments",  # Same feature name
            schema_changes=["ALTER TABLE users ADD COLUMN stripe_customer_id TEXT"],
            tables_affected=["users"],
        )

        # Both should have unique branches
        assert intent_a.branch_name != intent_b.branch_name
        assert intent_a.branch_name.startswith("feature/")
        assert intent_b.branch_name.startswith("feature/")
        assert "stripe" in intent_a.branch_name
        assert "stripe" in intent_b.branch_name

    def test_branch_allocation_with_special_characters(self, registry):
        """Branch names should handle special characters safely."""
        intent = registry.register(
            agent_id="claude-special",
            feature_name="api/v2/users endpoint",
            schema_changes=["ALTER TABLE users ADD COLUMN x TEXT"],
            tables_affected=["users"],
        )

        # Should have sanitized branch name
        assert "/" not in intent.branch_name or intent.branch_name.startswith("feature/")
        assert "api_v2_users" in intent.branch_name or "endpoint" in intent.branch_name.lower()


class TestStatusTrackingAndAudit:
    """Test status transitions and audit trail."""

    def test_complete_lifecycle_audit_trail(self, registry, test_db_connection):
        """Complete status lifecycle should be tracked."""
        intent = registry.register(
            agent_id="claude-test",
            feature_name="test_feature",
            schema_changes=["ALTER TABLE t ADD COLUMN c TEXT"],
            tables_affected=["t"],
        )

        # Transition through lifecycle
        registry.mark_in_progress(
            intent.id, reason="Developer started work", changed_by="claude-test"
        )
        registry.mark_completed(intent.id, reason="All changes applied", changed_by="claude-test")
        registry.mark_merged(intent.id, reason="Merged to main branch", changed_by="system")

        # Check audit trail
        with test_db_connection.cursor() as cursor:
            cursor.execute(
                "SELECT old_status, new_status, reason, changed_by FROM tb_pggit_intent_history "
                "WHERE intent_id = %s ORDER BY changed_at",
                (intent.id,),
            )
            rows = cursor.fetchall()

        # Should have 3 transitions
        assert len(rows) == 3

        # Verify each transition
        assert rows[0] == ("registered", "in_progress", "Developer started work", "claude-test")
        assert rows[1] == ("in_progress", "completed", "All changes applied", "claude-test")
        assert rows[2] == ("completed", "merged", "Merged to main branch", "system")

    def test_abandoned_intent_workflow(self, registry):
        """Test abandoning an intent mid-workflow."""
        intent = registry.register(
            agent_id="claude-test",
            feature_name="experimental",
            schema_changes=["ALTER TABLE t ADD COLUMN c TEXT"],
            tables_affected=["t"],
        )

        registry.mark_in_progress(intent.id, reason="Starting work")
        registry.mark_abandoned(intent.id, reason="Feature cancelled by product team")

        final_intent = registry.get_intent(intent.id)
        assert final_intent.status == IntentStatus.ABANDONED


class TestConflictTypes:
    """Test detection of various conflict types."""

    def test_function_redefinition_conflict(self, registry):
        """Detect when two agents modify the same function."""
        _ = registry.register(
            agent_id="claude-a",
            feature_name="calculate_total",
            schema_changes=[
                "CREATE FUNCTION calculate_total(items INT[]) RETURNS NUMERIC AS $$ "
                "SELECT SUM(i) FROM UNNEST(items) i $$ LANGUAGE SQL"
            ],
            tables_affected=[],
        )

        intent_b = registry.register(
            agent_id="claude-b",
            feature_name="optimize_calculate",
            schema_changes=[
                "DROP FUNCTION calculate_total",
                "CREATE FUNCTION calculate_total(items INT[], tax_rate NUMERIC) RETURNS NUMERIC "
                "LANGUAGE SQL AS $$ SELECT SUM(i) * (1 + tax_rate) FROM UNNEST(items) i $$",
            ],
            tables_affected=[],
        )

        # Should detect function conflict
        conflicts = registry.get_conflicts(intent_b.id)
        assert len(conflicts) > 0

        function_conflicts = [c for c in conflicts if c.conflict_type == ConflictType.FUNCTION]
        assert len(function_conflicts) > 0
        assert "calculate_total" in function_conflicts[0].affected_objects[0]

    def test_index_conflict_detection(self, registry):
        """Detect when two agents create overlapping indexes."""
        _ = registry.register(
            agent_id="claude-a",
            feature_name="email_index",
            schema_changes=[
                "CREATE INDEX idx_users_email ON users(email)",
            ],
            tables_affected=["users"],
        )

        intent_b = registry.register(
            agent_id="claude-b",
            feature_name="email_unique_index",
            schema_changes=[
                "CREATE UNIQUE INDEX idx_users_email_unique ON users(email)",
            ],
            tables_affected=["users"],
        )

        # Both on same table - should detect
        conflicts = registry.get_conflicts(intent_b.id)
        assert len(conflicts) > 0


class TestMetadataAndCustomization:
    """Test custom metadata and configuration."""

    def test_intent_metadata_preservation(self, registry):
        """Intent metadata should be preserved through registration."""
        metadata = {
            "ticket_id": "TICKET-123",
            "priority": "critical",
            "requires_review": True,
            "estimated_hours": 4,
            "team": "payments",
        }

        intent = registry.register(
            agent_id="claude-payments",
            feature_name="critical_fix",
            schema_changes=["ALTER TABLE users ADD COLUMN x TEXT"],
            tables_affected=["users"],
            metadata=metadata,
        )

        retrieved = registry.get_intent(intent.id)
        assert retrieved.metadata == metadata

    def test_estimated_duration_tracking(self, registry):
        """Estimated duration should be tracked."""
        quick_task = registry.register(
            agent_id="claude-quick",
            feature_name="quick_fix",
            schema_changes=["ALTER TABLE t ADD COLUMN c TEXT"],
            tables_affected=["t"],
            estimated_duration_ms=1000,
        )

        long_task = registry.register(
            agent_id="claude-long",
            feature_name="long_feature",
            schema_changes=["CREATE TABLE new_table (id INT)"],
            tables_affected=["new_table"],
            estimated_duration_ms=3600000,  # 1 hour
        )

        assert quick_task.estimated_duration_ms == 1000
        assert long_task.estimated_duration_ms == 3600000


class TestErrorRecovery:
    """Test error conditions and recovery."""

    def test_cannot_update_unknown_intent(self, registry):
        """Updating unknown intent should raise error."""
        with pytest.raises(ValueError, match="not found"):
            registry.mark_in_progress("nonexistent_id")

    def test_empty_table_list_extracted_from_ddl(self, registry):
        """Tables should be extracted even if not explicitly provided."""
        intent = registry.register(
            agent_id="claude-test",
            feature_name="test",
            schema_changes=[
                "ALTER TABLE users ADD COLUMN x TEXT",
                "ALTER TABLE orders ADD COLUMN y TEXT",
            ],
            tables_affected=None,  # Not provided - should extract
        )

        assert "users" in intent.tables_affected
        assert "orders" in intent.tables_affected
        assert len(intent.tables_affected) >= 2

    def test_conflicting_intents_cannot_be_same_agent(self, registry):
        """Same agent modifying same table should not create conflicts."""
        intent_a = registry.register(
            agent_id="claude-one",
            feature_name="feature_a",
            schema_changes=["ALTER TABLE users ADD COLUMN col_a TEXT"],
            tables_affected=["users"],
        )

        intent_b = registry.register(
            agent_id="claude-one",  # Same agent
            feature_name="feature_b",
            schema_changes=["ALTER TABLE users ADD COLUMN col_b TEXT"],
            tables_affected=["users"],
        )

        # Should not conflict - same agent
        assert intent_a.status == IntentStatus.REGISTERED
        assert intent_b.status == IntentStatus.REGISTERED
        assert len(registry.get_conflicts(intent_b.id)) == 0


class TestScalability:
    """Test behavior with many agents and intents."""

    def test_many_independent_intents(self, registry):
        """Should handle many independent intents."""
        intents = []
        for i in range(10):
            intent = registry.register(
                agent_id=f"claude-agent-{i}",
                feature_name=f"feature_{i}",
                schema_changes=[f"CREATE TABLE table_{i} (id INT)"],
                tables_affected=[f"table_{i}"],
            )
            intents.append(intent)

        # All should be registered without conflicts
        for intent in intents:
            assert intent.status == IntentStatus.REGISTERED
            assert len(registry.get_conflicts(intent.id)) == 0

        # Should be able to list all
        all_intents = registry.list_intents()
        assert len(all_intents) >= 10

    def test_many_conflicting_intents(self, registry):
        """Should handle many intents on same table."""
        intents = []
        for i in range(5):
            intent = registry.register(
                agent_id=f"agent-{i}",
                feature_name=f"feature_{i}",
                schema_changes=[f"ALTER TABLE users ADD COLUMN col_{i} TEXT"],
                tables_affected=["users"],
            )
            intents.append(intent)

        # First should not conflict, rest should
        assert intents[0].status == IntentStatus.REGISTERED
        for intent in intents[1:]:
            assert intent.status == IntentStatus.CONFLICTED

        # All except first should have conflicts
        for intent in intents[1:]:
            assert len(registry.get_conflicts(intent.id)) > 0
