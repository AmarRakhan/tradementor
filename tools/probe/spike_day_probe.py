"""Publieke probe (geen sleutels, geen orders): Spike als handelsdag 08:00-23:00 Amsterdam (06-21 UTC).
Per instelling: instap (trigger of opveer 0,3 %), TP netto na fees, en wat er gebeurt zonder TP:
H1/H2/H3 = hedge bij -1/-2/-3 % (verlies vast tot einde dag), T15/T60 = na 15/60 min sluiten,
H2T60 = hedge bij -2 % of na 60 min sluiten, EOD = laten staan en om 23:00 sluiten.
Positie $20, één positie per munt per instelling. Fees taker: crypto 0,04 %/kant, overig 0,0125 %/kant."""
import json, math, sys, time, urllib.request
from multiprocessing import Pool
BASE = "https://fapi.asterdex.com"
DAYS = [(1792476000000 + i * 86400000) for i in range(3)]   # 20,21,22 okt 06:00 UTC
T0 = DAYS[0] - 10 * 3600000
T1 = DAYS[-1] + 15 * 3600000
TFS = {"1m": 1, "5m": 5, "15m": 15}
LEVELS = [2, 3, 4, 5, 6, 7]
DISTS = [0, 2]
BOUNCES = [0.0, 0.3]
NETS = [0.1, 0.3, 0.5, 1.0]
HEDGES = [1, 2, 3]
RULES = ["H1", "H2", "H3", "T15", "T60", "H2T60", "EOD"]
LOW_FEE = set(open(sys.argv[3]).read().split())
def get(sym, s, e):
    with urllib.request.urlopen(f"{BASE}/fapi/v1/klines?symbol={sym}&interval=1m&startTime={s}&endTime={e}&limit=1500", timeout=25) as r:
        return json.loads(r.read())
def fetch(sym):
    rows, t = [], T0
    for _ in range(6):
        part = get(sym, t, T1)
        if not part: break
        rows += [[int(x[0]), float(x[2]), float(x[3]), float(x[4])] for x in part if not rows or int(x[0]) > rows[-1][0]]
        t = int(part[-1][0]) + 60000
        time.sleep(0.05)
        if len(part) < 1500: break
    return rows
