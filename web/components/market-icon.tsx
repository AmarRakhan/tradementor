"use client";

import { useState } from "react";
import { iconAsset, type MarketRow } from "@/lib/markets-universe.mjs";
import styles from "./markets-page.module.css";

// Build 644: coin icons from the public CoinCap set; stocks get a monogram,
// commodities a small drawn glyph (gold bars, oil drop, gas flame, copper).
const COMMODITY_GLYPH: Record<string, "bars" | "drop" | "flame" | "coin"> = { XAU: "bars", XAG: "bars", XPT: "bars", XPD: "bars", PAXG: "bars", CL: "drop", BZ: "drop", NATGAS: "flame", XCU: "coin" };

function hueFor(text: string) {
  let hash = 0;
  for (const char of text) hash = (hash * 31 + char.charCodeAt(0)) % 360;
  return hash;
}

function CommodityGlyph({ kind }: { kind: "bars" | "drop" | "flame" | "coin" }) {
  if (kind === "drop") return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.5c3.2 4.1 5.4 7.3 5.4 10.1A5.4 5.4 0 0 1 6.6 13.6C6.6 10.8 8.8 7.6 12 3.5Z" fill="#e8ecf2"/><path d="M9.4 14.2a2.7 2.7 0 0 0 2.6 2.6" stroke="#0b0b0c" strokeWidth="1.4" fill="none" strokeLinecap="round"/></svg>;
  if (kind === "flame") return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3c1.2 3.2 5 5.4 5 10a5 5 0 0 1-10 0c0-2.6 1.6-4 2.6-5.8.4 1.6 1.2 2.4 2 2.8C11.4 7.6 11.4 5.4 12 3Z" fill="#4fb7ff"/></svg>;
  if (kind === "coin") return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="7.5" fill="#d9844a"/><circle cx="12" cy="12" r="4.6" fill="none" stroke="#7a3c14" strokeWidth="1.4"/></svg>;
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 18.5 5 14h6l2 4.5Z" fill="#f2c230"/><path d="M11 18.5 13 14h6l2 4.5Z" fill="#e3ad16"/><path d="M7 13.5 9 9h6l2 4.5Z" fill="#ffd54d"/><path d="M5.2 14.2h5.6M13.2 14.2h5.6M9.2 9.2h5.6" stroke="#fff3b8" strokeWidth=".8"/></svg>;
}

export function MarketIcon({ row }: { row: Pick<MarketRow, "baseAsset" | "category"> }) {
  const [failed, setFailed] = useState(false);
  const base = row.baseAsset;
  const glyph = COMMODITY_GLYPH[base];
  const initials = base.replace(/^1000+/, "").slice(0, base.length > 4 ? 2 : 3);
  if (glyph) return <span className={`${styles.icon} ${styles.iconGlyph}`}><CommodityGlyph kind={glyph} /></span>;
  if (row.category !== "crypto" || failed) {
    const hue = hueFor(base);
    return <span className={`${styles.icon} ${styles.iconInitials}`} style={{ background: `radial-gradient(circle at 30% 24%, hsl(${hue} 70% 62%), hsl(${hue} 62% 34%))` }}>{initials}</span>;
  }
  return <span className={styles.icon}><img src={`https://assets.coincap.io/assets/icons/${iconAsset(base)}@2x.png`} alt="" loading="lazy" decoding="async" onError={() => setFailed(true)} /></span>;
}

