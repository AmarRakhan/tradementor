"use client";
import { useEffect } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import { firebaseAuth } from "@/lib/firebase";
import { BACKGROUND_SYNC_INTERVAL_MS } from "@/lib/trade-journal.mjs";

/**
 * Build 648: while the app is open and visible, run one read-only trade-journal step every 10 minutes, so new
 * closes, their bot context (seat/zone, spike entry) and Auto Hedge state are recorded close to when they happen.
 * One bounded step per interval; failures are silent (the Trade Historie card and the download catch up anyway).
 */
export function useTradeJournalBackgroundSync() {
  useEffect(() => {
    if (typeof window === "undefined") return;
    let stopped = false;
    const step = async () => {
      if (stopped || document.visibilityState !== "visible" || !firebaseAuth.currentUser) return;
      try { await authenticatedRequest("/api/exchanges/aster/trade-journal/sync", { method: "POST", body: "{}", cache: "no-store" }); }
      catch { /* busy, too soon, demo mode or offline: next interval */ }
    };
    const first = window.setTimeout(step, 20_000);
    const timer = window.setInterval(step, BACKGROUND_SYNC_INTERVAL_MS);
    return () => { stopped = true; window.clearTimeout(first); window.clearInterval(timer); };
  }, []);
}
