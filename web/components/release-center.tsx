"use client";

import { useEffect, useMemo, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";

type Status = "IN_BOUW" | "TESTEN" | "AKKOORD" | "LIVE";
type Feature = {
  key: string;
  status: Status;
  beta: boolean;
  stable: boolean;
  enabled?: boolean;
  updatedAt?: string;
};

type Snapshot = { channel?: string; features?: Record<string, Feature> };

const labels: Record<string, string> = {
  bot_configurator_v2: "Botconfigurator V2",
  directional_bollinger: "Directional Bollinger",
  exposure_refill: "Exposure refill",
  price_zones: "Price zones",
  margin_summary: "Margin summary",
};

export function ReleaseCenter() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");

  const load = async () => {
    try {
      const value = await authenticatedRequest("/api/admin/releases", { cache: "no-store" }) as Snapshot;
      setSnapshot(value); setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Releasecentrum kon niet worden geladen.");
    }
  };

  useEffect(() => { void load(); }, []);
  const rows = useMemo(() => Object.values(snapshot?.features || {}), [snapshot]);

  const update = async (row: Feature, next: Partial<Pick<Feature, "status"|"beta"|"stable">>, confirm = false) => {
    setBusy(row.key); setMessage("");
    try {
      await authenticatedRequest(`/api/admin/releases/${encodeURIComponent(row.key)}`, {
        method: "PUT",
        body: JSON.stringify({
          status: next.status ?? row.status,
          beta: next.beta ?? row.beta,
          stable: next.stable ?? row.stable,
          confirm,
        }),
      });
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Release wijzigen mislukt.");
    } finally {
      setBusy("");
    }
  };

  if (snapshot?.channel !== "BETA" && !message) return null;

  return (
    <section className="release-center" aria-label="Releasecentrum">
      <header><div><span>BETA-BEHEER</span><h3>Releasecentrum</h3><p>Test, keur goed en publiceer ieder blok afzonderlijk.</p></div><button type="button" onClick={() => void load()} disabled={Boolean(busy)}>↻</button></header>
      <div className="release-center-list">
        {rows.map((row) => (
          <article key={row.key} className={`release-row status-${row.status.toLowerCase()}`}>
            <div><strong>{labels[row.key] || row.key}</strong><small>{row.beta ? "BETA aan" : "BETA uit"} · {row.stable ? "STABLE aan" : "STABLE uit"}</small></div>
            <em>{row.status.replace("_", " ")}</em>
            <div className="release-actions">
              {row.status === "TESTEN" && <button type="button" disabled={busy===row.key} onClick={() => void update(row,{status:"AKKOORD"})}>✓ Getest en akkoord</button>}
              {row.status === "AKKOORD" && !row.stable && <button type="button" disabled={busy===row.key} onClick={() => {
                if (window.confirm(`${labels[row.key] || row.key} vrijgeven aan alle gebruikers? Alleen dit onderdeel wordt gepubliceerd.`)) void update(row,{status:"LIVE",stable:true},true);
              }}>Vrijgeven aan alle gebruikers</button>}
              {row.stable && <button type="button" className="rollback" disabled={busy===row.key} onClick={() => {
                if (window.confirm(`${labels[row.key] || row.key} terugtrekken naar alleen BETA?`)) void update(row,{status:"TESTEN",stable:false,beta:true},true);
              }}>Terug naar BETA</button>}
            </div>
          </article>
        ))}
      </div>
      {message && <p className="release-message">{message}</p>}
    </section>
  );
}
