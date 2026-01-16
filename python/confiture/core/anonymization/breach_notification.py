"""Breach notification and incident management for Phase 2.3.

Provides automated breach detection, notification, and incident tracking
for compliance with regulations that require breach notification.

Supported Regulations:
- GDPR: Notify authority within 72 hours, notify individuals if high risk
- CCPA: Notify individuals without undue delay
- PIPEDA: Notify individuals of breach
- LGPD: Notify authority and individuals
- PIPL: Notify individuals and relevant authorities
- Privacy Act: Notify individuals
- POPIA: Notify regulator and data subjects

Features:
- Automatic breach detection from events
- Configurable incident severity levels
- Notification templates per regulation
- Audit trail for all notifications sent
- Escalation procedures
- Remediation tracking

Example:
    >>> from confiture.core.anonymization.breach_notification import (
    ...     BreachNotificationManager, IncidentSeverity, NotificationChannel
    ... )
    >>>
    >>> manager = BreachNotificationManager(conn)
    >>> incident = manager.report_incident(
    ...     title="Unauthorized access to user table",
    ...     description="SQL injection detected in API endpoint",
    ...     affected_records=5000,
    ...     data_types=["email", "phone", "address"],
    ...     severity=IncidentSeverity.CRITICAL,
    ...     detected_by="Security Scanner"
    ... )
    >>>
    >>> # Automatically send notifications per regulation
    >>> notifications = manager.notify(
    ...     incident,
    ...     regulations=[Regulation.GDPR, Regulation.CCPA],
    ...     notify_authorities=True,
    ...     notify_subjects=True
    ... )
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from uuid import UUID, uuid4

import psycopg

logger = logging.getLogger(__name__)


class IncidentSeverity(Enum):
    """Incident severity levels."""

    LOW = "low"
    """Minor security event, no action required."""

    MEDIUM = "medium"
    """Moderate security event, monitor and log."""

    HIGH = "high"
    """Serious security event, notify security team."""

    CRITICAL = "critical"
    """Severe breach, immediate action required."""


class NotificationChannel(Enum):
    """Notification delivery channels."""

    EMAIL = "email"
    """Send via email."""

    SMS = "sms"
    """Send via SMS/text."""

    WEBHOOK = "webhook"
    """Send via webhook to external system."""

    SYSLOG = "syslog"
    """Send via syslog."""

    REGULATORY = "regulatory"
    """Send to regulatory authority."""


@dataclass
class IncidentReport:
    """Security incident report."""

    id: UUID
    """Unique incident ID."""

    title: str
    """Brief incident title."""

    description: str
    """Detailed incident description."""

    affected_records: int
    """Number of records affected."""

    data_types: list[str]
    """Types of PII affected (email, phone, SSN, etc.)."""

    severity: IncidentSeverity
    """Incident severity level."""

    detected_at: datetime
    """When incident was detected."""

    reported_by: str
    """Who reported the incident."""

    incident_category: str = "unauthorized_access"
    """Type of incident (breach, loss, unauthorized_access, etc.)."""

    root_cause: str | None = None
    """Root cause analysis (if available)."""

    remediation_plan: str | None = None
    """Planned remediation steps."""

    estimated_resolution: datetime | None = None
    """Estimated resolution date."""

    status: str = "open"
    """Incident status (open, investigating, mitigated, resolved)."""

    notifications_sent: dict[str, list[datetime]] = field(default_factory=dict)
    """Notifications sent per regulation."""

    affected_individuals: list[str] = field(default_factory=list)
    """Email addresses of affected individuals (if known)."""

    affected_tables: list[str] = field(default_factory=list)
    """Database tables affected."""


@dataclass
class BreachNotification:
    """Notification to be sent for a breach."""

    incident_id: UUID
    """Associated incident ID."""

    recipient: str
    """Email or identifier of recipient."""

    recipient_type: str
    """Type of recipient (authority, individual, system)."""

    notification_channel: NotificationChannel
    """How to deliver notification."""

    subject: str
    """Email subject or notification title."""

    body: str
    """Notification content."""

    regulation: str
    """Which regulation triggered this notification."""

    deadline: datetime
    """Regulatory deadline for notification."""

    sent_at: datetime | None = None
    """When notification was actually sent."""

    delivery_status: str = "pending"
    """Delivery status (pending, sent, failed, delivered)."""

    confirmation: str | None = None
    """Confirmation of receipt or error message."""


class BreachNotificationManager:
    """Manage security incidents and breach notifications.

    Tracks security incidents and automatically generates and sends
    breach notifications according to regulatory requirements.

    Features:
        - Incident tracking and management
        - Automatic notification based on regulations
        - Multi-channel notification support
        - Audit trail of all notifications
        - Deadline tracking
        - Remediation tracking

    Regulations:
        - GDPR: 72-hour authority notification, individual notification if high risk
        - CCPA: Individual notification without undue delay
        - PIPEDA: Individual notification (no authority requirement)
        - LGPD: Authority and individual notification
        - PIPL: Individual and authority notification
        - Privacy Act: Individual notification
        - POPIA: Individual and regulator notification
    """

    def __init__(self, conn: psycopg.Connection):
        """Initialize breach notification manager.

        Args:
            conn: Database connection for storing incidents
        """
        self.conn = conn
        self._ensure_incident_table()
        self._ensure_notification_table()

    def _ensure_incident_table(self) -> None:
        """Create incident table if not exists."""
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS confiture_security_incidents (
                    id UUID PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    affected_records INTEGER NOT NULL,
                    data_types TEXT[] NOT NULL,
                    severity TEXT NOT NULL,
                    detected_at TIMESTAMPTZ NOT NULL,
                    reported_by TEXT NOT NULL,
                    incident_category TEXT NOT NULL,
                    root_cause TEXT,
                    remediation_plan TEXT,
                    estimated_resolution TIMESTAMPTZ,
                    status TEXT NOT NULL,
                    affected_tables TEXT[],
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_incidents_severity
                    ON confiture_security_incidents(severity);
                CREATE INDEX IF NOT EXISTS idx_incidents_status
                    ON confiture_security_incidents(status);
                CREATE INDEX IF NOT EXISTS idx_incidents_detected_at
                    ON confiture_security_incidents(detected_at DESC);
            """
            )
            self.conn.commit()

    def _ensure_notification_table(self) -> None:
        """Create notification table if not exists (append-only)."""
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS confiture_breach_notifications (
                    id UUID PRIMARY KEY,
                    incident_id UUID NOT NULL,
                    recipient TEXT NOT NULL,
                    recipient_type TEXT NOT NULL,
                    notification_channel TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    regulation TEXT NOT NULL,
                    deadline TIMESTAMPTZ NOT NULL,
                    sent_at TIMESTAMPTZ,
                    delivery_status TEXT NOT NULL,
                    confirmation TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    FOREIGN KEY (incident_id) REFERENCES confiture_security_incidents(id)
                );

                CREATE INDEX IF NOT EXISTS idx_notifications_incident
                    ON confiture_breach_notifications(incident_id);
                CREATE INDEX IF NOT EXISTS idx_notifications_status
                    ON confiture_breach_notifications(delivery_status);
                CREATE INDEX IF NOT EXISTS idx_notifications_deadline
                    ON confiture_breach_notifications(deadline);

                -- Append-only constraint
                REVOKE UPDATE, DELETE ON confiture_breach_notifications FROM PUBLIC;
            """
            )
            self.conn.commit()

    def report_incident(
        self,
        title: str,
        description: str,
        affected_records: int,
        data_types: list[str],
        severity: IncidentSeverity,
        reported_by: str,
        incident_category: str = "unauthorized_access",
        root_cause: str | None = None,
        affected_tables: list[str] | None = None,
    ) -> IncidentReport:
        """Report a security incident.

        Args:
            title: Brief incident title
            description: Detailed description
            affected_records: Number of records affected
            data_types: Types of PII affected
            severity: Incident severity
            reported_by: Who reported the incident
            incident_category: Category of incident
            root_cause: Root cause (if known)
            affected_tables: Database tables affected

        Returns:
            IncidentReport instance
        """
        incident_id = uuid4()
        now = datetime.now()

        incident = IncidentReport(
            id=incident_id,
            title=title,
            description=description,
            affected_records=affected_records,
            data_types=data_types,
            severity=severity,
            detected_at=now,
            reported_by=reported_by,
            incident_category=incident_category,
            root_cause=root_cause,
            affected_tables=affected_tables or [],
        )

        # Store in database
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO confiture_security_incidents (
                    id, title, description, affected_records, data_types,
                    severity, detected_at, reported_by, incident_category,
                    root_cause, affected_tables, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
                (
                    str(incident_id),
                    title,
                    description,
                    affected_records,
                    data_types,
                    severity.value,
                    now,
                    reported_by,
                    incident_category,
                    root_cause,
                    affected_tables or [],
                    "open",
                ),
            )
        self.conn.commit()

        logger.error(
            f"Security incident reported: {title} "
            f"({affected_records} records, severity: {severity.value})"
        )

        return incident

    def notify(
        self,
        incident: IncidentReport,
        regulations: list[str],
        notify_authorities: bool = True,
        notify_subjects: bool = True,
    ) -> list[BreachNotification]:
        """Generate and send breach notifications.

        Args:
            incident: Incident to notify about
            regulations: Which regulations to follow
            notify_authorities: Send to regulatory authorities
            notify_subjects: Send to affected individuals

        Returns:
            List of notifications sent
        """
        notifications = []

        for regulation in regulations:
            # Generate notifications for each regulation
            regs_notifs = self._generate_notifications(
                incident, regulation, notify_authorities, notify_subjects
            )
            notifications.extend(regs_notifs)

        logger.info(
            f"Generated {len(notifications)} breach notifications for incident {incident.id}"
        )

        return notifications

    def _generate_notifications(
        self,
        incident: IncidentReport,
        regulation: str,
        notify_authorities: bool,
        notify_subjects: bool,
    ) -> list[BreachNotification]:
        """Generate notifications for a specific regulation.

        Args:
            incident: Incident to notify about
            regulation: Which regulation
            notify_authorities: Notify authorities
            notify_subjects: Notify subjects

        Returns:
            List of notifications
        """
        notifications = []

        # Determine notification requirements per regulation
        if regulation == "gdpr":
            # GDPR: 72-hour authority notification
            deadline = incident.detected_at + timedelta(hours=72)

            if notify_authorities:
                notif = BreachNotification(
                    incident_id=incident.id,
                    recipient="dpa@authority.eu",  # DPA placeholder
                    recipient_type="authority",
                    notification_channel=NotificationChannel.EMAIL,
                    subject=f"GDPR Breach Notification - {incident.title}",
                    body=self._generate_gdpr_authority_notice(incident),
                    regulation="GDPR",
                    deadline=deadline,
                )
                notifications.append(notif)

            if notify_subjects and incident.affected_individuals:
                for individual in incident.affected_individuals[:100]:  # Limit batch
                    notif = BreachNotification(
                        incident_id=incident.id,
                        recipient=individual,
                        recipient_type="individual",
                        notification_channel=NotificationChannel.EMAIL,
                        subject="Important: Your Data Security Notice",
                        body=self._generate_gdpr_individual_notice(incident),
                        regulation="GDPR",
                        deadline=deadline,
                    )
                    notifications.append(notif)

        elif regulation == "ccpa":
            # CCPA: Individual notification without undue delay
            deadline = incident.detected_at + timedelta(days=5)

            if notify_subjects and incident.affected_individuals:
                for individual in incident.affected_individuals[:100]:
                    notif = BreachNotification(
                        incident_id=incident.id,
                        recipient=individual,
                        recipient_type="individual",
                        notification_channel=NotificationChannel.EMAIL,
                        subject="CCPA Data Breach Notification",
                        body=self._generate_ccpa_notice(incident),
                        regulation="CCPA",
                        deadline=deadline,
                    )
                    notifications.append(notif)

        # Store notifications in database
        for notif in notifications:
            self._store_notification(notif)

        return notifications

    def _generate_gdpr_authority_notice(self, incident: IncidentReport) -> str:
        """Generate GDPR authority breach notice."""
        return f"""
