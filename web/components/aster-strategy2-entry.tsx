"use client";

import { Component, Suspense, lazy, useEffect, useState, type ReactNode } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";
import { AsterStrategy2Maker } from "@/components/aster-strategy2-maker";

type Props = {
  snapshot: Record<string, unknown> | null;
  serverConfirmed: boolean;
  onConfirmed: (strategy2: Record<string, unknown>) => void;
  onChanged: () => void;
};

type ReleaseFeature = {
  key?: string;
  status?: string;
  beta?: boolean;
  stable?: boolean;
  enabled?: boolean;
  ownerOnly?: boolean;
  updatedAt?: unknown;
};

type ReleaseState = {
  channel?: "BETA" | "STABLE";
  features?: Record<string, ReleaseFeature>;
};

type BotSettingsMode = "legacy" | "configurator3";

type BotSettingsPreference = {
  mode?: BotSettingsMode;
  configurator3Enabled?: boolean;
  configured?: boolean;
};

const MOCKUP_REFERENCE = "file_00000000d63482109f11a4ef9574daf3";
const ConfiguratorV3 = lazy(() =>
  import("@/components/aster-bot-configurator-v3").then((module) => ({ default: module.AsterBotConfiguratorV3 })),
);

class ConfiguratorBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: unknown) { console.error("[BotSettingsDualMode] isolated configurator failure", error); }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}

function strategy2From(snapshot: Record<string, unknown> | null) {
  return snapshot?.strategy2 && typeof snapshot.strategy2 === "object"
    ? snapshot.strategy2 as Record<string, unknown>
    : {};
}

