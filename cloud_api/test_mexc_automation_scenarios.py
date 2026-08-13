"""Five deterministic end-to-end strategy simulations; no exchange calls."""
from dataclasses import replace

from mexc_automation import AccountSnapshot, AutoSettings, AutoState, MarketSignal, decide, maximum_long


def run_path(prices, *, risks=None, recoveries=None, force_margin_at=None):
    settings = AutoSettings(cooldown_seconds=60)
    state = AutoState(125.0)
    long_qty = short_qty = 0.0
    long_entry = short_entry = 0.0
    realized = fees = 0.0
    previous = prices[0]
    actions = []
    lowest = 125.0
    for index, price in enumerate(prices):
        long_pnl = long_qty * (price - long_entry)
        short_pnl = short_qty * (short_entry - price)
        equity = 125.0 + realized + long_pnl + short_pnl - fees
        lowest = min(lowest, equity)
        long_notional, short_notional = long_qty * price, short_qty * price
        account = AccountSnapshot(
            current_equity=equity, available_equity=max(0.0, equity - (long_notional + short_notional) / 200),
            long_notional=long_notional, short_notional=short_notional,
            weighted_long_entry=long_entry, weighted_short_entry=short_entry,
            margin_used=(long_notional + short_notional) / 200,
            margin_ratio=.75 if force_margin_at == index else (long_notional + short_notional) * .0014 / max(equity, .01),
            liquidation_distance=1.0,
            net_session_pnl=equity - state.session_start_equity,
        )
        market = MarketSignal(
            timestamp=(index + 1) * 60, price=price, atr_percent=.0075,
            lower_low=price < previous,
            risk_score=(risks[index] if risks else 10),
            recovery_score=(recoveries[index] if recoveries else 10),
        )
        action = decide(settings, state, account, market)
        actions.append(action.kind)
        if action.kind in {"OPEN_LONG", "ADD_LONG"}:
            add_qty = action.target_notional / price
            long_entry = (long_entry * long_qty + price * add_qty) / (long_qty + add_qty) if long_qty else price
            long_qty += add_qty
            fees += action.target_notional * .0006
            state = replace(state, dca_count=state.dca_count + (action.kind == "ADD_LONG"), last_dca_price=price, last_order_time=market.timestamp, phase="DCA" if action.kind == "ADD_LONG" else "LONG")
        elif action.kind == "SET_HEDGE":
            target_qty = action.target_notional / price
            if target_qty > short_qty:
                delta = target_qty - short_qty
                short_entry = (short_entry * short_qty + price * delta) / target_qty if short_qty else price
                fees += delta * price * .0006
            elif target_qty < short_qty:
                delta = short_qty - target_qty
                realized += delta * (short_entry - price)
                fees += delta * price * .0006
            short_qty = target_qty
            short_entry = short_entry if short_qty else 0.0
            state = replace(state, last_order_time=market.timestamp, phase="PROTECT" if short_qty else "UNHEDGE")
        elif action.kind in {"CLOSE_ALL", "CLOSE_SHORT"}:
            if short_qty:
                realized += short_qty * (short_entry - price)
                fees += short_qty * price * .0006
                short_qty = 0.0
            if action.kind == "CLOSE_ALL" and long_qty:
                realized += long_qty * (price - long_entry)
                fees += long_qty * price * .0006
                long_qty = 0.0
            state = replace(state, last_order_time=market.timestamp, phase="CLOSED" if action.kind == "CLOSE_ALL" else "RECOVERY")
        assert long_notional <= maximum_long(settings, 125.0) * 1.05
        assert short_notional <= long_notional * settings.max_hedge_ratio + 1e-6
        previous = price
    return {"actions": actions, "lowest": lowest, "dca": state.dca_count, "longQty": long_qty, "shortQty": short_qty}


def test_scenario_1_rising_market_opens_then_takes_net_profit():
    result = run_path([100, 100.5, 101.0, 102.0, 104.0, 105.0])
    assert result["actions"][0] == "OPEN_LONG"
    assert "CLOSE_ALL" in result["actions"]


def test_scenario_2_orderly_decline_uses_dca_spacing_without_overfilling():
    result = run_path([100, 99.0, 98.0, 97.0, 96.0, 95.0, 94.0, 93.0, 92.0])
    assert 1 <= result["dca"] <= 7
    assert result["actions"].count("ADD_LONG") == result["dca"]


def test_scenario_3_bear_regime_opens_short_hedge():
    prices = [100, 99, 98, 97, 96]
    result = run_path(prices, risks=[10, 10, 90, 90, 90])
    assert "SET_HEDGE" in result["actions"]
    assert result["shortQty"] > 0


def test_scenario_4_recovery_unwinds_hedge_in_steps():
    prices = [100, 99, 98, 97, 98, 99, 100, 101]
    risks = [10, 10, 90, 90, 10, 10, 10, 10]
    recovery = [10, 10, 10, 10, 40, 55, 70, 85]
    result = run_path(prices, risks=risks, recoveries=recovery)
    assert result["actions"].count("SET_HEDGE") >= 2
    assert result["shortQty"] == 0


def test_scenario_5_margin_emergency_overrides_and_closes_everything():
    result = run_path([100, 99, 98], force_margin_at=2)
    assert result["actions"][-1] == "CLOSE_ALL"
    assert result["longQty"] == 0 and result["shortQty"] == 0
