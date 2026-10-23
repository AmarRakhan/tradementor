import json, sys, urllib.request, zlib, base64
sys.path.insert(0, "cloud_api")
from active_trades_zones import long_basket, kline_candles, basket_index_candles, derive_sr_zones
symbols = {"BTCUSDT": 30, "ETHUSDT": 20, "SOLUSDT": 12, "DOGEUSDT": 8, "LINKUSDT": 8, "LTCUSDT": 6, "INJUSDT": 6, "XRPUSDT": 10}
positions = [{"symbol": s, "side": "LONG", "notionalUsd": w} for s, w in symbols.items()] + [{"symbol": "BTCUSDT", "side": "SHORT", "notionalUsd": 30}]
for tf, interval in (("15m", "15m"), ("1u", "1h"), ("4u", "4h")):
    basket = long_basket(positions)
    data = {}
    for row in basket["symbols"]:
        url = f"https://fapi.asterdex.com/fapi/v1/klines?symbol={row['symbol']}&interval={interval}&limit=320"
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "qa645"}), timeout=20) as r:
            data[row["symbol"]] = kline_candles(json.loads(r.read()))
    index = basket_index_candles(basket, data)
    zones = derive_sr_zones(index["candles"])
    c = index["candles"][-120:]
    lo = min(x["low"] for x in c); hi = max(x["high"] for x in c)
    vis = [l for l in zones["levels"] if lo - (hi-lo)*.1 <= l["price"] <= hi + (hi-lo)*.1]
    payload = {"tf": tf, "c": [[x["time"], round(x["open"],3), round(x["high"],3), round(x["low"],3), round(x["close"],3)] for x in c],
               "l": [[round(l["price"],3), l["kind"][0], l["touches"], int(l["flipped"]), int(l["brokenAwaitingRetest"])] for l in vis],
               "z": zones["activeZone"], "used": index["usedSymbols"], "atr": round(zones["atr"],3), "n": len(zones["levels"]), "flips": sum(1 for l in zones["levels"] if l["flipped"])}
    blob = base64.b64encode(zlib.compress(json.dumps(payload, separators=(",", ":")).encode(), 9)).decode()
    print(f"::notice title=QA645 {tf} stats::levels={payload['n']} visible={len(vis)} flips={payload['flips']} atr={payload['atr']} used={len(payload['used'])} bars={len(index['candles'])}")
    for i in range(0, len(blob), 3500):
        print(f"::notice title=QA645 {tf} part {i//3500}::{blob[i:i+3500]}")
