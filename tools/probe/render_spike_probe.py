"""Publieke probe: RENDERUSDT 15m rond de Spike-instap van 23-10 09:25:33 UTC (geen sleutels)."""
import json, math, urllib.request
BASE = "https://fapi.asterdex.com"
ENTRY_MS = 1792747533131
def get(path):
    with urllib.request.urlopen(BASE + path, timeout=20) as r:
        return json.loads(r.read())
out = {}
for kind in ("klines", "markPriceKlines"):
    rows = get(f"/fapi/v1/{kind}?symbol=RENDERUSDT&interval=15m&endTime={ENTRY_MS + 3*900000}&limit=30")
    rows = [[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), int(r[6])] for r in rows]
    live = [r for r in rows if r[0] <= ENTRY_MS <= r[5]][0]
    closed = [r for r in rows if r[5] < live[0]][-20:]
    closes = [r[4] for r in closed]
    mean = sum(closes) / 20
    sd = math.sqrt(sum((c - mean) ** 2 for c in closes) / 20)
    out[kind] = {"liveOpenMs": live[0], "liveOHLC": live[1:5], "mean": mean, "sd": sd,
                 "sdPct": sd / mean * 100, "band2": mean - 2 * sd, "band4": mean - 4 * sd,
                 "band4DistPct": 4 * sd / mean * 100, "lowSigma": (mean - live[3]) / sd,
                 "next": [r[1:5] for r in rows if r[0] > live[0]][:3],
                 "closedRange": [min(closes), max(closes)]}
print(json.dumps(out))
