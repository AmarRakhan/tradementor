"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState, type MouseEvent, type PointerEvent } from "react";
import { SafeTradingChart, type TradeSelection } from "@/components/trading-chart";
import { PortfolioImpactBattle as PortfolioImpactBullBear } from "./portfolio-impact-battle-legacy";

type BattlePosition = Record<string, unknown>;
type BattleTimeframe = "1m" | "5m" | "15m" | "1h" | "4h" | "24h";
type ChartTimeframe = "1m" | "3m" | "5m" | "15m" | "30m" | "1h" | "2h" | "4h" | "6h" | "12h" | "1D" | "1W";

type Props = {
  positions: unknown[];
  equity: number | null;
  dataAvailable: boolean;
  updatedAt?: number | null;
  marketPressureOverride?: Partial<Record<BattleTimeframe, number>>;
};

type TapState = { at: number; x: number; y: number };

const BATTLE_TO_CHART: Record<BattleTimeframe, ChartTimeframe> = {
  "1m": "1m",
  "5m": "5m",
  "15m": "15m",
  "1h": "1h",
  "4h": "4h",
  "24h": "1D",
};
const CHART_TO_BATTLE: Partial<Record<ChartTimeframe, BattleTimeframe>> = {
  "1m": "1m",
  "5m": "5m",
  "15m": "15m",
  "1h": "1h",
  "4h": "4h",
  "1D": "24h",
};
const BATTLE_LABELS: Record<BattleTimeframe, string> = {
  "1m": "1m",
  "5m": "5m",
  "15m": "15m",
  "1h": "1u",
  "4h": "4u",
  "24h": "24u",
};
const BATTLE_BY_LABEL = new Map<string, BattleTimeframe>(Object.entries(BATTLE_LABELS).map(([id, label]) => [label, id as BattleTimeframe]));
const CHART_TIMEFRAMES = new Set<ChartTimeframe>(["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1D", "1W"]);
const DOUBLE_TAP_MS = 380;
const DOUBLE_TAP_DISTANCE_PX = 44;
const TOGGLE_DEDUPE_MS = 520;

function recordFrom(value: unknown): BattlePosition | null {
  return value && typeof value === "object" ? value as BattlePosition : null;
}

function finite(value: unknown) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function normalizedSymbol(value: unknown) {
  return String(value ?? "").toUpperCase().replace(/[\/_-]/g, "");
}

function normalizedSide(value: unknown) {
  const side = String(value ?? "").toUpperCase();
  return side === "LONG" || side === "SHORT" ? side : "";
}

function activeBtcSelection(positions: unknown[]): TradeSelection {
  const btcRows = positions
    .map(recordFrom)
    .filter((row): row is BattlePosition => Boolean(row && normalizedSymbol(row.symbol) === "BTCUSDT" && normalizedSide(row.side)));
  const activeRows = btcRows.filter((row) => (finite(row.quantity ?? row.size ?? row.positionAmt) ?? 0) !== 0);
  const row = activeRows[0] ?? btcRows[0] ?? null;
  const side = normalizedSide(row?.side);
  const entry = finite(row?.averageEntry ?? row?.entryPrice ?? row?.entry);
  const mark = finite(row?.markPrice ?? row?.mark ?? row?.price);
  const liquidationPrice = finite(row?.liquidationPrice ?? row?.liqPrice);
  const dcaCount = finite(row?.dcaCount ?? (recordFrom(row?.strategy2DcaLadder)?.filledDcaCount));
  const strategy2Role = String(row?.strategy2Role ?? "").trim();
  return {
    id: String(row?.id ?? row?.positionId ?? `BTCUSDT:${side || "MARKET"}:quick`),
    symbol: "BTCUSDT",
    exchange: "aster",
    side,
    ...(entry !== null ? { entry } : {}),
    ...(mark !== null ? { mark } : {}),
    ...(liquidationPrice !== null ? { liquidationPrice } : {}),
    ...(dcaCount !== null ? { dcaCount: Math.max(0, Math.round(dcaCount)) } : {}),
    ...(strategy2Role ? { strategy2Role } : {}),
  };
}

function eventElement(target: EventTarget | null) {
  return typeof Element !== "undefined" && target instanceof Element ? target : null;
}

function isInteractiveTarget(target: EventTarget | null) {
  const element = eventElement(target);
  return Boolean(element?.closest("button, a, input, select, textarea, [role='button']"));
}

function isToggleSurface(target: EventTarget | null, chartOpen: boolean) {
  const element = eventElement(target);
  if (!element || isInteractiveTarget(target)) return false;
  return chartOpen
    ? Boolean(element.closest(".chart-stage"))
    : Boolean(element.closest("section[data-bollinger-score]"));
}

function chartTimeframeFromText(value: string | null | undefined): ChartTimeframe | null {
  const timeframe = String(value ?? "").trim() as ChartTimeframe;
  return CHART_TIMEFRAMES.has(timeframe) ? timeframe : null;
}

