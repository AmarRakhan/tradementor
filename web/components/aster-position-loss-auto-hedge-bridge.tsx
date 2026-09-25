"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { authenticatedRequest } from "@/lib/cloud-client";

const TILE_HOST_ID = "aster-position-loss-auto-hedge-host";
const SCREEN_HOST_ID = "aster-position-loss-auto-hedge-back-host";
const TILE_REFERENCE = "file_00000000340881f4b05212f7cfd82727";
const SCREEN_REFERENCE = "file_00000000ecd08246bd1b15532fb478d6";

type LegView = {
  quantity?: number;
  entryPrice?: number;
  markPrice?: number;
  openPnl?: number;
  leverage?: number;
} | null;

type PairState = {
  symbol: string;
  status?: string;
  protectedSide?: "LONG" | "SHORT";
  hedgeSide?: "LONG" | "SHORT";
  generationId?: string;
  triggerAt?: string;
  triggerPnl?: number;
  recoveryAt?: string;
  rehedgeEnabled?: boolean;
  currentProtectedQty?: number;
  currentHedgeQty?: number;
  reservedHedgeQty?: number;
  normalFreeQty?: number;
  hedgeRatio?: number | null;
  protectedLeg?: LegView;
  hedgeLeg?: LegView;
  lastReason?: string;
  lastReconciledAt?: string;
};

type AutoHedgeState = {
  available?: boolean;
  ownerOnly?: boolean;
  enabled: boolean;
  thresholdUsd: number;
  workerEnabled?: boolean;
  executionEnabled?: boolean;
  operational?: boolean;
  status?: string;
  lastCheckedAt?: string;
  pairs?: PairState[];
  previewPairs?: Array<Record<string, unknown>>;
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
  pairs: [],
  previewPairs: [],
  lastReport: null,
  lastError: "",
};

