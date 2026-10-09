"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { authenticatedRequest, authenticatedStream } from "./cloud-client";
import { applyAsterRealtimeMark, parseSseChunk } from "./aster-realtime.mjs";
import { withBoundedRetry } from "./bounded-retry.mjs";
import { createLatestAsterRequestGate } from "./aster-strategy2-server-status.mjs";

export type ExchangeId = "hyperliquid" | "aster";
export type ExchangeSnapshot = { loading: boolean; data: Record<string, unknown> | null; error: string; updatedAt: number | null; serverUpdatedAt?: number | null; source: "none" | "server"; serverConfirmed: boolean; timings?: Record<string, number> };
export type ExchangeSnapshots = Record<ExchangeId, ExchangeSnapshot>;

const emptySnapshot = (): ExchangeSnapshot => ({ loading: false, data: null, error: "", updatedAt: null, serverUpdatedAt: null, source: "none", serverConfirmed: false });

const inFlight = new Map<string, Promise<{ data: Record<string, unknown>; timings: Record<string, number> }>>();

async function timedRead(path: string) {
  const started = performance.now();
  let attempts = 0;
  const value = await withBoundedRetry(async () => {
    attempts += 1;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 6_000);
    try { return await authenticatedRequest(path, { cache: "no-store", signal: controller.signal }); }
    finally { window.clearTimeout(timeout); }
  }, { attempts: 2, delays: [350] }) as Record<string, unknown>;
  return { value, durationMs: Math.round(performance.now() - started), attempts };
}

function fetchAsterSnapshot(uid: string, _generation: number) {
  const key = `${uid}:aster`;
  const current = inFlight.get(key);
  if (current) return current;
  const started = performance.now();
  const request = timedRead("/api/exchanges/aster").then((account) => ({
    data: account.value as Record<string, unknown>,
    timings: {
      statusMs: account.durationMs,
      statusAttempts: account.attempts,
      totalMs: Math.round(performance.now() - started),
    },
  })).finally(() => inFlight.delete(key));
  inFlight.set(key, request);
  return request;
}

