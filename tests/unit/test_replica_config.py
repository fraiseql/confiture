"""Tests for replica-safety config (issue #139, Phase 3)."""

from __future__ import annotations

from confiture.config.environment import Environment, InfrastructureConfig, MigrationConfig


def test_allow_unsafe_default_false() -> None:
    assert MigrationConfig().allow_unsafe_under_replication is False


def test_infrastructure_replicas_default_empty() -> None:
    assert InfrastructureConfig().replicas == []


def test_environment_has_infrastructure_default() -> None:
    env = Environment.model_validate(
        {
            "name": "test",
            "database_url": "postgresql://localhost/app",
            "include_dirs": ["db/schema"],
        }
    )
    assert env.infrastructure.replicas == []
    assert env.migration.allow_unsafe_under_replication is False


def test_environment_reads_replicas_and_bypass() -> None:
    env = Environment.model_validate(
        {
            "name": "test",
            "database_url": "postgresql://localhost/app",
            "include_dirs": ["db/schema"],
            "infrastructure": {"replicas": ["read-1", "read-2"]},
            "migration": {"allow_unsafe_under_replication": True},
        }
    )
    assert env.infrastructure.replicas == ["read-1", "read-2"]
    assert env.migration.allow_unsafe_under_replication is True
