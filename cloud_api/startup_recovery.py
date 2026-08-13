"""Deterministic startup/restart gate for multi-exchange automation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


StartupStatus = Literal["STARTING", "SYNCING", "READY", "DEGRADED", "PAUSED"]


@dataclass(frozen=True)
class ExchangeStartupState:
    exchange: str
    configured: bool
    exchange_read_ok: bool
    reconciliation_ready: bool
    stream_ready: bool
    persisted_enabled: bool | None
    protective_state_available: bool


@dataclass(frozen=True)
class ExchangeStartupGate:
    exchange: str
    automation_enabled: bool
    allow_risk_increase: bool
    allow_protective_actions: bool
    reason: str


@dataclass(frozen=True)
class StartupDecision:
    status: StartupStatus
    exchange_gates: tuple[ExchangeStartupGate, ...]
    reason: str


def recover_startup(states: tuple[ExchangeStartupState, ...]) -> StartupDecision:
    if not states:
        return StartupDecision("PAUSED", (), "Geen exchanges geconfigureerd")

    gates: list[ExchangeStartupGate] = []
    configured_count = 0
    ready_count = 0
    for state in states:
        name = state.exchange.lower()
        if not state.configured:
            gates.append(ExchangeStartupGate(
                name, False, False, False,
                "Niet geconfigureerd; installatie of pagina-open kan deze exchange niet starten",
            ))
            continue
        configured_count += 1
        protective = state.exchange_read_ok and state.protective_state_available
        fully_ready = state.exchange_read_ok and state.reconciliation_ready and state.stream_ready
        if fully_ready:
            ready_count += 1
        enabled = bool(state.persisted_enabled) if fully_ready else False
        if state.persisted_enabled is None:
            reason = "Enabled-status ontbreekt; veilig UIT"
        elif not state.exchange_read_ok:
            reason = "Exchange-read mislukt; nieuwe exposure geblokkeerd"
        elif not state.reconciliation_ready:
            reason = "Reconciliation is niet afgerond"
        elif not state.stream_ready:
            reason = "Realtime user-stream is niet gereed"
        elif enabled:
            reason = "Betrouwbare enabled-status hersteld na volledige synchronization"
        else:
            reason = "Automatisering stond betrouwbaar UIT"
        gates.append(ExchangeStartupGate(name, enabled, enabled, protective, reason))

    if configured_count == 0:
        status: StartupStatus = "PAUSED"
        reason = "Geen exchange is geconfigureerd"
    elif ready_count == configured_count:
        status = "READY"
        reason = "Alle geconfigureerde exchanges zijn gereconcilieerd"
    elif ready_count > 0:
        status = "DEGRADED"
        reason = "Alleen volledig gereed zijnde exchanges kunnen verder"
    else:
        status = "SYNCING"
        reason = "Nieuwe exposure wacht op exchange-reconciliation"
    return StartupDecision(status, tuple(gates), reason)


def retry_delay_seconds(attempt: int, *, base: int = 2, maximum: int = 60) -> int:
    """Bounded exponential reconnect delay; no tight retry loops."""
    safe_attempt = max(0, int(attempt))
    return min(maximum, base * (2 ** safe_attempt))