function shieldIcon() {
  return <svg viewBox="0 0 32 32" aria-hidden="true">
    <path d="M16 3.5 6.5 7.6v7.2c0 6.2 3.8 10.8 9.5 13.2 5.7-2.4 9.5-7 9.5-13.2V7.6L16 3.5Z" fill="none" stroke="currentColor" strokeWidth="2.3" strokeLinejoin="round" />
    <path d="m11.7 15.6 2.7 2.8 5.9-7" fill="none" stroke="currentColor" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round" />
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

function gearIcon() {
  return <svg viewBox="0 0 32 32" aria-hidden="true">
    <circle cx="16" cy="16" r="5" fill="none" stroke="currentColor" strokeWidth="2" />
    <path d="M16 3v4M16 25v4M3 16h4M25 16h4M6.8 6.8l2.8 2.8M22.4 22.4l2.8 2.8M25.2 6.8l-2.8 2.8M9.6 22.4l-2.8 2.8" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
  </svg>;
}

function Toggle({ checked, disabled, onChange, compact = false, label, labelText = false }: {
  checked: boolean;
  disabled?: boolean;
  onChange: () => void;
  compact?: boolean;
  label?: string;
  labelText?: boolean;
}) {
  return <button
    type="button"
    className={`plah-switch ${checked ? "on" : ""} ${compact ? "compact" : ""} ${labelText ? "labeled" : ""}`}
    role="switch"
    aria-checked={checked}
    aria-label={label}
    disabled={disabled}
    onTouchEnd={(event) => event.stopPropagation()}
    onDoubleClick={(event) => event.stopPropagation()}
    onClick={(event) => {
      event.stopPropagation();
      onChange();
    }}
  >{labelText ? <em>{checked ? "AAN" : "UIT"}</em> : null}<span /></button>;
}

function nlNumber(value: number | undefined, maximumFractionDigits = 8) {
  if (!Number.isFinite(Number(value))) return "–";
  return new Intl.NumberFormat("nl-NL", { maximumFractionDigits }).format(Number(value));
}

function money(value: number | undefined, signed = true) {
  if (!Number.isFinite(Number(value))) return "–";
  const number = Number(value);
  const sign = signed && number > 0 ? "+" : "";
  return `${sign}$${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(number)}`;
}

function thresholdMoney(value: number) {
  const digits = Number.isInteger(value) ? 0 : 2;
  return `$${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: digits, maximumFractionDigits: 2 }).format(value)}`;
}

function statusLabel(status?: string) {
  const value = String(status || "").toUpperCase();
  if (value === "HEDGED") return "HEDGED";
  if (value === "HEDGING" || value === "ADJUSTING") return "BIJWERKEN";
  if (value === "RECOVERY") return "RECOVERY";
  if (value === "REHEDGE_ARMED") return "GEWAPEND";
  if (value === "DISABLED") return "UITGESCHAKELD";
  if (value === "BLOCKED" || value === "ERROR" || value === "PRECISION_BLOCKED") return "FOUT";
  if (value === "CLOSED") return "GESLOTEN";
  return value || "ONBEKEND";
}

function statusClass(status?: string) {
  const value = String(status || "").toUpperCase();
  if (value === "HEDGED") return "hedged";
  if (value === "HEDGING" || value === "ADJUSTING") return "adjusting";
  if (value === "RECOVERY") return "recovery";
  if (value === "REHEDGE_ARMED") return "armed";
  if (value === "DISABLED" || value === "CLOSED") return "disabled";
  return "error";
}

function PairLeg({ side, role, leg }: {
  side: "LONG" | "SHORT";
  role: string;
  leg: LegView;
}) {
  if (!leg) return null;
  const pnl = Number(leg.openPnl || 0);
  return <div className="plah-leg-row">
    <span className={`plah-side-badge ${side.toLowerCase()}`}>{side}</span>
    <span className={`plah-role-badge ${role.toLowerCase().replaceAll(" ", "-")}`}>{role}</span>
    <span className="plah-leg-cell"><small>Qty</small><b>{nlNumber(leg.quantity)}</b></span>
    <span className="plah-leg-cell"><small>Entry</small><b>{nlNumber(leg.entryPrice, 6)}</b></span>
    <span className="plah-leg-cell"><small>Mark</small><b>{nlNumber(leg.markPrice, 6)}</b></span>
    <span className="plah-leg-cell pnl"><small>Open PnL</small><b className={pnl >= 0 ? "positive" : "negative"}>{money(pnl)}</b></span>
  </div>;
}

function CoinBadge({ symbol }: { symbol: string }) {
  const label = symbol.replace(/USDT$/i, "");
  return <span className="plah-coin-badge" aria-hidden="true">{label.slice(0, 2)}</span>;
}

function PairCard({ pair, saving, onRehedge }: {
  pair: PairState;
  saving: boolean;
  onRehedge: (pair: PairState, enabled: boolean) => void;
}) {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const status = String(pair.status || "").toUpperCase();
  const recovery = status === "RECOVERY" || status === "REHEDGE_ARMED" || status === "DISABLED";
  const protectedSide = pair.protectedSide || "SHORT";
  const hedgeSide = pair.hedgeSide || (protectedSide === "SHORT" ? "LONG" : "SHORT");
  const protectedPnl = Number(pair.protectedLeg?.openPnl || 0);
  const hedgePnl = Number(pair.hedgeLeg?.openPnl || 0);
  const net = protectedPnl + hedgePnl;
  const ratio = Number(pair.hedgeRatio);
  const stamp = recovery ? pair.recoveryAt || pair.triggerAt : pair.triggerAt;
  const stampText = stamp ? new Date(stamp).toLocaleString("nl-NL", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "";

  return <article className={`plah-pair-card ${statusClass(status)}`}>
    <div className="plah-pair-head">
      <div className="plah-pair-identity">
        <CoinBadge symbol={pair.symbol} />
        <div>
          <div className="plah-pair-title-row">
            <strong>{pair.symbol.replace(/USDT$/i, "")}</strong>
            <span className="plah-pair-chevron" aria-hidden="true">⌄</span>
            <span className={`plah-status-badge ${statusClass(status)}`}>{statusLabel(status)}</span>
          </div>
          {recovery ? <small className="plah-recovery-meta">
            <span>{stampText ? `Gehedged op ${stampText}` : "Eerder gehedged"}</span>
            <b>{status === "DISABLED" ? "Handmatig uitgeschakeld" : `Tegenpositie gesloten (${protectedSide})`}</b>
          </small> : <small>{stampText ? `Sinds ${stampText}` : "Auto Hedge actief"}</small>}
        </div>
      </div>

      <div className="plah-pair-actions">
        {recovery ? <div className="plah-rehedge-control">
          <span>Opnieuw hedgen</span>
          <Toggle
            checked={pair.rehedgeEnabled === true}
            disabled={saving}
            onChange={() => onRehedge(pair, pair.rehedgeEnabled !== true)}
            compact
            label={`Opnieuw hedgen voor ${pair.symbol}`}
          />
        </div> : <div className="plah-lock-state">
          <span>{shieldIcon()}</span>
          <div><small>Auto Hedge</small><b>Actief en vergrendeld</b></div>
        </div>}
        <button type="button" className="plah-more" aria-expanded={detailsOpen} aria-label={`Details ${pair.symbol}`} onClick={() => setDetailsOpen((value) => !value)}>⋮</button>
      </div>
    </div>

    <div className="plah-leg-stack">
      {!recovery && <PairLeg side={protectedSide} role="Beschermd" leg={pair.protectedLeg || null} />}
      <PairLeg
        side={recovery ? hedgeSide : hedgeSide}
        role={recovery ? "Recovery" : "Hedge-lock"}
        leg={pair.hedgeLeg || null}
      />
    </div>

    {!recovery ? <div className="plah-pair-summary">
      <span><small>Netto pair resultaat</small><b className={net >= 0 ? "positive" : "negative"}>{money(net)}</b></span>
      <span><small>Hedge ratio</small><b>{Number.isFinite(ratio) ? `${nlNumber(ratio, 1)}% (1:1)` : "–"}</b></span>
      <span><small>Status</small><b>{status === "HEDGED" ? "Volledig gehedged" : statusLabel(status)}</b></span>
    </div> : <div className="plah-recovery-note">
      <span>i</span>
      <p>
        Deze positie was eerder gehedged. De tegenpositie is gesloten.
        Zet <strong>Opnieuw hedgen</strong> aan om deze positie weer onder Auto Hedge-bescherming te brengen.
      </p>
    </div>}

    {status === "ADJUSTING" && <div className="plah-adjust-note">Quantity wordt automatisch teruggebracht naar exact 1:1.</div>}
    {(status === "BLOCKED" || status === "ERROR" || status === "PRECISION_BLOCKED") && <div className="plah-pair-error">{pair.lastReason || "Auto Hedge kan deze pair momenteel niet veilig bijwerken."}</div>}
    {detailsOpen && <div className="plah-technical-details">
      <span><small>Cyclus</small><b>{pair.generationId || "–"}</b></span>
      <span><small>Trigger PnL</small><b>{money(pair.triggerPnl)}</b></span>
      <span><small>Gereserveerd</small><b>{nlNumber(pair.reservedHedgeQty)}</b></span>
      <span><small>Vrije quantity</small><b>{nlNumber(pair.normalFreeQty)}</b></span>
      <p>{pair.lastReason || "Geen aanvullende melding."}</p>
    </div>}
  </article>;
}

export function AsterPositionLossAutoHedgeBridge() {
  const [tileHost, setTileHost] = useState<HTMLElement | null>(null);
  const [screenHost, setScreenHost] = useState<HTMLElement | null>(null);
  const [state, setState] = useState<AutoHedgeState>(DEFAULT_STATE);
  const [available, setAvailable] = useState<boolean | null>(null);
  const [draft, setDraft] = useState("10");
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [coinFilter, setCoinFilter] = useState("ALL");
  const lastTap = useRef(0);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const next = await authenticatedRequest("/api/exchanges/aster/position-loss-auto-hedge", { cache: "no-store" }) as AutoHedgeState;
      if (next.available === false) {
        setAvailable(false);
        document.documentElement.removeAttribute("data-position-loss-auto-hedge");
        setState(DEFAULT_STATE);
        return;
      }
      const threshold = Number(next.thresholdUsd);
      if (!Number.isFinite(threshold) || threshold <= 0) throw new Error("Auto Hedge verliesgrens is ongeldig.");
      setAvailable(true);
      document.documentElement.setAttribute("data-position-loss-auto-hedge", "true");
      setState({ ...next, pairs: Array.isArray(next.pairs) ? next.pairs : [] });
      setDraft(String(threshold));
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Auto Hedge kon niet worden geladen.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let alive = true;
    const sync = () => {
      if (!alive) return;
      const tile = document.getElementById(TILE_HOST_ID);
      setTileHost(tile);
      let host = document.getElementById(SCREEN_HOST_ID);
      if (!host) {
        host = document.createElement("div");
        host.id = SCREEN_HOST_ID;
        host.setAttribute("aria-hidden", "true");
        document.body.appendChild(host);
      }
      setScreenHost(host);
    };
    const observer = new MutationObserver(sync);
    observer.observe(document.body, { subtree: true, childList: true });
    sync();
    return () => {
      alive = false;
      observer.disconnect();
      document.getElementById(SCREEN_HOST_ID)?.remove();
      document.documentElement.removeAttribute("data-position-loss-auto-hedge");
      document.documentElement.removeAttribute("data-auto-hedge-screen-open");
    };
  }, []);

  useEffect(() => {
    if (!tileHost) return;
    void load();
    const timer = window.setInterval(() => { void load(); }, open ? 3000 : 10000);
    const onVisible = () => { if (document.visibilityState === "visible") void load(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [tileHost, load, open]);

  useEffect(() => {
    const currentPairs = Array.isArray(state.pairs) ? state.pairs : [];
    const syncTradecentrum = () => {
      const tradecentrum = document.querySelector<HTMLElement>(
        'article[data-reference="nexora_tradecentrum_actieve_posities.png"]',
      );
      if (!tradecentrum) return;
      const rows = Array.from(tradecentrum.querySelectorAll<HTMLElement>('[role="table"]>[role="row"]')).slice(1);
      for (const row of rows) {
        const coinCell = row.querySelector<HTMLElement>('button[role="cell"]');
        if (!coinCell) continue;
        const existing = coinCell.querySelector<HTMLElement>(".plah-tc-auto-hedge");
        const text = (coinCell.textContent || "").toUpperCase();
        const pair = currentPairs.find((item) => {
          const coin = String(item.symbol || "").replace(/USDT$/i, "").toUpperCase();
          return coin.length >= 2 && (text.startsWith(coin) || text.includes(` ${coin}`));
        });
        if (!pair) {
          existing?.remove();
          continue;
        }
        const small = coinCell.querySelector<HTMLElement>("small");
        if (!small) continue;
        const cls = statusClass(pair.status);
        const label = `AH ${statusLabel(pair.status)}`;
        const badge = existing || document.createElement("em");
        const nextClass = `plah-tc-auto-hedge ${cls}`;
        if (badge.className !== nextClass) badge.className = nextClass;
        if (badge.textContent !== label) badge.textContent = label;
        badge.title = "Auto Hedge-status";
        if (!existing) small.appendChild(badge);
      }
    };
    syncTradecentrum();
    const observer = new MutationObserver(syncTradecentrum);
    observer.observe(document.body, { subtree: true, childList: true });
    return () => {
      observer.disconnect();
      document.querySelectorAll(".plah-tc-auto-hedge").forEach((node) => node.remove());
    };
  }, [state.pairs]);

  useEffect(() => {
    if (!screenHost) return;
    screenHost.classList.toggle("plah-screen-open", open);
    screenHost.setAttribute("aria-hidden", open ? "false" : "true");
    document.documentElement.toggleAttribute("data-auto-hedge-screen-open", open);
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !saving) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKey);
    };
  }, [open, screenHost, saving]);

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
      setState({ ...next, pairs: Array.isArray(next.pairs) ? next.pairs : [] });
      setDraft(String(Number(next.thresholdUsd)));
      if (!next.executionEnabled) {
        const actions = Array.isArray(next.lastReport?.actions) ? next.lastReport?.actions ?? [] : [];
        const due = actions.filter((item) => Number(item.requiredDelta) > 0).length;
        setMessage(`Testcontrole klaar · ${due} pair${due === 1 ? "" : "s"} vragen een 1:1-aanpassing · 0 orders verstuurd.`);
      } else {
        setMessage(enabled ? "Auto Hedge staat aan." : "Nieuwe Auto Hedge-triggers staan uit; bestaande locks blijven bewaakt.");
      }
      return true;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Auto Hedge kon niet worden opgeslagen.");
      return false;
    } finally {
      setSaving(false);
    }
  };

  const setRehedge = async (pair: PairState, enabled: boolean) => {
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const next = await authenticatedRequest(
        `/api/exchanges/aster/position-loss-auto-hedge/pairs/${encodeURIComponent(pair.symbol)}/rehedge`,
        { method: "PUT", body: JSON.stringify({ enabled }) },
      ) as AutoHedgeState;
      setState({ ...next, pairs: Array.isArray(next.pairs) ? next.pairs : [] });
      setMessage(enabled
        ? `${pair.symbol.replace(/USDT$/i, "")} doet opnieuw mee met Auto Hedge.`
        : `${pair.symbol.replace(/USDT$/i, "")} blijft Recovery zonder automatische rehedge.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Opnieuw hedgen kon niet worden aangepast.");
    } finally {
      setSaving(false);
    }
  };

  const threshold = Number(draft.replace(",", "."));
  const sliderValue = Math.max(5, Math.min(100, Number.isFinite(threshold) ? threshold : 10));
  const pairs = Array.isArray(state.pairs) ? state.pairs : [];
  const hasLockedPair = pairs.some((pair) =>
    ["HEDGING", "HEDGED", "ADJUSTING", "BLOCKED", "ERROR", "PRECISION_BLOCKED"].includes(String(pair.status || "").toUpperCase()),
  );
  const status = state.operational ? "ACTIEF" : state.enabled ? "TEST" : hasLockedPair ? "LOCK" : "UIT";
  const tileStatus = state.enabled ? "ACTIEF" : "UIT";
  const coinOptions = useMemo(() => [...new Set(pairs.map((pair) => pair.symbol))].sort(), [pairs]);
  const visiblePairs = coinFilter === "ALL" ? pairs : pairs.filter((pair) => pair.symbol === coinFilter);

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

  const tile = tileHost && available === true ? createPortal(
    <div
      className="plah-tile"
      data-reference={TILE_REFERENCE}
      role="button"
      tabIndex={0}
      aria-label={`Auto Hedge ${tileStatus}. Dubbel tik voor instellingen.`}
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
        <strong className={state.enabled ? "on" : ""}>{tileStatus}</strong>
      </span>
      <Toggle checked={state.enabled} disabled={saving || loading} onChange={() => void persist(!state.enabled, threshold, !state.enabled)} compact label="Auto Hedge" />
    </div>,
    tileHost,
  ) : null;

  const screen = screenHost && available === true ? createPortal(
    <section className="plah-screen" data-reference={SCREEN_REFERENCE} aria-label="Auto Hedge">
      <div className="plah-screen-scroll">
        <div className="plah-screen-topline">
          <button type="button" className="plah-back-link" onClick={() => setOpen(false)} disabled={saving}>
            <span aria-hidden="true">‹</span> Terug naar Dashboard
          </button>
          <div className="plah-mini-brand"><span>{shieldIcon()}</span><b>AUTO HEDGE</b></div>
        </div>

        <header className="plah-hero">
          <span className="plah-hero-shield">{shieldIcon()}</span>
          <div>
            <h3>AUTO HEDGE</h3>
            <p>Beschermt verliesgevende posities met een volledige tegengestelde hedge.</p>
          </div>
          <Toggle checked={state.enabled} disabled={saving} onChange={() => void persist(!state.enabled, threshold, !state.enabled)} label="Auto Hedge hoofdschakelaar" labelText />
        </header>

        <section className="plah-threshold-card">
          <div className="plah-threshold-head">
            <label htmlFor="plah-threshold-number">Hedge vanaf verlies per positie</label>
            <div className="plah-exact-box"><small>Exact bedrag</small><label><b>$</b><input id="plah-threshold-number" type="number" min="0.01" max="100000" step="0.01" inputMode="decimal" value={draft} onChange={(event) => setDraft(event.target.value)} disabled={saving} /></label></div>
          </div>
          <div className="plah-threshold-value">{thresholdMoney(Number.isFinite(threshold) ? threshold : 10)}</div>
          <input className="plah-range" type="range" min="5" max="100" step="1" value={sliderValue} onChange={(event) => setDraft(event.target.value)} disabled={saving} aria-label="Auto Hedge verliesgrens" />
          <div className="plah-range-labels" aria-hidden="true"><span>$5</span><span>$10</span><span>$25</span><span>$50</span><span>$100</span></div>
          <p className="plah-info"><span>i</span> Bij -{thresholdMoney(Number.isFinite(threshold) ? threshold : 10)} of lager wordt de tegengestelde zijde aangepast tot exact 1:1 coin quantity.</p>
        </section>

        <div className="plah-scope-grid">
          <article><span>{layersIcon()}</span><div><small>Bestaande posities</small><strong>Inbegrepen</strong></div><b>✓</b></article>
          <article><span>{clockIcon()}</span><div><small>Nieuwe posities</small><strong>Realtime bewaakt</strong></div><b>✓</b></article>
          <article><span>{gearIcon()}</span><div><small>Controle-interval</small><strong>Elke 3 seconden</strong></div><b>✓</b></article>
        </div>

        {!state.executionEnabled && <div className="plah-test-mode">
          TESTMODUS · actuele Aster-posities worden exact 1:1 doorgerekend, maar Auto Hedge verstuurt nog geen orders.
        </div>}
        {!state.enabled && hasLockedPair && <div className="plah-lock-off-note">
          Nieuwe triggers staan UIT · bestaande HEDGE_LOCKED-posities blijven beschermd en worden niet vrijgegeven.
        </div>}
        {error && <div className="plah-error" role="alert">{error}</div>}
        {message && <div className="plah-success">{message}</div>}

        <section className="plah-positions">
          <div className="plah-positions-head">
            <div>
              <h4>Gehedgde posities</h4>
              <p>Alleen coins die (in het verleden) door Auto Hedge zijn gehedged.</p>
            </div>
            <select value={coinFilter} onChange={(event) => setCoinFilter(event.target.value)} aria-label="Filter gehedgde coins">
              <option value="ALL">Alle coins</option>
              {coinOptions.map((symbol) => <option value={symbol} key={symbol}>{symbol.replace(/USDT$/i, "")}</option>)}
            </select>
          </div>

          <div className="plah-pair-list">
            {visiblePairs.length ? visiblePairs.map((pair) =>
              <PairCard key={pair.symbol} pair={pair} saving={saving} onRehedge={(item, enabled) => void setRehedge(item, enabled)} />
            ) : <div className="plah-empty">
              <span>{shieldIcon()}</span>
              <strong>Nog geen historische Auto Hedge-pairs</strong>
              <p>Coins verschijnen hier zodra Auto Hedge een pair daadwerkelijk heeft beschermd. Shadow-resultaten worden niet als echte hedge opgeslagen.</p>
            </div>}
          </div>
        </section>

        <section className="plah-important">
          <span>{shieldIcon()}</span>
          <div><b>Belangrijk</b><p>Alleen door Auto Hedge gereserveerde hedge-quantity is vergrendeld. Normale strategieposities blijven normaal werken; verdwijnt normale dekking, dan vult Auto Hedge het ontbrekende verschil opnieuw aan.</p></div>
          <button type="button" onClick={() => void persist(state.enabled, threshold, true)} disabled={saving || loading}>
            {saving ? "Controleren…" : "Nu controleren"} <span>›</span>
          </button>
        </section>
      </div>
    </section>,
    screenHost,
  ) : null;

  return <>{tile}{screen}</>;
}
