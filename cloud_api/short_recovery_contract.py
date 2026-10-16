"""Order-free, backwards-aware SHORT recovery arithmetic. Not wired to execution."""
from dataclasses import dataclass
from decimal import Decimal

def D(value):
    return Decimal(str(value))

@dataclass(frozen=True)
class Plan:
    anchor: Decimal
    initial_short_qty: Decimal
    step_pct: Decimal
    steps: int

    def __post_init__(self):
        if self.anchor <= 0 or self.initial_short_qty <= 0:
            raise ValueError("positive anchor/quantity required")
        if isinstance(self.steps, bool) or not isinstance(self.steps, int) or not 1 <= self.steps <= 100:
            raise ValueError("steps must be 1..100")
        if self.step_pct <= 0 or self.step_pct * self.steps >= 100:
            raise ValueError("absolute final level must remain positive")

    def trigger(self, step: int) -> Decimal:
        if not 1 <= step <= self.steps: raise ValueError("step out of range")
        return self.anchor * (D(1) - D(step) * self.step_pct / D(100))

    def cumulative_target_closed(self, step: int) -> Decimal:
        if not 0 <= step <= self.steps: raise ValueError("step out of range")
        return self.initial_short_qty * D(step) / D(self.steps)

def decision(plan: Plan, *, mark: Decimal, completed_steps: int, short_qty: Decimal,
             long_qty: Decimal, enabled: bool, pending: bool = False) -> str:
    if not enabled: return "DISABLED"
    if pending: return "WAIT_PENDING"
    if long_qty <= 0: return "BLOCKED_NO_LONG"
    if not 0 <= completed_steps <= plan.steps or short_qty < 0: return "BLOCKED_BAD_STATE"
    if completed_steps == plan.steps:
        return "REHEDGE_READY" if short_qty == 0 else "WAIT_FINAL_FILL"
    if short_qty == 0: return "BLOCKED_EARLY_ZERO"
    return "REDUCE_STEP" if mark <= plan.trigger(completed_steps + 1) else "HOLD_PARTIAL"

def rollback_risk(*, enabled: bool, completed_steps: int, total_steps: int,
                  long_qty: Decimal, short_qty: Decimal) -> str:
    if enabled and 0 < completed_steps < total_steps and long_qty > short_qty >= 0:
        return "OLD_RECONCILER_WILL_TOP_UP_PARTIAL_HEDGE"
    return "REQUIRES_EXTERNAL_COMPATIBILITY_VERIFICATION"

def cycle_net_pnl(long_open, short_open, short_realized, fees, funding):
    return D(long_open) + D(short_open) + D(short_realized) - D(fees) + D(funding)
