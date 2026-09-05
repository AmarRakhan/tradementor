import React from "react";
import { createRoot } from "react-dom/client";
import { PortfolioImpactBattle } from "../../components/portfolio-impact-battle";

const longs = Array.from({length:25},()=>({side:"long",pnl:-19.99/25,notional:3482.15/25}));
const shorts = Array.from({length:19},()=>({side:"short",pnl:-150.98/19,notional:5271.40/19}));

createRoot(document.getElementById("root")!).render(
  <main className="qa-shell">
    <PortfolioImpactBattle positions={[...longs,...shorts]} equity={41278.62} dataAvailable updatedAt={Date.now()} />
  </main>
);
