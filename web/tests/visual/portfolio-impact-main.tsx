import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { PortfolioImpactBattle } from "../../components/portfolio-impact-battle";

function positions(longPnl: number, shortPnl: number) {
  const longs = Array.from({ length: 25 }, () => ({ side: "long", pnl: longPnl / 25, notional: 3482.15 / 25 }));
  const shorts = Array.from({ length: 19 }, () => ({ side: "short", pnl: shortPnl / 19, notional: 5271.40 / 19 }));
  return [...longs, ...shorts];
}

function Fixture() {
  const [tick, setTick] = useState({ long: -19.99, short: -150.98, at: Date.now() });
  useEffect(() => {
    const first = window.setTimeout(() => setTick({ long: -20.31, short: -149.20, at: Date.now() }), 320);
    const second = window.setTimeout(() => setTick({ long: -20.55, short: -147.92, at: Date.now() }), 720);
    return () => { window.clearTimeout(first); window.clearTimeout(second); };
  }, []);
  return <PortfolioImpactBattle positions={positions(tick.long, tick.short)} equity={41278.62} dataAvailable updatedAt={tick.at} />;
}

createRoot(document.getElementById("root")!).render(<main className="qa-shell"><Fixture /></main>);
