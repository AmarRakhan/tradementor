import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { AsterRecentTrades } from "../../components/aster-recent-trades";

const w = window as any;
function snapshotFromWorld() {
  const positions = (w.__world as any[]).filter((p) => p.qty > 0).map((p) => ({
    symbol: p.symbol, side: p.side, quantity: p.qty, entryPrice: p.entry, averageEntry: p.entry, markPrice: p.mark,
    unrealizedPnl: w.__pnl(p), leverage: 5, notionalUsd: p.qty * p.mark, initialMarginUsd: (p.qty * p.mark) / 5,
    openedAt: Date.now() - 3_600_000,
    ...(p.hedged ? { positionLossAutoHedge: { status: "HEDGED", role: p.side === "SHORT" ? "HEDGE" : "PROTECTED" } } : {}),
  }));
  return { loading: false, data: { positions, recentTradeActivity: { entries: [], exits: [] } }, error: "", updatedAt: Date.now(), serverUpdatedAt: Date.now(), source: "server" as const, serverConfirmed: true };
}
function Harness() {
  const [snapshot, setSnapshot] = useState(snapshotFromWorld);
  return (
    <main className="qa-shell">
      <AsterRecentTrades snapshot={snapshot} onRetry={() => { w.__refreshCount = (w.__refreshCount || 0) + 1; setSnapshot(snapshotFromWorld()); }} />
    </main>
  );
}
createRoot(document.getElementById("root")!).render(<Harness />);