export function AsterStrategy2Entry(props: Props) {
  const [release, setRelease] = useState<ReleaseState | null>(null);
  const [mode, setMode] = useState<BotSettingsMode | null>(null);
  const [switching, setSwitching] = useState(false);
  const [preferenceMessage, setPreferenceMessage] = useState("");

  const strategy2 = strategy2From(props.snapshot);
  const enabled = strategy2.enabled === true;

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      authenticatedRequest("/api/releases/me", { cache: "no-store" }) as Promise<ReleaseState>,
      authenticatedRequest("/api/preferences/bot-settings-ui", { cache: "no-store" }) as Promise<BotSettingsPreference>,
    ]).then(([nextRelease, preference]) => {
      if (cancelled) return;
      setRelease(nextRelease);
      const fallback: BotSettingsMode = nextRelease.channel === "BETA" ? "configurator3" : "legacy";
      const nextMode = preference.mode === "configurator3" || preference.mode === "legacy" ? preference.mode : fallback;
      setMode(nextMode);
      window.localStorage.setItem("tradementor.botSettingsUiVersion", nextMode);
    }).catch(async () => {
      if (cancelled) return;
      try {
        const nextRelease = await authenticatedRequest("/api/releases/me", { cache: "no-store" }) as ReleaseState;
        if (cancelled) return;
        setRelease(nextRelease);
        const local = window.localStorage.getItem("tradementor.botSettingsUiVersion");
        const fallback: BotSettingsMode = nextRelease.channel === "BETA" ? "configurator3" : "legacy";
        setMode(local === "configurator3" || local === "legacy" ? local : fallback);
        setPreferenceMessage("UI-keuze kon niet uit de cloud worden gelezen; de laatst bekende apparaatkeuze wordt gebruikt.");
      } catch {
        if (!cancelled) {
          setRelease({ channel: "STABLE", features: {} });
          setMode("legacy");
          setPreferenceMessage("Nieuwe configurator tijdelijk niet beschikbaar; oude instellingen blijven actief.");
        }
      }
    });
    return () => { cancelled = true; };
  }, []);

  const changeMode = async (nextMode: BotSettingsMode) => {
    if (switching || nextMode === mode) return;
    const previousMode = mode;
    // Build 508: tab navigation is a local UI action and must feel immediate on
    // mobile. Persisting the preference and refreshing release entitlements may
    // take a network round-trip, but neither is allowed to block the visual tab.
    setMode(nextMode);
    window.localStorage.setItem("tradementor.botSettingsUiVersion", nextMode);
    setSwitching(true);
    setPreferenceMessage("");
    try {
      await authenticatedRequest("/api/preferences/bot-settings-ui", {
        method: "PUT",
        body: JSON.stringify({ mode: nextMode }),
      });
      setPreferenceMessage(
        nextMode === "configurator3"
          ? "Nieuwe configurator actief. Je live bot en open posities zijn niet gewijzigd."
          : "Oude instellingen actief. Je live bot en open posities zijn niet gewijzigd.",
      );
      if (nextMode === "configurator3") {
        void authenticatedRequest("/api/releases/me", { cache: "no-store" })
          .then((nextRelease) => setRelease(nextRelease as ReleaseState))
          .catch(() => {
            // Entitlement refresh is best-effort; the selected UI remains usable.
          });
      }
    } catch (error) {
      // Keep the user's chosen tab locally usable even if cloud preference
      // persistence is temporarily unavailable. A later reload can retry sync.
      if (previousMode) window.localStorage.setItem("tradementor.botSettingsUiVersion", nextMode);
      setPreferenceMessage(
        error instanceof Error
          ? `Weergave gewijzigd; cloudopslag volgt later: ${error.message}`
          : "Weergave gewijzigd; cloudopslag volgt later.",
      );
    } finally {
      setSwitching(false);
    }
  };

  const fallback = (
    <div className="botsettings-dual-fallback">
      <p>De nieuwe configurator kon niet worden geladen. Oude instellingen blijven volledig beschikbaar.</p>
      <AsterStrategy2Maker {...props} embedded />
    </div>
  );

  return (
    <article className="botsettings-dual-mode" data-reference={MOCKUP_REFERENCE} data-ui-mode={mode ?? "loading"}>
      <header className="botsettings-dual-heading">
        <div><span className="kicker">ASTER BOT</span><h2>Botinstellingen</h2></div>
        <span className={`strategy-state ${enabled ? "on" : ""}`}>{enabled ? "AAN" : "UIT"}</span>
      </header>

      <div className="botsettings-mode-tabs" role="tablist" aria-label="Botinstellingen weergave">
        <button
          type="button"
          role="tab"
          aria-selected={mode === "legacy"}
          className={mode === "legacy" ? "active" : ""}
          disabled={switching || mode === null}
          onClick={() => void changeMode("legacy")}
        >
          <strong>Oude instellingen</strong>
          <small>Klassieke weergave (huidig)</small>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "configurator3"}
          className={mode === "configurator3" ? "active" : ""}
          disabled={switching || mode === null}
          onClick={() => void changeMode("configurator3")}
        >
          <span><strong>Nieuwe configurator</strong><em>BETA</em></span>
          <small>Vereenvoudigde configurator 3.0</small>
        </button>
      </div>

      <div className="botsettings-mode-info">
        <span aria-hidden="true">ⓘ</span>
        <p>Beide versies gebruiken dezelfde instellingen en trading-engine. Je kunt op elk moment wisselen. Je live bot en open posities blijven actief.</p>
      </div>
      {preferenceMessage && <p className="botsettings-mode-message" aria-live="polite">{preferenceMessage}</p>}

      {mode === null ? (
        <div className="botsettings-mode-loading">Botinstellingen laden…</div>
      ) : mode === "legacy" ? (
        <AsterStrategy2Maker {...props} embedded />
      ) : (
        <ConfiguratorBoundary fallback={fallback}>
          <Suspense fallback={<div className="botsettings-mode-loading">Bot Configurator 3.0 laden…</div>}>
            <ConfiguratorV3 {...props} release={release ?? { channel: "STABLE", features: {} }} />
          </Suspense>
        </ConfiguratorBoundary>
      )}

      <style>{`
        .botsettings-dual-mode{display:grid;gap:14px;min-width:0}
        .botsettings-dual-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;padding:2px 2px 0}
        .botsettings-dual-heading h2{margin:4px 0 0;font-size:clamp(30px,7vw,42px);line-height:1.02;letter-spacing:-.035em}
        .botsettings-mode-tabs{display:grid;grid-template-columns:1fr 1fr;border:1px solid rgba(190,205,188,.48);border-radius:18px;overflow:hidden;background:rgba(3,15,10,.72);box-shadow:inset 0 0 0 1px rgba(214,181,90,.08)}
        .botsettings-mode-tabs button{min-width:0;border:0;border-radius:17px;padding:12px 10px 11px;background:transparent;color:rgba(240,244,241,.9);display:grid;gap:4px;text-align:center;cursor:pointer;transition:.18s ease}
        .botsettings-mode-tabs button+button{border-left:1px solid rgba(190,205,188,.26)}
        .botsettings-mode-tabs button.active{background:linear-gradient(135deg,rgba(0,122,76,.72),rgba(0,187,118,.48));box-shadow:inset 0 0 0 1px rgba(45,255,166,.95),0 0 22px rgba(0,220,135,.12);color:#fff}
        .botsettings-mode-tabs button:disabled{cursor:default;opacity:.72}
        .botsettings-mode-tabs strong{font-size:15px;line-height:1.15}
        .botsettings-mode-tabs small{font-size:11px;line-height:1.2;color:rgba(225,232,227,.68);white-space:normal}
        .botsettings-mode-tabs span{display:flex;align-items:center;justify-content:center;gap:7px;min-width:0}
        .botsettings-mode-tabs em{font-style:normal;font-size:10px;font-weight:900;letter-spacing:.04em;color:#1b1605;background:linear-gradient(180deg,#f6d35b,#d9a92f);border-radius:999px;padding:3px 7px;box-shadow:0 0 12px rgba(226,182,52,.22)}
        .botsettings-mode-info{display:grid;grid-template-columns:28px 1fr;align-items:center;gap:10px;border:1px solid rgba(21,218,140,.5);border-radius:16px;padding:12px 14px;background:linear-gradient(180deg,rgba(5,38,28,.72),rgba(3,20,15,.82))}
        .botsettings-mode-info>span{font-size:22px;color:#78bdff}
        .botsettings-mode-info p{margin:0;color:rgba(235,242,238,.84);font-size:12px;line-height:1.5}
        .botsettings-mode-message{margin:-5px 3px 0;color:rgba(214,224,218,.7);font-size:11px;line-height:1.35}
        .botsettings-mode-loading{min-height:160px;border:1px solid rgba(214,181,90,.24);border-radius:18px;display:grid;place-items:center;color:rgba(230,235,232,.7);background:rgba(3,15,10,.55)}
        .botsettings-dual-fallback>p{margin:0 0 10px;padding:10px 12px;border:1px solid rgba(214,181,90,.35);border-radius:12px;color:#e8d48f;background:rgba(34,27,7,.5)}
        @media(max-width:430px){
          .botsettings-dual-mode{gap:12px}
          .botsettings-mode-tabs button{padding:11px 7px 10px}
          .botsettings-mode-tabs strong{font-size:13px}
          .botsettings-mode-tabs small{font-size:10px}
          .botsettings-mode-tabs em{font-size:9px;padding:2px 6px}
          .botsettings-mode-info{grid-template-columns:24px 1fr;padding:10px 11px}
          .botsettings-mode-info p{font-size:11px}
        }
        @media(max-width:350px){
          .botsettings-mode-tabs strong{font-size:12px}
          .botsettings-mode-tabs small{font-size:9px}
          .botsettings-mode-tabs button{padding-inline:5px}
        }
      `}</style>
    </article>
  );
}
