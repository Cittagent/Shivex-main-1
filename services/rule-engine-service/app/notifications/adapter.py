"""Notification adapter layer for multi-channel alerting.

This module provides adapter interfaces for different notification
channels. Actual provider SDK implementations will be added in future.
"""

import logging
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, Optional
from abc import ABC, abstractmethod
from datetime import datetime

import httpx

from app.models.rule import Rule
from app.config import settings
from app.utils.recipients import normalize_phone_recipient
from app.utils.timezone import format_platform_datetime, platform_tz_label

logger = logging.getLogger(__name__)


class NotificationChannel(ABC):
    """Abstract base class for notification channels."""
    
    @abstractmethod
    async def send(
        self,
        message: str,
        rule: Rule,
        device_id: str,
        **kwargs: Any,
    ) -> bool:
        """Send notification through this channel.
        
        Args:
            message: Notification message
            rule: Rule that triggered the notification
            device_id: Device identifier
            **kwargs: Additional channel-specific parameters
            
        Returns:
            True if sent successfully, False otherwise
        """
        pass
    
    @abstractmethod
    async def send_alert(
        self,
        subject: str,
        message: str,
        rule: Rule,
        device_id: str,
        alert_type: str = "threshold_alert",
        **kwargs: Any,
    ) -> bool:
        """Send formatted alert notification.
        
        Args:
            subject: Email subject
            message: Alert message body
            rule: Rule that triggered
            device_id: Device identifier
            alert_type: Type of alert (rule_created, threshold_alert)
            **kwargs: Additional parameters
            
        Returns:
            True if sent successfully
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """Check if channel is healthy and available.
        
        Returns:
            True if channel is healthy
        """
        pass


class EmailAdapter(NotificationChannel):
    """Email notification adapter with SMTP support."""
    
    def __init__(self):
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
    
    async def send(
        self,
        message: str,
        rule: Rule,
        device_id: str,
        **kwargs: Any,
    ) -> bool:
        """Send email notification."""
        device_names = kwargs.get("device_names")
        return await self.send_alert(
            subject=f"Alert: {rule.rule_name}",
            message=message,
            rule=rule,
            device_id=device_id,
            alert_type="threshold_alert",
            device_names=device_names
        )
    
    async def send_alert(
        self,
        subject: str,
        message: str,
        rule: Rule,
        device_id: str,
        alert_type: str = "threshold_alert",
        device_names: str = None,
        **kwargs: Any,
    ) -> bool:
        """Send formatted email alert."""
        if not self._enabled:
            logger.info(
                "Email notifications disabled",
                extra={"channel": "email"}
            )
            return True
        
        if not self._smtp_username or not self._smtp_password:
            logger.warning(
                "Email not configured - SMTP credentials missing",
                extra={"channel": "email"}
            )
            return False
        
        recipients = self._recipients_for_rule(rule)
        if not recipients:
            logger.warning(
                "Email recipients not configured on rule",
                extra={"channel": "email", "rule_id": str(rule.rule_id) if rule.rule_id else None},
            )
            return True
        
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self._from_address
            msg["To"] = ", ".join(recipients)
            
            if alert_type == "rule_created":
                html_content = self._format_rule_created_message(rule, device_id, message, device_names)
            else:
                html_content = self._format_alert_message(rule, device_id, message)
            
            text_part = MIMEText(message, "plain")
            html_part = MIMEText(html_content, "html")
            
            msg.attach(text_part)
            msg.attach(html_part)
            
            context = ssl.create_default_context()
            
            with smtplib.SMTP(self._smtp_host, self._smtp_port) as server:
                server.starttls(context=context)
                server.ehlo()
                server.login(self._smtp_username, self._smtp_password)
                server.sendmail(self._from_address, recipients, msg.as_string())
            
            logger.info(
                "Email sent successfully",
                extra={
                    "channel": "email",
                    "to": recipients,
                    "subject": subject,
                    "rule_id": str(rule.rule_id) if rule.rule_id else None,
                    "device_id": device_id,
                    "alert_type": alert_type,
                }
            )
            return True
            
        except Exception as e:
            logger.error(
                "Failed to send email",
                extra={
                    "channel": "email",
                    "error": str(e),
                    "rule_id": str(rule.rule_id) if rule.rule_id else None,
                    "device_id": device_id,
                }
            )
            return False
    
    def _format_alert_message(self, rule: Rule, device_id: str, message: str) -> str:
        """Format threshold alert email."""
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
                <p><span class="label">Time:</span> {format_platform_datetime(datetime.utcnow())}</p>
            </div>
        </div>
        <div class="footer">
            <p>This is an automated alert from Energy Platform</p>
        </div>
    </div>
</body>
</html>
"""
    
    def _format_rule_created_message(self, rule: Rule, device_id: str, message: str, device_names: str = None) -> str:
        """Format rule created confirmation email."""
        status_value = rule.status.value if hasattr(rule.status, 'value') else str(rule.status)
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
                <p><span class="label">Created:</span> {format_platform_datetime(rule.created_at) if rule.created_at else format_platform_datetime(datetime.utcnow())}</p>
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
    
    async def health_check(self) -> bool:
        """Check email service health."""
        if not self._enabled:
            return False
        
        try:
            with smtplib.SMTP(self._smtp_host, self._smtp_port) as server:
                server.starttls()
                server.login(self._smtp_username, self._smtp_password)
            return True
        except Exception as e:
            logger.error(f"Email health check failed: {e}")
            return False


