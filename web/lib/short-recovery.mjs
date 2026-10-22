// SHORT Recovery 2.0 — display helpers only (no orders, no exchange logic).

// Amar 18:02: the user chooses the TOTAL drop and the number of steps; distance per step = total / steps.
export function validateRecoverySettings(stepsRaw, totalPctRaw) {
  const steps = Number(stepsRaw);
  const totalPct = Number(String(totalPctRaw).replace(",", "."));
  if (!Number.isInteger(steps) || steps < 1 || steps > 100) return { ok: false, message: "Aantal stappen: geheel getal van 1 t/m 100." };
  if (!Number.isFinite(totalPct) || totalPct <= 0) return { ok: false, message: "Totale daling moet groter dan 0% zijn." };
  if (totalPct >= 100) return { ok: false, message: "Totale daling moet onder 100% blijven." };
  return { ok: true, steps, totalPct, stepPct: totalPct / steps, sellPct: 100 / steps };
}

export function recoveryLadder(stepsRaw, totalPctRaw, anchor = 100) {
  const v = validateRecoverySettings(stepsRaw, totalPctRaw);
  if (!v.ok) return [];
  return Array.from({ length: v.steps }, (_, i) => {
    const k = i + 1;
    const drop = (v.totalPct * k) / v.steps;
    return {
      step: k,
      dropPct: Number(drop.toFixed(6)),
      price: Number((anchor * (1 - drop / 100)).toFixed(8)),
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
