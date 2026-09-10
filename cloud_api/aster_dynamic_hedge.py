"""Pure fail-closed Dynamic Hedge / liquidation-safety controller for Aster.

No network calls and no order submission live here.  The live runtime must supply
exchange-confirmed account risk plus a separately planned candidate impact before
this module can ever authorize risk-adding hedge exposure.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

OWNERSHIP_STATES = {
    "NORMAL", "ADOPTING", "DYNAMIC_HEDGE_ACTIVE", "MANUAL_ACTION_LOCK", "HANDING_BACK",
}
ENGINE_STATES = {
    "MONITORING", "POSITIONS_ADOPTING", "HEDGE_BUILDING", "HEDGE_STABLE", "HEDGE_REDUCING",
    "PROTECT_MARGIN_BUFFER", "REDUCE_GROSS_EXPOSURE", "AUTOMATION_PAUSED", "DATA_UNRELIABLE",
}
RISK_ADDING_ACTIONS = {"OPEN_LONG", "OPEN_SHORT", "DCA_LONG", "DCA_SHORT"}


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def robust_hedge_coverage(long_exposure: Any, short_exposure: Any) -> float | None:
    """Symmetric hedge coverage: smaller side divided by dominant side."""
    long_value = _finite(long_exposure)
    short_value = _finite(short_exposure)
    if long_value is None or short_value is None or long_value < 0 or short_value < 0:
        return None
    dominant = max(long_value, short_value)
    if dominant <= 0:
        return 100.0
    return round(min(long_value, short_value) / dominant * 100.0, 6)


def net_exposure(long_exposure: Any, short_exposure: Any) -> tuple[float | None, str]:
    long_value = _finite(long_exposure)
    short_value = _finite(short_exposure)
    if long_value is None or short_value is None:
        return None, "UNKNOWN"
    value = long_value - short_value
    side = "FLAT" if abs(value) < 1e-9 else ("LONG" if value > 0 else "SHORT")
    return round(value, 8), side


@dataclass(frozen=True)
class DynamicHedgeConfig:
    # Central server-side policy. Percentages refer to Aster's account-wide
    # liquidation-risk ratio, where 100% is the maintenance/liquidation boundary.
    safe_risk_pct: float = 25.0
    caution_risk_pct: float = 50.0
    high_risk_pct: float = 75.0
    minimum_projected_buffer_ratio: float = 1.35
    minimum_projected_buffer_usd: float = 5.0
    normal_target_min_pct: float = 25.0
    normal_target_max_pct: float = 40.0
    caution_target_min_pct: float = 40.0
    caution_target_max_pct: float = 60.0
    high_target_min_pct: float = 60.0
    high_target_max_pct: float = 80.0
    target_hysteresis_pct: float = 2.0

    def validated(self) -> "DynamicHedgeConfig":
        values = (
            self.safe_risk_pct, self.caution_risk_pct, self.high_risk_pct,
            self.minimum_projected_buffer_ratio, self.minimum_projected_buffer_usd,
            self.normal_target_min_pct, self.normal_target_max_pct,
            self.caution_target_min_pct, self.caution_target_max_pct,
            self.high_target_min_pct, self.high_target_max_pct, self.target_hysteresis_pct,
        )
        if any(not math.isfinite(float(x)) for x in values):
            raise ValueError("Dynamic Hedge policy bevat een ongeldige waarde")
        if not 0 < self.safe_risk_pct < self.caution_risk_pct < self.high_risk_pct < 100:
            raise ValueError("Liquidatierisicogrenzen moeten oplopend onder 100% liggen")
        if self.minimum_projected_buffer_ratio <= 1:
            raise ValueError("Minimum buffer ratio moet groter dan 1 zijn")
        if self.minimum_projected_buffer_usd < 0:
            raise ValueError("Minimum margin buffer mag niet negatief zijn")
        bands = (
            (self.normal_target_min_pct, self.normal_target_max_pct),
            (self.caution_target_min_pct, self.caution_target_max_pct),
            (self.high_target_min_pct, self.high_target_max_pct),
        )
        if any(not 0 <= low <= high <= 100 for low, high in bands):
            raise ValueError("Hedge-doelzones moeten tussen 0% en 100% liggen")
        if not (bands[0][1] <= bands[1][1] <= bands[2][1]):
            raise ValueError("Hedge-doelzones moeten met risico kunnen oplopen")
        if not 0 <= self.target_hysteresis_pct <= 20:
            raise ValueError("Hysterese is ongeldig")
        return self

    def public_dict(self) -> dict[str, float]:
        return {
            "safeRiskPct": self.safe_risk_pct,
            "cautionRiskPct": self.caution_risk_pct,
            "highRiskPct": self.high_risk_pct,
            "minimumProjectedBufferRatio": self.minimum_projected_buffer_ratio,
            "minimumProjectedBufferUsd": self.minimum_projected_buffer_usd,
            "normalTargetMinPct": self.normal_target_min_pct,
            "normalTargetMaxPct": self.normal_target_max_pct,
            "cautionTargetMinPct": self.caution_target_min_pct,
            "cautionTargetMaxPct": self.caution_target_max_pct,
            "highTargetMinPct": self.high_target_min_pct,
            "highTargetMaxPct": self.high_target_max_pct,
            "targetHysteresisPct": self.target_hysteresis_pct,
        }


def safety_status(risk: dict[str, Any], config: DynamicHedgeConfig | None = None) -> str:
    policy = (config or DynamicHedgeConfig()).validated()
    reliable = bool(risk.get("reliable", False))
    liquidation = _finite(risk.get("liquidationRiskPct"))
    equity = _finite(risk.get("equity"))
    maintenance = _finite(risk.get("maintenanceMarginUsd", risk.get("maintenanceMargin")))
    if not reliable or liquidation is None or equity is None or maintenance is None:
        return "DATA_ONBETROUWBAAR"
    if equity < 0 or maintenance < 0:
        return "DATA_ONBETROUWBAAR"
    if maintenance > 0 and equity <= maintenance:
        return "KRITIEK"
    if liquidation >= policy.high_risk_pct:
        return "KRITIEK"
    if liquidation >= policy.caution_risk_pct:
        return "HOOG_RISICO"
    if liquidation >= policy.safe_risk_pct:
        return "OPLETTEN"
    return "VEILIG"


def dynamic_target_range(risk: dict[str, Any], config: DynamicHedgeConfig | None = None) -> tuple[float, float] | None:
    policy = (config or DynamicHedgeConfig()).validated()
    status = safety_status(risk, policy)
    if status in {"DATA_ONBETROUWBAAR", "KRITIEK"}:
        return None
    if status == "HOOG_RISICO":
        return policy.high_target_min_pct, policy.high_target_max_pct
    if status == "OPLETTEN":
        return policy.caution_target_min_pct, policy.caution_target_max_pct
    return policy.normal_target_min_pct, policy.normal_target_max_pct


def _projected_guard(candidate: dict[str, Any] | None, policy: DynamicHedgeConfig) -> tuple[bool, str]:
    """Authorize a risk-adding candidate only with complete projected margin evidence."""
    if not isinstance(candidate, dict):
        return False, "PROJECTED_MARGIN_EVIDENCE_MISSING"
    projected_buffer = _finite(candidate.get("projectedMarginBufferUsd"))
    projected_ratio = _finite(candidate.get("projectedBufferRatio"))
    projected_maintenance = _finite(candidate.get("projectedMaintenanceMarginUsd"))
    projected_equity = _finite(candidate.get("projectedEquity"))
    if None in (projected_buffer, projected_ratio, projected_maintenance, projected_equity):
        return False, "PROJECTED_MARGIN_EVIDENCE_MISSING"
    if projected_equity is None or projected_maintenance is None or projected_equity <= projected_maintenance:
        return False, "PROJECTED_LIQUIDATION_BUFFER_UNSAFE"
    if projected_buffer is None or projected_buffer < policy.minimum_projected_buffer_usd:
        return False, "PROJECTED_MARGIN_BUFFER_TOO_LOW"
    if projected_ratio is None or projected_ratio < policy.minimum_projected_buffer_ratio:
        return False, "PROJECTED_BUFFER_RATIO_TOO_LOW"
    current_buffer = _finite(candidate.get("currentMarginBufferUsd"))
    current_ratio = _finite(candidate.get("currentBufferRatio"))
    if current_buffer is not None and projected_buffer > current_buffer + 1e-9:
        return True, "PROJECTED_MARGIN_IMPROVES"
    if current_ratio is not None and projected_ratio > current_ratio + 1e-9:
        return True, "PROJECTED_RATIO_IMPROVES"
    return True, "PROJECTED_MARGIN_WITHIN_POLICY"


def assess_dynamic_hedge(
    *,
    enabled: bool,
    ownership_state: str,
    exposure: dict[str, Any],
    risk: dict[str, Any],
    candidate: dict[str, Any] | None = None,
    config: DynamicHedgeConfig | None = None,
) -> dict[str, Any]:
    """Return one deterministic, non-executing controller decision.

    Monitoring always works. Risk-adding authorization stays false until a live
    planner supplies projected margin evidence for the exact candidate order.
    """
    policy = (config or DynamicHedgeConfig()).validated()
    owner = str(ownership_state or "NORMAL").upper()
    if owner not in OWNERSHIP_STATES:
        owner = "NORMAL"
    long_value = _finite(exposure.get("longExposureUsd"))
    short_value = _finite(exposure.get("shortExposureUsd"))
    coverage = robust_hedge_coverage(long_value, short_value)
    net_value, net_side = net_exposure(long_value, short_value)
    gross = None if long_value is None or short_value is None else round(long_value + short_value, 8)
    safe = safety_status(risk, policy)
    targets = dynamic_target_range(risk, policy)
    reliable = bool(exposure.get("reliable", False)) and bool(risk.get("reliable", False)) and coverage is not None

    base = {
        "enabled": bool(enabled),
        "ownershipState": owner,
        "monitoringAlwaysActive": True,
        "reliable": reliable,
        "safetyStatus": safe,
        "hedgeCoveragePercent": coverage,
        "netExposureUsd": net_value,
        "netSide": net_side,
        "grossExposureUsd": gross,
        "targetMinPercent": targets[0] if targets else None,
        "targetMaxPercent": targets[1] if targets else None,
        "riskAddingAllowed": False,
        "recommendedAction": "HOLD",
        "reasonCode": "MONITORING_ONLY",
        "engineState": "MONITORING",
    }
    if not reliable or safe == "DATA_ONBETROUWBAAR":
        return {**base, "engineState": "DATA_UNRELIABLE", "reasonCode": "EXCHANGE_RISK_DATA_UNRELIABLE"}
    if not enabled:
        return base
    if owner == "ADOPTING":
        return {**base, "engineState": "POSITIONS_ADOPTING", "reasonCode": "ADOPTION_IN_PROGRESS"}
    if owner in {"MANUAL_ACTION_LOCK", "HANDING_BACK"}:
        return {**base, "engineState": "AUTOMATION_PAUSED", "reasonCode": owner}
    if owner != "DYNAMIC_HEDGE_ACTIVE":
        return {**base, "engineState": "AUTOMATION_PAUSED", "reasonCode": "OWNERSHIP_NOT_ACTIVE"}
    if safe == "KRITIEK":
        return {**base, "engineState": "REDUCE_GROSS_EXPOSURE", "reasonCode": "LIQUIDATION_BUFFER_CRITICAL", "recommendedAction": "REDUCE_GROSS_EXPOSURE"}
    if targets is None or coverage is None:
        return {**base, "engineState": "DATA_UNRELIABLE", "reasonCode": "TARGET_UNAVAILABLE"}

    low, high = targets
    hysteresis = policy.target_hysteresis_pct
    if coverage < low - hysteresis:
        desired = "OPEN_SHORT" if (long_value or 0) > (short_value or 0) else "OPEN_LONG"
        allowed, reason = _projected_guard(candidate, policy)
        if not allowed:
            return {**base, "engineState": "PROTECT_MARGIN_BUFFER", "reasonCode": reason, "recommendedAction": desired, "riskAddingAllowed": False}
        return {**base, "engineState": "HEDGE_BUILDING", "reasonCode": reason, "recommendedAction": desired, "riskAddingAllowed": True}
    if coverage > high + hysteresis:
        desired = "CLOSE_SHORT" if (long_value or 0) >= (short_value or 0) else "CLOSE_LONG"
        return {**base, "engineState": "HEDGE_REDUCING", "reasonCode": "ABOVE_DYNAMIC_TARGET", "recommendedAction": desired, "riskAddingAllowed": False}
    return {**base, "engineState": "HEDGE_STABLE", "reasonCode": "WITHIN_DYNAMIC_TARGET"}
