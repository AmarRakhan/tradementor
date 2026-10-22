"""Spike-take-profit en trailing (Spike 1.1, besluiten Amar 22-10-2026).

Puur rekenwerk, geen exchange- of Firestore-toegang.

- Geldt alleen voor posities die via de Spike-filter zijn geopend en nog nooit
  gehedged zijn. Na een hedge geldt de normale TP (dat beslist de scanner).
- TP is een koersbeweging vanaf de instapprijs, in procenten.
- Zonder trailing: sluiten zodra de winst de TP bereikt.
- Met trailing: de TP is het activeringspunt. Daarna wordt het hoogste
  winstpunt bijgehouden en wordt gesloten zodra de winst de ingestelde afstand
  vanaf dat hoogste punt terugvalt. Omdat trailing < TP wordt afgedwongen, sluit
  dat altijd met winst (vóór kosten).
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

# Tolerantie tegen afrondingsruis van floats (in procentpunten): 100,1 / 100 − 1
# mag niet net onder 0,1 % uitkomen.
_EPS = 1e-9


@dataclass(frozen=True)
class SpikeTpDecision:
    close: bool
    profit_pct: float
    peak_pct: float | None
    trailing_active: bool
    exit_level_pct: float | None
    reason: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "close": self.close,
            "profitPct": round(self.profit_pct, 4),
            "peakPct": None if self.peak_pct is None else round(self.peak_pct, 4),
            "trailingActive": self.trailing_active,
            "exitLevelPct": None if self.exit_level_pct is None else round(self.exit_level_pct, 4),
            "reason": self.reason,
        }


def profit_pct(*, side: str, entry: float, mark: float) -> float:
    if side == "LONG":
        return (mark / entry - 1.0) * 100.0
    return (1.0 - mark / entry) * 100.0


def evaluate_spike_take_profit(*, side: str, entry: float, mark: float, tp_pct: float,
                               trailing_enabled: bool, trailing_pct: float,
                               previous_peak_pct: float | None) -> SpikeTpDecision:
    if side not in ("LONG", "SHORT"):
        raise ValueError("SPIKE_TP_INVALID_SIDE")
    for value in (entry, mark, tp_pct):
        if not (isinstance(value, (int, float)) and math.isfinite(value) and value > 0):
            raise ValueError("SPIKE_TP_INVALID_INPUT")
    current = profit_pct(side=side, entry=entry, mark=mark)
    if not trailing_enabled:
        if current >= tp_pct - _EPS:
            return SpikeTpDecision(True, current, None, False, tp_pct, "SPIKE_TP_REACHED")
        return SpikeTpDecision(False, current, None, False, tp_pct, "SPIKE_TP_WAIT")

    if not (math.isfinite(trailing_pct) and 0 < trailing_pct < tp_pct):
        raise ValueError("SPIKE_TP_INVALID_TRAILING")
    peak = previous_peak_pct if previous_peak_pct is not None and math.isfinite(previous_peak_pct) else None
    if peak is None:
        if current < tp_pct - _EPS:
            return SpikeTpDecision(False, current, None, False, None, "SPIKE_TRAILING_WAIT_ACTIVATION")
        peak = current
    else:
        peak = max(peak, current)
    exit_level = peak - trailing_pct
    if current <= exit_level + _EPS:
        return SpikeTpDecision(True, current, peak, True, exit_level, "SPIKE_TRAILING_EXIT")
    return SpikeTpDecision(False, current, peak, True, exit_level, "SPIKE_TRAILING_FOLLOW")