export function useExchangeData(cloudReady: boolean, uid: string) {
  const [state, setState] = useState<{ uid: string; snapshots: ExchangeSnapshots }>(() => ({ uid, snapshots: { hyperliquid: emptySnapshot(), aster: emptySnapshot() } }));
  const mounted = useRef(true);
  const refreshAllInFlight = useRef<Promise<PromiseSettledResult<void>[]> | null>(null);
  const realtimeBatch = useRef<Map<string, Record<string, unknown>>>(new Map());
  const realtimeBatchTimer = useRef<number | null>(null);
  const asterRequestGate = useRef({ uid, gate: createLatestAsterRequestGate() });

  const currentAsterRequestGate = useCallback(() => {
    if (asterRequestGate.current.uid !== uid) {
      asterRequestGate.current = { uid, gate: createLatestAsterRequestGate() };
    }
    return asterRequestGate.current.gate;
  }, [uid]);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  useEffect(() => {
    if (state.uid === uid) return;
    asterRequestGate.current = { uid, gate: createLatestAsterRequestGate() };
    setState({ uid, snapshots: { hyperliquid: emptySnapshot(), aster: emptySnapshot() } });
  }, [state.uid, uid]);

  const snapshots = useMemo(() => state.uid === uid ? state.snapshots : { hyperliquid: emptySnapshot(), aster: emptySnapshot() }, [state, uid]);

  const refresh = useCallback(async (exchange: ExchangeId) => {
    if (!uid) return;
    const gate = exchange === "aster" ? currentAsterRequestGate() : null;
    const requestToken = gate?.begin();
    setState((current) => current.uid !== uid ? current : ({ ...current, snapshots: { ...current.snapshots, [exchange]: { ...current.snapshots[exchange], loading: true, error: "" } } }));
    try {
      const data = exchange === "hyperliquid"
          ? await Promise.all([
            authenticatedRequest("/api/exchanges/hyperliquid"),
            authenticatedRequest("/api/execution/status"),
            authenticatedRequest("/api/exchanges/hyperliquid/dca-deals"),
            authenticatedRequest("/api/exchanges/hyperliquid/closed-trades"),
          ]).then(([account, execution, dca, closed]) => ({ ...account, ...execution, ...dca, ...closed }))
        : await fetchAsterSnapshot(uid, requestToken?.generation ?? 0);
      if (!mounted.current) return;
      if (exchange === "aster" && !gate?.accepts(requestToken)) return;
      const updatedAt = Date.now();
      const payload = exchange === "aster" ? data.data : data;
      const timings = exchange === "aster" ? data.timings : undefined;
      setState((current) => {
        if (current.uid !== uid) return current;
        if (exchange === "aster") console.info("[TradeMentor Aster timing]", timings);
        return { ...current, snapshots: { ...current.snapshots, [exchange]: {
          loading: false, data: payload, error: "", updatedAt, serverUpdatedAt: updatedAt, source: "server", serverConfirmed: true, ...(timings ? { timings } : {})
        } } };
      });
    } catch (reason) {
      if (!mounted.current) return;
      if (exchange === "aster" && !gate?.accepts(requestToken)) return;
      setState((current) => current.uid !== uid ? current : ({ ...current, snapshots: { ...current.snapshots, [exchange]: { ...current.snapshots[exchange], loading: false, serverConfirmed: current.snapshots[exchange].serverConfirmed, error: reason instanceof Error ? reason.message : "Exchangegegevens zijn niet beschikbaar." } } }));
    }
  }, [currentAsterRequestGate, uid]);

  const confirmAsterStrategy2 = useCallback((strategy2: Record<string, unknown>) => {
    if (!uid || !strategy2 || typeof strategy2 !== "object") return;
    currentAsterRequestGate().confirmMutation();
    const updatedAt = Date.now();
    setState((current) => {
      if (current.uid !== uid) return current;
      const previous = current.snapshots.aster;
      const data = { ...(previous.data || {}), strategy2 };
      return {
        ...current,
        snapshots: {
          ...current.snapshots,
          aster: { ...previous, loading: false, data, error: "", updatedAt, source: "server", serverConfirmed: true },
        },
      };
    });
  }, [currentAsterRequestGate, uid]);

  const refreshAll = useCallback(() => {
    if (refreshAllInFlight.current) return refreshAllInFlight.current;
    // Only Aster is an active automatic exchange source. Hyperliquid remains\n    // available through explicit refresh("hyperliquid") for legacy/manual views.\n    const request = Promise.allSettled((["aster"] as ExchangeId[]).map(refresh));
    refreshAllInFlight.current = request;
    void request.finally(() => { if (refreshAllInFlight.current === request) refreshAllInFlight.current = null; });
    return request;
  }, [refresh]);

  useEffect(() => {
    if (!uid) return;
    // Startup fast path: authenticated Aster reads use the Firebase token directly,
    // so they do not need to wait for the separate session/bootstrap round-trip.
    void refresh("aster");
  }, [refresh, uid]);

  useEffect(() => {
    if (!uid) return;
    const controller = new AbortController();
    let stopped = false;
    let retryMs = 1000;
    const run = async () => {
      while (!stopped) {
        try {
          const response = await authenticatedStream("/api/exchanges/aster/realtime", { signal: controller.signal });
          const reader = response.body!.getReader();
          const decoder = new TextDecoder();
          let buffer = ""; retryMs = 1000;
          while (!stopped) {
            const { value, done } = await reader.read();
            if (done) throw new Error("Realtime Aster-stream gesloten");
            const parsed = parseSseChunk(buffer, decoder.decode(value, { stream: true }));
            buffer = parsed.rest;
            for (const event of parsed.events) {
              if (!event || typeof event !== "object" || !("symbol" in event) || !("markPrice" in event)) continue;
              realtimeBatch.current.set(String(event.symbol).toUpperCase(), event as Record<string, unknown>);
            }
            if (realtimeBatch.current.size && realtimeBatchTimer.current === null) {
              realtimeBatchTimer.current = window.setTimeout(() => {
                realtimeBatchTimer.current = null;
                const events = Array.from(realtimeBatch.current.values());
                realtimeBatch.current.clear();
              setState((current) => {
                if (current.uid !== uid) return current;
                const previous = current.snapshots.aster;
                if (!previous.data) return current;
                const data = events.reduce((value, event) => applyAsterRealtimeMark(value, event), previous.data) as Record<string, unknown>;
                if (data === previous.data) return current;
                return { ...current, snapshots: { ...current.snapshots, aster: { ...previous, data, updatedAt: Date.now() } } };
              });
              }, 250);
            }
          }
        } catch (error) {
          if (stopped || controller.signal.aborted) return;
          console.warn("[TradeMentor Aster realtime] reconnect", error);
          await new Promise((resolve) => window.setTimeout(resolve, retryMs));
          retryMs = Math.min(15_000, retryMs * 2);
        }
      }
    };
    void run();
    return () => { stopped = true; controller.abort(); if (realtimeBatchTimer.current !== null) window.clearTimeout(realtimeBatchTimer.current); realtimeBatchTimer.current = null; realtimeBatch.current.clear(); };
  }, [uid]);

  useEffect(() => {
    if (!cloudReady) return;
    refreshAll();
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") refreshAll();
    // Canonical account status is the sole browser account snapshot. Market
    // prices use the realtime stream; no browser persistence or history merge
    // is allowed to create a second account truth.
    }, 60_000);
    const visible = () => { if (document.visibilityState === "visible") refreshAll(); };
    document.addEventListener("visibilitychange", visible);
    return () => { window.clearInterval(interval); document.removeEventListener("visibilitychange", visible); };
  }, [cloudReady, refreshAll]);

  return { snapshots, refresh, refreshAll, confirmAsterStrategy2 };
}
