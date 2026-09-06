"use client";

import { useEffect } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";

function shortDcaInput(dialog: Element) {
  for (const label of Array.from(dialog.querySelectorAll("label"))) {
    if ((label.textContent || "").includes("DCA-afstand SHORT")) {
      return label.querySelector("input") as HTMLInputElement | null;
    }
  }
  return null;
}

function strategySettings(payload: Record<string, unknown>) {
  const strategy2 = payload.strategy2 && typeof payload.strategy2 === "object" ? payload.strategy2 as Record<string, unknown> : {};
  return strategy2.settings && typeof strategy2.settings === "object" ? strategy2.settings as Record<string, unknown> : {};
}

export function AsterShortDcaSaveGuard() {
  useEffect(() => {
    const applyStickyFooter = () => {
      for (const dialog of Array.from(document.querySelectorAll('[role="dialog"]'))) {
        const text = dialog.textContent || "";
        if (!text.includes("LONG / SHORT") || !text.includes("DCA")) continue;
        const footer = dialog.querySelector("footer") as HTMLElement | null;
        if (!footer) continue;
        Object.assign(footer.style, {
          position: "sticky", bottom: "0", zIndex: "4",
          padding: "10px 0 calc(8px + env(safe-area-inset-bottom))",
          background: "linear-gradient(180deg,rgba(2,5,4,.72),#020504 34%)",
          backdropFilter: "blur(8px)",
        });
      }
    };

    const onClick = (event: MouseEvent) => {
      const button = (event.target as Element | null)?.closest("button") as HTMLButtonElement | null;
      if (!button || !/opslaan/i.test(button.textContent || "")) return;
      const dialog = button.closest('[role="dialog"]');
      if (!dialog || !(dialog.textContent || "").includes("LONG / SHORT")) return;
      const input = shortDcaInput(dialog);
      if (!input) return;
      const pct = Number(String(input.value).replace(",", "."));
      if (!Number.isFinite(pct) || pct <= 0 || pct > 50) return;
      const wanted = pct / 100;

      window.setTimeout(() => {
        void (async () => {
          try {
            const snapshot = await authenticatedRequest("/api/exchanges/aster", { cache: "no-store" }) as Record<string, unknown>;
            const current = strategySettings(snapshot);
            const stored = Number(current.shortDcaDistance);
            if (Number.isFinite(stored) && Math.abs(stored - wanted) < 1e-9) return;
            await authenticatedRequest("/api/exchanges/aster/strategy2/settings", {
              method: "PUT",
              body: JSON.stringify({ settings: { ...current, shortDcaDistance: wanted } }),
            });
            const verified = await authenticatedRequest("/api/exchanges/aster", { cache: "no-store" }) as Record<string, unknown>;
            const confirmed = Number(strategySettings(verified).shortDcaDistance);
            if (!Number.isFinite(confirmed) || Math.abs(confirmed - wanted) >= 1e-9) {
              console.error("SHORT DCA save verification failed", { wanted, confirmed });
            }
          } catch (error) {
            console.error("SHORT DCA persistence guard failed", error);
          }
        })();
      }, 650);
    };

    applyStickyFooter();
    const observer = new MutationObserver(applyStickyFooter);
    observer.observe(document.body, { subtree: true, childList: true });
    document.addEventListener("click", onClick, true);
    return () => { observer.disconnect(); document.removeEventListener("click", onClick, true); };
  }, []);
  return null;
}
