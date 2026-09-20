from aster_sniper import SniperSettings, evaluate_candidate, exit_decision, backtest_candles
from aster_symbol_ownership import strategy2_active_symbols, sniper_active_symbols, ownership_intersection, owner_can_claim


def candle(i, close, volume=1000, taker=.55):
    return [i, close*.999, close*1.001, close*.998, close, volume, i+1, volume*close, 20, volume*close*taker, volume*close*(1-taker), 0]


def test_settings_hard_defaults():
    cfg=SniperSettings()
    assert cfg.max_trade_seconds==180
    assert cfg.tp_min_percent==.18
    assert cfg.tp_max_percent==.45
    assert cfg.max_loss_usd==.10
    assert cfg.max_concurrent==3


def test_symbol_ownership_is_exclusive_by_coin_not_side():
    s2={"ownedLegs":[{"symbol":"BTCUSDT","side":"LONG"}]}
    sniper={"activeTrades":[{"symbol":"ETHUSDT","side":"SHORT"}]}
    assert strategy2_active_symbols(s2)=={"BTCUSDT"}
    assert sniper_active_symbols(sniper)=={"ETHUSDT"}
    assert owner_can_claim("SNIPER","BTCUSDT",s2,sniper) is False
    assert owner_can_claim("ASTER","ETHUSDT",s2,sniper) is False
    assert owner_can_claim("SNIPER","SOLUSDT",s2,sniper) is True


def test_overlap_invariant_detects_any_direction():
    s2={"ownedLegs":[{"symbol":"BTCUSDT","side":"LONG"}]}
    sniper={"activeTrades":[{"symbol":"BTCUSDT","side":"SHORT"}]}
    assert ownership_intersection(s2,sniper)=={"BTCUSDT"}


def test_exit_loss_tp_and_timeout():
    cfg=SniperSettings()
    trade={"openedAtMs":1000,"tpPercent":.18}
    base={"positionAmt":"1","markPrice":"100"}
    assert exit_decision(trade,{**base,"unRealizedProfit":"-0.11"},now_ms=2000,settings=cfg)["action"]=="CLOSE_LOSS"
    assert exit_decision(trade,{**base,"unRealizedProfit":"0.20"},now_ms=2000,settings=cfg)["action"]=="CLOSE_TP"
    assert exit_decision(trade,{**base,"unRealizedProfit":"0"},now_ms=182000,settings=cfg)["action"]=="CLOSE_TIMEOUT"


def test_candidate_returns_all_twelve_named_checks():
    cfg=SniperSettings()
    candles=[candle(i,100+i*.03,1000+i*2,.55) for i in range(100)]
    result=evaluate_candidate("BTCUSDT",candles_1m=candles,candles_3m=candles,candles_5m=candles,
        ticker_24h={"quoteVolume":"100000000"},book={"bidPrice":"102.99","askPrice":"103.01"},
        depth={"bids":[["103","100"]]*20,"asks":[["103.01","80"]]*20},settings=cfg)
    assert len(result["checks"])==12
    assert {x["name"] for x in result["checks"]}=={
        "Bollinger Band locatie","Momentum","Trendfilter","Volume bevestiging","Orderflow","Orderboek",
        "Liquiditeit","Spread check","Volatiliteit","Kosten check","Liquidatiebuffer","Historische edge"}


def test_backtest_is_deterministic():
    cfg=SniperSettings()
    candles=[candle(i,100+i*.02+(i%7)*.01) for i in range(120)]
    assert backtest_candles(candles,cfg)==backtest_candles(candles,cfg)
