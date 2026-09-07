import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { PortfolioImpactBattle } from "../../components/portfolio-impact-battle";

function positions(longPnl: number, shortPnl: number) {
  const longs = Array.from({ length: 25 }, (_, index) => ({ side: "long", symbol: `${["BTC", "ETH", "SOL", "BNB", "XRP"][index % 5]}USDT`, pnl: longPnl / 25, notional: 3482.15 / 25 }));
  const shorts = Array.from({ length: 19 }, (_, index) => ({ side: "short", symbol: `${["BTC", "ETH", "SOL", "BNB", "XRP"][index % 5]}USDT`, pnl: shortPnl / 19, notional: 5271.40 / 19 }));
  return [...longs, ...shorts];
}

const basePressure = {
  "1m": -82,
  "5m": -64,
  "15m": -42,
  "1h": 2,
  "4h": 38,
  "24h": 78,
} as const;

function Fixture() {
  const [pressure, setPressure] = useState<Record<string, number>>({ ...basePressure });
  const set15m = (score: number) => setPressure((current) => ({ ...current, "15m": score }));
  return <>
    <div style={{ position: "fixed", left: -10000, top: 0 }} aria-hidden="true">
      <button id="qa-neutral" onClick={() => set15m(0)}>neutral</button>
      <button id="qa-short60" onClick={() => set15m(-22)}>short60</button>
      <button id="qa-long60" onClick={() => set15m(22)}>long60</button>
    </div>
    <PortfolioImpactBattle
      positions={positions(-20.55, -147.92)}
      equity={41278.62}
      dataAvailable
      updatedAt={Date.now()}
      marketPressureOverride={pressure}
    />
  </>;
}

createRoot(document.getElementById("root")!).render(<main className="qa-shell"><Fixture /></main>);
