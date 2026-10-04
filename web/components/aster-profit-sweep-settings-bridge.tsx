"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { authenticatedRequest } from "@/lib/cloud-client";

const SETTINGS_HOST_ID = "aster-profit-sweep-settings-host";
const PRESETS = [5, 10, 25, 50] as const;

function money(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "US$ —";
  return `US$ ${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value)}`;
}

export function AsterProfitSweepSettingsBridge() {
  const [host, setHost] = useState<HTMLElement | null>(null);
  const [open, setOpen] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [percent, setPercent] = useState<number | null>(null);
  const [draft, setDraft] = useState("5");
  const [minimumTransfer, setMinimumTransfer] = useState("1");
  const [pendingSavings, setPendingSavings] = useState<number | null>(null);
  const [todayTransferred, setTodayTransferred] = useState<number | null>(null);
  const [spotUsdcBalance, setSpotUsdcBalance] = useState<number | null>(null);
  const [transferInFlight, setTransferInFlight] = useState(false);
  const [automaticTransferEnabled, setAutomaticTransferEnabled] = useState(false);
  const [transferAsset, setTransferAsset] = useState<"USDT" | "USDC">("USDT");
  const [loadingSettings, setLoadingSettings] = useState(false);
  const [saving, setSaving] = useState(false);
  const [settingsError, setSettingsError] = useState("");
  const [savedMessage, setSavedMessage] = useState("");
  const settingsAttempted = useRef(false);

  const applySettings = useCallback((result: any) => {
    const next = Number(result.sweepPercent);
    const minimum = Number(result.minimumTransfer ?? 1);
    if (!Number.isFinite(next) || next < 0 || next > 100) throw new Error("Ongeldig spaarpercentage ontvangen");
    if (!Number.isFinite(minimum) || minimum <= 0) throw new Error("Ongeldige minimale transfer ontvangen");
    setEnabled(result.enabled === true);
    setPercent(next);
    setDraft(String(next));
    setMinimumTransfer(String(minimum));
    setPendingSavings(Number.isFinite(Number(result.pendingSavings)) ? Number(result.pendingSavings) : 0);
    setTodayTransferred(Number.isFinite(Number(result.todayTransferred)) ? Number(result.todayTransferred) : 0);
    setTransferInFlight(result.transferInFlight === true);
    setAutomaticTransferEnabled(result.automaticTransferEnabled === true);
    setTransferAsset(result.transferAsset === "USDC" ? "USDC" : "USDT");
  }, []);

  const loadSpotBalance = useCallback(async () => {
    try {
      const result = await authenticatedRequest("/api/exchanges/aster/spot-balance?asset=USDC", { cache: "no-store" });
      const total = Number(result.total ?? 0);
      setSpotUsdcBalance(Number.isFinite(total) ? total : 0);
    } catch {
      setSpotUsdcBalance(null);
    }
  }, []);

  const loadSettings = useCallback(async () => {
    setLoadingSettings(true);
    setSettingsError("");
    try {
      const [settingsResult] = await Promise.all([
        authenticatedRequest("/api/exchanges/aster/profit-sweep-settings", { cache: "no-store" }),
        loadSpotBalance(),
      ]);
      applySettings(settingsResult);
    } catch (reason) {
      setSettingsError(reason instanceof Error ? reason.message : "Profit sparen kon niet worden geladen");
    } finally {
      setLoadingSettings(false);
    }
  }, [applySettings, loadSpotBalance]);

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

  useEffect(() => {
    const openFromProfitPot = () => {
      setSavedMessage("");
      setSettingsError("");
      setOpen(true);
      void loadSettings();
    };
    window.addEventListener("aster-profit-pot-open", openFromProfitPot);
    return () => window.removeEventListener("aster-profit-pot-open", openFromProfitPot);
  }, [loadSettings]);

  const openSettings = () => {
    setSavedMessage("");
    setSettingsError("");
    setOpen(true);
    if (!loadingSettings) void loadSettings();
  };

  const save = async () => {
    const next = Number(draft.replace(",", "."));
    const threshold = Number(minimumTransfer.replace(",", "."));
    if (!Number.isFinite(next) || next < 0 || next > 100) {
      setSettingsError("Vul een percentage tussen 0% en 100% in.");
      return;
    }
    if (!Number.isFinite(threshold) || threshold < 0.01 || threshold > 1000) {
      setSettingsError("Vul een minimale transfer tussen US$ 0,01 en US$ 1.000 in.");
      return;
    }
    setSaving(true);
    setSettingsError("");
    setSavedMessage("");
    try {
      const result = await authenticatedRequest("/api/exchanges/aster/profit-sweep-settings", {
        method: "PUT",
        body: JSON.stringify({ enabled, sweepPercent: next, minimumTransfer: threshold, transferAsset }),
      });
      applySettings(result);
      setSavedMessage(result.enabled === true ? "Opgeslagen · Profit sparen actief" : "Opgeslagen · Profit sparen staat uit");
      window.dispatchEvent(new CustomEvent("aster-profit-sweep-settings-updated"));
      window.setTimeout(() => setOpen(false), 500);
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

  const thresholdValue = Number(minimumTransfer.replace(",", "."));
  const safeThreshold = Number.isFinite(thresholdValue) && thresholdValue > 0 ? thresholdValue : 1;

  const modal = open && typeof document !== "undefined" ? createPortal(
    <div className="aps-profit-pot-modal aps-profit-pot-flip-scene" role="presentation" onClick={() => setOpen(false)}>
      <section className="aps-profit-pot-dialog aps-profit-pot-flip-back" role="dialog" aria-modal="true" aria-labelledby="aps-profit-pot-title" onClick={(event) => event.stopPropagation()}>
        <div className="aps-profit-pot-dialog-head">
          <div>
            <small>PROFIT POT INSTELLINGEN</small>
            <h2 id="aps-profit-pot-title">Automatisch sparen naar Spot</h2>
          </div>
          <button type="button" className="aps-profit-pot-close" onClick={() => setOpen(false)} aria-label="Sluiten">×</button>
        </div>

        <div className="aps-profit-pot-setting-list">
          <div className="aps-profit-pot-setting-row">
            <span>Profit Sparen</span>
            <button type="button" className={`aps-profit-pot-switch ${enabled ? "on" : ""}`} role="switch" aria-checked={enabled} onClick={() => setEnabled((current) => !current)} disabled={saving}>
              <span />
            </button>
          </div>

          <label className="aps-profit-pot-setting-row aps-profit-pot-setting-edit">
            <span>Spaarpercentage</span>
            <span className="aps-profit-pot-compact-input">
              <input type="number" min="0" max="100" step="0.1" inputMode="decimal" value={draft} onChange={(event) => setDraft(event.target.value)} disabled={saving} />
              <b>%</b>
            </span>
          </label>
          <div className="aps-profit-pot-presets" aria-label="Snelle percentages">
            {PRESETS.map((preset) => <button key={preset} type="button" onClick={() => setDraft(String(preset))} disabled={saving}>{preset}%</button>)}
          </div>

          <label className="aps-profit-pot-setting-row aps-profit-pot-setting-edit">
            <span>Minimale transfer</span>
            <span className="aps-profit-pot-compact-input money">
              <b>US$</b>
              <input type="number" min="0.01" max="1000" step="0.01" inputMode="decimal" value={minimumTransfer} onChange={(event) => setMinimumTransfer(event.target.value)} disabled={saving} />
            </span>
          </label>

          <div className="aps-profit-pot-setting-row">
            <span>Huidig opgespaard</span>
            <strong>{money(pendingSavings)}</strong>
          </div>
          <div className="aps-profit-pot-setting-row">
            <span>Vandaag naar Spot</span>
            <strong>{money(todayTransferred)}</strong>
          </div>
          <div className="aps-profit-pot-setting-row">
            <span>Spot saldo (USDC)</span>
            <strong>{money(spotUsdcBalance)}</strong>
          </div>
          <div className="aps-profit-pot-setting-row">
            <span>Transfer naar</span>
            <strong>Spot wallet · {transferAsset}</strong>
          </div>
          <div className="aps-profit-pot-setting-row">
            <span>Alleen positieve winsttrades</span>
            <span className="aps-profit-pot-fixed-on">AAN</span>
          </div>
          <div className="aps-profit-pot-setting-row">
            <span>Kleine bedragen opsparen</span>
            <span className="aps-profit-pot-fixed-on">AAN</span>
          </div>
          <div className="aps-profit-pot-setting-row">
            <span>Opnieuw proberen bij mislukte transfer</span>
            <span className="aps-profit-pot-fixed-on">AAN</span>
          </div>
        </div>

        <div className="aps-profit-pot-simple-info">
          {draft || "0"}% van iedere positieve gesloten nettowinst wordt toegevoegd aan de spaarbuffer. Zodra de spaarpot {money(safeThreshold)} bereikt, wordt één drempelbedrag automatisch naar Spot overgezet.
        </div>
        {transferInFlight && <div className="aps-profit-pot-message">Een drempeltransfer wordt veilig verwerkt.</div>}
        {loadingSettings && <div className="aps-profit-pot-message">Instellingen laden…</div>}
        {settingsError && <div className="aps-profit-pot-error" role="alert">{settingsError}</div>}
        {savedMessage && <div className="aps-profit-pot-success">{savedMessage}</div>}

        <div className="aps-profit-pot-actions">
          <button className="aps-profit-pot-cancel" type="button" onClick={() => setOpen(false)} disabled={saving}>Annuleren</button>
          <button className="aps-profit-pot-save" type="button" onClick={save} disabled={saving || loadingSettings}>{saving ? "Opslaan…" : "Opslaan"}</button>
        </div>
      </section>
    </div>,
    document.body,
  ) : null;

  return <>{button}{modal}</>;
}
