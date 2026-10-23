"use client";

import { useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { authenticatedRequest } from "@/lib/cloud-client";
import { WEBAPP_BUILD_NUMBER } from "@/lib/app-version";
import { recoveryPairs, summarizeRehedgeAll } from "@/lib/rehedge-all.mjs";
import styles from "./aster-trade-center.module.css";

// Re-Hedge All (build 623: both sides, also pairs halfway the afbouw): one server request. The server starts the EXISTING Auto Hedge cycle for every candidate;
// this component contains no order, size or hedge logic.

type Pair = { symbol?: string; status?: string };
type RehedgeAllResult = { found?: number; ordersSent?: number; mode?: string; status?: string; items?: Record<string, unknown>[] };
type RehedgeAllRow = { symbol: string; outcome: string; label: string; longNotional: string; shortBefore: string; shortAfter: string; addedQty: number; hedgePercent: string };
type RehedgeAllSummary = { found: number; protected: number; busy: number; skipped: number; attention: number; ordersSent: number; testMode: boolean; rows: RehedgeAllRow[] };
type AutoHedgeState = { enabled?: boolean; pairs?: Pair[] };

const GOLD = "#e8c46a";

export function RehedgeAllButton() {
  const inFlight = useRef(false);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState<Pair[] | null>(null);
  const [summary, setSummary] = useState<RehedgeAllSummary | null>(null);
  const [message, setMessage] = useState("");

  const open = async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setMessage("");
    try {
      const state = await authenticatedRequest("/api/exchanges/aster/position-loss-auto-hedge", { cache: "no-store" }) as AutoHedgeState;
      if (state.enabled !== true) {
        setMessage("Zet Auto Hedge eerst AAN om Recovery-posities opnieuw te hedgen.");
        return;
      }
      const pairs: Pair[] = recoveryPairs(state.pairs);
      if (!pairs.length) {
        setMessage("Geen Recovery- of half afgebouwde posities om opnieuw te hedgen.");
        return;
      }
      setConfirming(pairs);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Recovery-posities konden niet worden geladen.");
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  const confirm = async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setMessage("");
    try {
      const response = await authenticatedRequest("/api/exchanges/aster/position-loss-auto-hedge/rehedge-all", {
        method: "POST",
        body: JSON.stringify({ confirm: true, clientBuild: WEBAPP_BUILD_NUMBER }),
        cache: "no-store",
      }) as { rehedgeAll?: RehedgeAllResult };
      setConfirming(null);
      setSummary(summarizeRehedgeAll(response.rehedgeAll) as RehedgeAllSummary);
    } catch (reason) {
      setConfirming(null);
      setMessage(reason instanceof Error ? reason.message : "Re-Hedge All kon niet worden uitgevoerd. Er is niets dubbel verstuurd.");
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  const modal = (content: ReactNode, label: string) =>
    typeof document !== "undefined" && createPortal(
      <div className={styles.modal} role="dialog" aria-modal="true" aria-label={label}>
        <div>{content}</div>
      </div>,
      document.body,
    );

  return (
    <>
      <button
        type="button"
        data-testid="rehedge-all"
        disabled={busy}
        onClick={open}
        style={{ padding: "8px 6px", borderRadius: 8, border: `1px solid ${GOLD}`, background: "rgba(232,196,106,.1)", color: GOLD, fontWeight: 800, whiteSpace: "nowrap", minWidth: 0 }}
      >
        {busy ? "Re-Hedging…" : "Re-Hedge All"}
      </button>
      {message && (
        <p role="status" style={{ gridColumn: "1 / -1", margin: 0, fontSize: 10, color: "#a7b6cb" }}>{message}</p>
      )}
      {confirming && modal(
        <>
          <h3>{confirming.length} {confirming.length === 1 ? "positie" : "posities"} opnieuw 100% hedgen?</h3>
          <p>
            Iedere Recovery-positie en elke positie die half is afgebouwd gaat direct terug naar 100% onder Auto Hedge,
            ook als hij in de plus staat. Bij een LONG wordt de SHORT aangevuld, bij een SHORT de LONG, tot de{" "}
            <strong>actuele hoeveelheid</strong> bij Aster; bestaande hedge en openstaande orders tellen mee. Er wordt
            altijd naar beneden afgerond: de hedge wordt nooit groter dan de positie. Een hedge die al groter is, wordt
            overgeslagen en gemeld. Afbouwen telt daarna vanaf de koers van nu.
          </p>
          <p style={{ wordBreak: "break-word" }}>{confirming.map((pair) => String(pair.symbol || "").replace(/USDT$/i, "")).join(" · ")}</p>
          <footer>
            <button type="button" disabled={busy} onClick={() => setConfirming(null)}>Annuleren</button>
            <button type="button" disabled={busy} onClick={confirm} style={{ borderColor: GOLD, color: GOLD }}>
              {busy ? "Re-Hedging…" : `Bevestig Re-Hedge All · ${confirming.length}`}
            </button>
          </footer>
        </>,
        "Re-Hedge All bevestigen",
      )}
      {summary && modal(
        <>
          <h3>Re-Hedge All afgerond</h3>
          {summary.testMode && <p>Testmodus: Auto Hedge-uitvoering staat uit, er zijn geen orders verstuurd.</p>}
          <dl>
            <dt>Recovery-posities gevonden</dt><dd>{summary.found}</dd>
            <dt>Volledig beschermd</dt><dd className={styles.profit}>{summary.protected}</dd>
            <dt>Bezig (Auto Hedge maakt af)</dt><dd>{summary.busy}</dd>
            <dt>Overgeslagen</dt><dd>{summary.skipped}</dd>
            <dt>Vereist controle</dt><dd className={summary.attention ? styles.loss : undefined}>{summary.attention}</dd>
          </dl>
          <div style={{ maxHeight: 260, overflowY: "auto", display: "grid", gap: 6 }} data-testid="rehedge-all-rows">
            {summary.rows.map((row: RehedgeAllRow) => (
              <div key={row.symbol} style={{ padding: 8, borderRadius: 8, background: "#111d32", fontSize: 10 }}>
                <strong>{row.symbol}</strong> · {row.label}
                <div style={{ color: "#8993a8", marginTop: 3 }}>
                  LONG {row.longNotional} · SHORT {row.shortBefore} → {row.shortAfter} · {row.hedgePercent}
                </div>
              </div>
            ))}
          </div>
          <footer><button type="button" onClick={() => setSummary(null)}>Sluiten</button></footer>
        </>,
        "Re-Hedge All resultaat",
      )}
    </>
  );
}
