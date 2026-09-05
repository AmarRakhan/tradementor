import random
import pytest
from aster_multi_bb import MultiBbConfig, _asymmetric_flags


def cfg(**overrides):
    raw = {"engine":"multi_bb_v1","maximumPositions":10,"longSlots":5,"shortSlots":5,"entryMarginUsd":1,"entryNotionalUsd":50,"entrySizingMode":"margin","minimumLeverage":50,"dcaDistance":.003,"dcaMarginUsd":.3,"maxDca":20,"takeProfit":.015,"takeProfitEnabled":True,"asymmetricHedgeModeEnabled":True,"shortStartMultiplier":5}
    raw.update(overrides)
    return MultiBbConfig.from_mapping(raw)


def test_defaults_are_backward_compatible():
    c = MultiBbConfig.from_mapping({"engine":"multi_bb_v1"})
    assert c.asymmetric_hedge_enabled is False
    assert c.public_dict()["asymmetricHedgeModeEnabled"] is False


def test_multiplier_round_trip_and_limits():
    c = cfg(shortStartMultiplier=1.5)
    assert c.short_start_multiplier == 1.5
    assert c.public_dict()["shortStartMultiplier"] == 1.5
    with pytest.raises(ValueError): cfg(shortStartMultiplier=.5)
    with pytest.raises(ValueError): cfg(shortStartMultiplier=11)


def test_asymmetric_mode_requires_exact_equal_pair_capacity():
    with pytest.raises(ValueError): cfg(maximumPositions=10,longSlots=6, shortSlots=4)
    with pytest.raises(ValueError): cfg(maximumPositions=9,longSlots=5, shortSlots=4)


def test_independent_dca_and_tp_lock_flags():
    c = cfg()
    state = {"BTCUSDT|LONG":{"asymmetricHedge":True,"pairedShortKey":"BTCUSDT|SHORT","pairedShortPending":False,"dcaCount":3}, "BTCUSDT|SHORT":{"asymmetricHedge":True,"pairedLongKey":"BTCUSDT|LONG","dcaCount":7}}
    pmap = {"BTCUSDT|LONG":{},"BTCUSDT|SHORT":{}}
    lf = _asymmetric_flags(c, side="LONG", state_row=state["BTCUSDT|LONG"], state=state, pmap=pmap)
    sf = _asymmetric_flags(c, side="SHORT", state_row=state["BTCUSDT|SHORT"], state=state, pmap=pmap)
    assert lf["blockLongTp"] is True
    assert sf["disableShortTp"] is True
    assert sf["allowShortDca"] is True
    state["BTCUSDT|LONG"]["dcaCount"] = 20
    sf = _asymmetric_flags(c, side="SHORT", state_row=state["BTCUSDT|SHORT"], state=state, pmap=pmap)
    assert sf["closeShort"] is True
    assert sf["allowShortDca"] is False


def test_short_flat_unlocks_long_tp():
    c = cfg()
    long = {"asymmetricHedge":True,"pairedShortKey":"BTCUSDT|SHORT","pairedShortPending":False}
    flags = _asymmetric_flags(c, side="LONG", state_row=long, state={"BTCUSDT|LONG":long}, pmap={"BTCUSDT|LONG":{}})
    assert flags["blockLongTp"] is False


def test_10000_randomized_state_invariants():
    rnd = random.Random(20260904)
    c = cfg()
    for _ in range(10_000):
        long_dca = rnd.randint(0, 20)
        short_dca = rnd.randint(0, 20)
        short_open = rnd.choice([True, False])
        pending = False if short_open else rnd.choice([True, False])
        long = {"asymmetricHedge":True,"pairedShortKey":"X|SHORT","pairedShortPending":pending,"dcaCount":long_dca}
        short = {"asymmetricHedge":True,"pairedLongKey":"X|LONG","dcaCount":short_dca}
        state = {"X|LONG":long,"X|SHORT":short}
        pmap = {"X|LONG":{}}
        if short_open: pmap["X|SHORT"] = {}
        lf = _asymmetric_flags(c, side="LONG", state_row=long, state=state, pmap=pmap)
        sf = _asymmetric_flags(c, side="SHORT", state_row=short, state=state, pmap=pmap)
        assert lf["blockLongTp"] == (short_open or pending)
        assert sf["closeShort"] == (long_dca >= 20)
        assert sf["allowShortDca"] == (long_dca < 20)
        # The two counters are intentionally independent: no equality/rebalance invariant exists.
        assert long_dca == long["dcaCount"] and short_dca == short["dcaCount"]


