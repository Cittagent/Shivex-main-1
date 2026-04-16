"""Rule evaluation engine for real-time telemetry processing."""

from collections import defaultdict, deque
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.rule import Rule, RuleType, CooldownMode
from app.schemas.rule import EvaluationResult, TelemetryPayload
from app.schemas.telemetry import TelemetryIn
from app.services.rule import RuleService, AlertService
from app.services.notification_delivery import NotificationDeliveryAuditService
from app.repositories.rule import RuleRepository, AlertRepository
from app.notifications.adapter import NotificationAdapter
from app.config import settings
from app.utils.timezone import format_platform_datetime
from services.shared.tenant_context import TenantContext

logger = logging.getLogger(__name__)


class RuleEvaluator:
    _recent_alert_timestamps: defaultdict[str, deque[datetime]] = defaultdict(deque)
    _alert_rate_limit = 50
    _alert_rate_window = timedelta(seconds=60)

    def __init__(self, session: AsyncSession, ctx: TenantContext):
        self._session = session
        self._ctx = ctx
        self._rule_service = RuleService(session, ctx)
        self._alert_service = AlertService(session, ctx)
        self._rule_repository = RuleRepository(session, ctx)
        self._alert_repository = AlertRepository(session, ctx)
        self._notification_audit_service = NotificationDeliveryAuditService(session, ctx)
        self._notification_adapter = NotificationAdapter(audit_service=self._notification_audit_service)

    def _require_rule_tenant(self, rule: Rule) -> str:
        tenant_id = self._ctx.require_tenant()
        if rule.tenant_id != tenant_id:
            raise ValueError("Rule tenant does not match evaluator tenant scope.")
        return tenant_id

    @staticmethod
    def _get_platform_tz() -> ZoneInfo:
        return ZoneInfo(settings.PLATFORM_TIMEZONE)

    @classmethod
    def _prune_recent_alerts(cls, device_id: str, now: datetime) -> deque[datetime]:
        window_start = now - cls._alert_rate_window
        timestamps = cls._recent_alert_timestamps[device_id]
        while timestamps and timestamps[0] < window_start:
            timestamps.popleft()
        return timestamps

    @classmethod
    def _should_skip_due_to_alert_storm(cls, device_id: str, now: datetime) -> bool:
        timestamps = cls._prune_recent_alerts(device_id, now)
        return len(timestamps) > cls._alert_rate_limit

    @classmethod
    def _record_alert(cls, device_id: str, when: datetime) -> None:
        timestamps = cls._prune_recent_alerts(device_id, when)
        timestamps.append(when)

    async def evaluate_telemetry(
        self,
        telemetry: TelemetryPayload,
    ) -> tuple[int, int, List[EvaluationResult]]:

        device_id = telemetry.device_id
        now = datetime.now(timezone.utc)

        if self._should_skip_due_to_alert_storm(device_id, now):
            logger.warning(
                "rule_evaluation_skipped_alert_storm",
                extra={"device_id": device_id, "window_seconds": 60, "threshold": 50},
            )
            return 0, 0, []

        rules = await self._rule_service.get_active_rules_for_device(
            device_id=device_id,
        )

        if not rules:
            logger.debug(
                "No active rules for device",
                extra={"device_id": device_id},
            )
            return 0, 0, []

        triggered_rules: List[EvaluationResult] = []

        for rule in rules:
            self._require_rule_tenant(rule)
            result = await self._evaluate_single_rule(rule, telemetry)

            if result.triggered:
                acquired = await self._rule_repository.try_acquire_trigger_slot(
                    rule_id=str(rule.rule_id),
                    device_id=device_id,
                    cooldown_mode=rule.cooldown_mode,
                    cooldown_seconds=rule.effective_cooldown_seconds(),
                )
                if not acquired:
                    continue
                # Keep the in-session entity aligned with the atomic DB update.
                rule.last_triggered_at = now
                if rule.cooldown_mode == CooldownMode.NO_REPEAT.value:
                    rule.triggered_once = True

                triggered_rules.append(result)

                created_alert = await self._alert_service.create_alert(
                    rule=rule,
                    device_id=device_id,
                    actual_value=result.actual_value,
                    severity=self._determine_severity(rule, result.actual_value),
                )
                self._record_alert(device_id, now)

                await self._send_notifications(rule, device_id, result, alert_id=str(created_alert.alert_id))

        await self._session.commit()

        logger.info(
            "Rule evaluation completed",
            extra={
                "device_id": device_id,
                "rules_evaluated": len(rules),
                "rules_triggered": len(triggered_rules),
            },
        )

        return len(rules), len(triggered_rules), triggered_rules

    async def _evaluate_single_rule(
        self,
        rule: Rule,
        telemetry: TelemetryPayload,
    ) -> EvaluationResult:
        if rule.rule_type == RuleType.TIME_BASED.value:
            triggered, actual_value = self._evaluate_time_based_rule(rule, telemetry)
            condition = "running_in_window"
            threshold = 1.0
        elif rule.rule_type == RuleType.CONTINUOUS_IDLE_DURATION.value:
            triggered, actual_value = self._evaluate_continuous_idle_rule(rule, telemetry)
            condition = ">="
            threshold = float(rule.duration_minutes or 0)
        else:
            actual_value = self._extract_property_value(telemetry, rule.property or "")
            triggered = self._evaluate_condition(
                actual_value=actual_value,
                threshold=rule.threshold if rule.threshold is not None else 0.0,
                operator=rule.condition or "=",
            )
            condition = rule.condition or "="
            threshold = rule.threshold if rule.threshold is not None else 0.0

        message = None
        if triggered:
            if rule.rule_type == RuleType.TIME_BASED.value:
                message = (
                    f"Device running during restricted window "
                    f"{rule.time_window_start}-{rule.time_window_end} {settings.PLATFORM_TIMEZONE}"
                )
            elif rule.rule_type == RuleType.CONTINUOUS_IDLE_DURATION.value:
                message = (
                    f"Device idle continuously for {actual_value:.2f} minutes "
                    f"(threshold: {rule.duration_minutes} minutes)"
                )
            else:
                message = (
                    f"{rule.property} is {actual_value} "
                    f"(threshold: {rule.condition} {rule.threshold})"
                )

        return EvaluationResult(
            rule_id=rule.rule_id,
            rule_name=rule.rule_name,
            triggered=triggered,
            actual_value=actual_value,
            threshold=threshold,
            condition=condition,
            message=message,
        )

    def _evaluate_time_based_rule(
        self,
        rule: Rule,
        telemetry: TelemetryPayload,
    ) -> tuple[bool, float]:
        if not rule.time_window_start or not rule.time_window_end:
            return False, 0.0

        if not self._is_running_signal(telemetry):
            return False, 0.0

        if self._is_timestamp_in_window(telemetry.timestamp, rule.time_window_start, rule.time_window_end):
            return True, 1.0

        return False, 0.0

    def _evaluate_continuous_idle_rule(
        self,
        rule: Rule,
        telemetry: TelemetryPayload,
    ) -> tuple[bool, float]:
        if rule.duration_minutes is None:
            return False, 0.0

        streak_duration_sec = max(int(telemetry.idle_streak_duration_sec or 0), 0)
        streak_duration_minutes = streak_duration_sec / 60.0
        if telemetry.projected_load_state != "idle":
            return False, streak_duration_minutes

        return streak_duration_sec >= int(rule.duration_minutes) * 60, streak_duration_minutes

    def _is_running_signal(self, telemetry: TelemetryPayload) -> bool:
        dynamic_fields = telemetry.get_dynamic_fields()

        power = dynamic_fields.get("power")
        if power is None:
            power = dynamic_fields.get("active_power")
        if power is not None:
            return power > 0

        current = dynamic_fields.get("current")
        if current is None:
            return False

        voltage = dynamic_fields.get("voltage")
        if voltage is None:
            return current > 0

        return current > 0 and voltage > 0

    def _is_timestamp_in_window(self, timestamp: datetime, start_hhmm: str, end_hhmm: str) -> bool:
        local_tz = self._get_platform_tz()
        ts = (
            timestamp.astimezone(local_tz)
            if timestamp.tzinfo
            else timestamp.replace(tzinfo=ZoneInfo("UTC")).astimezone(local_tz)
        )
        current_minutes = ts.hour * 60 + ts.minute

        start_h, start_m = (int(v) for v in start_hhmm.split(":"))
        end_h, end_m = (int(v) for v in end_hhmm.split(":"))
        start_minutes = start_h * 60 + start_m
        end_minutes = end_h * 60 + end_m

        if start_minutes == end_minutes:
            return True
        if start_minutes < end_minutes:
            return start_minutes <= current_minutes < end_minutes
        return current_minutes >= start_minutes or current_minutes < end_minutes

    def _extract_property_value(
        self,
        telemetry: TelemetryPayload,
        property_name: str,
    ) -> float:
        
        dynamic_fields = telemetry.get_dynamic_fields()
        
        if property_name in dynamic_fields:
            return dynamic_fields[property_name]
        
        value = getattr(telemetry, property_name, None)
        if value is not None and isinstance(value, (int, float)):
            return float(value)
        
        raise ValueError(f"Unknown property: {property_name}")

    def _evaluate_condition(
        self,
        actual_value: float,
        threshold: float,
        operator: str,
    ) -> bool:

        operators = {
            ">": lambda a, t: a > t,
            "<": lambda a, t: a < t,
            "==": lambda a, t: a == t,
            "=": lambda a, t: a == t,
            "!=": lambda a, t: a != t,
            ">=": lambda a, t: a >= t,
            "<=": lambda a, t: a <= t,
        }

        if operator not in operators:
            raise ValueError(f"Unknown operator: {operator}")

        return operators[operator](actual_value, threshold)

    def _determine_severity(self, rule: Rule, actual_value: float) -> str:
        if rule.rule_type == RuleType.TIME_BASED.value:
            return "medium"
        if rule.rule_type == RuleType.CONTINUOUS_IDLE_DURATION.value:
            return "medium"

        if not rule.threshold or rule.threshold == 0:
            deviation = abs(actual_value)
        else:
            deviation = abs((actual_value - rule.threshold) / rule.threshold)

        if deviation > 0.5:
            return "critical"
        elif deviation > 0.25:
            return "high"
        elif deviation > 0.1:
            return "medium"
        else:
            return "low"

    async def _send_notifications(
        self,
        rule: Rule,
        device_id: str,
        result: EvaluationResult,
        alert_id: Optional[str] = None,
    ) -> None:

        if not rule.notification_channels:
            return

        message = (
            f"🚨 Alert: {rule.rule_name}\n"
            f"Device: {device_id}\n"
            f"Condition: "
            f"{self._describe_rule_condition(rule)}\n"
            f"Actual: {result.actual_value}\n"
            f"Time: {format_platform_datetime(datetime.now(timezone.utc))}"
        )

        for channel in rule.notification_channels:
            try:
                await self._notification_adapter.send(
                    channel=channel,
                    message=message,
                    rule=rule,
                    device_id=device_id,
                    alert_id=alert_id,
                )
                logger.info(
                    "Notification sent",
                    extra={
                        "channel": channel,
                        "rule_id": str(rule.rule_id),
                        "device_id": device_id,
                    },
                )
            except Exception as e:
                logger.error(
                    "Failed to send notification",
                    extra={
                        "channel": channel,
                        "rule_id": str(rule.rule_id),
                        "error": str(e),
                    },
                )

    @staticmethod
    def _describe_rule_condition(rule: Rule) -> str:
        if rule.rule_type == RuleType.TIME_BASED.value:
            return "running in restricted window"
        if rule.rule_type == RuleType.CONTINUOUS_IDLE_DURATION.value:
            return f"idle continuously for {rule.duration_minutes} minute(s)"
        return f"{rule.property} {rule.condition} {rule.threshold}"

    async def evaluate(
        self,
        telemetry: TelemetryIn,
    ) -> List[Rule]:

        device_id = telemetry.device_id
        metric = telemetry.metric
        value = telemetry.value

        rules = await self._rule_repository.get_active_rules_for_device(device_id)

        matched_rules: List[Rule] = []

        for rule in rules:

            if rule.property != metric:
                continue

            if self._evaluate_condition(value, rule.threshold, rule.condition):
                matched_rules.append(rule)

        logger.debug(
            "Simple evaluation completed",
            extra={
                "device_id": device_id,
                "metric": metric,
                "value": value,
                "rules_evaluated": len(rules),
                "rules_matched": len(matched_rules),
            },
        )

        return matched_rules
