"""Publieke simulatie (geen sleutels, geen orders) van Amars hele systeem op Aster-1m-data.
Modes: fetch OUT.npz | sim DATA.npz SHARD NSHARDS OUT.json | report DIR OUT.json
Model (LONG-instappen): Spike-instap (tf/niveau/min-afstand/opveer) 08-23 u Amsterdam, positie $P;
Spike-TP (netto na fees) zolang niet gehedged; hedge 1:1 bij verlies H % van de positie;
hedge afbouwen (SHORT-ladder vanaf hedgekoers, totaal T % in S stappen, alleen met winst na fees,
na laatste stap automatisch weer 1:1); samen sluiten als LONG op TP-koers staat en open benen netto groen zijn;
portfolio-TP: alles dicht als equity sinds vorige reset >= X % van basis $325; niets anders wordt gesloten."""
import json, math, os, sys, time, urllib.request, itertools
import numpy as np
np.seterr(all="ignore")
BASE = "https://fapi.asterdex.com"
T0 = 1790035200000 - 6 * 3600000          # 2026-09-22 00:00 UTC min 6 u referentie
T_END = 1792702800000                     # 2026-10-22 21:00 UTC
P = 20.0; BASE_EQ = 325.0; MAX_OPEN = 40
def get(sym, s, e):
    for a in range(6):
        try:
            with urllib.request.urlopen(f"{BASE}/fapi/v1/klines?symbol={sym}&interval=1m&startTime={s}&endTime={e}&limit=1500", timeout=30) as r:
                return json.loads(r.read())
        except Exception:
            time.sleep(2 + 3 * a)
    return []
def fetch(out):
    syms = open("tools/probe/tradable.txt").read().split()
    low = set(open("tools/probe/low_fee.txt").read().split())
    t0 = T0 // 900000 * 900000
    N = (T_END - t0) // 60000
    H = np.full((len(syms), N), np.nan, np.float32); L = H.copy(); C = H.copy()
    for si, sym in enumerate(syms):
        t = t0
        while t < T_END:
            part = get(sym, t, T_END)
            if not part: break
            for x in part:
                i = (int(x[0]) - t0) // 60000
                if 0 <= i < N: H[si, i] = float(x[2]); L[si, i] = float(x[3]); C[si, i] = float(x[4])
            t = int(part[-1][0]) + 60000
            time.sleep(0.12)
            if len(part) < 1500: break
    # gaten opvullen: close vooruit, high/low = close
    for si in range(len(syms)):
        c = C[si]; last = np.nan
        for i in range(N):
            if np.isnan(c[i]): c[i] = last
            else: last = c[i]
        m = np.isnan(H[si]); H[si][m] = c[m]; L[si][m] = c[m]
    fee = np.array([0.0125 if s in low else 0.04 for s in syms], np.float32) / 100
    np.savez_compressed(out, H=H, L=L, C=C, fee=fee, t0=np.int64(t0), syms=np.array(syms))
    print("fetched", len(syms), N)

