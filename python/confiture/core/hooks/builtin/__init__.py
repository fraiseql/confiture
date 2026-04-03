"""Builtin migration hooks for production deployments."""

from confiture.core.hooks.builtin.audit_hook import AuditConfig, AuditHook
from confiture.core.hooks.builtin.backup_hook import BackupConfig, BackupHook
from confiture.core.hooks.builtin.discord_hook import DiscordConfig, DiscordNotificationHook
from confiture.core.hooks.builtin.email_hook import EmailConfig, EmailNotificationHook
from confiture.core.hooks.builtin.notification_hook import (
    SlackConfig,
    SlackNotificationHook,
)
from confiture.core.hooks.builtin.teams_hook import TeamsConfig, TeamsNotificationHook
from confiture.core.hooks.builtin.webhook_hook import WebhookConfig, WebhookNotificationHook

__all__ = [
    "AuditConfig",
    "AuditHook",
    "BackupConfig",
    "BackupHook",
    "DiscordConfig",
    "DiscordNotificationHook",
    "EmailConfig",
    "EmailNotificationHook",
    "SlackConfig",
    "SlackNotificationHook",
    "TeamsConfig",
    "TeamsNotificationHook",
    "WebhookConfig",
    "WebhookNotificationHook",
]
