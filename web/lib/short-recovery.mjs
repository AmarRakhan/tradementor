// SHORT Recovery 2.0 — display helpers only (no orders, no exchange logic).

// Amar 18:02: the user chooses the TOTAL move and the number of steps; distance per step = total / steps.
// Build 623: the same for both sides. hedgeSide "SHORT" = SHORT-hedge of a LONG, reduced on a falling price;
// hedgeSide "LONG" = LONG-hedge of a SHORT, reduced on a rising price.
export function validateRecoverySettings(stepsRaw, totalPctRaw, hedgeSide = "SHORT") {
  const word = hedgeSide === "LONG" ? "Totale stijging" : "Totale daling";
  const steps = Number(stepsRaw);
  const totalPct = Number(String(totalPctRaw).replace(",", "."));
  if (!Number.isInteger(steps) || steps < 1 || steps > 100) return { ok: false, message: "Aantal stappen: geheel getal van 1 t/m 100." };
  if (!Number.isFinite(totalPct) || totalPct <= 0) return { ok: false, message: `${word} moet groter dan 0% zijn.` };
  if (totalPct >= 100) return { ok: false, message: `${word} moet onder 100% blijven.` };
  return { ok: true, steps, totalPct, stepPct: totalPct / steps, sellPct: 100 / steps };
}

export function recoveryLadder(stepsRaw, totalPctRaw, anchor = 100, hedgeSide = "SHORT") {
  const v = validateRecoverySettings(stepsRaw, totalPctRaw, hedgeSide);
  if (!v.ok) return [];
  const sign = hedgeSide === "LONG" ? 1 : -1;
  return Array.from({ length: v.steps }, (_, i) => {
    const k = i + 1;
    const drop = (v.totalPct * k) / v.steps;
    return {
      step: k,
      dropPct: Number(drop.toFixed(6)),
      price: Number((anchor * (1 + (sign * drop) / 100)).toFixed(8)),
      remainingPct: Number((((v.steps - k) / v.steps) * 100).toFixed(4)),
    };
  });
}

const EVENT_LABELS = {
  CYCLE_STARTED: "Cyclus gestart",
  CYCLE_STARTED_AFTER_REOPEN: "Nieuwe cyclus op 90%",
  STEP_REDUCE: "Afbouwstap",
  LADDER_HOLD: "Wacht op volgende stap",
  LADDER_DONE_REFILL_1_TO_1: "Leeg · opnieuw 100% hedgen",
  STEP_TOO_SMALL_CLOSE_ALL: "Stap te klein · alles sluiten",
  CLOSING_ALL: "Alles sluiten",
  CLOSED_ALL_REOPEN_90: "90% terugzetten",
  REOPENING_90: "90% terugzetten",
  SKIPPED_BELOW_MINIMUM: "Overgeslagen (te klein voor Aster)",
  REOPEN_MARGIN_UNPROVEN_SKIP: "Overgeslagen (marge)",
  WAIT_FOR_1_TO_1: "Wacht op 1:1 hedge",
  PENDING_ORDER_HOLD: "Order loopt nog",
  JOINT_EXIT_NET_POSITIVE_CLOSING_SHORT: "TP netto plus · SHORT sluiten",
  JOINT_EXIT_CLOSING_SHORT: "TP netto plus · SHORT sluiten",
  JOINT_EXIT_SHORT_FLAT_WAIT_LONG_TP: "SHORT dicht · LONG-TP volgt",
  JOINT_EXIT_EXPIRED_REHEDGE: "TP verlopen · opnieuw hedgen",
  JOINT_EXIT_NET_POSITIVE_CLOSING_HEDGE: "TP netto plus · hedge sluiten",
  JOINT_EXIT_CLOSING_HEDGE: "TP netto plus · hedge sluiten",
  JOINT_EXIT_HEDGE_FLAT_WAIT_TP: "Hedge dicht · TP volgt",
  STEP_WAIT_PROFIT_AFTER_FEES: "Wacht: stap nog geen winst na fees",
  OVER_COVERED_HOLD: "Andere kant al groter · niets verkocht",
  REHEDGE_ALL: "Re-Hedge All · weer 100%",
  GRID_DONE_NO_REHEDGE: "Afgebouwd · niet opnieuw hedgen",
};