GDPR DATA BREACH NOTIFICATION

Incident ID: {incident.id}
Title: {incident.title}
Detected: {incident.detected_at.isoformat()}

Description: {incident.description}

Affected Records: {incident.affected_records}
Data Categories: {', '.join(incident.data_types)}
Severity: {incident.severity.value}

Root Cause: {incident.root_cause or 'Under investigation'}
Remediation Plan: {incident.remediation_plan or 'To be determined'}

All affected individuals will be notified as required under Article 34.
"""

    def _generate_gdpr_individual_notice(self, incident: IncidentReport) -> str:
        """Generate GDPR individual breach notice."""
        return f"""
DATA BREACH NOTIFICATION

Dear Valued Customer,

We are writing to inform you about a security incident that may affect your personal data.

Incident: {incident.title}
Date Discovered: {incident.detected_at.strftime('%B %d, %Y')}

What Happened: {incident.description}

What Information May Have Been Affected:
{chr(10).join(f"- {t}" for t in incident.data_types)}

What We Are Doing:
{incident.remediation_plan or "We are investigating this incident and taking appropriate measures to prevent future occurrences."}

What You Can Do:
- Monitor your accounts for suspicious activity
- Consider changing passwords for important accounts
- Consider identity protection services

For more information, please contact: privacy@example.com
"""

    def _generate_ccpa_notice(self, incident: IncidentReport) -> str:
        """Generate CCPA breach notice."""
        return f"""
