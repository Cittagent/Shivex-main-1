import asyncio
import sys
from pathlib import Path

from fastapi import Request

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SERVICES_ROOT = REPO_ROOT / "services"
if str(SERVICES_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICES_ROOT))

from src.ai.copilot_engine import CopilotEngine
from src.api import chat as chat_module
from src.response.schema import ChatRequest, CopilotResponse
from services.shared.tenant_context import TenantContext


class _UnavailableModelClient:
    def is_provider_configured(self) -> bool:
        return False

    def is_available(self) -> bool:
        return False

    async def generate(self, messages, max_tokens=1000):
        raise AssertionError("generate() should not run when provider is unavailable")


class _StubEngine:
    def __init__(self):
        self.calls: list[dict] = []

    async def process_question(self, **kwargs):
        self.calls.append(kwargs)
        return CopilotResponse(answer="curated-ok", reasoning="deterministic")


def _request_with_tenant(tenant_id: str = "tenant-a") -> Request:
    req = Request(scope={"type": "http", "method": "POST", "path": "/api/v1/copilot/chat", "headers": []})
    req.state.tenant_context = TenantContext(
        tenant_id=tenant_id,
        user_id="u-1",
        role="tenant_admin",
        plant_ids=[],
        is_super_admin=False,
        entitlements=None,
    )
    return req


def test_curated_chat_works_when_provider_not_configured(monkeypatch):
    stub_engine = _StubEngine()
    unavailable_model = _UnavailableModelClient()
    monkeypatch.setattr(chat_module, "_get_engine", lambda: (unavailable_model, stub_engine))

    async def _fake_tariff(_tenant_id: str):
        return 8.5, "INR"

    monkeypatch.setattr(chat_module, "get_current_tariff", _fake_tariff)

    response = asyncio.run(
        chat_module.chat(
            ChatRequest(message="Summarize today's factory performance"),
            _request_with_tenant(),
        )
    )

    assert response.error_code is None
    assert response.answer == "curated-ok"
    assert stub_engine.calls
    assert stub_engine.calls[0]["message"] == "Summarize today's factory performance"


def test_unsupported_question_without_provider_returns_safe_fallback(monkeypatch):
    unavailable_model = _UnavailableModelClient()
    engine = CopilotEngine(model_client=unavailable_model)
    monkeypatch.setattr(chat_module, "_get_engine", lambda: (unavailable_model, engine))

    async def _fake_tariff(_tenant_id: str):
        return 8.5, "INR"

    monkeypatch.setattr(chat_module, "get_current_tariff", _fake_tariff)

    response = asyncio.run(
        chat_module.chat(
            ChatRequest(message="Show OEE by line"),
            _request_with_tenant(),
        )
    )

    assert response.error_code == "APPROVED_QUESTIONS_ONLY"
    assert response.answer == "This Copilot currently supports approved factory questions only."


def test_curated_questions_endpoint_works_without_provider():
    response = asyncio.run(chat_module.curated_questions(_request_with_tenant()))
    assert response.starter_questions
