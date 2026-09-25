"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { authenticatedRequest } from "@/lib/cloud-client";

const TILE_HOST_ID = "aster-position-loss-auto-hedge-host";
const BACK_HOST_ID = "aster-position-loss-auto-hedge-back-host";
const TILE_REFERENCE = "file_00000000340881f4b05212f7cfd82727";
const SETTINGS_REFERENCE = "file_00000000ee58820abf41140132367883";

type AutoHedgeState = {
  available?: boolean;
  ownerOnly?: boolean;
  enabled: boolean;
  thresholdUsd: number;
  workerEnabled?: boolean;
  executionEnabled?: boolean;
  operational?: boolean;
  status?: string;
  lastReport?: {
    mode?: string;
    ordersSent?: number;
    status?: string;
    reason?: string;
    actions?: Array<Record<string, unknown>>;
    final?: Array<Record<string, unknown>>;
  } | null;
  lastError?: string;
};

const DEFAULT_STATE: AutoHedgeState = {
  enabled: false,
  thresholdUsd: 10,
  lastReport: null,
  lastError: "",
};

function shieldIcon() {
  return <svg viewBox="0 0 32 32" aria-hidden="true">
    <path d="M16 3.5 6.5 7.6v7.2c0 6.2 3.8 10.8 9.5 13.2 5.7-2.4 9.5-7 9.5-13.2V7.6L16 3.5Z" fill="none" stroke="currentColor" strokeWidth="2.3" strokeLinejoin="round" />
    <path d="m11.7 15.6 2.7 2.8 5.9-7" fill="none" stroke="currentColor" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round" />
  </svg>;
}

function targetIcon() {
  return <svg viewBox="0 0 32 32" aria-hidden="true">
    <circle cx="16" cy="16" r="9" fill="none" stroke="currentColor" strokeWidth="2" />
    <circle cx="16" cy="16" r="3.5" fill="none" stroke="currentColor" strokeWidth="2" />
    <path d="M16 2v5M16 25v5M2 16h5M25 16h5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
  </svg>;
}

function layersIcon() {
  return <svg viewBox="0 0 32 32" aria-hidden="true">
    <path d="m16 4 11 6-11 6L5 10l11-6Z" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
    <path d="m5 16 11 6 11-6M5 22l11 6 11-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
  </svg>;
}

function clockIcon() {
  return <svg viewBox="0 0 32 32" aria-hidden="true">
    <circle cx="16" cy="16" r="12" fill="none" stroke="currentColor" strokeWidth="2" />
    <path d="M16 9v8l5 3" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
  </svg>;
}

function Toggle({ checked, disabled, onChange, compact = false }: {
  checked: boolean;
  disabled?: boolean;
  onChange: () => void;
  compact?: boolean;
}) {
  return <button
    type="button"
    className={`plah-switch ${checked ? "on" : ""} ${compact ? "compact" : ""}`}
    role="switch"
    aria-checked={checked}
    disabled={disabled}
    onTouchEnd={(event) => event.stopPropagation()}
    onDoubleClick={(event) => event.stopPropagation()}
    onClick={(event) => {
      event.stopPropagation();
      onChange();
    }}
  ><span /></button>;
}

function moneyThreshold(value: number) {
  const digits = Number.isInteger(value) ? 0 : 2;
  return `$${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: digits, maximumFractionDigits: 2 }).format(value)}`;
}

