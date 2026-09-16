"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { authenticatedRequest } from "@/lib/cloud-client";

const SETTINGS_HOST_ID = "aster-profit-sweep-settings-host";
const PRESETS = [5, 10, 25, 50] as const;

export function AsterProfitSweepSettingsBridge() {
  const [host, setHost] = useState<HTMLElement | null>(null);
  const [open, setOpen] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [percent, setPercent] = useState<number | null>(null);
  const [automaticTransferEnabled, setAutomaticTransferEnabled] = useState(false);
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
      setAutomaticTransferEnabled(result.automaticTransferEnabled === true);
    } catch (reason) {
      setSettingsError(reason instanceof Error ? reason.message : "Profit sparen kon niet worden geladen");
    } finally {
      setLoadingSettings(false);
    }
  }, []);

  useEffect(() => {
    let alive = true;
    const sync = () => {
      if (!alive) return;
      const next = document.getElementById(SETTINGS_HOST_ID);
      setHost((current) => current === next ? current : next);
    };
    const observer = new MutationObserver(sync);
    observer.observe(document.body, { subtree: true, childList: true });
    sync();
    const timer = window.setInterval(sync, 5000);
    return () => {
      alive = false;
      observer.disconnect();
      window.clearInterval(timer);
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
      const automatic = result.automaticTransferEnabled === true;
      setEnabled(result.enabled === true);
      setPercent(saved);
      setDraft(String(saved));
      setAutomaticTransferEnabled(automatic);
      setSavedMessage(
        result.enabled === true
          ? automatic
            ? `Opgeslagen · automatisch sparen actief op ${saved}%`
            : `Opgeslagen · nieuwe winstboekingen gebruiken ${saved}%`
          : "Opgeslagen · Profit sparen staat uit",
      );
    } catch (reason) {
      setSettingsError(reason instanceof Error ? reason.message : "Opslaan is mislukt");
    } finally {
      setSaving(false);
    }
  };

  const button = host ? createPortal(
    <button className="aps-profit-save-card" type="button" onClick={openSettings} aria-label="Profit sparen instellen">
      <small>PROFIT SPAREN</small>
      <strong>{percent === null ? "—" : enabled ? `${percent}%` : "UIT"}</strong>
      <em>{enabled && automaticTransferEnabled ? "automatisch" : "instellen"}</em>
    </button>,
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
        {enabled && automaticTransferEnabled ? (
          <div className="aps-profit-pot-config-only"><strong>Automatisch actief.</strong> Na een bevestigde winstgevende Aster-sluiting wordt het ingestelde percentage veilig van Futures naar Spot verplaatst. Bij verlies, onvoldoende vrije margin of onzekere transfer wordt niets opnieuw verstuurd.</div>
        ) : (
          <div className="aps-profit-pot-config-only">Automatische Futures → Spot-transfer is nog niet actief voor deze instelling. Opslaan bewaart wel jouw percentage voor toekomstige winstboekingen.</div>
        )}
        {loadingSettings && <div className="aps-profit-pot-message">Instelling laden…</div>}
        {settingsError && <div className="aps-profit-pot-error" role="alert">{settingsError}</div>}
        {savedMessage && <div className="aps-profit-pot-success">{savedMessage}</div>}

        <button className="aps-profit-pot-save" type="button" onClick={save} disabled={saving || loadingSettings}>{saving ? "Opslaan…" : "Instelling opslaan"}</button>
      </section>
    </div>,
    document.body,
  ) : null;

  return <>{button}{modal}</>;
}