export function recoveryEventLabel(event) {
  return EVENT_LABELS[event] || (event ? String(event) : "–");
}

/** One row per Auto Hedge pair with a live or shadow Recovery record. */
export function recoveryRows(pairs, liveMode) {
  const field = liveMode ? "shortRecovery" : "shortRecoveryShadow";
  return (Array.isArray(pairs) ? pairs : [])
    .filter((p) => p && typeof p[field] === "object" && p[field])
    .map((p) => {
      const r = p[field];
      const steps = Number(r.steps) || 0;
      const reached = Number(r.stepsReached) || 0;
      const long = Number(p.currentProtectedQty) || 0;
      const target = Number(r.lastTarget);
      const hedgePct = long > 0 && Number.isFinite(target) ? Math.round((target / long) * 1000) / 10 : null;
      return {
        symbol: String(p.symbol || ""),
        phase: String(r.phase || ""),
        cycle: Number(r.cycleId) || 0,
        progress: steps ? `${reached}/${steps}` : "–",
        anchor: r.anchor ? Number(r.anchor) : null,
        hedgePct,
        event: recoveryEventLabel(r.lastEvent),
      };
    })
    .sort((a, b) => a.symbol.localeCompare(b.symbol));
}

/** Badge for a pair that SHORT afbouwen has partly unwound (Amar 22:04: "HEDGED 75%" instead of UNWIND).
 *  label  = short text for the narrow Tradecentrum badge, e.g. "HEDGED 75%";
 *  detail = longer text for the pair card, e.g. "HEDGED 75% · stap 1/4 · TEST".
 *  null while the pair is still fully hedged (no step done yet). TEST = test mode (dashed style, no real orders). */
export function unwindBadge(pair) {
  if (!pair || typeof pair !== "object") return null;
  const live = pair.shortRecovery && typeof pair.shortRecovery === "object" ? pair.shortRecovery : null;
  const rec = live || (pair.shortRecoveryShadow && typeof pair.shortRecoveryShadow === "object" ? pair.shortRecoveryShadow : null);
  if (!rec || !rec.phase) return null;
  // Only for a pair that Auto Hedge still holds (not RECOVERY/manual release): a stale record never relabels it.
  const status = String(pair.status || "").toUpperCase();
  if (!["HEDGED", "HEDGING", "ADJUSTING"].includes(status)) return null;
  const phase = String(rec.phase);
  const reached = Number(rec.stepsReached) || 0;
  const steps = Number(rec.steps) || 0;
  const exiting = phase === "PAIR_EXIT" || (pair.pairExit && typeof pair.pairExit === "object");
  const active = reached > 0 || phase === "REOPEN_CLOSE" || phase === "REOPEN_OPEN" || exiting;
  if (!active) return null;
  const long = Number(pair.currentProtectedQty) || 0;
  const target = Number(rec.lastTarget);
  const pct = long > 0 && Number.isFinite(target) ? Math.round(Math.min(100, (target / long) * 100)) : null;
  // Nothing reduced (e.g. step too small for Aster and skipped): keep the plain HEDGED label.
  if (phase === "LADDER" && !exiting && (pct === null || pct >= 100)) return null;
  const label = exiting ? "HEDGED · TP" : pct === null ? "HEDGED" : `HEDGED ${pct}%`;
  const parts = [label];
  if (phase === "LADDER" && steps) parts.push(`stap ${Math.min(reached, steps)}/${steps}`);
  if (phase.startsWith("REOPEN")) parts.push("100% dicht · 90% terug");
  if (!live) parts.push("TEST");
  return { label, detail: parts.join(" · "), cls: live ? "unwind" : "unwind test" };
}
