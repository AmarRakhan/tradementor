"""Publieke probe: exchangeInfo-velden per verhandelbare munt (om crypto en aandelen te scheiden)."""
import json, sys, urllib.request
syms = set(open(sys.argv[1]).read().split())
with urllib.request.urlopen("https://fapi.asterdex.com/fapi/v1/exchangeInfo", timeout=30) as r:
    info = json.loads(r.read())
rows = {x["symbol"]: {k: v for k, v in x.items() if k not in ("filters", "orderTypes", "timeInForce")} for x in info.get("symbols", []) if x["symbol"] in syms}
json.dump(rows, open(sys.argv[2], "w"))
