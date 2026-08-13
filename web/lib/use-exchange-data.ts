"use client";

import { useCallback, useEffect, useState } from "react";
import { authenticatedRequest } from "./cloud-client";
import { demoModeEnabled, demoSnapshot } from "./demo-data";

export type ExchangeId = "hyperliquid" | "aster";
export type ExchangeSnapshot = { loading: boolean; data: Record<string, unknown> | null; error: string; updatedAt: number | null };
export type ExchangeSnapshots = Record<ExchangeId, ExchangeSnapshot>;

const emptySnapshot = (): ExchangeSnapshot => ({ loading: false, data: null, error: "", updatedAt: null });

export function useExchangeData(cloudReady: boolean) {
  const [snapshots, setSnapshots] = useState<ExchangeSnapshots>({ hyperliquid: emptySnapshot(), aster: emptySnapshot() });

  const refresh = useCallback(async (exchange: ExchangeId) => {
    if (demoModeEnabled()) {
      setSnapshots((current) => ({ ...current, [exchange]: demoSnapshot(exchange) }));
      return;
    }
    setSnapshots((current) => ({ ...current, [exchange]: { ...current[exchange], loading: true, error: "" } }));
    try {
      const data = exchange === "hyperliquid"
          ? await Promise.all([
            authenticatedRequest("/api/exchanges/hyperliquid"),
            authenticatedRequest("/api/execution/status"),
            authenticatedRequest("/api/exchanges/hyperliquid/dca-deals"),
            authenticatedRequest("/api/exchanges/hyperliquid/closed-trades"),
          ]).then(([account, execution, dca, closed]) => ({ ...account, ...execution, ...dca, ...closed }))
        : await authenticatedRequest(`/api/exchanges/${exchange}`).then(async (account) => {
            try {
              const closed = await authenticatedRequest(`/api/exchanges/${exchange}/closed-trades`);
              return { ...account, ...closed };
            } catch {
              return account;
            }
          });
      setSnapshots((current) => ({ ...current, [exchange]: { loading: false, data, error: "", updatedAt: Date.now() } }));
    } catch (reason) {
      setSnapshots((current) => ({ ...current, [exchange]: { ...current[exchange], loading: false, error: reason instanceof Error ? reason.message : "Exchangegegevens zijn niet beschikbaar." } }));
    }
  }, []);

  const refreshAll = useCallback(() => Promise.allSettled((["hyperliquid", "aster"] as ExchangeId[]).map(refresh)), [refresh]);

  useEffect(() => {
    if (!cloudReady) return;
    refreshAll();
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") refreshAll();
    // Account/history endpoints are snapshots, not ticker streams. Market
    // prices use WebSockets elsewhere; polling these signed endpoints every
    // 15 seconds can exhaust Aster's shared-IP request quota.
    }, 60_000);
    const visible = () => { if (document.visibilityState === "visible") refreshAll(); };
    document.addEventListener("visibilitychange", visible);
    return () => { window.clearInterval(interval); document.removeEventListener("visibilitychange", visible); };
  }, [cloudReady, refreshAll]);

  return { snapshots, refresh, refreshAll };
}
