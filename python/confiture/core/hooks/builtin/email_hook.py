"""Email notification hook via SMTP."""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from confiture.core.hooks.base import Hook, HookResult
from confiture.core.hooks.context import ExecutionContext, HookContext

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailConfig:
    """Configuration for email notification hook."""

    smtp_server: str
    smtp_username: str
    smtp_password: str
    from_email: str
    to_emails: list[str]
    smtp_port: int = 587  # TLS
    subject_prefix: str = "[Confiture Migration]"
    send_on_success: bool = True
    send_on_failure: bool = True


class EmailNotificationHook(Hook[ExecutionContext]):
    """Send migration status emails via SMTP.

    Registers on HookPhase.after_execute. Sends HTML emails with
    migration details. Can be configured to send on success, failure, or both.
    """

    def __init__(self, config: EmailConfig) -> None:
        super().__init__(
            hook_id="builtin.email",
            name="Email Notification",
            priority=9,  # run last
        )
        self._config = config

    async def execute(
        self,
        context: HookContext[ExecutionContext],
    ) -> HookResult:
        ctx = context.get_data()

        # Check if we should send based on success/failure settings
        if ctx.metadata.get("success", True) and not self._config.send_on_success:
            return HookResult(success=True, stats={"skipped": "success notification disabled"})

        if not ctx.metadata.get("success", True) and not self._config.send_on_failure:
            return HookResult(success=True, stats={"skipped": "failure notification disabled"})

        subject, html_body = self._build_email(ctx)

        try:
            # Create message
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self._config.from_email
            msg["To"] = ", ".join(self._config.to_emails)

            # Attach HTML body
            html_part = MIMEText(html_body, "html")
            msg.attach(html_part)

            # Send email
            server = smtplib.SMTP(self._config.smtp_server, self._config.smtp_port)
            server.starttls()
            server.login(self._config.smtp_username, self._config.smtp_password)
            server.sendmail(self._config.from_email, self._config.to_emails, msg.as_string())
            server.quit()

            logger.info("Email notification sent to %s", self._config.to_emails)
            return HookResult(success=True, stats={"recipients": len(self._config.to_emails)})

        except Exception as exc:
            logger.warning("Email notification failed: %s", exc)
            return HookResult(success=False, error=str(exc))

    def _build_email(self, ctx: ExecutionContext) -> tuple[str, str]:
        """Build email subject and HTML body."""
        migration_name = ctx.metadata.get("migration_name", "unknown")
        direction = ctx.metadata.get("direction", "unknown")
        success = ctx.metadata.get("success", True)
        error = ctx.metadata.get("error")

        status = "✅ SUCCEEDED" if success else "❌ FAILED"
        color = "#28a745" if success else "#dc3545"

        subject = f"{self._config.subject_prefix} {migration_name} ({direction}) {status}"

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="border: 1px solid #ddd; border-radius: 8px; padding: 20px; margin: 20px 0;">
                <h2 style="color: {color}; margin-top: 0;">
                    Migration {status}
                </h2>

                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 8px 0; font-weight: bold;">Migration:</td>
                        <td style="padding: 8px 0;">{migration_name}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; font-weight: bold;">Direction:</td>
                        <td style="padding: 8px 0;">{direction}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; font-weight: bold;">Duration:</td>
                        <td style="padding: 8px 0;">{ctx.elapsed_time_ms}ms</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; font-weight: bold;">Time:</td>
                        <td style="padding: 8px 0;">{
            __import__("datetime")
            .datetime.now(__import__("datetime").UTC)
            .strftime("%Y-%m-%d %H:%M UTC")
        }</td>
                    </tr>
                </table>

                {
            "<div style='margin-top: 20px; padding: 15px; background-color: #f8d7da; border: 1px solid #f5c6cb; border-radius: 4px;'>"
            + f"<strong>Error:</strong><br><pre>{error}</pre>"
            + "</div>"
            if error
            else ""
        }
            </div>

            <div style="text-align: center; color: #666; font-size: 12px; margin-top: 20px;">
                Sent by Confiture Migration Tool
            </div>
        </body>
        </html>
        """

        return subject, html
