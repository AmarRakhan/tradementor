"use client";

import { useEffect } from "react";

const primary = ["1m", "5m", "15m", "1h", "6h"];
const extra: Array<{ label: string; source: string }> = [
  { label: "12h", source: "12h" },
  { label: "1d", source: "1D" },
  { label: "3d", source: "2h" },
  { label: "1w", source: "4h" },
  { label: "1m", source: "12h" },
  { label: "3m", source: "1D" },
  { label: "Alles", source: "1W" },
];

function enhanceTimeframes(root: HTMLElement) {
  if (root.dataset.referenceEnhanced === "true") return;
  const originals = Array.from(root.querySelectorAll(":scope > button")) as HTMLButtonElement[];
  if (!originals.length) return;
  const byLabel = new Map(originals.map(button => [button.textContent?.trim() || "", button]));
  if (!primary.every(label => byLabel.has(label))) return;

  root.dataset.referenceEnhanced = "true";
  for (const button of originals) {
    if (!primary.includes(button.textContent?.trim() || "")) {
      button.style.display = "none";
      button.setAttribute("aria-hidden", "true");
      button.tabIndex = -1;
    }
  }

  const details = document.createElement("details");
  details.className = "strategy2-more-timeframes";
  const summary = document.createElement("summary");
  summary.textContent = "Meer ▾";
  summary.setAttribute("aria-label", "Meer timeframes");
  details.appendChild(summary);

  const menu = document.createElement("div");
  menu.className = "aster-detail-timeframe-menu";
  for (const item of extra) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = item.label;
    button.dataset.sourceTimeframe = item.source;
    button.addEventListener("click", () => {
      const source = byLabel.get(item.source);
      source?.click();
      summary.textContent = item.label === "12h" ? "Meer ▾" : `${item.label} ▾`;
      details.classList.add("active");
      details.open = false;
    });
    menu.appendChild(button);
  }
  details.appendChild(menu);
  root.appendChild(details);

  const syncActive = () => {
    const selected = originals.find(button => button.classList.contains("active"));
    const selectedText = selected?.textContent?.trim() || "";
    const isPrimary = primary.includes(selectedText);
    details.classList.toggle("active", !isPrimary && Boolean(selectedText));
    if (isPrimary) summary.textContent = "Meer ▾";
    for (const button of Array.from(menu.querySelectorAll("button"))) {
      button.classList.toggle("active", button.getAttribute("data-source-timeframe") === selectedText);
    }
  };
  new MutationObserver(syncActive).observe(root, { subtree: true, attributes: true, attributeFilter: ["class"] });
  syncActive();
}

export function Strategy2ReferenceEnhancer() {
  useEffect(() => {
    const apply = () => {
      document.querySelectorAll<HTMLElement>(".aster-detail-timeframes").forEach(enhanceTimeframes);
    };
    apply();
    const observer = new MutationObserver(apply);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, []);
  return null;
}
