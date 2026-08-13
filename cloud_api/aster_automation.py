"""One-action-per-tick lifecycle for Aster Profit Harvest Hedge."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable
from aster_strategy import AsterStrategySettings, Account, Leg, Pair, Action, dca_trigger, harvest_due, risk_mode


@dataclass(frozen=True)
class TickMarket:
    prices: dict[str, float]
    taker_fee_rate: float = .0004


def decide_tick(settings: AsterStrategySettings, account: Account, pairs: Iterable[Pair], market: TickMarket) -> Action:
    pairs = list(pairs)
    mode = risk_mode(settings, account)
    # A half-open hedge not created by our atomic harvest path is always first.
    for pair in pairs:
        if bool(pair.long) != bool(pair.short):
            leg = pair.long or pair.short
            return Action("CLOSE_LEG", pair.symbol, leg.side if leg else None,
                          reason="Onverwacht ongedekte pair direct neutraliseren", safety=True)
    legs = [(pair, leg) for pair in pairs for leg in (pair.long, pair.short) if leg]
    if mode == "EMERGENCY" and legs:
        pair, leg = min(legs, key=lambda item: item[1].unrealized_pnl)
        return Action("CLOSE_LEG", pair.symbol, leg.side, reason="80% noodrem beschermt kapitaal", safety=True)
    profitable = []
    for pair, leg in legs:
        fee = leg.notional * market.taker_fee_rate
        if harvest_due(settings, leg, fee, fee): profitable.append((pair, leg))
    if profitable:
        pair, leg = max(profitable, key=lambda item: item[1].unrealized_pnl)
        return Action("HARVEST_RESET", pair.symbol, leg.side, leg.notional,
                      "Netto winstdoel na kosten bereikt", safety=mode != "NORMAL")
    if mode in {"BLOCK", "REDUCE"}:
        return Action("HOLD", reason=f"Marginbeveiliging {mode}: geen nieuw risico", safety=True)
    if not settings.enabled:
        return Action("HOLD", reason="Veilige stop: alleen bestaande winst en noodrem blijven actief", safety=True)
    for pair, leg in legs:
        price = market.prices.get(pair.symbol, 0)
        if dca_trigger(settings, leg, price):
            next_notional = settings.base_notional * settings.dca_multiplier
            # Real margin and pair-budget checks happen against current leverage
            # in the executor; this pure layer only decides whether a level is due.
            return Action("ADD_DCA", pair.symbol, leg.side, next_notional,
                          f"DCA-niveau {leg.dca_count+1} geraakt")
    return Action("FILL_SLOT", reason="Geen beheeractie; scanner mag vrije plek vullen")
