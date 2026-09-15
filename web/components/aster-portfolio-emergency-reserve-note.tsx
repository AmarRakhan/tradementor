"use client";

import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { authenticatedRequest } from "@/lib/cloud-client";

type ReserveState = {
  enabled?: boolean;
  status?: string;
  hedgeReserveUsd?: number;
  availableBalanceUsd?: number;
  hedgeHeadroomUsd?: number;
  hedgeFeasibleNow?: boolean;
  technicalSafetyOverride?: boolean;
  triggerReason?: string;
};

const API = "/api/exchanges/aster/portfolio-emergency-hedge";
const money = (value: unknown) => `US$ ${new Intl.NumberFormat("nl-NL", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
}).format(Number(value) || 0)}`;

export function AsterPortfolioEmergencyReserveNote() {
  const [host, setHost] = useState<HTMLElement | null>(null);
  const [state, setState] = useState<ReserveState>({});

  useEffect(() => {
    let frame = 0;
    let alive = true;
    const mount = () => {
      if (!alive) return;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const config = document.querySelector<HTMLElement>(".pnh-panel .pnh-config");
        if (!config) {
          document.getElementById("pnh-reserve-status-host")?.remove();
          setHost(null);
          return;
        }
        let node = document.getElementById("pnh-reserve-status-host");
        if (!node) {
          node = document.createElement("div");
          node.id = "pnh-reserve-status-host";
        }
        if (node.parentElement !== config.parentElement || node.previousElementSibling !== config) {
          config.insertAdjacentElement("afterend", node);
        }
        setHost(node);
      });
    };
    const observer = new MutationObserver(mount);
    observer.observe(document.body, { childList: true, subtree: true });
    mount();
    return () => {
      alive = false;
      observer.disconnect();
      cancelAnimationFrame(frame);
      document.getElementById("pnh-reserve-status-host")?.remove();
    };
  }, []);

  const refresh = useCallback(async () => {
    try {
      const next = await authenticatedRequest(API, { cache: "no-store" }) as ReserveState;
      setState(next);
    } catch {
      // The parent emergency panel owns connectivity/error messaging.
    }
  }, []);

  useEffect(() => {
    const first = window.setTimeout(() => { void refresh(); }, 0);
    const timer = window.setInterval(() => { void refresh(); }, 3000);
    return () => {
      window.clearTimeout(first);
      window.clearInterval(timer);
    };
  }, [refresh]);

  if (!host || state.enabled !== true) return null;
  const feasible = state.hedgeFeasibleNow !== false;
  const technical = state.technicalSafetyOverride === true;
  const reason = String(state.triggerReason || "").toUpperCase();

  return createPortal(
    <div className={`pnh-reserve-note ${feasible ? "ok" : "warn"} ${technical ? "technical" : ""}`}>
      <div>
        <strong>{feasible ? "✓ NOODRESERVE BESCHIKBAAR" : "⚠ NOODRESERVE TE KLEIN"}</strong>
        <small>Geschat nodig {money(state.hedgeReserveUsd)} · beschikbaar {money(state.availableBalanceUsd)}</small>
      </div>
      <p>
        {reason === "MARGIN_SAFETY_OVERRIDE"
          ? "Technische veiligheidsgrens heeft eerder ingegrepen dan je ingestelde portfoliobodem."
          : technical
            ? "Beschikbare marge nadert de technische veiligheidsgrens; de bot mag eerder hedgen dan je ingestelde bodem."
            : "Je ingestelde portfoliobodem blijft leidend zolang de berekende hedge-reserve veilig beschikbaar blijft."}
      </p>
      <style>{`
        .pnh-reserve-note{margin-top:9px;padding:9px 10px;border:1px solid rgba(44,242,162,.23);border-radius:10px;background:rgba(5,31,21,.66);font-family:var(--font-geist-sans),sans-serif}
        .pnh-reserve-note>div{display:flex;align-items:center;justify-content:space-between;gap:8px}.pnh-reserve-note strong{color:#55efb2;font-size:7.5px;letter-spacing:.08em}.pnh-reserve-note small{color:#89a499;font-size:7px}.pnh-reserve-note p{margin:5px 0 0;color:#738d81;font-size:7px;line-height:1.4}.pnh-reserve-note.warn,.pnh-reserve-note.technical{border-color:rgba(226,181,83,.4);background:rgba(56,39,8,.28)}.pnh-reserve-note.warn strong,.pnh-reserve-note.technical strong{color:#efc769}@media(max-width:430px){.pnh-reserve-note>div{align-items:flex-start;flex-direction:column;gap:2px}}
      `}</style>
    </div>,
    host,
  );
}
