"""Durable notification outbox planning and enqueue service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rule import NotificationDeliveryStatus, NotificationOutbox, Rule
from app.notifications.adapter import NotificationAdapter
from app.queue import NotificationQueueItem, get_notification_queue
from app.repositories.notification_outbox import NotificationOutboxRepository
from app.services.notification_delivery import NotificationDeliveryAuditService
from app.utils.notification_delivery import hash_recipient, mask_recipient
from services.shared.tenant_context import TenantContext


@dataclass(frozen=True)
class NotificationContent:
    subject: str
    message: str
    alert_context: dict[str, Any]
    event_type: str = "threshold_alert"


class NotificationOutboxService:
    def __init__(self, session: AsyncSession, ctx: TenantContext):
        self._session = session
        self._ctx = ctx
        self._audit_service = NotificationDeliveryAuditService(session, ctx)
        self._outbox_repo = NotificationOutboxRepository(session, ctx)
        self._adapter = NotificationAdapter(audit_service=self._audit_service)
        self._queue = get_notification_queue()

    async def enqueue_alert_notifications(
        self,
        *,
        rule: Rule,
        device_id: str,
        alert_id: str,
        content: NotificationContent,
    ) -> None:
        tenant_id = self._ctx.require_tenant()
        for channel in list(rule.notification_channels or []):
            recipients, resolution_metadata = await self._adapter.resolve_recipients(channel, rule)
            provider_name = self._adapter.provider_name_for(channel)
            metadata = {
                "subject": content.subject,
                "alert_type": content.event_type,
                "device_id": device_id,
                **resolution_metadata,
            }
            if not recipients:
                queued_log = await self._audit_service.create_queued_intent(
                    channel=channel,
                    raw_recipient="",
                    provider_name=provider_name,
                    event_type=content.event_type,
                    rule_id=str(rule.rule_id) if rule.rule_id else None,
                    alert_id=alert_id,
                    device_id=device_id,
                    attempted_at=datetime.now(timezone.utc),
                    metadata_json=metadata,
                )
                await self._audit_service.mark_skipped_log(
                    queued_log.id,
                    failure_code="NO_ACTIVE_RECIPIENTS",
                    failure_message=f"No active recipients configured for {channel} channel.",
                    metadata_json=metadata,
                )
                outbox_row = NotificationOutbox(
                    tenant_id=tenant_id,
                    alert_id=alert_id,
                    rule_id=str(rule.rule_id) if rule.rule_id else None,
                    ledger_log_id=queued_log.id,
                    device_id=device_id,
                    event_type=content.event_type,
                    channel=channel,
                    provider_name=provider_name,
                    recipient_raw="",
                    recipient_masked=mask_recipient(channel, ""),
                    recipient_hash=hash_recipient(""),
                    subject=content.subject,
                    message=content.message,
                    payload_json={
                        "alert_context": content.alert_context,
                        "resolution_metadata": resolution_metadata,
                    },
                    status=NotificationDeliveryStatus.SKIPPED.value,
                    next_attempt_at=datetime.now(timezone.utc),
                    failure_code="NO_ACTIVE_RECIPIENTS",
                    failure_message=f"No active recipients configured for {channel} channel.",
                    failed_at=datetime.now(timezone.utc),
                )
                await self._outbox_repo.create_outbox_entry(outbox_row)
                continue

            for recipient in recipients:
                queued_log = await self._audit_service.create_queued_intent(
                    channel=channel,
                    raw_recipient=recipient,
                    provider_name=provider_name,
                    event_type=content.event_type,
                    rule_id=str(rule.rule_id) if rule.rule_id else None,
                    alert_id=alert_id,
                    device_id=device_id,
                    attempted_at=datetime.now(timezone.utc),
                    metadata_json=metadata,
                )
                outbox_row = NotificationOutbox(
                    tenant_id=tenant_id,
                    alert_id=alert_id,
                    rule_id=str(rule.rule_id) if rule.rule_id else None,
                    ledger_log_id=queued_log.id,
                    device_id=device_id,
                    event_type=content.event_type,
                    channel=channel,
                    provider_name=provider_name,
                    recipient_raw=recipient,
                    recipient_masked=mask_recipient(channel, recipient),
                    recipient_hash=hash_recipient(recipient),
                    subject=content.subject,
                    message=content.message,
                    payload_json={
                        "alert_context": content.alert_context,
                        "resolution_metadata": resolution_metadata,
                    },
                    status=NotificationDeliveryStatus.QUEUED.value,
                    next_attempt_at=datetime.now(timezone.utc),
                )
                created = await self._outbox_repo.create_outbox_entry(outbox_row)
                await self._queue.enqueue(
                    NotificationQueueItem(
                        outbox_id=created.id,
                        tenant_id=tenant_id,
                        channel=channel,
                    )
                )
