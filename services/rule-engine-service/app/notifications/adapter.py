"""Notification adapter layer for multi-channel alerting."""

from __future__ import annotations

import logging
import smtplib
import ssl
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import formatdate, make_msgid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, Optional

import httpx

from app.config import settings
from app.models.rule import NotificationDeliveryStatus, Rule
from app.services.notification_delivery import NotificationDeliveryAuditService
from app.utils.recipients import normalize_phone_recipient
from app.utils.timezone import format_platform_datetime, platform_tz_label

logger = logging.getLogger(__name__)


@dataclass
class NotificationRecipientResult:
    recipient: str
    channel: str
    provider_name: str
    status: str
    attempted_at: datetime
    provider_message_id: Optional[str] = None
    accepted_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    failure_code: Optional[str] = None
    failure_message: Optional[str] = None
    billable_units: int = 0
    audit_log_id: Optional[str] = None
    metadata_json: Optional[dict[str, Any]] = None


@dataclass
class NotificationDispatchResult:
    channel: str
    provider_name: str
    recipient_results: list[NotificationRecipientResult] = field(default_factory=list)
    forced_success: Optional[bool] = None

    @property
    def overall_success(self) -> bool:
        if self.forced_success is not None:
            return self.forced_success
        return all(
            result.status in {NotificationDeliveryStatus.PROVIDER_ACCEPTED.value, NotificationDeliveryStatus.DELIVERED.value}
            for result in self.recipient_results
        ) or not self.recipient_results


