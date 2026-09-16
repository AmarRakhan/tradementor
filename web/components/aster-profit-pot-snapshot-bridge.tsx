"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { authenticatedRequest } from "@/lib/cloud-client";

const PROFIT_POT_REFERENCE = "file_00000000f5ec8210bf3f2c300b972c25";
const HOST_ID = "aster-profit-pot-snapshot-host";
const PRESETS = [5, 10, 25, 50] as const;

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
  const [open, setOpen] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [percent, setPercent] = useState<number | null>(null);
  const [draft, setDraft] = useState("25");
  const [loadingSettings, setLoadingSettings] = useState(false);
  const [saving, setSaving] = useState(false);
  const [settingsError, setSettingsError] = useState("");
  const [savedMessage, setSavedMessage] = useState("");
  const settingsAttempted = useRef(false);

  const loadSettings = useCallback(async () => {
    setLoadingSettings(true);
    setSettingsError("");
    try {
      const result = await authenticatedRequest("/api/exchanges/aster/profit-sweep-settings");
      const next = Number(result.sweepPercent);
      if (!Number.isFinite(next) || next < 0 || next > 100) throw new Error("Ongeldig spaarpercentage ontvangen");
      setEnabled(result.enabled === true);
      setPercent(next);
      setDraft(String(next));
    } catch (reason) {
      setSettingsError(reason instanceof Error ? reason.message : "Profit sparen kon niet worden geladen");
    } finally {
      setLoadingSettings(false);
    }
  }, []);

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

  useEffect(() => {
    if (!host || settingsAttempted.current) return;
    settingsAttempted.current = true;
    void loadSettings();
  }, [host, loadSettings]);

  const openSettings = () => {
    setSavedMessage("");
    setSettingsError("");
    setOpen(true);
    if (!loadingSettings) void loadSettings();
  };

  const save = async () => {
    const next = Number(draft.replace(",", "."));
    if (!Number.isFinite(next) || next < 0 || next > 100) {
      setSettingsError("Vul een percentage tussen 0% en 100% in.");
      return;
    }
    setSaving(true);
    setSettingsError("");
    setSavedMessage("");
    try {
      const result = await authenticatedRequest("/api/exchanges/aster/profit-sweep-settings", {
        method: "PUT",
        body: JSON.stringify({ enabled, sweepPercent: next }),
      });
      const saved = Number(result.sweepPercent);
      if (!Number.isFinite(saved)) throw new Error("Opslaan is niet bevestigd");
      setEnabled(result.enabled === true);
      setPercent(saved);
      setDraft(String(saved));
      setSavedMessage(result.enabled === true ? `Opgeslagen · nieuwe winstboekingen gebruiken ${saved}%` : "Opgeslagen · Profit sparen staat uit");
    } catch (reason) {
      setSettingsError(reason instanceof Error ? reason.message : "Opslaan is mislukt");
    } finally {
      setSaving(false);
    }
  };

  const tile = host ? createPortal(
    <div className="aps-profit-pot-row" aria-label="Profit Pot / Spot">
      <article className="aps-profit-pot-card" data-reference={PROFIT_POT_REFERENCE}>
        <span className="aps-profit-pot-icon">{profitPotIcon()}</span>
        <div className="aps-profit-pot-copy">
          <small>PROFIT POT / SPOT</small>
          <strong>{value}</strong>
        </div>
      </article>
      <button className="aps-profit-save-card" type="button" onClick={openSettings} aria-label="Profit sparen instellen">
        <small>PROFIT SPAREN</small>
        <strong>{percent === null ? "—" : enabled ? `${percent}%` : "UIT"}</strong>
        <em>instellen</em>
      </button>
    </div>,
    host,
  ) : null;

  const examplePercent = Number(draft.replace(",", "."));
  const exampleAmount = Number.isFinite(examplePercent) ? Math.max(0, Math.min(100, examplePercent)) * 0.1 : 0;

  const modal = open && typeof document !== "undefined" ? createPortal(
    <div className="aps-profit-pot-modal" role="presentation" onClick={() => setOpen(false)}>
      <section className="aps-profit-pot-dialog" role="dialog" aria-modal="true" aria-labelledby="aps-profit-pot-title" onClick={(event) => event.stopPropagation()}>
        <div className="aps-profit-pot-dialog-head">
          <div>
            <small>PROFIT POT</small>
            <h2 id="aps-profit-pot-title">Profit sparen</h2>
          </div>
          <button type="button" className="aps-profit-pot-close" onClick={() => setOpen(false)} aria-label="Sluiten">×</button>
        </div>

        <div className="aps-profit-pot-toggle-row">
          <div><strong>Profit sparen</strong><small>Alleen positieve gerealiseerde nettowinst</small></div>
          <button type="button" className={`aps-profit-pot-switch ${enabled ? "on" : ""}`} role="switch" aria-checked={enabled} onClick={() => setEnabled((current) => !current)} disabled={saving}>
            <span />
          </button>
        </div>

        <p className="aps-profit-pot-explainer">Het gekozen percentage geldt alleen voor <strong>nieuwe positieve gerealiseerde nettowinst</strong>. Inleg, positieomvang, margin en ongerealiseerde PnL tellen niet mee.</p>

        <label className="aps-profit-pot-field">
          <span>Spaarpercentage</span>
          <span className="aps-profit-pot-input-wrap">
            <input type="number" min="0" max="100" step="0.1" inputMode="decimal" value={draft} onChange={(event) => setDraft(event.target.value)} disabled={saving} />
            <b>%</b>
          </span>
        </label>

        <div className="aps-profit-pot-presets" aria-label="Snelle percentages">
          {PRESETS.map((preset) => <button key={preset} type="button" onClick={() => setDraft(String(preset))} disabled={saving}>{preset}%</button>)}
        </div>

        <div className="aps-profit-pot-formula">Voorbeeld: bij US$10 nettowinst en {draft || "0"}% sparen wordt US${exampleAmount.toFixed(2)} gereserveerd voor de Profit Pot.</div>
        <div className="aps-profit-pot-config-only">Veiligheidsfase: automatische Futures → Spot-transfer is in deze build nog niet actief. Deze instelling wordt nu alleen per gebruiker opgeslagen.</div>
        {loadingSettings && <div className="aps-profit-pot-message">Instelling laden…</div>}
        {settingsError && <div className="aps-profit-pot-error" role="alert">{settingsError}</div>}
        {savedMessage && <div className="aps-profit-pot-success">{savedMessage}</div>}

        <button className="aps-profit-pot-save" type="button" onClick={save} disabled={saving || loadingSettings}>{saving ? "Opslaan…" : "Instelling opslaan"}</button>
      </section>
    </div>,
    document.body,
  ) : null;

  return <>{tile}{modal}</>;
}