def test_asymmetric_entry_allocator_only_plans_same_symbol_pairs():
    from test_aster_multi_bb import Client, Ref
    import time
    from aster_multi_bb import run_multi_bb_step
    c=Client(tickers=[{"symbol":"AAAUSDT","quoteVolume":"1000"},{"symbol":"BBBUSDT","quoteVolume":"900"}],prices={"AAAUSDT":100,"BBBUSDT":100},leverage=100)
    settings=cfg(maximumPositions=4,longSlots=2,shortSlots=2,universeTopN=2)
    r=run_multi_bb_step(client=c,ref=Ref(),raw_state={},settings=settings,uid="u",account={"availableBalance":"1000"},positions=[],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=True)
    entries=[x for x in r["actions"] if x["kind"] in {"ENTRY","ASYM_SHORT_ENTRY"}]
    assert len(entries)==4
    by_symbol={}
    for x in entries: by_symbol.setdefault(x["symbol"],set()).add(x["side"])
    assert by_symbol=={"AAAUSDT":{"LONG","SHORT"},"BBBUSDT":{"LONG","SHORT"}}
    assert not any(x["kind"]=="ENTRY" and x["side"]=="SHORT" for x in r["actions"])
    for symbol in by_symbol:
        long=next(x for x in entries if x["symbol"]==symbol and x["side"]=="LONG")
        short=next(x for x in entries if x["symbol"]==symbol and x["side"]=="SHORT")
        assert short["leverage"]==long["leverage"]
        assert short["marginUsd"]==pytest.approx(long["marginUsd"]*5)


def test_legacy_positions_do_not_consume_new_pair_capacity():
    from test_aster_multi_bb import Client, Ref
    import time
    from aster_multi_bb import run_multi_bb_step
    positions=[]; state={}
    for i in range(7):
        symbol=f"OLDL{i}USDT"; positions.append({"symbol":symbol,"positionSide":"LONG","positionAmt":"1","entryPrice":"100","markPrice":"100","leverage":"100"})
        state[f"{symbol}|LONG"]={"dcaCount":0,"lastBotFillPrice":100,"lastKnownQty":1,"lastKnownEntry":100,"cycleStartedAtMs":1,"botManaged":True}
    for i in range(4):
        symbol=f"OLDS{i}USDT"; positions.append({"symbol":symbol,"positionSide":"SHORT","positionAmt":"-1","entryPrice":"100","markPrice":"100","leverage":"100"})
        state[f"{symbol}|SHORT"]={"dcaCount":0,"lastBotFillPrice":100,"lastKnownQty":1,"lastKnownEntry":100,"cycleStartedAtMs":1,"botManaged":True}
    tickers=[{"symbol":"NEWUSDT","quoteVolume":"999999"}]
    prices={"NEWUSDT":100, **{p["symbol"]:100 for p in positions}}
    c=Client(positions=positions,tickers=tickers,prices=prices,leverage=100)
    settings=cfg(maximumPositions=14,longSlots=7,shortSlots=7,universeTopN=50,entryMarginUsd=.1,shortStartMultiplier=5)
    r=run_multi_bb_step(client=c,ref=Ref(),raw_state={"multiBbPositions":state},settings=settings,uid="u",account={"availableBalance":"100"},positions=positions,open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=True)
    entries=[x for x in r["actions"] if x["kind"] in {"ENTRY","ASYM_SHORT_ENTRY"}]
    assert {(x["symbol"],x["side"]) for x in entries} == {("NEWUSDT","LONG"),("NEWUSDT","SHORT")}
    assert r["asymmetricHedgeActivePairs"] == 1
    assert r["remainingPairs"] == 6
    assert r["legacyPositionsDuringAsymmetric"] == 11


def test_existing_asymmetric_pairs_do_consume_pair_capacity():
    from test_aster_multi_bb import Client, Ref
    import time
    from aster_multi_bb import run_multi_bb_step
    long={"symbol":"PAIRUSDT","positionSide":"LONG","positionAmt":"1","entryPrice":"100","markPrice":"100","leverage":"100"}
    short={"symbol":"PAIRUSDT","positionSide":"SHORT","positionAmt":"-5","entryPrice":"100","markPrice":"100","leverage":"100"}
    state={"PAIRUSDT|LONG":{"asymmetricHedge":True,"pairedShortKey":"PAIRUSDT|SHORT","pairedShortPending":False,"botManaged":True,"dcaCount":0,"lastBotFillPrice":100},"PAIRUSDT|SHORT":{"asymmetricHedge":True,"pairedLongKey":"PAIRUSDT|LONG","botManaged":True,"dcaCount":0,"lastBotFillPrice":100}}
    c=Client(positions=[long,short],tickers=[{"symbol":"NEWUSDT","quoteVolume":"1000"}],prices={"PAIRUSDT":100,"NEWUSDT":100},leverage=100)
    settings=cfg(maximumPositions=2,longSlots=1,shortSlots=1,universeTopN=50,entryMarginUsd=.1)
    r=run_multi_bb_step(client=c,ref=Ref(),raw_state={"multiBbPositions":state},settings=settings,uid="u",account={"availableBalance":"100"},positions=[long,short],open_orders=[],timestamp_ms=int(time.time()*1000),dry_run=True)
    assert r["asymmetricHedgeActivePairs"] == 1 and r["remainingPairs"] == 0
    assert not any(x["kind"]=="ENTRY" for x in r["actions"])