export function AsterPositionLossAutoHedgeBridge() {
  const [tileHost, setTileHost] = useState<HTMLElement | null>(null);
  const [backHost, setBackHost] = useState<HTMLElement | null>(null);
  const [state, setState] = useState<AutoHedgeState>(DEFAULT_STATE);
  const [available, setAvailable] = useState<boolean | null>(null);
  const [draft, setDraft] = useState("10");
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const lastTap = useRef(0);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const next = await authenticatedRequest("/api/exchanges/aster/position-loss-auto-hedge", { cache: "no-store" }) as AutoHedgeState;
      if (next.available === false) {
        setAvailable(false);
        document.documentElement.removeAttribute("data-position-loss-auto-hedge");
        setState(DEFAULT_STATE);
        setError("");
        return;
      }
      const threshold = Number(next.thresholdUsd);
      if (!Number.isFinite(threshold) || threshold <= 0) throw new Error("Auto Hedge verliesgrens is ongeldig.");
      setAvailable(true);
      document.documentElement.setAttribute("data-position-loss-auto-hedge", "true");
      setState(next);
      setDraft(String(threshold));
      setError("");
    } catch (reason) {
      document.documentElement.removeAttribute("data-position-loss-auto-hedge");
      setError(reason instanceof Error ? reason.message : "Auto Hedge kon niet worden geladen.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let alive = true;
    let frame = 0;
    const sync = () => {
      if (!alive) return;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const tile = document.getElementById(TILE_HOST_ID);
        const snapshot = document.querySelector<HTMLElement>(".aster-portfolio-snapshot");
        if (!tile || !snapshot) {
          setTileHost(null);
          setBackHost(null);
          return;
        }
        setTileHost((current) => current === tile ? current : tile);
        let back = document.getElementById(BACK_HOST_ID);
        if (!back) {
          back = document.createElement("div");
          back.id = BACK_HOST_ID;
          back.setAttribute("aria-hidden", "true");
          snapshot.appendChild(back);
        } else if (back.parentElement !== snapshot) {
          snapshot.appendChild(back);
        }
        snapshot.classList.add("plah-has-flip");
        setBackHost((current) => current === back ? current : back);
      });
    };
    const observer = new MutationObserver(sync);
    observer.observe(document.body, { subtree: true, childList: true });
    sync();
    const timer = window.setInterval(sync, 3000);
    return () => {
      alive = false;
      observer.disconnect();
      clearInterval(timer);
      cancelAnimationFrame(frame);
      const snapshot = document.querySelector<HTMLElement>(".aster-portfolio-snapshot");
      snapshot?.classList.remove("plah-has-flip", "plah-is-flipped");
      document.getElementById(BACK_HOST_ID)?.remove();
      document.documentElement.removeAttribute("data-position-loss-auto-hedge");
    };
  }, []);

  useEffect(() => {
    if (!tileHost) return;
    void load();
    const timer = window.setInterval(() => { void load(); }, 10000);
    const onVisible = () => { if (document.visibilityState === "visible") void load(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [tileHost, load]);

  useEffect(() => {
    const snapshot = document.querySelector<HTMLElement>(".aster-portfolio-snapshot");
    if (!snapshot || !backHost) return;
    snapshot.classList.toggle("plah-is-flipped", open);
    backHost.setAttribute("aria-hidden", open ? "false" : "true");
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !saving) setOpen(false);
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKey);
    };
  }, [open, backHost, saving]);

  const persist = async (enabled: boolean, threshold: number, applyNow = false) => {
    if (!Number.isFinite(threshold) || threshold < 0.01 || threshold > 100000) {
      setError("Vul een verliesgrens tussen $0,01 en $100.000 in.");
      return false;
    }
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const endpoint = applyNow
        ? "/api/exchanges/aster/position-loss-auto-hedge/apply"
        : "/api/exchanges/aster/position-loss-auto-hedge";
      const next = await authenticatedRequest(endpoint, {
        method: applyNow ? "POST" : "PUT",
        body: JSON.stringify({ enabled, thresholdUsd: threshold }),
      }) as AutoHedgeState;
      setState(next);
      setDraft(String(Number(next.thresholdUsd)));
      setMessage(applyNow
        ? "Instelling opgeslagen en alle actuele open posities zijn opnieuw gecontroleerd."
        : enabled ? "Auto Hedge staat aan." : "Auto Hedge staat uit.");
      return true;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Auto Hedge kon niet worden opgeslagen.");
      return false;
    } finally {
      setSaving(false);
    }
  };

  const toggle = () => {
    const threshold = Number(draft.replace(",", "."));
    void persist(!state.enabled, threshold, !state.enabled);
  };

  const openFromCard = () => {
    setMessage("");
    setError("");
    setOpen(true);
  };

  const onTouchEnd = () => {
    const now = Date.now();
    if (now - lastTap.current < 340) {
      lastTap.current = 0;
      openFromCard();
    } else {
      lastTap.current = now;
    }
  };

  const threshold = Number(draft.replace(",", "."));
  const sliderValue = Math.max(5, Math.min(100, Number.isFinite(threshold) ? threshold : 10));
  const statusLabel = state.operational ? "ACTIEF" : state.enabled ? "TEST" : "UIT";

  const tile = tileHost && available === true ? createPortal(
    <div
      className="plah-tile"
      data-reference={TILE_REFERENCE}
      role="button"
      tabIndex={0}
      aria-label={`Auto Hedge ${state.enabled ? "actief" : "uit"}, vanaf min ${moneyThreshold(Number(state.thresholdUsd) || 10)} verlies. Dubbel tik voor instellingen.`}
      onDoubleClick={openFromCard}
      onTouchEnd={onTouchEnd}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          openFromCard();
        }
      }}
    >
      <span className="plah-tile-icon">{shieldIcon()}</span>
      <span className="plah-tile-copy">
        <small>AUTO HEDGE</small>
        <strong>vanaf -{moneyThreshold(Number(state.thresholdUsd) || 10)}</strong>
        <em className={state.enabled ? "on" : ""}>{statusLabel}</em>
      </span>
      <Toggle checked={state.enabled} disabled={saving || loading} onChange={toggle} compact />
    </div>,
    tileHost,
  ) : null;

  const settings = backHost && available === true ? createPortal(
    <section className="plah-back" data-reference={SETTINGS_REFERENCE} aria-label="Auto Hedge instellingen">
      <div className="plah-back-scroll">
        <button type="button" className="plah-back-link" onClick={() => setOpen(false)} disabled={saving}>
          <span aria-hidden="true">‹</span> Terug naar Dashboard
        </button>

        <div className="plah-mini-brand"><span>{shieldIcon()}</span><b>AUTO HEDGE</b></div>

        <header className="plah-hero">
          <span className="plah-hero-shield">{shieldIcon()}</span>
          <div>
            <h3>AUTO HEDGE</h3>
            <p>Beschermt verliesgevende posities met een volledige tegengestelde hedge.</p>
          </div>
        </header>

        <div className="plah-toggle-row">
          <div><strong>AUTO HEDGE</strong><em>{statusLabel}</em></div>
          <Toggle checked={state.enabled} disabled={saving} onChange={toggle} />
        </div>

        <div className="plah-threshold-card">
          <div className="plah-threshold-head">
            <label htmlFor="plah-threshold-number">Hedge vanaf verlies per positie</label>
            <span className="plah-threshold-value">{moneyThreshold(Number.isFinite(threshold) ? threshold : 10)}</span>
          </div>
          <input
            className="plah-range"
            type="range"
            min="5"
            max="100"
            step="1"
            value={sliderValue}
            onChange={(event) => setDraft(event.target.value)}
            disabled={saving}
            aria-label="Auto Hedge verliesgrens"
          />
          <div className="plah-range-labels" aria-hidden="true"><span>$5</span><span>$10</span><span>$25</span><span>$50</span><span>$100</span></div>
          <div className="plah-number-row">
            <span>Exact bedrag</span>
            <label><b>$</b><input id="plah-threshold-number" type="number" min="0.01" max="100000" step="0.01" inputMode="decimal" value={draft} onChange={(event) => setDraft(event.target.value)} disabled={saving} /></label>
          </div>
          <p className="plah-info"><span>i</span> Bij -{moneyThreshold(Number.isFinite(threshold) ? threshold : 10)} of lager wordt de tegengestelde zijde aangevuld tot exact 1:1 coin quantity.</p>
        </div>

        <div className="plah-scope-grid">
          <article><span>{layersIcon()}</span><div><small>Bestaande posities</small><strong>Inbegrepen</strong></div><b>✓</b></article>
          <article><span>{clockIcon()}</span><div><small>Nieuwe posities</small><strong>Realtime bewaakt</strong></div><b>✓</b></article>
        </div>

        <div className="plah-monitor-note">
          <span>{targetIcon()}</span>
          <p>Zowel bestaande open posities als nieuwe posities worden continu gemonitord. Bij het bereiken van de ingestelde verliesdrempel wordt alleen de ontbrekende tegen-quantity aangevuld.</p>
        </div>

        {state.enabled && !state.operational ? <div className="plah-test-mode">TESTMODUS · actuele posities worden berekend en gereconcilieerd, maar er worden geen orders verstuurd.</div> : null}
        {error ? <div className="plah-error" role="alert">{error}</div> : null}
        {message ? <div className="plah-success">{message}</div> : null}

        <button
          type="button"
          className="plah-apply"
          disabled={saving || loading}
          onClick={() => void persist(state.enabled, threshold, true)}
        >
          <span aria-hidden="true">⇄</span>
          <span><strong>{saving ? "CONTROLEREN…" : "VOLLEDIG DICHTHEDGEN"}</strong><small>Pas de ingestelde verliesgrens direct toe op alle open posities.</small></span>
        </button>
      </div>
    </section>,
    backHost,
  ) : null;

  return <>{tile}{settings}</>;
}
