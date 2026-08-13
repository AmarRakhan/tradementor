"""Pure portfolio-cycle math for safe tests without exchange access."""

from __future__ import annotations


def normalized_target_percentage(value: float) -> float:
    return max(1.0, min(1000.0, float(value)))


def adjusted_start_value(start_value: float, external_cash_flow: float = 0.0) -> float:
    """Keep trading performance separate from deposits and withdrawals."""
    return max(0.0, float(start_value) + float(external_cash_flow))


def cycle_start_decision(status: str, active_position_count: int) -> str:
    """Continue unfinished cycles; only start fresh when no positions remain."""
    if str(status or "inactive") in {"active", "closing", "completed_with_failures"}:
        return "continue"
    return "blocked" if int(active_position_count) > 0 else "start"


def cycle_payload_values(
    start_value: float,
    current_value: float,
    target_percentage: float,
    external_cash_flow: float = 0.0,
) -> dict[str, float | bool]:
    original_start = max(0.0, float(start_value))
    start = adjusted_start_value(original_start, external_cash_flow)
    current = float(current_value)
    target = normalized_target_percentage(target_percentage)
    target_value = start * (1.0 + target / 100.0)
    growth = ((current - start) / start * 100.0) if start > 0 else 0.0
    return {
        "originalStartPortfolioValue": original_start,
        "adjustedStartPortfolioValue": start,
        "externalCashFlowUsd": float(external_cash_flow),
        "targetPortfolioValue": target_value,
        "growthPercentage": growth,
        "remainingUsd": max(0.0, target_value - current),
        "progressPercentage": min(100.0, max(0.0, growth / target * 100.0)),
        "targetReached": start > 0 and current + 1e-9 >= target_value,
    }
