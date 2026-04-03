"""Builtin migration hooks for production deployments."""

from confiture.core.hooks.builtin.audit_hook import AuditConfig, AuditHook
from confiture.core.hooks.builtin.backup_hook import BackupConfig, BackupHook
from confiture.core.hooks.builtin.notification_hook import (
    SlackConfig,
    SlackNotificationHook,
)
