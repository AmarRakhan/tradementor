// Build 651 (Amar 24-10): live voorbeeld + advies voor hedge afbouwen. Pure rekenfuncties, dezelfde regels als de
// server (short_recovery_runtime._grid): delen per verdeling, klein eerst verkopen, klein eerst terugzetten (B),
// terughedgen X%, noodrem, Aster-minimum. Alleen voor uitleg: de server beslist over echte orders.

export const ASTER_MIN_NOTIONAL = 5;

export function partWeights(n, dist = "EQUAL") {
  const k = Math.max(1, Math.floor(Number(n) || 1));
  return Array.from({ length: k }, (_, i) => (dist === "ASCENDING" ? i + 1 : dist === "STEEP" ? 2 ** i : 1));
}

/** Largest number of parts (<= steps) whose smallest part is still >= the Aster minimum at the bottom price. */
export function fitParts({ hedgeUsd, steps, totalPct, distribution = "EQUAL", minNotional = ASTER_MIN_NOTIONAL }) {
  const bottom = Math.max(0, 1 - Number(totalPct) / 100);
  for (let k = Math.max(1, Math.floor(steps)); k >= 1; k -= 1) {
    const w = partWeights(k, distribution);
    const smallest = (hedgeUsd * w[0]) / w.reduce((a, b) => a + b, 0);
    if (smallest * bottom >= minNotional - 1e-9) return k;
  }
  return 0;
}

/** Stake (inleg) needed so that ``parts`` parts fit, rounded up to 10 cents. */
export function stakeForParts({ parts, totalPct, distribution = "EQUAL", leverage, maxHedgePct = 100, minNotional = ASTER_MIN_NOTIONAL }) {
  const w = partWeights(parts, distribution);
  const share = w[0] / w.reduce((a, b) => a + b, 0);
  const bottom = Math.max(0.01, 1 - Number(totalPct) / 100);
  const hedgeUsd = minNotional / share / bottom;
  const stake = hedgeUsd / (Math.max(1, maxHedgePct) / 100) / Math.max(1, leverage);
  return Math.ceil(stake * 10 - 1e-9) / 10;
}

/** Tab "Inleg voor mijn instellingen". */
export function adviseStake({ steps, totalPct, distribution, leverage, maxHedgePct = 100, stake }) {
  const rows = [];
  for (let k = 1; k <= steps; k += 1) rows.push({ parts: k, stake: stakeForParts({ parts: k, totalPct, distribution, leverage, maxHedgePct }) });
  const recommended = rows[rows.length - 1].stake;
  const hedgeUsd = Number(stake) > 0 ? Number(stake) * leverage * (maxHedgePct / 100) : null;
  const current = hedgeUsd == null ? null : fitParts({ hedgeUsd, steps, totalPct, distribution });
  const equalAll = stakeForParts({ parts: steps, totalPct, distribution: "EQUAL", leverage, maxHedgePct });
  return { recommended, rows, current, equalAll };
}

/** Tab "Instellingen voor mijn inleg": one advice per goal (SAFE / BALANCE / PROFIT). */
export function adviseSettings({ stake, leverage, maxHedgePct = 100, totalPct = 10, goal = "BALANCE" }) {
  const total = Math.min(30, Math.max(2, Number(totalPct) || 10));
  const hedgeUsd = Math.max(0, Number(stake)) * Math.max(1, leverage) * (maxHedgePct / 100);
  const equal = fitParts({ hedgeUsd, steps: 5, totalPct: total, distribution: "EQUAL" });
  const asc = fitParts({ hedgeUsd, steps: 5, totalPct: total, distribution: "ASCENDING" });
  if (equal === 0) return { ok: false, hedgeUsd, reason: "Positie te klein voor het Aster-minimum: afbouwen kan niet, de hedge blijft 1:1." };
  let s;
  if (goal === "SAFE") s = { steps: equal, distribution: "EQUAL", rebuySteps: 1, rehedgePct: 100 };
  else if (goal === "PROFIT" && asc >= 2) s = { steps: asc, distribution: "ASCENDING", rebuySteps: Math.min(2, asc), rehedgePct: 75 };
  else s = { steps: equal, distribution: "EQUAL", rebuySteps: Math.min(2, equal), rehedgePct: 75 };
  const safety = Math.round(total * 0.6 * 10) / 10;
  const settings = { ...s, totalPct: total, safetyNetPct: safety };
  const w = partWeights(settings.steps, settings.distribution);
  const W = w.reduce((a, b) => a + b, 0);
  const smallestUsd = (hedgeUsd * w[0]) / W;
  const backUsd = (smallestUsd * settings.rehedgePct) / 100;
  return { ok: true, hedgeUsd, settings, smallestUsd, backUsd, backFits: backUsd >= ASTER_MIN_NOTIONAL - 1e-9 };
}

function levelPrice(anchor, k, n, total, up) {
  const move = (total * k) / n / 100;
  return up ? anchor * (1 + move) : anchor * (1 - move);
}