class _TwilioChannelAdapter(NotificationChannel, ABC):
    """Twilio-backed notification adapter for SMS and WhatsApp."""

    channel_name: str

    def __init__(
        self,
        *,
        channel_name: str,
        enabled: bool,
        account_sid: Optional[str],
        auth_token: Optional[str],
        from_number: Optional[str],
        prefix: str = "",
    ):
        self.channel_name = channel_name
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

    async def send(
        self,
        message: str,
        rule: Rule,
        device_id: str,
        **kwargs: Any,
    ) -> bool:
        return await self.send_alert(
            subject=f"Alert: {rule.rule_name}",
            message=message,
            rule=rule,
            device_id=device_id,
            alert_type="threshold_alert",
            **kwargs,
        )

    async def send_alert(
        self,
        subject: str,
        message: str,
        rule: Rule,
        device_id: str,
        alert_type: str = "threshold_alert",
        **kwargs: Any,
    ) -> bool:
        if not self._enabled:
            logger.info(
                "%s notifications disabled or not configured",
                self.channel_name.capitalize(),
                extra={"channel": self.channel_name},
            )
            return True

        if not self._configured():
            logger.warning(
                "%s notifications enabled but not configured",
                self.channel_name.capitalize(),
                extra={"channel": self.channel_name},
            )
            return False

        recipients = self._recipients_for_rule(rule, self.channel_name)
        if not recipients:
            logger.warning(
                "%s recipients not configured on rule",
                self.channel_name.capitalize(),
                extra={"channel": self.channel_name, "rule_id": str(rule.rule_id) if rule.rule_id else None},
            )
            return True

        body = f"{self._prefix}{message}".strip()
        try:
            async with httpx.AsyncClient(timeout=10.0, auth=(self._account_sid, self._auth_token)) as client:
                for recipient in recipients:
                    to_value = recipient
                    from_value = self._from_number or ""
                    if self.channel_name == "whatsapp":
                        if not from_value.startswith("whatsapp:"):
                            from_value = f"whatsapp:{from_value}"
                    payload = {
                        "From": from_value,
                        "To": to_value,
                        "Body": body,
                    }
                    response = await client.post(
                        f"https://api.twilio.com/2010-04-01/Accounts/{self._account_sid}/Messages.json",
                        data=payload,
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                    if response.status_code >= 400:
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
                        return False

            logger.info(
                "%s sent successfully",
                self.channel_name.capitalize(),
                extra={
                    "channel": self.channel_name,
                    "to": recipients,
                    "rule_id": str(rule.rule_id) if rule.rule_id else None,
                    "device_id": device_id,
                    "alert_type": alert_type,
                },
            )
            return True
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
            return False

    async def health_check(self) -> bool:
        return bool(self._enabled and self._configured())


class SmsAdapter(_TwilioChannelAdapter):
    def __init__(self):
        super().__init__(
            channel_name="sms",
            enabled=settings.SMS_ENABLED,
            account_sid=settings.TWILIO_ACCOUNT_SID,
            auth_token=settings.TWILIO_AUTH_TOKEN,
            from_number=settings.TWILIO_SMS_FROM_NUMBER,
        )


class WhatsAppAdapter(_TwilioChannelAdapter):
    def __init__(self):
        super().__init__(
            channel_name="whatsapp",
            enabled=settings.WHATSAPP_ENABLED,
            account_sid=settings.TWILIO_ACCOUNT_SID,
            auth_token=settings.TWILIO_AUTH_TOKEN,
            from_number=settings.TWILIO_WHATSAPP_FROM_NUMBER,
            prefix="WhatsApp: ",
        )


class NotificationAdapter:
    """Main notification adapter that routes to appropriate channels."""
    
    def __init__(self):
        self._adapters: Dict[str, NotificationChannel] = {
            "email": EmailAdapter(),
            "sms": SmsAdapter(),
            "whatsapp": WhatsAppAdapter(),
        }
    
    async def send(
        self,
        channel: str,
        message: str,
        rule: Rule,
        device_id: str,
        **kwargs: Any,
    ) -> bool:
        """Send notification through specified channel."""
        if channel not in self._adapters:
            raise ValueError(f"Unsupported notification channel: {channel}")
        
        adapter = self._adapters[channel]
        return await adapter.send(message, rule, device_id, **kwargs)
    
    async def send_alert(
        self,
        channel: str,
        subject: str,
        message: str,
        rule: Rule,
        device_id: str,
        alert_type: str = "threshold_alert",
        **kwargs: Any,
    ) -> bool:
        """Send formatted alert through specified channel."""
        if channel not in self._adapters:
            raise ValueError(f"Unsupported notification channel: {channel}")
        
        adapter = self._adapters[channel]
        return await adapter.send_alert(subject, message, rule, device_id, alert_type, **kwargs)
    
    async def health_check(self) -> Dict[str, bool]:
        """Check health of all notification channels."""
        results = {}
        for channel_name, adapter in self._adapters.items():
            try:
                results[channel_name] = await adapter.health_check()
            except Exception as e:
                logger.error(
                    f"Health check failed for {channel_name}",
                    extra={"error": str(e)}
                )
                results[channel_name] = False
        
        return results
    
    def get_supported_channels(self) -> list:
        """Get list of supported notification channels."""
        return list(self._adapters.keys())


notification_adapter = NotificationAdapter()
