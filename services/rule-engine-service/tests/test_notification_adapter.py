from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

RULE_SERVICE_ROOT = Path(__file__).resolve().parents[1]
SERVICES_ROOT = RULE_SERVICE_ROOT.parent
REPO_ROOT = RULE_SERVICE_ROOT.parent.parent
sys.path = [p for p in sys.path if p not in {str(RULE_SERVICE_ROOT), str(SERVICES_ROOT), str(REPO_ROOT)}]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(SERVICES_ROOT))
sys.path.insert(0, str(RULE_SERVICE_ROOT))

os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

from app.models.rule import Rule, RuleScope, RuleStatus, RuleType
from app.notifications.adapter import EmailAdapter, NotificationAdapter, SmsAdapter, WhatsAppAdapter


def _make_rule(*, rule_id: str, recipients: list[dict]) -> Rule:
    now = datetime.now(timezone.utc)
    return Rule(
        rule_id=rule_id,
        tenant_id="TENANT-A",
        rule_name=f"Rule {rule_id}",
        description=None,
        scope=RuleScope.SELECTED_DEVICES.value,
        property="power",
        condition=">",
        threshold=10.0,
        rule_type=RuleType.THRESHOLD.value,
        status=RuleStatus.ACTIVE.value,
        notification_channels=["email"],
        notification_recipients=recipients,
        device_ids=["P1"],
        created_at=now,
        updated_at=now,
    )


class _FakeResponse:
    def __init__(self, status_code: int = 201):
        self.status_code = status_code


class _FakeAsyncClient:
    requests: list[dict] = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, data=None, headers=None):
        self.requests.append(
            {
                "url": url,
                "data": dict(data or {}),
                "headers": dict(headers or {}),
                "auth": self.kwargs.get("auth"),
            }
        )
        return _FakeResponse()


class _FakeSMTP:
    sent_messages: list[dict] = []

    def __init__(self, host, port):
        self.host = host
        self.port = port

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def starttls(self, context=None):
        return None

    def ehlo(self):
        return None

    def login(self, username, password):
        self.username = username
        self.password = password

    def sendmail(self, from_address, recipients, message):
        self.sent_messages.append(
            {
                "from": from_address,
                "recipients": list(recipients),
                "message": message,
            }
        )


@pytest.mark.asyncio
async def test_email_adapter_sends_only_rule_attached_recipients(monkeypatch):
    _FakeSMTP.sent_messages = []
    monkeypatch.setattr("app.notifications.adapter.smtplib.SMTP", _FakeSMTP)

    adapter = EmailAdapter()
    adapter._enabled = True
    adapter._smtp_host = "smtp.example.com"
    adapter._smtp_port = 587
    adapter._smtp_username = "user"
    adapter._smtp_password = "pass"
    adapter._from_address = "alerts@example.com"

    plant_a_rule = _make_rule(
        rule_id="rule-plant-a",
        recipients=[
            {"channel": "email", "value": "opsA@example.com"},
            {"channel": "email", "value": "opsA@example.com"},
            {"channel": "email", "value": "guardA@example.com"},
        ],
    )
    _plant_b_rule = _make_rule(
        rule_id="rule-plant-b",
        recipients=[
            {"channel": "email", "value": "opsB@example.com"},
        ],
    )

    sent = await adapter.send_alert(
        subject="Plant A alert",
        message="Alert fired",
        rule=plant_a_rule,
        device_id="P1",
    )

    assert sent is True
    assert len(_FakeSMTP.sent_messages) == 1
    assert _FakeSMTP.sent_messages[0]["recipients"] == [
        "guarda@example.com",
        "opsa@example.com",
    ]
    assert "opsb@example.com" not in _FakeSMTP.sent_messages[0]["message"].lower()


