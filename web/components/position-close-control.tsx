"use client";

import { useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";

export function PositionCloseControl({ symbol, exchange, onClosed }: { symbol: string; exchange: "hyperliquid" | "mexc" | "aster"; onClosed: () => void }) {
  const [open, setOpen] = useState(false);
  const [percentage, setPercentage] = useState(100);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  if (exchange !== "hyperliquid") return <span className="close-unavailable">Sluiten via {exchange.toUpperCase()}</span>;

  async function close() {
    setBusy(true); setMessage("");
    try {
      await authenticatedRequest(`/api/exchanges/hyperliquid/positions/${encodeURIComponent(symbol)}/close`, {
        method: "POST", body: JSON.stringify({ confirm: true, percentage }),
      });
      setMessage(`${percentage}% reduce-only sluiting bevestigd.`);
      setOpen(false); setConfirmed(false); onClosed();
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Sluiten is niet gelukt."); }
    finally { setBusy(false); }
  }

  return <div className="position-close">
    <button type="button" className="money-button" aria-label={`${symbol} sluiten`} onClick={() => setOpen((value) => !value)}>＄</button>
    {open && <div className="close-popover"><strong>Positie verkleinen</strong><div>{[25,50,75,100].map((value) => <button type="button" key={value} className={percentage === value ? "active" : ""} onClick={() => { setPercentage(value); setConfirmed(false); }}>{value}%</button>)}</div><label><input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />Reduce-only marktorder bevestigen</label><button type="button" className="confirm-close" disabled={!confirmed || busy} onClick={close}>{busy ? "Sluiten…" : `${percentage}% sluiten`}</button></div>}
    {message && <small>{message}</small>}
  </div>;
}
