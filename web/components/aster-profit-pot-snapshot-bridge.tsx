"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

const PROFIT_POT_REFERENCE = "file_00000000f5ec8210bf3f2c300b972c25";
const HOST_ID = "aster-profit-pot-snapshot-host";

function existingProfitPotValue(): string {
  const rows = Array.from(document.querySelectorAll<HTMLElement>(".metric-strip .metric"));
  const row = rows.find((item) => item.querySelector("span")?.textContent?.trim().toUpperCase() === "PROFIT POT / SPOT");
  const value = row?.querySelector<HTMLElement>("strong")?.textContent?.trim() || "";
  if (!value || value === "—") return "US$ —";
  return value;
}

function profitPotIcon() {
  return <svg viewBox="0 0 32 32" aria-hidden="true" focusable="false">
    <path d="M9 5.5h14M11 5.5v4h10v-4M8 11.5h16v14.5H8z" fill="none" stroke="currentColor" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M11.5 16h9M11.5 20.5h9" fill="none" stroke="currentColor" strokeWidth="2.3" strokeLinecap="round" />
  </svg>;
}

export function AsterProfitPotSnapshotBridge() {
  const [host, setHost] = useState<HTMLElement | null>(null);
  const [value, setValue] = useState("US$ —");

  useEffect(() => {
    let alive = true;
    let frame = 0;
    const sync = () => {
      if (!alive) return;
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        if (!alive) return;
        const snapshot = document.querySelector<HTMLElement>(".aster-portfolio-snapshot");
        const grid = snapshot?.querySelector<HTMLElement>(":scope > .aps-grid");
        if (!snapshot || !grid) {
          document.getElementById(HOST_ID)?.remove();
          setHost((current) => current === null ? current : null);
          setValue("US$ —");
          return;
        }
        let mount = document.getElementById(HOST_ID) as HTMLElement | null;
        if (!mount) {
          mount = document.createElement("div");
          mount.id = HOST_ID;
        }
        if (mount.parentElement !== snapshot || grid.nextElementSibling !== mount) grid.insertAdjacentElement("afterend", mount);
        setHost((current) => current === mount ? current : mount);
        const next = existingProfitPotValue();
        setValue((current) => current === next ? current : next);
      });
    };

    const observer = new MutationObserver(sync);
    observer.observe(document.body, { subtree: true, childList: true, characterData: true });
    window.addEventListener("hashchange", sync);
    window.addEventListener("popstate", sync);
    sync();
    const timer = window.setInterval(sync, 5000);
    return () => {
      alive = false;
      observer.disconnect();
      window.clearInterval(timer);
      window.cancelAnimationFrame(frame);
      window.removeEventListener("hashchange", sync);
      window.removeEventListener("popstate", sync);
      document.getElementById(HOST_ID)?.remove();
    };
  }, []);

  if (!host) return null;
  return createPortal(
    <div className="aps-profit-pot-row" aria-label="Profit Pot / Spot">
      <article className="aps-profit-pot-card" data-reference={PROFIT_POT_REFERENCE}>
        <span className="aps-profit-pot-icon">{profitPotIcon()}</span>
        <div className="aps-profit-pot-copy">
          <small>PROFIT POT / SPOT</small>
          <strong>{value}</strong>
        </div>
      </article>
    </div>,
    host,
  );
}
