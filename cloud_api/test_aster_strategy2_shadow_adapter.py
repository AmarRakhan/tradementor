import pytest

from aster_strategy2_runtime import owned_to_mapping
from aster_strategy2_shadow import plan_validated_shadow
from aster_strategy2_shadow_adapter import (
    ReadOnlyAccountSnapshot, ShadowSnapshotRejected, validated_entry_symbols,
    validated_shadow_inputs,
)
from aster_strategy2_state import OwnedLeg


NOW = 2_000_000


def owned(*, costs_updated_at_ms=NOW):
    return OwnedLeg("aster-strategy-2", "strategy2", "BTCUSDT", "LONG", "cycle", 1,
                    1, 100, fees=.1, funding=.2,
                    costs_updated_at_ms=costs_updated_at_ms)


def position(mark=110):
    return {"symbol": "BTCUSDT", "positionSide": "LONG", "positionAmt": "1",
            "entryPrice": "100", "markPrice": str(mark),
            "unRealizedProfit": str(mark - 100), "leverage": "10"}


def snapshot(**changes):
    leg = changes.pop("leg", owned())
    values = dict(
        account_uid="account", scan_id="scan", captured_at_ms=NOW,
        strategy_state={"exclusiveOwnership": True,
            "settings": {"mode": "live", "baseNotional": 25, "takeProfit": .005},
            "ownedLegs": [owned_to_mapping(leg)], "adjustedHighWaterMark": 1000},
        hedge_mode=True,
        account={"totalMarginBalance": "1000", "totalWalletBalance": "990",
                 "totalUnrealizedProfit": "10", "totalMaintMargin": "10",
                 "availableBalance": "500"},
        positions=(position(),), open_orders=(), exchange_reliable=True,
        entry_symbols=(),
    )
    values.update(changes)
    return ReadOnlyAccountSnapshot(**values)


@pytest.mark.parametrize("changes", [
    {"exchange_reliable": False},
    {"hedge_mode": False},
    {"open_orders": ({"orderId": "open"},)},
])
def test_unreliable_exchange_truth_fails_closed(changes):
    with pytest.raises(ShadowSnapshotRejected):
        validated_shadow_inputs(snapshot(**changes))



def test_mismatched_ownership_isolates_unknown_legs_and_keeps_proven_tp_closable():
    stored_only = OwnedLeg(
        "aster-strategy-2", "strategy2", "SOLUSDT", "SHORT", "stored", 1,
        1, 100, costs_updated_at_ms=NOW,
    )
    state = snapshot().strategy_state | {
        "ownedLegs": [owned_to_mapping(owned()), owned_to_mapping(stored_only)],
        "pendingReopens": [{
            "symbol": "REOPENUSDT", "side": "SHORT", "closedCycleId": "closed",
            "packageId": "package", "notional": 25, "createdScanId": "prior",
        }],
    }
    unknown = {
        "symbol": "ETHUSDT", "positionSide": "SHORT", "positionAmt": "-1",
        "entryPrice": "100", "markPrice": "95", "unRealizedProfit": "5",
        "leverage": "10",
    }
    value = validated_shadow_inputs(snapshot(
        strategy_state=state,
        positions=(position(), unknown),
        entry_symbols=("NEWUSDT",),
    ))
    assert value.ownership_isolated is True
    assert [(leg.symbol, leg.side) for leg in value.owned] == [("BTCUSDT", "LONG")]
    plan = plan_validated_shadow(value)
    assert [action["kind"] for action in plan["actions"]] == ["TAKE_PROFIT_CLOSE"]
    assert plan["counts"]["DCA"] == 0
    assert plan["counts"]["REOPEN"] == 0
    assert plan["counts"]["OPEN_BASE"] == 0
    assert plan["externalWrites"] == plan["exchangeSubmissions"] == 0

def test_stale_fees_and_funding_block_profit_close_only():
    value = validated_shadow_inputs(snapshot(leg=owned(costs_updated_at_ms=1)))
    plan = plan_validated_shadow(value)
    assert plan["wouldSendCount"] == 0
    assert plan["externalWrites"] == plan["exchangeSubmissions"] == 0


def test_fresh_validated_snapshot_can_plan_but_never_execute_profit_close():
    value = validated_shadow_inputs(snapshot())
    plan = plan_validated_shadow(value)
    assert plan["counts"]["TAKE_PROFIT_CLOSE"] == 1
    assert plan["externalWrites"] == plan["exchangeSubmissions"] == 0


def test_invalid_persisted_order_counter_fails_closed():
    state = snapshot().strategy_state | {"orderQueueState": {"ordersUsed": 16}}
    with pytest.raises(ShadowSnapshotRejected):
        validated_shadow_inputs(snapshot(strategy_state=state))


def contract(symbol="NEWUSDT", minimum="5"):
    return {"symbol": symbol, "status": "TRADING", "contractType": "PERPETUAL",
            "quoteAsset": "USDT", "marginAsset": "USDT", "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": ".01"},
                {"filterType": "LOT_SIZE", "minQty": ".01", "maxQty": "1000", "stepSize": ".01"},
                {"filterType": "MARKET_LOT_SIZE", "minQty": ".01", "maxQty": "1000", "stepSize": ".01"},
                {"filterType": "MIN_NOTIONAL", "notional": minimum},
            ]}


def market(symbol="NEWUSDT", price="10"):
    return ({"symbol": symbol, "price": price},
            {"symbol": symbol, "lastPrice": price, "quoteVolume": "100000000",
             "count": 1000, "priceChangePercent": "1", "highPrice": "11", "lowPrice": "9"},
            {"symbol": symbol, "brackets": [{"notionalFloor": "0", "notionalCap": "1000",
             "initialLeverage": 50, "maintMarginRatio": ".004"}]})


def entry_symbols(*, row=None, available="500", brackets=None):
    price, ticker, default_brackets = market()
    return validated_entry_symbols(
        config=validated_shadow_inputs(snapshot()).config,
        owned=(owned(),), positions=(position(),),
        account={"availableBalance": available},
        exchange_info={"symbols": [row or contract()]},
        ticker_prices=(price,), tickers_24h=(ticker,),
        leverage_brackets=(default_brackets,) if brackets is None else brackets,
        captured_at_ms=NOW,
    )


def test_entry_contract_validation_is_read_only_and_accepts_executable_symbol():
    assert entry_symbols() == ("NEWUSDT",)


def test_entry_contract_minimum_maximum_and_margin_fail_closed():
    assert entry_symbols(row=contract(minimum="26.43")) == ()
    capped = ({"symbol": "NEWUSDT", "brackets": [{"notionalFloor": "0",
               "notionalCap": "20", "initialLeverage": 50, "maintMarginRatio": ".004"}]},)
    assert entry_symbols(brackets=capped) == ()
    assert entry_symbols(available="0") == ()


def test_missing_leverage_brackets_never_guesses_contract_capacity():
    assert entry_symbols(brackets=()) == ()