export function PortfolioImpactBattle(props: Props) {
  const [chartOpen, setChartOpen] = useState(false);
  const [battleTimeframe, setBattleTimeframe] = useState<BattleTimeframe>("15m");
  const [chartTimeframe, setChartTimeframe] = useState<ChartTimeframe>("15m");
  const slotRef = useRef<HTMLDivElement | null>(null);
  const restoreTopRef = useRef<number | null>(null);
  const lastTapRef = useRef<TapState | null>(null);
  const lastToggleAtRef = useRef(0);
  const prefetchedTimeframesRef = useRef(new Set<ChartTimeframe>());
  const selection = useMemo(() => activeBtcSelection(props.positions), [props.positions]);

  const toggleView = () => {
    const now = typeof performance !== "undefined" ? performance.now() : Date.now();
    if (now - lastToggleAtRef.current < TOGGLE_DEDUPE_MS) return;
    lastToggleAtRef.current = now;
    lastTapRef.current = null;
    const top = slotRef.current?.getBoundingClientRect().top;
    restoreTopRef.current = Number.isFinite(top) ? Number(top) : null;

    if (!chartOpen) {
      setChartTimeframe(BATTLE_TO_CHART[battleTimeframe]);
      setChartOpen(true);
      return;
    }

    const matchingBattleTimeframe = CHART_TO_BATTLE[chartTimeframe];
    if (matchingBattleTimeframe) setBattleTimeframe(matchingBattleTimeframe);
    setChartOpen(false);
  };

  useLayoutEffect(() => {
    const expectedTop = restoreTopRef.current;
    const slot = slotRef.current;
    if (expectedTop !== null && slot) {
      const currentTop = slot.getBoundingClientRect().top;
      const delta = currentTop - expectedTop;
      if (Number.isFinite(delta) && Math.abs(delta) > 0.5) window.scrollBy({ top: delta, left: 0, behavior: "auto" });
      restoreTopRef.current = null;
    }
  }, [chartOpen]);

  useLayoutEffect(() => {
    const slot = slotRef.current;
    if (!slot) return;
    const selector = chartOpen
      ? "[role='group'][aria-label='Timeframe kiezen'] button"
      : "[role='group'][aria-label='BTC Bollinger timeframe'] button";
    const wanted = chartOpen ? chartTimeframe : BATTLE_LABELS[battleTimeframe];
    const buttons = Array.from(slot.querySelectorAll<HTMLButtonElement>(selector));
    if (!buttons.length) return;
    const active = buttons.find((button) => button.classList.contains("active") || button.getAttribute("aria-pressed") === "true");
    if (active?.textContent?.trim() === wanted) return;
    buttons.find((button) => button.textContent?.trim() === wanted)?.click();
  }, [battleTimeframe, chartOpen, chartTimeframe]);

  useEffect(() => {
    if (chartOpen) return;
    const timeframe = BATTLE_TO_CHART[battleTimeframe];
    if (prefetchedTimeframesRef.current.has(timeframe)) return;
    prefetchedTimeframesRef.current.add(timeframe);
    const params = new URLSearchParams({ exchange: "aster", symbol: "BTCUSDT", interval: timeframe.toLowerCase(), limit: "600" });
    void fetch(`/api/market-data?${params.toString()}`)
      .then(async (response) => {
        if (!response.ok) throw new Error(`BTC prefetch ${response.status}`);
        await response.json();
      })
      .catch(() => prefetchedTimeframesRef.current.delete(timeframe));
  }, [battleTimeframe, chartOpen]);

  const handleClickCapture = (event: MouseEvent<HTMLDivElement>) => {
    const element = eventElement(event.target);
    const button = element?.closest("button");
    if (!(button instanceof HTMLButtonElement)) return;

    const bullGroup = button.closest("[role='group'][aria-label='BTC Bollinger timeframe']");
    if (bullGroup) {
      const next = BATTLE_BY_LABEL.get(button.textContent?.trim() ?? "");
      if (next) setBattleTimeframe(next);
      return;
    }

    const chartGroup = button.closest("[role='group'][aria-label='Timeframe kiezen']");
    if (chartGroup) {
      const next = chartTimeframeFromText(button.textContent);
      if (next) setChartTimeframe(next);
    }
  };

  const handleDoubleClick = (event: MouseEvent<HTMLDivElement>) => {
    if (!isToggleSurface(event.target, chartOpen)) return;
    toggleView();
  };

  const handlePointerUp = (event: PointerEvent<HTMLDivElement>) => {
    if (event.pointerType !== "touch" && event.pointerType !== "pen") return;
    if (!isToggleSurface(event.target, chartOpen)) {
      lastTapRef.current = null;
      return;
    }
    const now = typeof performance !== "undefined" ? performance.now() : Date.now();
    const previous = lastTapRef.current;
    if (previous) {
      const age = now - previous.at;
      const distance = Math.hypot(event.clientX - previous.x, event.clientY - previous.y);
      if (age > 0 && age <= DOUBLE_TAP_MS && distance <= DOUBLE_TAP_DISTANCE_PX) {
        toggleView();
        return;
      }
    }
    lastTapRef.current = { at: now, x: event.clientX, y: event.clientY };
  };

  return (
    <div
      ref={slotRef}
      data-btc-quick-view={chartOpen ? "chart" : "bull-bear"}
      onClickCapture={handleClickCapture}
      onDoubleClick={handleDoubleClick}
      onPointerUp={handlePointerUp}
    >
      {chartOpen
        ? <SafeTradingChart selection={selection} mode="aster-detail" />
        : <PortfolioImpactBullBear {...props} />}
    </div>
  );
}
