import asyncio
from contextlib import asynccontextmanager

from src.ai.copilot_engine import CopilotEngine
from src.db.query_engine import QueryResult
from src.response.schema import CuratedContext
from src.templates.curated_catalog import CATALOG, match_curated_question


class _NonJsonModelClient:
    async def generate(self, messages, max_tokens=1000):
        return "not valid json"


class _UnavailableModelClient:
    def is_available(self) -> bool:
        return False

    async def generate(self, messages, max_tokens=1000):
        raise AssertionError("generate() must not be called in curated-only mode")


class _StrictCuratedModelClient:
    async def generate(self, messages, max_tokens=1000):
        raise AssertionError("curated handlers must not call generate()")


def _engine() -> CopilotEngine:
    return CopilotEngine(_NonJsonModelClient())


def _install_happy_path_stubs(engine: CopilotEngine) -> None:
    async def fake_execute_query(sql: str, tenant_id: str):
        if "GROUP BY d.plant_id" in sql and "total_energy_kwh" in sql:
            return QueryResult(columns=["plant_id", "total_energy_kwh"], rows=[["plant-a", 90.0], ["plant-b", 42.0]], row_count=2)
        if "GROUP BY d.plant_id" in sql and "total_idle_cost" in sql:
            return QueryResult(columns=["plant_id", "total_idle_cost", "currency"], rows=[["plant-a", 55.0, "INR"], ["plant-b", 16.4, "INR"]], row_count=2)
        if "idle_hours_today" in sql and "idle_kwh_today" in sql:
            return QueryResult(
                columns=["device_id", "device_name", "legacy_status", "last_seen_timestamp", "idle_hours_today", "idle_kwh_today"],
                rows=[
                    ["COMPRESSOR-003", "Compressor 003", "active", "2026-04-12 09:00:00", 2.2, 8.4],
                    ["COMPRESSOR-002", "Compressor 002", "stopped", "2026-04-12 08:00:00", 1.1, 4.2],
                ],
                row_count=2,
            )
        if "ORDER BY today_energy_kwh DESC" in sql:
            limit = 5 if "LIMIT 5" in sql else 10
            rows = [
                ["COMPRESSOR-001", "Compressor 001", 42.0],
                ["COMPRESSOR-002", "Compressor 002", 35.5],
                ["COMPRESSOR-003", "Compressor 003", 27.0],
                ["COMPRESSOR-004", "Compressor 004", 18.0],
                ["COMPRESSOR-005", "Compressor 005", 9.5],
            ]
            return QueryResult(columns=["device_id", "device_name", "today_energy_kwh"], rows=rows[:limit], row_count=limit)
        if "SUM(ls.today_energy_kwh)" in sql:
            return QueryResult(columns=["total_energy_kwh"], rows=[[132.0]], row_count=1)
        if "today_loss_cost_inr" in sql:
            return QueryResult(
                columns=["device_id", "device_name", "today_loss_cost_inr", "today_loss_kwh"],
                rows=[
                    ["COMPRESSOR-004", "Compressor 004", 320.5, 14.2],
                    ["COMPRESSOR-001", "Compressor 001", 140.0, 6.0],
                ],
                row_count=2,
            )
        if "SUM(i.idle_cost)" in sql and "GROUP BY d.plant_id" not in sql:
            return QueryResult(columns=["total_idle_cost", "currency"], rows=[[71.4, "INR"]], row_count=1)
        if "ORDER BY i.idle_cost DESC" in sql:
            return QueryResult(
                columns=["device_id", "device_name", "idle_cost", "idle_energy_kwh", "currency"],
                rows=[
                    ["COMPRESSOR-003", "Compressor 003", 71.4, 8.4, "INR"],
                    ["COMPRESSOR-002", "Compressor 002", 28.0, 3.1, "INR"],
                ],
                row_count=2,
            )
        if "COUNT(*) AS alert_count" in sql:
            return QueryResult(columns=["alert_count"], rows=[[5]], row_count=1)
        if "GROUP BY runtime_status" in sql:
            return QueryResult(
                columns=["runtime_status", "machine_count", "total_running_seconds", "total_effective_seconds"],
                rows=[["running", 3, 21600, 19800], ["stopped", 2, 3600, 1800]],
                row_count=2,
            )
        if "efficiency_pct" in sql and "health_score" in sql:
            return QueryResult(
                columns=["device_id", "device_name", "efficiency_pct", "health_score", "today_energy_kwh", "runtime_status"],
                rows=[["COMPRESSOR-002", "Compressor 002", 72.5, 91.4, 14.2, "running"]],
                row_count=1,
            )
        raise AssertionError(f"Unexpected SQL: {sql}")

    async def fake_list_devices():
        return [
            {"device_id": "COMPRESSOR-001", "device_name": "Compressor 001"},
            {"device_id": "COMPRESSOR-002", "device_name": "Compressor 002"},
            {"device_id": "COMPRESSOR-003", "device_name": "Compressor 003"},
            {"device_id": "COMPRESSOR-004", "device_name": "Compressor 004"},
        ]

    async def fake_fetch_telemetry(device_id, start, end, fields=None, limit=1000):
        return {
            "data": {
                "items": [
                    {"timestamp": "2026-04-06T00:00:00Z", "power": 18.0},
                    {"timestamp": "2026-04-07T00:00:00Z", "power": 20.5},
                    {"timestamp": "2026-04-08T00:00:00Z", "power": 19.2},
                ]
            }
        }

    engine.query_engine.execute_query = fake_execute_query  # type: ignore[assignment]
    engine._list_devices = fake_list_devices  # type: ignore[assignment]
    engine.data_service.fetch_telemetry = fake_fetch_telemetry  # type: ignore[assignment]


