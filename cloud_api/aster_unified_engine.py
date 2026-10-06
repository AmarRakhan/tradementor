"""Canonical AsterBot policy and decision contracts.

This module is intentionally pure: it performs no exchange I/O and no Firestore
writes. Runtime callers supply the latest server-authoritative settings and
exchange truth on every reconciliation tick.

Design rules:
- current config is policy; runtime state contains facts only;
- price-zone seats are an optional AsterBot module, not a separate strategy;
- every initial entry is admitted by one deterministic gate;
- historical/legacy values never override current policy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable
import hashlib
import json


class ActionType(str, Enum):
    INITIAL_ENTRY = "INITIAL_ENTRY"
    DCA_ADD = "DCA_ADD"
    HEDGE_OPEN = "HEDGE_OPEN"
    HEDGE_CLOSE = "HEDGE_CLOSE"
    RECOVERY_OPEN = "RECOVERY_OPEN"
    CLOSE_TP = "CLOSE_TP"
    CLOSE_SL = "CLOSE_SL"
    CLOSE_MANUAL = "CLOSE_MANUAL"


class DecisionStatus(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"


class FilterStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    SKIP = "SKIP"


@dataclass(frozen=True)
class FilterResult:
    name: str
    status: FilterStatus
    reason: str = ""
    values: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "reason": self.reason,
            "values": dict(self.values),
        }


@dataclass(frozen=True)
class PriceZonePolicy:
    enabled: bool
    long_seats_per_zone: int
    short_seats_per_zone: int


@dataclass(frozen=True)
class AsterBotPolicy:
    config_version: int
    maximum_positions: int
    long_slots: int
    short_slots: int
    price_zone: PriceZonePolicy
    bollinger_enabled: bool
    bollinger_long_timeframe: str
    bollinger_short_timeframe: str
    dca_long_distance: float
    dca_short_distance: float
    dca_long_amount: float
    dca_short_amount: float
    max_dca_long: int
    max_dca_short: int
    take_profit_long: float
    take_profit_short: float

    def side_enabled(self, side: str) -> bool:
        normalized = str(side).upper()
        if normalized == "LONG":
            return self.price_zone.long_seats_per_zone > 0 if self.price_zone.enabled else self.long_slots > 0
        if normalized == "SHORT":
            return self.price_zone.short_seats_per_zone > 0 if self.price_zone.enabled else self.short_slots > 0
        return False

    def current_position_policy(self, side: str) -> dict[str, Any]:
        normalized = str(side).upper()
        if normalized not in {"LONG", "SHORT"}:
            raise ValueError("side must be LONG or SHORT")
        is_short = normalized == "SHORT"
        return {
            "configVersion": self.config_version,
            "side": normalized,
            "dcaDistance": self.dca_short_distance if is_short else self.dca_long_distance,
            "dcaAmount": self.dca_short_amount if is_short else self.dca_long_amount,
            "maxDca": self.max_dca_short if is_short else self.max_dca_long,
            "takeProfit": self.take_profit_short if is_short else self.take_profit_long,
        }

    def public_dict(self) -> dict[str, Any]:
        return {
            "configVersion": self.config_version,
            "maxPositions": self.maximum_positions,
            "allocation": {
                "longEnabled": self.side_enabled("LONG"),
                "shortEnabled": self.side_enabled("SHORT"),
                "longSlots": self.long_slots,
                "shortSlots": self.short_slots,
            },
            "priceZoneSeats": {
                "enabled": self.price_zone.enabled,
                "longSeatsPerZone": self.price_zone.long_seats_per_zone,
                "shortSeatsPerZone": self.price_zone.short_seats_per_zone,
            },
            "entryFilters": {
                "bollinger": {
                    "enabled": self.bollinger_enabled,
                    "longTimeframe": self.bollinger_long_timeframe,
                    "shortTimeframe": self.bollinger_short_timeframe,
                }
            },
            "dca": {
                "longDistance": self.dca_long_distance,
                "shortDistance": self.dca_short_distance,
                "longAmount": self.dca_long_amount,
                "shortAmount": self.dca_short_amount,
                "maxLong": self.max_dca_long,
                "maxShort": self.max_dca_short,
            },
            "takeProfit": {
                "long": self.take_profit_long,
                "short": self.take_profit_short,
            },
        }


def policy_from_settings(settings: Any) -> AsterBotPolicy:
    """Project the *current* runtime settings into one canonical policy.

    No value is read from position state. Legacy field names may have been
    normalized by the settings parser, but after that projection only the
    current settings object is authoritative.
    """
    zone_enabled = bool(getattr(settings, "zone_soldiers_enabled", False))
    return AsterBotPolicy(
        config_version=max(1, int(getattr(settings, "version", 1) or 1)),
        maximum_positions=max(0, int(getattr(settings, "maximum_positions", 0) or 0)),
        long_slots=max(0, int(getattr(settings, "long_slots", 0) or 0)),
        short_slots=max(0, int(getattr(settings, "short_slots", 0) or 0)),
        price_zone=PriceZonePolicy(
            enabled=zone_enabled,
            long_seats_per_zone=max(0, int(getattr(settings, "zone_base_long_soldiers", 0) or 0)),
            short_seats_per_zone=max(0, int(getattr(settings, "zone_base_short_soldiers", 0) or 0)),
        ),
        bollinger_enabled=bool(getattr(settings, "bollinger_entry_filter_15m_enabled", False)),
        bollinger_long_timeframe=str(getattr(settings, "bollinger_long_timeframe", getattr(settings, "bollinger_entry_filter_timeframe", "15m"))),
        bollinger_short_timeframe=str(getattr(settings, "bollinger_short_timeframe", getattr(settings, "bollinger_entry_filter_timeframe", "15m"))),
        dca_long_distance=float(getattr(settings, "long_dca_distance", getattr(settings, "dca_distance", 0.0)) or 0.0),
        dca_short_distance=float(getattr(settings, "short_dca_distance", getattr(settings, "dca_distance", 0.0)) or 0.0),
        dca_long_amount=float(getattr(settings, "long_dca_margin_usd", getattr(settings, "dca_margin_usd", 0.0)) or 0.0),
        dca_short_amount=float(getattr(settings, "short_dca_margin_usd", getattr(settings, "dca_margin_usd", 0.0)) or 0.0),
        max_dca_long=max(0, int(getattr(settings, "max_dca_long", getattr(settings, "max_dca", 0)) or 0)),
        max_dca_short=max(0, int(getattr(settings, "max_dca_short", getattr(settings, "max_dca", 0)) or 0)),
        take_profit_long=float(getattr(settings, "long_take_profit_value", getattr(settings, "take_profit", 0.0)) or 0.0),
        take_profit_short=float(getattr(settings, "short_take_profit_value", getattr(settings, "take_profit", 0.0)) or 0.0),
    )


@dataclass(frozen=True)
class InitialEntryContext:
    uid: str
    symbol: str
    side: str
    bot_enabled: bool
    current_config_version: int
    observed_config_version: int
    account_position_count: int
    side_position_count: int
    active_zone: int | None = None
    active_zone_side_count: int = 0
    duplicate_position_open: bool = False
    filter_results: tuple[FilterResult, ...] = ()


@dataclass(frozen=True)
class AdmissionDecision:
    status: DecisionStatus
    reason_code: str
    decision_id: str
    config_version: int
    action_type: ActionType
    symbol: str
    side: str
    capacity: dict[str, Any]
    filter_results: tuple[FilterResult, ...]

    @property
    def allowed(self) -> bool:
        return self.status is DecisionStatus.ALLOW

    def public_dict(self) -> dict[str, Any]:
        return {
            "decisionId": self.decision_id,
            "status": self.status.value,
            "reasonCode": self.reason_code,
            "configVersion": self.config_version,
            "actionType": self.action_type.value,
            "symbol": self.symbol,
            "side": self.side,
            "capacityResult": dict(self.capacity),
            "filterResults": [item.public_dict() for item in self.filter_results],
        }


def _decision_id(context: InitialEntryContext, policy: AsterBotPolicy) -> str:
    payload = json.dumps({
        "uid": context.uid,
        "symbol": context.symbol.upper(),
        "side": context.side.upper(),
        "configVersion": policy.config_version,
        "accountPositionCount": context.account_position_count,
        "activeZone": context.active_zone,
        "activeZoneSideCount": context.active_zone_side_count,
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _deny(context: InitialEntryContext, policy: AsterBotPolicy, reason: str,
          capacity: dict[str, Any]) -> AdmissionDecision:
    return AdmissionDecision(
        DecisionStatus.DENY, reason, _decision_id(context, policy), policy.config_version,
        ActionType.INITIAL_ENTRY, context.symbol.upper(), context.side.upper(),
        capacity, tuple(context.filter_results),
    )


def evaluate_initial_entry(policy: AsterBotPolicy, context: InitialEntryContext) -> AdmissionDecision:
    """Single deterministic admission gate for normal AsterBot initial exposure."""
    side = context.side.upper()
    zone_limit = (
        policy.price_zone.long_seats_per_zone if side == "LONG"
        else policy.price_zone.short_seats_per_zone if side == "SHORT"
        else 0
    )
    side_limit = policy.long_slots if side == "LONG" else policy.short_slots if side == "SHORT" else 0
    capacity = {
        "maximumPositions": policy.maximum_positions,
        "accountOpen": max(0, int(context.account_position_count)),
        "sideOpen": max(0, int(context.side_position_count)),
        "sideLimit": side_limit,
        "priceZoneSeatsEnabled": policy.price_zone.enabled,
        "activeZone": context.active_zone,
        "activeZoneSideOpen": max(0, int(context.active_zone_side_count)),
        "activeZoneSideLimit": zone_limit if policy.price_zone.enabled else None,
    }
    if not context.bot_enabled:
        return _deny(context, policy, "BOT_DISABLED", capacity)
    if context.current_config_version != policy.config_version or context.observed_config_version != policy.config_version:
        return _deny(context, policy, "STALE_CONFIG_VERSION", capacity)
    if side not in {"LONG", "SHORT"}:
        return _deny(context, policy, "INVALID_SIDE", capacity)
    if context.duplicate_position_open:
        return _deny(context, policy, "POSITION_ALREADY_OPEN", capacity)
    if context.account_position_count >= policy.maximum_positions:
        return _deny(context, policy, "GLOBAL_POSITION_CAP_REACHED", capacity)
    if not policy.side_enabled(side):
        return _deny(context, policy, f"{side}_DISABLED", capacity)
    if policy.price_zone.enabled:
        if context.active_zone is None:
            return _deny(context, policy, "ACTIVE_ZONE_UNAVAILABLE", capacity)
        if context.active_zone_side_count >= zone_limit:
            return _deny(context, policy, f"ZONE_{side}_CAP_REACHED", capacity)
    elif context.side_position_count >= side_limit:
        return _deny(context, policy, f"{side}_SLOT_CAP_REACHED", capacity)

    for result in context.filter_results:
        if result.status is FilterStatus.FAIL:
            return _deny(context, policy, f"FILTER_FAIL:{result.name}", capacity)
        if result.status is FilterStatus.ERROR:
            return _deny(context, policy, f"FILTER_ERROR:{result.name}", capacity)

    return AdmissionDecision(
        DecisionStatus.ALLOW, "ALL_ACTIVE_RULES_PASSED", _decision_id(context, policy),
        policy.config_version, ActionType.INITIAL_ENTRY, context.symbol.upper(), side,
        capacity, tuple(context.filter_results),
    )


def require_allowed(decision: AdmissionDecision, *, action_type: ActionType = ActionType.INITIAL_ENTRY) -> AdmissionDecision:
    if decision.action_type is not action_type:
        raise ValueError(f"ACTION_TYPE_MISMATCH:{decision.action_type.value}!={action_type.value}")
    if not decision.allowed:
        raise PermissionError(f"ASTERBOT_ACTION_DENIED:{decision.reason_code}")
    return decision


def all_filters_pass(results: Iterable[FilterResult]) -> bool:
    return all(item.status in {FilterStatus.PASS, FilterStatus.SKIP} for item in results)


@dataclass(frozen=True)
class PositionActionContext:
    uid: str
    symbol: str
    side: str
    action_type: ActionType
    position_open: bool
    trigger_met: bool
    dca_count: int = 0
    take_profit_enabled: bool = True


@dataclass(frozen=True)
class PositionActionDecision:
    status: DecisionStatus
    reason_code: str
    decision_id: str
    config_version: int
    action_type: ActionType
    symbol: str
    side: str
    current_policy: dict[str, Any]

    @property
    def allowed(self) -> bool:
        return self.status is DecisionStatus.ALLOW

    def public_dict(self) -> dict[str, Any]:
        return {
            "decisionId": self.decision_id,
            "status": self.status.value,
            "reasonCode": self.reason_code,
            "configVersion": self.config_version,
            "actionType": self.action_type.value,
            "symbol": self.symbol,
            "side": self.side,
            "currentPolicy": dict(self.current_policy),
        }


def evaluate_position_action(policy: AsterBotPolicy, context: PositionActionContext) -> PositionActionDecision:
    """Evaluate a future action against current policy, never position-copied policy."""
    side = context.side.upper()
    current = policy.current_position_policy(side)
    identity = json.dumps({
        "uid": context.uid,
        "symbol": context.symbol.upper(),
        "side": side,
        "action": context.action_type.value,
        "configVersion": policy.config_version,
        "dcaCount": max(0, int(context.dca_count)),
        "triggerMet": bool(context.trigger_met),
    }, sort_keys=True, separators=(",", ":"))
    decision_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]

    def result(status: DecisionStatus, reason: str) -> PositionActionDecision:
        return PositionActionDecision(
            status, reason, decision_id, policy.config_version, context.action_type,
            context.symbol.upper(), side, current,
        )

    if not context.position_open:
        return result(DecisionStatus.DENY, "POSITION_NOT_OPEN")
    if not context.trigger_met:
        return result(DecisionStatus.DENY, "TRIGGER_NOT_MET")

    if context.action_type is ActionType.DCA_ADD:
        maximum = int(current["maxDca"])
        if maximum <= 0:
            return result(DecisionStatus.DENY, "DCA_DISABLED")
        if int(context.dca_count) >= maximum:
            return result(DecisionStatus.DENY, "MAX_DCA_REACHED")
        if float(current["dcaAmount"]) <= 0:
            return result(DecisionStatus.DENY, "DCA_AMOUNT_INVALID")
        return result(DecisionStatus.ALLOW, "CURRENT_DCA_POLICY_PASSED")

    if context.action_type is ActionType.CLOSE_TP:
        if not context.take_profit_enabled:
            return result(DecisionStatus.DENY, "TAKE_PROFIT_DISABLED")
        if float(current["takeProfit"]) <= 0:
            return result(DecisionStatus.DENY, "TAKE_PROFIT_INVALID")
        return result(DecisionStatus.ALLOW, "CURRENT_TP_POLICY_PASSED")

    if context.action_type in {
        ActionType.CLOSE_SL, ActionType.CLOSE_MANUAL,
        ActionType.HEDGE_OPEN, ActionType.HEDGE_CLOSE, ActionType.RECOVERY_OPEN,
    }:
        return result(DecisionStatus.ALLOW, "CURRENT_ACTION_POLICY_PASSED")

    return result(DecisionStatus.DENY, "UNSUPPORTED_POSITION_ACTION")


def require_position_action_allowed(decision: PositionActionDecision) -> PositionActionDecision:
    if not decision.allowed:
        raise PermissionError(f"ASTERBOT_POSITION_ACTION_DENIED:{decision.reason_code}")
    return decision