TFS = {"1m": 1, "5m": 5, "15m": 15}
SIGNALS = [(tf, k, 0, b) for tf in TFS for k in (2, 6) for b in (0.0, 0.3)]
def signals(H, L, C, t0, sig):
    """Lijst per minuut: {minuut: [(sym, prijs)]} voor LONG-instappen."""
    tf, k, d, b = sig; mult = TFS[tf]; S, N = C.shape
    nb = N // mult
    Ct = C[:, :nb * mult].reshape(S, nb, mult)[:, :, -1]
    Lt = L[:, :nb * mult].reshape(S, nb, mult)
    out = {}
    cs = np.cumsum(np.concatenate([np.zeros((S, 1)), Ct], 1), 1)
    cs2 = np.cumsum(np.concatenate([np.zeros((S, 1)), Ct.astype(np.float64) ** 2], 1), 1)
    for bi in range(20, nb):
        mu = (cs[:, bi] - cs[:, bi - 20]) / 20
        var = np.maximum((cs2[:, bi] - cs2[:, bi - 20]) / 20 - mu ** 2, 0)
        dev = np.sqrt(var)
        trig = np.minimum(mu - k * dev, mu * (1 - d / 100))
        hit = np.where((dev > 0) & (Lt[:, bi, :].min(1) <= trig))[0]
        for s in hit:
            j0 = bi * mult
            jj = j0 + int(np.argmax(L[s, j0:j0 + mult] <= trig[s]))
            minute_utc = (t0 // 60000 + jj) % 1440
            if not (360 <= minute_utc < 1260): continue   # 08:00-23:00 Amsterdam (zomertijd)
            if b:
                lo = L[s, jj:jj + 60]; cl = C[s, jj:jj + 60]
                run = np.minimum.accumulate(lo)
                ok = np.where(cl >= run * (1 + b / 100))[0]
                if len(ok) == 0: continue
                e = jj + int(ok[0]); price = float(C[s, e])
            else:
                e = jj; price = float(trig[s])
            out.setdefault(e, []).append((int(s), price))
    return out

def simulate(H, L, C, fee, t0, sig_events, tp_net, hpct, ladder, ptp, dca=0.0, max_hedged=MAX_OPEN):
    """lq/le = LONG-hoeveelheid (1 = $P) en gemiddelde instap; DCA koopt dca x basis op elke afbouwstap."""
    N, S = C.shape
    pos = np.zeros(S, bool); hed = np.zeros(S, bool)
    lq = np.zeros(S); le = np.ones(S); sq = np.zeros(S); sa = np.ones(S); anc = np.zeros(S)
    kk = np.zeros(S, int); cyc = np.zeros(S); dk = np.zeros(S, int)
    tpp = np.zeros(S); hp = np.zeros(S)
    realized = 0.0; base_line = 0.0
    T, Sst = ladder if ladder else (0, 0)
    rate = fee.astype(np.float64)
    tp_g = tp_net / 100 + 2 * rate
    eq_day = []; ptp_hits = 0; trades = 0; wins = 0; hedges = 0; dcas = 0
    def unreal(c):
        u = np.where(pos, P * lq * ((c - le) / le - rate), 0)
        u += np.where(pos & hed, P * sq * ((sa - c) / sa - rate), 0)
        return float(u.sum())
    for m in range(N):
        h = H[m].astype(np.float64); l = L[m].astype(np.float64); c = C[m].astype(np.float64)
        uh = pos & ~hed
        if uh.any():
            hit_h = uh & (l <= hp)
            if hit_h.any():
                hed |= hit_h; sq[hit_h] = lq[hit_h]; sa[hit_h] = hp[hit_h]; anc[hit_h] = hp[hit_h]
                kk[hit_h] = 0; cyc[hit_h] = lq[hit_h]; dk[hit_h] = 0
                realized -= float((P * lq * rate)[hit_h].sum()); hedges += int(hit_h.sum())
            hit_t = uh & ~hit_h & (h >= tpp)
            if hit_t.any():
                realized += float((P * lq * ((tpp - le) / le - rate))[hit_t].sum())
                pos[hit_t] = False; wins += int(hit_t.sum())
        hd = pos & hed
        if hd.any() and Sst:
            lvl = anc * (1 - T / 100 * (kk + 1) / Sst)
            prof = (sa - lvl) / sa - 2 * rate > 0
            step = hd & (sq > 1e-9) & (l <= lvl) & prof
            if step.any():
                q = np.minimum(sq, cyc / Sst)
                realized += float((P * q * ((sa - lvl) / sa - rate))[step].sum())
                sq[step] -= q[step]; kk[step] += 1
                if dca:
                    buy = step & (dk < Sst)
                    if buy.any():
                        le[buy] = (le[buy] * lq[buy] + lvl[buy] * dca) / (lq[buy] + dca); lq[buy] += dca; dk[buy] += 1
                        realized -= float((P * dca * rate)[buy].sum()); dcas += int(buy.sum())
                        tpp[buy] = le[buy] * (1 + tp_g[buy])
                done = step & (kk >= Sst)
                if done.any():
                    add = lq[done] - sq[done]
                    sa[done] = np.where(sq[done] > 1e-9, (sa[done] * sq[done] + c[done] * add) / lq[done], c[done])
                    sq[done] = lq[done]; anc[done] = c[done]; kk[done] = 0; cyc[done] = lq[done]
                    realized -= float((P * add * rate[done]).sum())
        if hd.any():
            at = hd & (h >= tpp)
            if at.any():
                net = P * lq * (tpp - le) / le + P * sq * (sa - tpp) / sa - P * rate * (lq + sq)
                cl = at & (net > 0)
                if cl.any():
                    realized += float(net[cl].sum()); pos[cl] = False; hed[cl] = False; sq[cl] = 0; wins += int(cl.sum())
        if ptp:
            eq = realized + (unreal(c) if pos.any() else 0.0)
            if eq - base_line >= ptp / 100 * BASE_EQ:
                realized = eq; base_line = eq; pos[:] = False; hed[:] = False; sq[:] = 0; ptp_hits += 1
        ev = sig_events.get(m)
        if ev:
            for s_, price in ev:
                if pos[s_] or pos.sum() >= MAX_OPEN or (pos & hed).sum() >= max_hedged: continue
                pos[s_] = True; hed[s_] = False; sq[s_] = 0; lq[s_] = 1.0; le[s_] = price
                tpp[s_] = price * (1 + tp_g[s_]); hp[s_] = price * (1 - hpct / 100)
                realized -= P * rate[s_]; trades += 1
        if (t0 // 60000 + m) % 1440 == 1259:
            eq_day.append(round(realized + unreal(c), 3))
    return {"eq": eq_day, "trades": trades, "wins": wins, "hedges": hedges, "dcas": dcas, "ptp": ptp_hits,
            "openEnd": int(pos.sum()), "hedgedEnd": int((pos & hed).sum())}

TPS = [0.5, 1.0]; HS = [1, 2]; LADDERS = [(6, 3), (20, 4)]; PTPS = [1, 2, 0]; DCAS = [0.0, 0.2, 0.5]; MAXH = [10, 40]
G = {}
def _run(params):
    tp, hpct, lad, ptp, dca, mh = params
    return params, simulate(G["H"], G["L"], G["C"], G["fee"], G["t0"], G["ev"], tp, hpct, lad, ptp, dca, mh)
def sim_shard(data, shard, nsh, out):
    from multiprocessing import get_context
    z = np.load(data)
    H, L, C, fee, t0 = z["H"], z["L"], z["C"], z["fee"], int(z["t0"])
    G.update(H=np.ascontiguousarray(H.T), L=np.ascontiguousarray(L.T), C=np.ascontiguousarray(C.T), fee=fee, t0=t0)
    res = {}
    for i, sig in enumerate(SIGNALS):
        if i % nsh != shard: continue
        G["ev"] = signals(H, L, C, t0, sig)
        with get_context("fork").Pool(4) as pool:
            for params, r in pool.imap_unordered(_run, list(itertools.product(TPS, HS, LADDERS, PTPS, DCAS, MAXH))):
                tp, hpct, lad, ptp, dca, mh = params
                res[f"{sig[0]}|{sig[1]}|{sig[2]}|{sig[3]}|{tp}|{hpct}|{lad}|{ptp}|{dca}|{mh}"] = r
        print("done", sig, flush=True)
    json.dump(res, open(out, "w"))

def report(d, out):
    allr = {}
    for f in os.listdir(d):
        if f.endswith(".json"): allr.update(json.load(open(os.path.join(d, f))))
    rows = {}
    for k, r in allr.items():
        eq = [0.0] + r["eq"]
        daily = [round(eq[i + 1] - eq[i], 3) for i in range(len(eq) - 1)]
        def seg(a, b):
            ds = daily[a:b]; cur = peak = dd = 0.0
            for v in ds:
                cur += v; peak = max(peak, cur); dd = min(dd, cur - peak)
            return {"tot": round(sum(ds), 2), "green": sum(1 for v in ds if v > 0), "days": len(ds),
                    "worst": round(min(ds), 2) if ds else 0, "maxDD": round(dd, 2)}
        rows[k] = {"train": seg(0, 16), "test": seg(16, len(daily)), "all": seg(0, len(daily)),
                   "trades": r["trades"], "wins": r["wins"], "hedges": r["hedges"], "dcas": r.get("dcas", 0), "ptp": r["ptp"],
                   "openEnd": r["openEnd"], "hedgedEnd": r["hedgedEnd"], "daily": daily}
    json.dump(rows, open(out, "w"))
    print("rows", len(rows))

if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "fetch": fetch(sys.argv[2])
    elif mode == "sim": sim_shard(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5])
    elif mode == "report": report(sys.argv[2], sys.argv[3])