@pytest.mark.asyncio
async def test_email_adapter_skips_send_when_rule_has_no_email_recipients(monkeypatch):
    _FakeSMTP.sent_messages = []
    monkeypatch.setattr("app.notifications.adapter.smtplib.SMTP", _FakeSMTP)

    adapter = EmailAdapter()
    adapter._enabled = True
    adapter._smtp_host = "smtp.example.com"
    adapter._smtp_port = 587
    adapter._smtp_username = "user"
    adapter._smtp_password = "pass"
    adapter._from_address = "alerts@example.com"

    rule = _make_rule(rule_id="rule-no-recipients", recipients=[])

    sent = await adapter.send_alert(
        subject="No recipients",
        message="Alert fired",
        rule=rule,
        device_id="P1",
    )

    assert sent is True
    assert _FakeSMTP.sent_messages == []


@pytest.mark.asyncio
async def test_sms_adapter_sends_normalized_phone_recipients(monkeypatch):
    _FakeAsyncClient.requests = []
    monkeypatch.setattr("app.notifications.adapter.httpx.AsyncClient", _FakeAsyncClient)

    adapter = SmsAdapter()
    adapter._enabled = True
    adapter._account_sid = "AC123"
    adapter._auth_token = "secret"
    adapter._from_number = "+15550000000"

    rule = _make_rule(
        rule_id="rule-sms",
        recipients=[
            {"channel": "sms", "value": "+1 (555) 123-4567"},
            {"channel": "sms", "value": "1 555 123 4567"},
            {"channel": "email", "value": "ops@example.com"},
        ],
    )

    sent = await adapter.send_alert(
        subject="SMS alert",
        message="Threshold exceeded",
        rule=rule,
        device_id="P1",
    )

    assert sent is True
    assert len(_FakeAsyncClient.requests) == 1
    request = _FakeAsyncClient.requests[0]
    assert request["url"].endswith("/Messages.json")
    assert request["data"]["From"] == "+15550000000"
    assert request["data"]["To"] == "+15551234567"
    assert request["data"]["Body"] == "Threshold exceeded"
    assert request["auth"] == ("AC123", "secret")


@pytest.mark.asyncio
async def test_whatsapp_adapter_prefixes_phone_recipients(monkeypatch):
    _FakeAsyncClient.requests = []
    monkeypatch.setattr("app.notifications.adapter.httpx.AsyncClient", _FakeAsyncClient)

    adapter = WhatsAppAdapter()
    adapter._enabled = True
    adapter._account_sid = "AC456"
    adapter._auth_token = "secret"
    adapter._from_number = "+15550000001"

    rule = _make_rule(
        rule_id="rule-whatsapp",
        recipients=[
            {"channel": "whatsapp", "value": "+1 (555) 987-6543"},
        ],
    )

    sent = await adapter.send_alert(
        subject="WhatsApp alert",
        message="Threshold exceeded",
        rule=rule,
        device_id="P1",
    )

    assert sent is True
    assert len(_FakeAsyncClient.requests) == 1
    request = _FakeAsyncClient.requests[0]
    assert request["data"]["From"] == "whatsapp:+15550000001"
    assert request["data"]["To"] == "whatsapp:+15559876543"
    assert request["data"]["Body"] == "WhatsApp: Threshold exceeded"
    assert request["auth"] == ("AC456", "secret")


@pytest.mark.asyncio
async def test_sms_adapter_fails_closed_when_enabled_without_credentials(monkeypatch):
    _FakeAsyncClient.requests = []
    monkeypatch.setattr("app.notifications.adapter.httpx.AsyncClient", _FakeAsyncClient)

    adapter = SmsAdapter()
    adapter._enabled = True
    adapter._account_sid = None
    adapter._auth_token = None
    adapter._from_number = None

    rule = _make_rule(
        rule_id="rule-sms-missing-creds",
        recipients=[{"channel": "sms", "value": "+1 (555) 123-4567"}],
    )

    sent = await adapter.send_alert(
        subject="SMS alert",
        message="Threshold exceeded",
        rule=rule,
        device_id="P1",
    )

    assert sent is False
    assert _FakeAsyncClient.requests == []


def test_notification_adapter_supported_channels_are_email_sms_whatsapp():
    adapter = NotificationAdapter()
    assert adapter.get_supported_channels() == ["email", "sms", "whatsapp"]