def work(sym):
    try:
        m = fetch(sym)
    except Exception:
        return sym, None
    if len(m) < 3000: return sym, None
    rt = 0.025 if sym in LOW_FEE else 0.08
    T = [r[0] for r in m]; H = [r[1] for r in m]; L = [r[2] for r in m]; C = [r[3] for r in m]
    idx = {t: i for i, t in enumerate(T)}
    def eod_index(t):
        for d in DAYS:
            if d <= t < d + 15 * 3600000:
                return d, idx.get(d + 15 * 3600000 - 60000)
        return None, None
    out = {}
    for tf, mult in TFS.items():
        ms = mult * 60000
        rows = []
        i = 0
        while i < len(m):
            b = T[i] // ms * ms; j = i; lo = L[i]; hi = H[i]
            while j + 1 < len(m) and T[j + 1] // ms * ms == b:
                j += 1; lo = min(lo, L[j]); hi = max(hi, H[j])
            rows.append((b, lo, hi, C[j], i, j)); i = j + 1
        closes = [r[3] for r in rows]
        for ci in range(20, len(rows)):
            b, lo, hi, _, i0, i1 = rows[ci]
            day, eod = eod_index(b)
            if day is None or eod is None: continue
            p = closes[ci - 20:ci]; mu = sum(p) / 20; dev = math.sqrt(sum((v - mu) ** 2 for v in p) / 20)
            if not dev > 0: continue
            for side in ("LONG", "SHORT"):
                sgn = 1 if side == "LONG" else -1
                for k in LEVELS:
                    for d in DISTS:
                        if side == "LONG":
                            trig = min(mu - k * dev, mu * (1 - d / 100))
                            if lo > trig: continue
                            j = next((q for q in range(i0, i1 + 1) if L[q] <= trig), None)
                        else:
                            trig = max(mu + k * dev, mu * (1 + d / 100))
                            if hi < trig: continue
                            j = next((q for q in range(i0, i1 + 1) if H[q] >= trig), None)
                        if j is None: continue
                        for bnc in BOUNCES:
                            if bnc:
                                ext, e = (L[j] if side == "LONG" else H[j]), None
                                for q in range(j, min(eod, j + 60)):
                                    ext = min(ext, L[q]) if side == "LONG" else max(ext, H[q])
                                    if (side == "LONG" and C[q] >= ext * (1 + bnc / 100)) or (side == "SHORT" and C[q] <= ext * (1 - bnc / 100)):
                                        e = q; break
                                if e is None: continue
                                ei, ep, s = e, C[e], e + 1
                            else:
                                ei, ep, s = j, trig, j
                            if ei >= eod: continue
                            tp_t = {n: None for n in NETS}; adv_t = {h: None for h in HEDGES}
                            for q in range(s, eod + 1):
                                fav = (C[q] if q == j and s == j else (H[q] if side == "LONG" else L[q]))
                                g = sgn * (fav - ep) / ep * 100
                                a = sgn * (ep - (L[q] if side == "LONG" else H[q])) / ep * 100
                                for h in HEDGES:
                                    if adv_t[h] is None and a >= h: adv_t[h] = q
                                for n in NETS:
                                    if tp_t[n] is None and g >= n + rt: tp_t[n] = q
                                if tp_t[NETS[-1]] is not None: break
                            def mtm(q):
                                return sgn * (C[q] - ep) / ep * 100 - rt
                            for n in NETS:
                                tpq = tp_t[n]
                                for rule in RULES:
                                    if rule in ("H1", "H2", "H3"):
                                        h = int(rule[1]); aq = adv_t[h]
                                        if tpq is not None and (aq is None or tpq < aq): res = (n, tpq, 1)
                                        elif aq is not None: res = (-h - 2 * rt, eod, 0)
                                        else: res = (mtm(eod), eod, 0)
                                    elif rule in ("T15", "T60"):
                                        lim = min(eod, ei + int(rule[1:]))
                                        res = (n, tpq, 1) if tpq is not None and tpq <= lim else (mtm(lim), lim, 0)
                                    elif rule == "H2T60":
                                        lim = min(eod, ei + 60); aq = adv_t[2]
                                        if tpq is not None and tpq <= lim and (aq is None or tpq < aq): res = (n, tpq, 1)
                                        elif aq is not None and aq < lim: res = (-2 - 2 * rt, eod, 0)
                                        else: res = (mtm(lim), lim, 0)
                                    else:
                                        res = (n, tpq, 1) if tpq is not None else (mtm(eod), eod, 0)
                                    key = f"{side}|{tf}|{k}|{d}|{bnc}|{n}|{rule}"
                                    out.setdefault(key, []).append((T[ei], T[res[1]], res[0], res[2], day))
    final = {}
    for key, lst in out.items():
        lst.sort(); busy = 0; keep = []
        for t_in, t_out, pnl, win, day in lst:
            if t_in < busy: continue
            keep.append((t_in, t_out, round(pnl, 4), win, day)); busy = t_out + 60000
        final[key] = keep
    return sym, final
if __name__ == "__main__":
    symbols = open(sys.argv[1]).read().split()
    agg = {}
    with Pool(4) as pool:
        for sym, res in pool.imap_unordered(work, symbols):
            if not res: continue
            for key, lst in res.items():
                a = agg.setdefault(key, {"days": {str(d): [0, 0, 0.0, 0] for d in DAYS}, "diff": {}})
                for t_in, t_out, pnl, win, day in lst:
                    dd = a["days"][str(day)]
                    dd[0] += 1; dd[1] += win; dd[2] += pnl; dd[3] += (t_out >= day + 15 * 3600000 - 60000)
                    a["diff"][t_in] = a["diff"].get(t_in, 0) + 1
                    a["diff"][t_out + 60000] = a["diff"].get(t_out + 60000, 0) - 1
    out = {}
    for key, a in agg.items():
        cur = mx = 0
        for t in sorted(a["diff"]):
            cur += a["diff"][t]; mx = max(mx, cur)
        out[key] = {"days": a["days"], "maxOpen": mx}
    json.dump({"days": DAYS, "results": out}, open(sys.argv[2], "w"))
    print("ok", len(out))