/** Price path per scenario, in steps of one level, as moves relative to 100 (DOWN = protected LONG). */
export function scenarioPath(scenario, { steps, totalPct, rebuySteps, safetyNetPct }) {
  const step = Number(totalPct) / Math.max(1, steps);
  const path = [0];
  const go = (to) => { const last = path[path.length - 1]; const dir = to > last ? 1 : -1; for (let v = last + dir * step; dir > 0 ? v <= to + 1e-9 : v >= to - 1e-9; v += dir * step) path.push(+v.toFixed(6)); };
  if (scenario === "FALL") { go(-Number(totalPct)); go(-Number(totalPct) - Number(safetyNetPct) - 2 * step); }
  else if (scenario === "CHOP") { for (let i = 0; i < 3; i += 1) { go(-2 * step); go(-step); go(-3 * step); go(-step); } }
  else { go(-Number(totalPct)); go(step * Math.max(1, rebuySteps)); go(step * (Math.max(1, rebuySteps) + 1)); }
  return path;
}

/** Simulate one scenario with LONG 10 at 100 (or the mirror for a protected SHORT). */
export function simulate(settings, scenario = "RECOVER", { maxHedgePct = 100, side = "SHORT" } = {}) {
  const up = side === "LONG";                       // LONG-hedge of a SHORT position: price rises
  const n = Math.max(1, Math.floor(settings.steps));
  const total = Number(settings.totalPct);
  const g = Math.max(0, Math.floor(settings.rebuySteps ?? 1));
  const pct = (settings.rehedgePct ?? 100) / 100;
  const safety = Number(settings.safetyNetPct ?? total);
  const dist = settings.distribution || "EQUAL";
  const w = partWeights(n, dist);
  const W = w.reduce((a, b) => a + b, 0);
  const longQty = 10;
  const maxFrac = Math.max(0.01, maxHedgePct / 100);
  let anchor = 100;
  let base = longQty * maxFrac;
  let sold = [];
  let kept = 0;
  let done = false;
  let shortQty = base;
  let shortCost = base * anchor;                    // avg entry * qty of the hedge
  let realized = 0;
  const released = (set) => (set.length >= n ? base : (base * set.reduce((a, i) => a + w[i - 1], 0)) / W);
  const sign = up ? -1 : 1;                         // hedge profit sign per price drop
  const points = [];
  let noodrem = null;
  for (const move of scenarioPath(scenario, settings)) {
    const price = up ? 100 - move : 100 + move;     // FALL for a SHORT position means the price RISES
    const events = [];
    const lvl = (k) => levelPrice(anchor, k, n, total, up);
    const away = (p, l) => (up ? p >= l - 1e-9 : p <= l + 1e-9);
    if (!done) {
      let count = sold.length;
      while (count < n && away(price, lvl(count + 1))) count += 1;
      if (count > sold.length) {
        const unsold = Array.from({ length: n }, (_, i) => i + 1).filter((i) => !sold.includes(i));
        sold = [...sold, ...unsold.slice(0, count - sold.length)].sort((a, b) => a - b);
      } else if (g > 0) {
        while (count > 0 && (up ? price <= lvl(count - g) + 1e-9 : price >= lvl(count - g) - 1e-9)) count -= 1;
        if (count < sold.length) {
          const before = released(sold);
          sold = sold.slice(sold.length - count);
          const restored = before - released(sold);
          kept += pct > 0 ? restored * (1 - pct) : restored;
        }
      }
      if (sold.length >= n && pct === 0) done = true;
      const last = lvl(n);
      const net = up ? last * (1 + safety / 100) : last * (1 - safety / 100);
      if (!done && sold.length >= n && pct > 0 && away(price, net)) {
        noodrem = noodrem ?? price;
        const refill = longQty * maxFrac * pct;
        events.push({ type: "NOODREM", qty: refill - shortQty });
        shortCost += (refill - shortQty) * price; shortQty = refill;
        anchor = price; base = refill; sold = []; kept = 0;
        points.push({ move, price, shortQty, net: longQty - shortQty, events });
        continue;
      }
    }
    const target = Math.max(0, base - kept - released(sold));
    const delta = target - shortQty;
    if (delta < -1e-9) {
      const avg = shortQty > 0 ? shortCost / shortQty : price;
      realized += sign * (avg - price) * -delta;
      shortCost -= avg * -delta;
      events.push({ type: "SELL", qty: -delta });
    } else if (delta > 1e-9) {
      shortCost += delta * price;
      events.push({ type: "REBUY", qty: delta });
    }
    shortQty = target;
    points.push({ move, price, shortQty, net: longQty - shortQty, events });
  }
  const end = points[points.length - 1].price;
  const avg = shortQty > 0 ? shortCost / shortQty : end;
  const hedgeOpen = sign * (avg - end) * shortQty;
  const longPnl = (up ? 100 - end : end - 100) * longQty;
  const result = realized + hedgeOpen + longPnl;
  const fixed = (up ? 100 - end : end - 100) * longQty * (1 - maxFrac);   // plain hedge at the same max %
  const maxNet = Math.max(...points.map((p) => p.net));
  const atMax = points.filter((p) => Math.abs(p.net - maxNet) < 1e-9).map((p) => p.price);
  return { points, result, fixed, maxNet, maxNetFrom: Math.min(...atMax), maxNetTo: Math.max(...atMax), noodrem,
           noodremAt: (up ? levelPrice(100, n, n, total, true) * (1 + safety / 100) : levelPrice(100, n, n, total, false) * (1 - safety / 100)) };
}
