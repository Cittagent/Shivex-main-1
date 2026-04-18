from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings

logger = logging.getLogger("auth-service.mailer")


class MailerService:
    def _platform_name(self) -> str:
        return (settings.PLATFORM_NAME or "Shivex").strip() or "Shivex"

    def _assert_configured(self) -> None:
        required = {
            "EMAIL_SMTP_HOST": settings.EMAIL_SMTP_HOST,
            "EMAIL_FROM_ADDRESS": settings.EMAIL_FROM_ADDRESS,
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise RuntimeError(f"Invite email configuration missing: {missing}")

    def _send(self, recipient: str, subject: str, html: str, text: str) -> None:
        self._assert_configured()
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = settings.EMAIL_FROM_ADDRESS
        message["To"] = recipient
        message.attach(MIMEText(text, "plain"))
        message.attach(MIMEText(html, "html"))

        context = ssl.create_default_context()
        with smtplib.SMTP(settings.EMAIL_SMTP_HOST, settings.EMAIL_SMTP_PORT) as server:
            server.ehlo()
            if server.has_extn("starttls"):
                server.starttls(context=context)
                server.ehlo()
            if settings.EMAIL_SMTP_USERNAME and settings.EMAIL_SMTP_PASSWORD:
                server.login(settings.EMAIL_SMTP_USERNAME, settings.EMAIL_SMTP_PASSWORD)
            server.sendmail(settings.EMAIL_FROM_ADDRESS, [recipient], message.as_string())

    async def send_invite_email(self, *, recipient: str, full_name: str | None, invite_link: str) -> None:
        greeting = full_name or recipient
        platform_name = self._platform_name()
        subject = f"Your {platform_name} invitation"
        text = (
            f"Hello {greeting},\n\n"
            f"You have been invited to {platform_name}. Use the link below to set your password. "
            f"This link expires in {settings.INVITE_TOKEN_EXPIRE_MINUTES} minutes.\n\n"
            f"{invite_link}\n"
        )
        html = (
            "<html><body>"
            f"<p>Hello {greeting},</p>"
            f"<p>You have been invited to {platform_name}. Use the link below to set your password.</p>"
            f"<p><a href=\"{invite_link}\">Set your password</a></p>"
            f"<p>This link expires in {settings.INVITE_TOKEN_EXPIRE_MINUTES} minutes.</p>"
            "</body></html>"
        )
        await asyncio.to_thread(self._send, recipient, subject, html, text)
        logger.info("Sent invitation email", extra={"recipient": recipient})

    async def send_password_reset_email(self, *, recipient: str, full_name: str | None, reset_link: str) -> None:
        greeting = full_name or recipient
        platform_name = self._platform_name()
        subject = f"Reset your {platform_name} password"
        text = (
            f"Hello {greeting},\n\n"
            f"We received a request to reset your {platform_name} password. "
            f"This link expires in {settings.PASSWORD_RESET_EXPIRE_MINUTES} minutes.\n\n"
            f"{reset_link}\n"
        )
        html = (
            "<html><body>"
            f"<p>Hello {greeting},</p>"
            f"<p>We received a request to reset your {platform_name} password.</p>"
            f"<p><a href=\"{reset_link}\">Reset password</a></p>"
            f"<p>This link expires in {settings.PASSWORD_RESET_EXPIRE_MINUTES} minutes.</p>"
            "</body></html>"
        )
        await asyncio.to_thread(self._send, recipient, subject, html, text)
        logger.info("Sent password reset email", extra={"recipient": recipient})


mailer_svc = MailerService()