def test_every_curated_question_returns_data_or_healthy_no_data_without_internal_error():
    engine = _engine()
    _install_happy_path_stubs(engine)

    statuses: dict[str, str] = {}
    for question in CATALOG:
        context = CuratedContext(device_id="COMPRESSOR-001") if question.required_context == "device" else None
        response = asyncio.run(
            engine.process_question(
                question.text,
                [],
                8.5,
                "INR",
                tenant_id="tenant-a",
                curated_context=context,
            )
        )
        assert response.error_code in {None, "NO_DATA"}
        assert response.error_code != "INTERNAL_ERROR"
        assert response.answer
        statuses[question.id] = "answered_with_data" if response.error_code is None else "answered_with_healthy_no_data"

    assert set(statuses.values()) <= {"answered_with_data", "answered_with_healthy_no_data"}


def test_device_trend_requires_explicit_or_structured_device_context():
    engine = _engine()

    async def fake_list_devices():
        return [{"device_id": "COMPRESSOR-001", "device_name": "Compressor 001"}]

    engine._list_devices = fake_list_devices  # type: ignore[assignment]

    response = asyncio.run(
        engine.process_question(
            "Show this machine trend for last 7 days",
            [],
            8.5,
            "INR",
            tenant_id="tenant-a",
            curated_context=None,
        )
    )

    assert response.error_code == "NO_DATA"
    assert response.answer == "Please mention or select a machine to show its 7-day trend."
    assert response.chart is None


def test_device_trend_handles_insufficient_history_safely():
    engine = _engine()

    async def fake_list_devices():
        return [{"device_id": "COMPRESSOR-001", "device_name": "Compressor 001"}]

    async def fake_fetch_telemetry(device_id, start, end, fields=None, limit=1000):
        return {"data": {"items": []}}

    engine._list_devices = fake_list_devices  # type: ignore[assignment]
    engine.data_service.fetch_telemetry = fake_fetch_telemetry  # type: ignore[assignment]

    response = asyncio.run(
        engine.process_question(
            "Show this machine trend for last 7 days",
            [],
            8.5,
            "INR",
            tenant_id="tenant-a",
            curated_context=CuratedContext(device_id="COMPRESSOR-001"),
        )
    )

    assert response.error_code == "NO_DATA"
    assert response.answer == "Not enough data for last 7 days trend for COMPRESSOR-001."
    assert response.chart is None