class NotificationChannel(ABC):
    """Abstract base class for notification channels."""

    channel_name: str
    provider_name: str

    @abstractmethod
    async def dispatch_alert(
        self,
        subject: str,
        message: str,
        rule: Rule,
        device_id: str,
        alert_type: str = "threshold_alert",
        alert_id: Optional[str] = None,
        **kwargs: Any,
    ) -> NotificationDispatchResult:
        """Dispatch a notification and return per-recipient delivery outcomes."""

    async def send(
        self,
        message: str,
        rule: Rule,
        device_id: str,
        **kwargs: Any,
    ) -> bool:
        result = await self.dispatch_alert(
            subject=f"Alert: {rule.rule_name}",
            message=message,
            rule=rule,
            device_id=device_id,
            alert_type=kwargs.pop("alert_type", "threshold_alert"),
            alert_id=kwargs.pop("alert_id", None),
            **kwargs,
        )
        return result.overall_success

    async def send_alert(
        self,
        subject: str,
        message: str,
        rule: Rule,
        device_id: str,
        alert_type: str = "threshold_alert",
        alert_id: Optional[str] = None,
        **kwargs: Any,
    ) -> bool:
        result = await self.dispatch_alert(
            subject=subject,
            message=message,
            rule=rule,
            device_id=device_id,
            alert_type=alert_type,
            alert_id=alert_id,
            **kwargs,
        )
        return result.overall_success

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if channel is healthy and available."""


class EmailAdapter(NotificationChannel):
    """Email notification adapter with SMTP support."""

    channel_name = "email"
    provider_name = "smtp"

    def __init__(self, audit_service: Optional[NotificationDeliveryAuditService] = None):
        self._audit_service = audit_service
        self._enabled = settings.EMAIL_ENABLED
        self._smtp_host = settings.EMAIL_SMTP_HOST
        self._smtp_port = settings.EMAIL_SMTP_PORT
        self._smtp_username = settings.EMAIL_SMTP_USERNAME
        self._smtp_password = settings.EMAIL_SMTP_PASSWORD
        self._from_address = settings.EMAIL_FROM_ADDRESS

    @staticmethod
    def _recipients_for_rule(rule: Rule) -> list[str]:
        recipients: list[str] = []
        for row in list(getattr(rule, "notification_recipients", []) or []):
            if not isinstance(row, dict):
                continue
            channel = str(row.get("channel") or "").strip().lower()
            value = str(row.get("value") or "").strip().lower()
            if channel != "email" or not value:
                continue
            recipients.append(value)
        return sorted(set(recipients))

    async def dispatch_alert(
        self,
        subject: str,
        message: str,
        rule: Rule,
        device_id: str,
        alert_type: str = "threshold_alert",
        alert_id: Optional[str] = None,
        device_names: Optional[str] = None,
        **kwargs: Any,
    ) -> NotificationDispatchResult:
        recipients = self._recipients_for_rule(rule)
        result = NotificationDispatchResult(channel=self.channel_name, provider_name=self.provider_name)
        if not recipients:
            logger.warning(
                "Email recipients not configured on rule",
                extra={"channel": "email", "rule_id": str(rule.rule_id) if rule.rule_id else None},
            )
            return result

        metadata = {
            "subject": subject,
            "alert_type": alert_type,
            "device_id": device_id,
        }
        if not self._enabled:
            await self._record_skipped_batch(
                recipients=recipients,
                rule=rule,
                device_id=device_id,
                event_type=alert_type,
                alert_id=alert_id,
                metadata=metadata,
                failure_code="channel_disabled",
                failure_message="Email notifications are disabled.",
                result=result,
            )
            logger.info("Email notifications disabled", extra={"channel": "email"})
            result.forced_success = True
            return result

        if not self._smtp_username or not self._smtp_password:
            await self._record_skipped_batch(
                recipients=recipients,
                rule=rule,
                device_id=device_id,
                event_type=alert_type,
                alert_id=alert_id,
                metadata=metadata,
                failure_code="missing_configuration",
                failure_message="Email SMTP credentials are missing.",
                result=result,
            )
            logger.warning("Email not configured - SMTP credentials missing", extra={"channel": "email"})
            result.forced_success = False
            return result

        attempt_logs = await self._create_attempt_logs(
            recipients=recipients,
            rule=rule,
            device_id=device_id,
            event_type=alert_type,
            alert_id=alert_id,
            metadata=metadata,
        )

        try:
            context = ssl.create_default_context()
            with smtplib.SMTP(self._smtp_host, self._smtp_port) as server:
                server.starttls(context=context)
                server.ehlo()
                server.login(self._smtp_username, self._smtp_password)
                for recipient in recipients:
                    msg = self._build_message(
                        recipient=recipient,
                        subject=subject,
                        plain_message=message,
                        rule=rule,
                        device_id=device_id,
                        alert_type=alert_type,
                        device_names=device_names,
                    )
                    refused = server.sendmail(self._from_address, [recipient], msg.as_string()) or {}
                    refusal = refused.get(recipient)
                    if refusal is not None:
                        code, detail = self._normalize_smtp_refusal(refusal)
                        result.recipient_results.append(
                            await self._record_failed_result(
                                recipient=recipient,
                                attempt_log_id=attempt_logs.get(recipient),
                                failure_code=code,
                                failure_message=detail,
                                metadata=metadata,
                            )
                        )
                        continue
                    result.recipient_results.append(
                        await self._record_provider_accepted_result(
                            recipient=recipient,
                            attempt_log_id=attempt_logs.get(recipient),
                            metadata=metadata,
                        )
                    )

            logger.info(
                "Email sent",
                extra={
                    "channel": "email",
                    "to": recipients,
                    "subject": subject,
                    "rule_id": str(rule.rule_id) if rule.rule_id else None,
                    "device_id": device_id,
                    "alert_type": alert_type,
                },
            )
            return result
        except Exception as exc:
            logger.error(
                "Failed to send email",
                extra={
                    "channel": "email",
                    "error": str(exc),
                    "rule_id": str(rule.rule_id) if rule.rule_id else None,
                    "device_id": device_id,
                },
            )
            for recipient in recipients:
                result.recipient_results.append(
                    await self._record_failed_result(
                        recipient=recipient,
                        attempt_log_id=attempt_logs.get(recipient),
                        failure_code=exc.__class__.__name__,
                        failure_message=str(exc),
                        metadata=metadata,
                    )
                )
            return result

    def _build_message(
        self,
        *,
        recipient: str,
        subject: str,
        plain_message: str,
        rule: Rule,
        device_id: str,
        alert_type: str,
        device_names: Optional[str],
    ) -> MIMEMultipart:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._from_address
        msg["To"] = recipient
        msg["Date"] = formatdate(localtime=False)
        msg["Message-ID"] = make_msgid(domain=self._message_id_domain())

        if alert_type == "rule_created":
            html_content = self._format_rule_created_message(rule, device_id, plain_message, device_names)
        else:
            html_content = self._format_alert_message(rule, device_id, plain_message)

        msg.attach(MIMEText(plain_message, "plain"))
        msg.attach(MIMEText(html_content, "html"))
        return msg

    def _message_id_domain(self) -> Optional[str]:
        from_address = (self._from_address or "").strip()
        if "@" not in from_address:
            return None
        return from_address.split("@", 1)[1].strip().lower() or None

    @staticmethod
    def _normalize_smtp_refusal(refusal: Any) -> tuple[str, str]:
        if isinstance(refusal, tuple) and len(refusal) >= 2:
            code = str(refusal[0])
            message = refusal[1]
            if isinstance(message, bytes):
                message = message.decode("utf-8", errors="replace")
            return code, str(message)
        return "smtp_refused", str(refusal)

    def _format_alert_message(self, rule: Rule, device_id: str, message: str) -> str:
        condition_text, property_text = self._describe_rule(rule)
        return f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: #dc3545; color: white; padding: 20px; text-align: center; }}
        .content {{ padding: 20px; background: #f8f9fa; }}
        .alert-box {{ background: white; border-left: 4px solid #dc3545; padding: 15px; margin: 10px 0; }}
        .footer {{ text-align: center; padding: 20px; color: #666; font-size: 12px; }}
        .label {{ font-weight: bold; color: #555; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>🚨 Energy Alert</h2>
        </div>
        <div class="content">
            <div class="alert-box">
                <p><span class="label">Rule:</span> {rule.rule_name}</p>
                <p><span class="label">Device ID:</span> {device_id}</p>
                <p><span class="label">Property:</span> {property_text}</p>
                <p><span class="label">Condition:</span> {condition_text}</p>
                <p><span class="label">Message:</span> {message}</p>
                <p><span class="label">Time:</span> {format_platform_datetime(datetime.now(timezone.utc))}</p>
            </div>
        </div>
        <div class="footer">
            <p>This is an automated alert from Energy Platform</p>
        </div>
    </div>
</body>
</html>
"""

    def _format_rule_created_message(self, rule: Rule, device_id: str, message: str, device_names: str | None = None) -> str:
        status_value = rule.status.value if hasattr(rule.status, "value") else str(rule.status)
        condition_text, property_text = self._describe_rule(rule)

        devices_display = device_names if device_names else device_id

        return f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: #28a745; color: white; padding: 20px; text-align: center; }}
        .content {{ padding: 20px; background: #f8f9fa; }}
        .info-box {{ background: white; border-left: 4px solid #28a745; padding: 15px; margin: 10px 0; }}
        .footer {{ text-align: center; padding: 20px; color: #666; font-size: 12px; }}
        .label {{ font-weight: bold; color: #555; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>✅ Rule Created Successfully</h2>
        </div>
        <div class="content">
            <p>A new monitoring rule has been created in the Energy Platform.</p>
            <div class="info-box">
                <p><span class="label">Rule Name:</span> {rule.rule_name}</p>
                <p><span class="label">Rule ID:</span> {rule.rule_id}</p>
                <p><span class="label">Devices:</span> {devices_display}</p>
                <p><span class="label">Status:</span> {status_value}</p>
                <p><span class="label">Property:</span> {property_text}</p>
                <p><span class="label">Condition:</span> {condition_text}</p>
                <p><span class="label">Notification Channels:</span> {', '.join(rule.notification_channels) if rule.notification_channels else 'None'}</p>
                <p><span class="label">Created:</span> {format_platform_datetime(rule.created_at) if rule.created_at else format_platform_datetime(datetime.now(timezone.utc))}</p>
            </div>
            <p>{message}</p>
        </div>
        <div class="footer">
            <p>This is a confirmation email from Energy Platform</p>
        </div>
    </div>
</body>
</html>
"""

    @staticmethod
    def _describe_rule(rule: Rule) -> tuple[str, str]:
        if rule.rule_type == "time_based":
            return (
                f"running between {rule.time_window_start}-{rule.time_window_end} {platform_tz_label()}",
                "power status",
            )
        if rule.rule_type == "continuous_idle_duration":
            return (
                f"idle continuously for {rule.duration_minutes} minute(s)",
                "idle duration",
            )
        return (f"{rule.condition} {rule.threshold}", rule.property)

    async def _record_skipped_batch(
        self,
        *,
        recipients: list[str],
        rule: Rule,
        device_id: str,
        event_type: str,
        alert_id: Optional[str],
        metadata: dict[str, Any],
        failure_code: str,
        failure_message: str,
        result: NotificationDispatchResult,
    ) -> None:
        for recipient in recipients:
            audit_log_id = None
            if self._audit_service is not None:
                row = await self._audit_service.mark_skipped(
                    channel=self.channel_name,
                    raw_recipient=recipient,
                    provider_name=self.provider_name,
                    event_type=event_type,
                    rule_id=str(rule.rule_id) if rule.rule_id else None,
                    alert_id=alert_id,
                    device_id=device_id,
                    failure_code=failure_code,
                    failure_message=failure_message,
                    metadata_json=metadata,
                )
                audit_log_id = row.id
            result.recipient_results.append(
                NotificationRecipientResult(
                    recipient=recipient,
                    channel=self.channel_name,
                    provider_name=self.provider_name,
                    status=NotificationDeliveryStatus.SKIPPED.value,
                    attempted_at=datetime.now(timezone.utc),
                    failure_code=failure_code,
                    failure_message=failure_message,
                    audit_log_id=audit_log_id,
                    metadata_json=metadata,
                )
            )

    async def _create_attempt_logs(
        self,
        *,
        recipients: list[str],
        rule: Rule,
        device_id: str,
        event_type: str,
        alert_id: Optional[str],
        metadata: dict[str, Any],
    ) -> dict[str, Optional[str]]:
        if self._audit_service is None:
            return {recipient: None for recipient in recipients}
        attempt_logs: dict[str, Optional[str]] = {}
        for recipient in recipients:
            row = await self._audit_service.create_send_attempt(
                channel=self.channel_name,
                raw_recipient=recipient,
                provider_name=self.provider_name,
                event_type=event_type,
                rule_id=str(rule.rule_id) if rule.rule_id else None,
                alert_id=alert_id,
                device_id=device_id,
                metadata_json=metadata,
            )
            attempt_logs[recipient] = row.id
        return attempt_logs

    async def _record_provider_accepted_result(
        self,
        *,
        recipient: str,
        attempt_log_id: Optional[str],
        metadata: dict[str, Any],
        provider_message_id: Optional[str] = None,
    ) -> NotificationRecipientResult:
        accepted_at = datetime.now(timezone.utc)
        if self._audit_service is not None and attempt_log_id is not None:
            await self._audit_service.mark_provider_accepted(
                attempt_log_id,
                provider_message_id=provider_message_id,
                accepted_at=accepted_at,
                metadata_json=metadata,
            )
        return NotificationRecipientResult(
            recipient=recipient,
            channel=self.channel_name,
            provider_name=self.provider_name,
            status=NotificationDeliveryStatus.PROVIDER_ACCEPTED.value,
            attempted_at=accepted_at,
            accepted_at=accepted_at,
            provider_message_id=provider_message_id,
            billable_units=1,
            audit_log_id=attempt_log_id,
            metadata_json=metadata,
        )

    async def _record_failed_result(
        self,
        *,
        recipient: str,
        attempt_log_id: Optional[str],
        failure_code: Optional[str],
        failure_message: Optional[str],
        metadata: dict[str, Any],
    ) -> NotificationRecipientResult:
        failed_at = datetime.now(timezone.utc)
        if self._audit_service is not None and attempt_log_id is not None:
            await self._audit_service.mark_failed(
                attempt_log_id,
                failure_code=failure_code,
                failure_message=failure_message,
                failed_at=failed_at,
                metadata_json=metadata,
            )
        return NotificationRecipientResult(
            recipient=recipient,
            channel=self.channel_name,
            provider_name=self.provider_name,
            status=NotificationDeliveryStatus.FAILED.value,
            attempted_at=failed_at,
            failed_at=failed_at,
            failure_code=failure_code,
            failure_message=failure_message,
            audit_log_id=attempt_log_id,
            metadata_json=metadata,
        )

    async def health_check(self) -> bool:
        if not self._enabled:
            return False
        try:
            with smtplib.SMTP(self._smtp_host, self._smtp_port) as server:
                server.starttls()
                server.login(self._smtp_username, self._smtp_password)
            return True
        except Exception as exc:
            logger.error("Email health check failed", extra={"error": str(exc)})
            return False


class _TwilioChannelAdapter(NotificationChannel, ABC):
    """Twilio-backed notification adapter for SMS and WhatsApp."""

    provider_name = "twilio"

    def __init__(
        self,
        *,
        channel_name: str,
        enabled: bool,
        account_sid: Optional[str],
        auth_token: Optional[str],
        from_number: Optional[str],
        prefix: str = "",
        audit_service: Optional[NotificationDeliveryAuditService] = None,
    ):
        self.channel_name = channel_name
        self._audit_service = audit_service
        self._enabled = enabled
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._from_number = from_number
        self._prefix = prefix

    @staticmethod
    def _recipients_for_rule(rule: Rule, channel: str) -> list[str]:
        recipients: list[str] = []
        for row in list(getattr(rule, "notification_recipients", []) or []):
            if not isinstance(row, dict):
                continue
            row_channel = str(row.get("channel") or "").strip().lower()
            value = str(row.get("value") or "").strip()
            if row_channel != channel or not value:
                continue
            if channel == "sms":
                recipients.append(normalize_phone_recipient(value))
            elif channel == "whatsapp":
                normalized = normalize_phone_recipient(value)
                recipients.append(normalized if normalized.startswith("whatsapp:") else f"whatsapp:{normalized}")
        return sorted(set(recipients))

    def _configured(self) -> bool:
        return bool(self._account_sid and self._auth_token and self._from_number)

    async def dispatch_alert(
        self,
        subject: str,
        message: str,
        rule: Rule,
        device_id: str,
        alert_type: str = "threshold_alert",
        alert_id: Optional[str] = None,
        **kwargs: Any,
    ) -> NotificationDispatchResult:
        recipients = self._recipients_for_rule(rule, self.channel_name)
        result = NotificationDispatchResult(channel=self.channel_name, provider_name=self.provider_name)
        if not recipients:
            logger.warning(
                "%s recipients not configured on rule",
                self.channel_name.capitalize(),
                extra={"channel": self.channel_name, "rule_id": str(rule.rule_id) if rule.rule_id else None},
            )
            return result

        metadata = {
            "subject": subject,
            "alert_type": alert_type,
            "device_id": device_id,
        }
        if not self._enabled:
            await self._record_skipped_batch(
                recipients=recipients,
                rule=rule,
                device_id=device_id,
                event_type=alert_type,
                alert_id=alert_id,
                metadata=metadata,
                failure_code="channel_disabled",
                failure_message=f"{self.channel_name} notifications are disabled.",
                result=result,
            )
            logger.info(
                "%s notifications disabled or not configured",
                self.channel_name.capitalize(),
                extra={"channel": self.channel_name},
            )
            result.forced_success = True
            return result

        if not self._configured():
            await self._record_skipped_batch(
                recipients=recipients,
                rule=rule,
                device_id=device_id,
                event_type=alert_type,
                alert_id=alert_id,
                metadata=metadata,
                failure_code="missing_configuration",
                failure_message=f"{self.channel_name} provider credentials are missing.",
                result=result,
            )
            logger.warning(
                "%s notifications enabled but not configured",
                self.channel_name.capitalize(),
                extra={"channel": self.channel_name},
            )
            result.forced_success = False
            return result

        body = f"{self._prefix}{message}".strip()
        try:
            async with httpx.AsyncClient(timeout=10.0, auth=(self._account_sid, self._auth_token)) as client:
                for recipient in recipients:
                    attempt_log_id = await self._create_attempt_log(
                        recipient=recipient,
                        rule=rule,
                        device_id=device_id,
                        event_type=alert_type,
                        alert_id=alert_id,
                        metadata=metadata,
                    )
                    to_value = recipient
                    from_value = self._from_number or ""
                    if self.channel_name == "whatsapp" and not from_value.startswith("whatsapp:"):
                        from_value = f"whatsapp:{from_value}"
                    payload = {"From": from_value, "To": to_value, "Body": body}
                    try:
                        response = await client.post(
                            f"https://api.twilio.com/2010-04-01/Accounts/{self._account_sid}/Messages.json",
                            data=payload,
                            headers={"Content-Type": "application/x-www-form-urlencoded"},
                        )
                    except Exception as exc:
                        result.recipient_results.append(
                            await self._record_failed_result(
                                recipient=recipient,
                                attempt_log_id=attempt_log_id,
                                failure_code=exc.__class__.__name__,
                                failure_message=str(exc),
                                metadata=metadata,
                            )
                        )
                        continue

                    if response.status_code >= 400:
                        failure_code, failure_message = self._extract_twilio_failure(response)
                        logger.error(
                            "%s notification send failed",
                            self.channel_name.capitalize(),
                            extra={
                                "channel": self.channel_name,
                                "status_code": response.status_code,
                                "rule_id": str(rule.rule_id) if rule.rule_id else None,
                                "device_id": device_id,
                                "recipient": recipient,
                            },
                        )
                        result.recipient_results.append(
                            await self._record_failed_result(
                                recipient=recipient,
                                attempt_log_id=attempt_log_id,
                                failure_code=failure_code,
                                failure_message=failure_message,
                                metadata=metadata,
                            )
                        )
                        continue

                    provider_message_id = self._extract_twilio_sid(response)
                    result.recipient_results.append(
                        await self._record_provider_accepted_result(
                            recipient=recipient,
                            attempt_log_id=attempt_log_id,
                            metadata=metadata,
                            provider_message_id=provider_message_id,
                        )
                    )

            logger.info(
                "%s sent",
                self.channel_name.capitalize(),
                extra={
                    "channel": self.channel_name,
                    "to": recipients,
                    "rule_id": str(rule.rule_id) if rule.rule_id else None,
                    "device_id": device_id,
                    "alert_type": alert_type,
                },
            )
            return result
        except Exception as exc:
            logger.error(
                "Failed to send %s notification",
                self.channel_name,
                extra={
                    "channel": self.channel_name,
                    "error": str(exc),
                    "rule_id": str(rule.rule_id) if rule.rule_id else None,
                    "device_id": device_id,
                },
            )
            if not result.recipient_results:
                for recipient in recipients:
                    result.recipient_results.append(
                        NotificationRecipientResult(
                            recipient=recipient,
                            channel=self.channel_name,
                            provider_name=self.provider_name,
                            status=NotificationDeliveryStatus.FAILED.value,
                            attempted_at=datetime.now(timezone.utc),
                            failed_at=datetime.now(timezone.utc),
                            failure_code=exc.__class__.__name__,
                            failure_message=str(exc),
                            metadata_json=metadata,
                        )
                    )
            return result

    @staticmethod
    def _extract_twilio_sid(response: Any) -> Optional[str]:
        json_loader = getattr(response, "json", None)
        if callable(json_loader):
            try:
                payload = json_loader()
                if isinstance(payload, dict):
                    return payload.get("sid")
            except Exception:
                return None
        return None

    @staticmethod
    def _extract_twilio_failure(response: Any) -> tuple[str, str]:
        code = str(getattr(response, "status_code", "provider_error"))
        json_loader = getattr(response, "json", None)
        if callable(json_loader):
            try:
                payload = json_loader()
                if isinstance(payload, dict):
                    return str(payload.get("code") or code), str(payload.get("message") or payload)
            except Exception:
                pass
        text = getattr(response, "text", None)
        return code, str(text or "Provider rejected notification.")

    async def _record_skipped_batch(
        self,
        *,
        recipients: list[str],
        rule: Rule,
        device_id: str,
        event_type: str,
        alert_id: Optional[str],
        metadata: dict[str, Any],
        failure_code: str,
        failure_message: str,
        result: NotificationDispatchResult,
    ) -> None:
        for recipient in recipients:
            audit_log_id = None
            if self._audit_service is not None:
                row = await self._audit_service.mark_skipped(
                    channel=self.channel_name,
                    raw_recipient=recipient,
                    provider_name=self.provider_name,
                    event_type=event_type,
                    rule_id=str(rule.rule_id) if rule.rule_id else None,
                    alert_id=alert_id,
                    device_id=device_id,
                    failure_code=failure_code,
                    failure_message=failure_message,
                    metadata_json=metadata,
                )
                audit_log_id = row.id
            result.recipient_results.append(
                NotificationRecipientResult(
                    recipient=recipient,
                    channel=self.channel_name,
                    provider_name=self.provider_name,
                    status=NotificationDeliveryStatus.SKIPPED.value,
                    attempted_at=datetime.now(timezone.utc),
                    failure_code=failure_code,
                    failure_message=failure_message,
                    audit_log_id=audit_log_id,
                    metadata_json=metadata,
                )
            )

    async def _create_attempt_log(
        self,
        *,
        recipient: str,
        rule: Rule,
        device_id: str,
        event_type: str,
        alert_id: Optional[str],
        metadata: dict[str, Any],
    ) -> Optional[str]:
        if self._audit_service is None:
            return None
        row = await self._audit_service.create_send_attempt(
            channel=self.channel_name,
            raw_recipient=recipient,
            provider_name=self.provider_name,
            event_type=event_type,
            rule_id=str(rule.rule_id) if rule.rule_id else None,
            alert_id=alert_id,
            device_id=device_id,
            metadata_json=metadata,
        )
        return row.id

    async def _record_provider_accepted_result(
        self,
        *,
        recipient: str,
        attempt_log_id: Optional[str],
        metadata: dict[str, Any],
        provider_message_id: Optional[str] = None,
    ) -> NotificationRecipientResult:
        accepted_at = datetime.now(timezone.utc)
        if self._audit_service is not None and attempt_log_id is not None:
            await self._audit_service.mark_provider_accepted(
                attempt_log_id,
                provider_message_id=provider_message_id,
                accepted_at=accepted_at,
                metadata_json=metadata,
            )
        return NotificationRecipientResult(
            recipient=recipient,
            channel=self.channel_name,
            provider_name=self.provider_name,
            status=NotificationDeliveryStatus.PROVIDER_ACCEPTED.value,
            attempted_at=accepted_at,
            accepted_at=accepted_at,
            provider_message_id=provider_message_id,
            billable_units=1,
            audit_log_id=attempt_log_id,
            metadata_json=metadata,
        )

    async def _record_failed_result(
        self,
        *,
        recipient: str,
        attempt_log_id: Optional[str],
        failure_code: Optional[str],
        failure_message: Optional[str],
        metadata: dict[str, Any],
    ) -> NotificationRecipientResult:
        failed_at = datetime.now(timezone.utc)
        if self._audit_service is not None and attempt_log_id is not None:
            await self._audit_service.mark_failed(
                attempt_log_id,
                failure_code=failure_code,
                failure_message=failure_message,
                failed_at=failed_at,
                metadata_json=metadata,
            )
        return NotificationRecipientResult(
            recipient=recipient,
            channel=self.channel_name,
            provider_name=self.provider_name,
            status=NotificationDeliveryStatus.FAILED.value,
            attempted_at=failed_at,
            failed_at=failed_at,
            failure_code=failure_code,
            failure_message=failure_message,
            audit_log_id=attempt_log_id,
            metadata_json=metadata,
        )

    async def health_check(self) -> bool:
        return bool(self._enabled and self._configured())


class SmsAdapter(_TwilioChannelAdapter):
    def __init__(self, audit_service: Optional[NotificationDeliveryAuditService] = None):
        super().__init__(
            channel_name="sms",
            enabled=settings.SMS_ENABLED,
            account_sid=settings.TWILIO_ACCOUNT_SID,
            auth_token=settings.TWILIO_AUTH_TOKEN,
            from_number=settings.TWILIO_SMS_FROM_NUMBER,
            audit_service=audit_service,
        )


class WhatsAppAdapter(_TwilioChannelAdapter):
    def __init__(self, audit_service: Optional[NotificationDeliveryAuditService] = None):
        super().__init__(
            channel_name="whatsapp",
            enabled=settings.WHATSAPP_ENABLED,
            account_sid=settings.TWILIO_ACCOUNT_SID,
            auth_token=settings.TWILIO_AUTH_TOKEN,
            from_number=settings.TWILIO_WHATSAPP_FROM_NUMBER,
            prefix="WhatsApp: ",
            audit_service=audit_service,
        )


class NotificationAdapter:
    """Main notification adapter that routes to appropriate channels."""

    def __init__(self, audit_service: Optional[NotificationDeliveryAuditService] = None):
        self._adapters: Dict[str, NotificationChannel] = {
            "email": EmailAdapter(audit_service=audit_service),
            "sms": SmsAdapter(audit_service=audit_service),
            "whatsapp": WhatsAppAdapter(audit_service=audit_service),
        }

    async def dispatch(
        self,
        channel: str,
        message: str,
        rule: Rule,
        device_id: str,
        **kwargs: Any,
    ) -> NotificationDispatchResult:
        if channel not in self._adapters:
            raise ValueError(f"Unsupported notification channel: {channel}")
        adapter = self._adapters[channel]
        return await adapter.dispatch_alert(
            subject=f"Alert: {rule.rule_name}",
            message=message,
            rule=rule,
            device_id=device_id,
            alert_type=kwargs.pop("alert_type", "threshold_alert"),
            alert_id=kwargs.pop("alert_id", None),
            **kwargs,
        )

    async def send(
        self,
        channel: str,
        message: str,
        rule: Rule,
        device_id: str,
        **kwargs: Any,
    ) -> bool:
        result = await self.dispatch(channel=channel, message=message, rule=rule, device_id=device_id, **kwargs)
        return result.overall_success

    async def dispatch_alert(
        self,
        channel: str,
        subject: str,
        message: str,
        rule: Rule,
        device_id: str,
        alert_type: str = "threshold_alert",
        alert_id: Optional[str] = None,
        **kwargs: Any,
    ) -> NotificationDispatchResult:
        if channel not in self._adapters:
            raise ValueError(f"Unsupported notification channel: {channel}")
        adapter = self._adapters[channel]
        return await adapter.dispatch_alert(
            subject=subject,
            message=message,
            rule=rule,
            device_id=device_id,
            alert_type=alert_type,
            alert_id=alert_id,
            **kwargs,
        )

    async def send_alert(
        self,
        channel: str,
        subject: str,
        message: str,
        rule: Rule,
        device_id: str,
        alert_type: str = "threshold_alert",
        alert_id: Optional[str] = None,
        **kwargs: Any,
    ) -> bool:
        result = await self.dispatch_alert(
            channel=channel,
            subject=subject,
            message=message,
            rule=rule,
            device_id=device_id,
            alert_type=alert_type,
            alert_id=alert_id,
            **kwargs,
        )
        return result.overall_success

    async def health_check(self) -> Dict[str, bool]:
        results = {}
        for channel_name, adapter in self._adapters.items():
            try:
                results[channel_name] = await adapter.health_check()
            except Exception as exc:
                logger.error("Health check failed for %s", channel_name, extra={"error": str(exc)})
                results[channel_name] = False
        return results

    def get_supported_channels(self) -> list[str]:
        return list(self._adapters.keys())


notification_adapter = NotificationAdapter()
