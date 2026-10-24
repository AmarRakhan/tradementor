"use client";

import { useEffect, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import { firebaseAuth } from "@/lib/firebase";
import { drawdownCaption, formatDrawdown, normalizeDrawdown, type EntryDrawdown } from "@/lib/entry-drawdown.mjs";

// Build 652: gem. max drawdown vanaf instap, per kant. Eén gedeelde lezing voor de Portfolio Snapshot en het
// Auto Hedge-scherm. Elke 60 s zolang de app zichtbaar is; terwijl de server nog rekent elke 15 s.
let shared: { data: EntryDrawdown | null; at: number; promise: Promise<EntryDrawdown> | null } = { data: null, at: 0, promise: null };
const listeners = new Set<(data: EntryDrawdown) => void>();

async function load(): Promise<EntryDrawdown> {
  if (shared.promise) return shared.promise;
  shared.promise = (async () => {
    const data = normalizeDrawdown(await authenticatedRequest("/api/exchanges/aster/entry-drawdown", { cache: "no-store" }));
    shared = { data, at: Date.now(), promise: null };
    listeners.forEach((fn) => fn(data));
    return data;
  })().catch((err) => { shared.promise = null; throw err; });
  return shared.promise;
}

export function useEntryDrawdown(): EntryDrawdown | null {
  const [data, setData] = useState<EntryDrawdown | null>(shared.data);
  useEffect(() => {
    if (typeof window === "undefined") return;
    let stopped = false;
    let timer = 0;
    listeners.add(setData);
    const tick = async () => {
      let next = 60_000;
      if (document.visibilityState === "visible" && firebaseAuth.currentUser) {
        try {
          const fresh = Date.now() - shared.at < 10_000 && shared.data ? shared.data : await load();
          if (!stopped) setData(fresh);
          if (fresh.refreshing || !fresh.complete) next = 15_000;
        } catch { next = 60_000; }
      }
      if (!stopped) timer = window.setTimeout(tick, next);
    };
    timer = window.setTimeout(tick, shared.data ? 1_000 : 300);
    return () => { stopped = true; window.clearTimeout(timer); listeners.delete(setData); };
  }, []);
  return data;
}

export function DrawdownTile({ side, data }: { side: "LONG" | "SHORT"; data: EntryDrawdown | null }) {
  const row = data ? (side === "LONG" ? data.long : data.short) : null;
  const value = formatDrawdown(row?.avgMaxDrawdownPct ?? null);
  return <article className={`aps-market-card aps-drawdown aps-drawdown-${side.toLowerCase()}`}
    aria-label={`${side} max drawdown, gemiddeld vanaf instap: ${value}`} data-drawdown={row?.avgMaxDrawdownPct ?? ""}>
    <span className="aps-market-copy">
      <small><i aria-hidden="true">{side === "LONG" ? "↘" : "↗"}</i>{side} MAX DRAWDOWN</small>
      <strong>{value}</strong>
      <em>{drawdownCaption(row, data?.refreshing ?? true)}</em>
    </span>
  </article>;
}

// Build 652: elke afbouwkaart toont het getal van de kant die hij beschermt.
// SHORT-hedge afbouwen beschermt LONG-posities -> LONG-getal; LONG-hedge afbouwen beschermt SHORT -> SHORT-getal.
export function DrawdownReference({ data, side, lastStepPct }: { data: EntryDrawdown | null; side: "LONG" | "SHORT"; lastStepPct?: number | null }) {
  const row = data ? (side === "LONG" ? data.long : data.short) : null;
  const value = row?.avgMaxDrawdownPct ?? null;
  const deeper = typeof value === "number" && typeof lastStepPct === "number" && Number.isFinite(lastStepPct) && lastStepPct > value;
  return <div className={`plah-dd plah-dd-${side.toLowerCase()}`} aria-label={`${side} gem. max drawdown vanaf instap`}>
    <div><small>{side === "LONG" ? "Long" : "Short"} gem. max drawdown</small><b>{formatDrawdown(value)}</b></div>
    {deeper && <p>Je laatste stap ({formatDrawdown(lastStepPct ?? null)}) ligt dieper: die wordt bij de meeste trades niet gehaald.</p>}
  </div>;
}