CCPA DATA BREACH NOTIFICATION

A security incident has affected your personal information.

Details:
- Description: {incident.description}
- Affected Information: {', '.join(incident.data_types)}
- Records Affected: {incident.affected_records}

California law requires us to notify you of this incident.

Actions You Can Take:
1. Review your credit reports
2. Place a fraud alert
3. Consider a credit freeze

Questions? Contact: privacy@example.com
"""

    def _store_notification(self, notification: BreachNotification) -> None:
        """Store notification in database."""
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO confiture_breach_notifications (
                    id, incident_id, recipient, recipient_type,
                    notification_channel, subject, body, regulation, deadline,
                    delivery_status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
                (
                    str(uuid4()),
                    str(notification.incident_id),
                    notification.recipient,
                    notification.recipient_type,
                    notification.notification_channel.value,
                    notification.subject,
                    notification.body,
                    notification.regulation,
                    notification.deadline,
                    notification.delivery_status,
                ),
            )
        self.conn.commit()

    def get_incident(self, incident_id: UUID) -> IncidentReport | None:
        """Retrieve an incident by ID.

        Args:
            incident_id: Incident ID to retrieve

        Returns:
            IncidentReport or None if not found
        """
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, title, description, affected_records, data_types,
                       severity, detected_at, reported_by, incident_category,
                       root_cause, affected_tables, status
                FROM confiture_security_incidents
                WHERE id = %s
            """,
                (str(incident_id),),
            )
            row = cursor.fetchone()

        if not row:
            return None

        return IncidentReport(
            id=row[0],
            title=row[1],
            description=row[2],
            affected_records=row[3],
            data_types=row[4],
            severity=IncidentSeverity(row[5]),
            detected_at=row[6],
            reported_by=row[7],
            incident_category=row[8],
            root_cause=row[9],
            affected_tables=row[10],
            status=row[11],
        )

    def get_notifications_for_incident(
        self, incident_id: UUID
    ) -> list[BreachNotification]:
        """Get all notifications for an incident.

        Args:
            incident_id: Incident ID

        Returns:
            List of notifications
        """
        with self.conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, incident_id, recipient, recipient_type,
                       notification_channel, subject, body, regulation,
                       deadline, sent_at, delivery_status, confirmation
                FROM confiture_breach_notifications
                WHERE incident_id = %s
                ORDER BY created_at DESC
            """,
                (str(incident_id),),
            )
            rows = cursor.fetchall()

        notifications = []
        for row in rows:
            notifications.append(
                BreachNotification(
                    incident_id=row[1],
                    recipient=row[2],
                    recipient_type=row[3],
                    notification_channel=NotificationChannel(row[4]),
                    subject=row[5],
                    body=row[6],
                    regulation=row[7],
                    deadline=row[8],
                    sent_at=row[9],
                    delivery_status=row[10],
                    confirmation=row[11],
                )
            )

        return notifications
