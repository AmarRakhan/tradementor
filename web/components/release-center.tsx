"use client";

import { useCallback, useEffect, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import styles from "./release-center.module.css";

type Feature = {
  key: string;
  status: "IN_BOUW" | "TESTEN" | "AKKOORD" | "LIVE";
  beta: boolean;
  stable: boolean;
  enabled?: boolean;
  updatedAt?: string;
};

const LABELS: Record<string, string> = {
  bot_configurator_v2: "Botconfigurator V2",
  directional_bollinger: "LONG/SHORT Bollinger",
  exposure_refill: "Exposure refill",
  price_zones: "Price zones / soldaten",
  margin_summary: "Margin samenvatting",
};

export function ReleaseCenter({ compact = false }: { compact?: boolean }) {
  const [features, setFeatures] = useState<Record<string, Feature>>({});
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    try {
      const payload = await authenticatedRequest("/api/admin/releases");
      setFeatures(payload.features || {});
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Releasegegevens konden niet worden geladen.");
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function update(key: string, body: Record<string, unknown>) {
    setBusy(key);
    setMessage("");
    try {
      const payload = await authenticatedRequest("/api/admin/releases/" + encodeURIComponent(key), {
        method: "PUT",
        body: JSON.stringify(body),
      });
      if (payload.feature) setFeatures((current) => ({ ...current, [key]: payload.feature }));
      else await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Releasewijziging mislukt.");
    } finally {
      setBusy("");
    }
  }

  const rows = Object.values(features);
  if (!rows.length && !message) return null;

  return <section className={compact ? styles.compact : styles.center} aria-label="Releasecentrum">
    <header className={styles.header}>
      <div><span>BETA RELEASES</span><h2>Releasecentrum</h2><p>Test, keur goed en publiceer ieder blok afzonderlijk.</p></div>
      <span className={styles.channel}>BETA</span>
    </header>
    {message && <p className={styles.message}>{message}</p>}
    <div className={styles.list}>
      {rows.map((feature) => {
        const key = feature.key;
        const label = LABELS[key] || key;
        return <article key={key} className={styles.row}>
          <div className={styles.info}>
            <strong>{label}</strong>
            <small>{feature.beta ? "BETA aan" : "BETA uit"} · {feature.stable ? "STABLE aan" : "STABLE uit"}</small>
          </div>
          <span className={styles[feature.status.toLowerCase()] || styles.status}>{feature.status.replace("_", " ")}</span>
          <div className={styles.actions}>
            {feature.status === "IN_BOUW" && <button disabled={busy === key} onClick={() => update(key, { status: "TESTEN", beta: true, stable: false })}>Naar testen</button>}
            {feature.status === "TESTEN" && <button disabled={busy === key} onClick={() => update(key, { status: "AKKOORD", beta: true, stable: false })}>✓ Getest en akkoord</button>}
            {feature.status === "AKKOORD" && <button className={styles.publish} disabled={busy === key} onClick={() => {
              if (window.confirm(label + " vrijgeven aan alle gebruikers? Alleen dit onderdeel wordt gepubliceerd.")) void update(key, { status: "LIVE", beta: true, stable: true, confirm: true });
            }}>Vrijgeven aan alle gebruikers</button>}
            {feature.status === "LIVE" && feature.stable && <button className={styles.rollback} disabled={busy === key} onClick={() => {
              if (window.confirm(label + " terugtrekken naar alleen BETA? Stable gebruikers krijgen direct de oude variant.")) void update(key, { status: "TESTEN", beta: true, stable: false, confirm: true });
            }}>Terug naar BETA</button>}
          </div>
        </article>;
      })}
    </div>
  </section>;
}