def test_total_energy_cost_handles_missing_tariff_safely():
    engine = _engine()
    _install_happy_path_stubs(engine)

    response = asyncio.run(
        engine.process_question(
            "What is today's total energy cost?",
            [],
            0.0,
            "INR",
            tenant_id="tenant-a",
        )
    )

    assert response.error_code == "NO_DATA"
    assert response.answer == "Today's energy usage is available, but total energy cost cannot be calculated because tariff is not configured."
    assert response.chart is None


def test_alert_count_uses_healthy_no_data_when_no_alerts_exist():
    engine = _engine()

    class _FakeResult:
        def first(self):
            return (0,)

    class _FakeDb:
        async def execute(self, *args, **kwargs):
            return _FakeResult()

    @asynccontextmanager
    async def fake_db_session():
        yield _FakeDb()

    from src.ai import copilot_engine as copilot_engine_module

    copilot_engine_module.get_db_session = fake_db_session  # type: ignore[assignment]

    response = asyncio.run(
        engine.process_question(
            "How many alerts were triggered today?",
            [],
            8.5,
            "INR",
            tenant_id="tenant-a",
        )
    )

    assert response.error_code == "NO_DATA"
    assert response.answer == "No alerts triggered today."
    assert response.chart is None


def test_plant_level_questions_return_healthy_no_data_when_plants_missing():
    engine = _engine()

    async def fake_execute_query(sql: str, tenant_id: str):
        if "GROUP BY d.plant_id" in sql:
            if "total_idle_cost" in sql:
                return QueryResult(columns=["plant_id", "total_idle_cost", "currency"], rows=[], row_count=0)
            return QueryResult(columns=["plant_id", "total_energy_kwh"], rows=[], row_count=0)
        raise AssertionError(f"Unexpected SQL: {sql}")

    engine.query_engine.execute_query = fake_execute_query  # type: ignore[assignment]

    energy_response = asyncio.run(
        engine.process_question(
            "Which plant consumed the most energy today?",
            [],
            8.5,
            "INR",
            tenant_id="tenant-a",
        )
    )
    idle_response = asyncio.run(
        engine.process_question(
            "Which plant has the highest idle loss today?",
            [],
            8.5,
            "INR",
            tenant_id="tenant-a",
        )
    )

    assert energy_response.error_code == "NO_DATA"
    assert energy_response.answer == "No plant-level energy data is available today."
    assert idle_response.error_code == "NO_DATA"
    assert idle_response.answer == "No plant-level idle loss recorded today."


def test_broken_ranked_machine_alert_runtime_path_is_removed():
    assert not hasattr(CopilotEngine, "_resolve_alert_target")


def test_curated_alias_resolves_and_returns_deterministic_table_chart_without_provider():
    assert match_curated_question("Which machine has the highest idle cost today?").id == "highest_loss_machine_today"

    engine = CopilotEngine(_UnavailableModelClient())
    _install_happy_path_stubs(engine)

    response = asyncio.run(
        engine.process_question(
            "Which machine has the highest idle cost today?",
            [],
            8.5,
            "INR",
            tenant_id="tenant-a",
        )
    )

    assert response.error_code is None
    assert response.data_table is not None
    assert response.chart is not None
    assert response.chart.type == "bar"


def test_curated_question_never_calls_model_generate():
    engine = CopilotEngine(_StrictCuratedModelClient())
    _install_happy_path_stubs(engine)

    response = asyncio.run(
        engine.process_question(
            "Which machine consumed the most power today?",
            [],
            8.5,
            "INR",
            tenant_id="tenant-a",
        )
    )

    assert response.error_code is None
    assert response.answer


def test_unsupported_question_returns_safe_fallback_when_provider_unavailable():
    engine = CopilotEngine(_UnavailableModelClient())

    response = asyncio.run(
        engine.process_question(
            "What will happen to output next quarter?",
            [],
            8.5,
            "INR",
            tenant_id="tenant-a",
        )
    )

    assert response.error_code == "APPROVED_QUESTIONS_ONLY"
    assert response.answer == "This Copilot currently supports approved factory questions only."
    assert response.follow_up_suggestions
