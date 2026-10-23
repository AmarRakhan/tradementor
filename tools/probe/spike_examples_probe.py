"""Publieke probe: 15m-candles (laatste ~75 uur) van de verhandelbare munten. Geen sleutels, geen orders."""
import json, sys, time, urllib.request
BASE = "https://fapi.asterdex.com"
symbols = open(sys.argv[1]).read().split()
out = {}
for sym in symbols:
    try:
        with urllib.request.urlopen(f"{BASE}/fapi/v1/klines?symbol={sym}&interval=15m&limit=300", timeout=20) as r:
            rows = json.loads(r.read())
        out[sym] = [[int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[7])] for x in rows]
    except Exception as exc:
        out[sym] = {"error": str(exc)[:200]}
    time.sleep(0.15)
json.dump(out, open(sys.argv[2], "w"))
print(len(out))
