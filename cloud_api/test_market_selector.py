from datetime import datetime, timezone

from aster_universe import build_snapshot


def _contract(symbol: str, quote: str = "USDT"):
    return {"symbol": symbol, "status": "TRADING", "contractType": "PERPETUAL",
        "quoteAsset": quote, "marginAsset": quote, "filters": [
            {"filterType":"PRICE_FILTER","tickSize":".01"},
            {"filterType":"LOT_SIZE","stepSize":".01"},
            {"filterType":"MARKET_LOT_SIZE","stepSize":".01"},
            {"filterType":"MIN_NOTIONAL","notional":"5"}]}


def _ticker(symbol: str, volume: int):
    return {"symbol":symbol,"lastPrice":"10","quoteVolume":str(volume*1_000_000),"count":10,
        "bidPrice":"9.99","askPrice":"10.01","priceChangePercent":"2",
        "highPrice":"11","lowPrice":"9"}


def test_selector_uses_aster_volume_and_excludes_other_quote_assets():
    value=build_snapshot({"symbols":[_contract("LOWUSDT"),_contract("HIGHUSDT"),_contract("OTHERUSDC","USDC")]},
        [_ticker("LOWUSDT",100),_ticker("HIGHUSDT",1000),_ticker("OTHERUSDC",9999)],2,
        fetched_at=datetime(2026,8,14,tzinfo=timezone.utc)).public_dict()
    assert value["selectedSymbols"]==["HIGHUSDT","LOWUSDT"]
    assert value["universeSource"]=="aster" and value["entryBlocked"] is False


def test_empty_selector_fails_closed_for_entries():
    value=build_snapshot({"symbols":[]},[],150,fetched_at=datetime(2026,8,14,tzinfo=timezone.utc)).public_dict()
    assert value["requestedTopN"]==150 and value["selectedMarketCount"]==0
    assert value["entryBlocked"] is True and value["entryBlockReason"]
