"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { authenticatedRequest } from "@/lib/cloud-client";
import { WEBAPP_BUILD_NUMBER } from "@/lib/app-version";

const TILE_HOST_ID = "aster-position-loss-auto-hedge-host";
const SCREEN_HOST_ID = "aster-position-loss-auto-hedge-back-host";
const TILE_REFERENCE = "file_00000000340881f4b05212f7cfd82727";
const SCREEN_REFERENCE = "file_00000000ecd08246bd1b15532fb478d6";
const OVERVIEW_REFERENCE = "file_000000005090821091d88f1b301841d7";
const SCALE_REFERENCE = "file_00000000d23482438b5f8f4588d6cf86";

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

type ScaleLegPreview = {
  side: "LONG" | "SHORT";
  currentQuantity: number;
  addedQuantity: number;
  quantityAfter: number;
  currentEntry: number;
  executionPrice: number;
  estimatedEntryAfter: number;
  entryEffect: "GUNSTIGER" | "ONGUNSTIGER" | "VRIJWEL GELIJK";
  leverage: number;
  currentPrice: number;
  currentBreakEven: number;
  estimatedBreakEvenAfter: number;
  breakEvenDistanceBeforePct: number;
  breakEvenDistanceAfterPct: number;
  breakEvenDirectionBefore: "UP" | "DOWN" | "REACHED";
  breakEvenDirectionAfter: "UP" | "DOWN" | "REACHED";
  breakEvenReachedBefore: boolean;
  breakEvenReachedAfter: boolean;
  distanceChangeKind: "CLOSER" | "FARTHER" | "UNCHANGED" | "ALREADY_REACHED";
  distanceChangePct: number | null;
};

type ScalePreview = {
  eventType: "LEGACY_HEDGE_SCALE";
  symbol: string;
  requestedMarginPerSideUsd: number;
  availableBalance: number;
  extraQuantity: number;
  estimatedLongMarginUsd: number;
  estimatedShortMarginUsd: number;
  estimatedTotalMarginUsd: number;
  estimatedFeesUsd: number;
  estimatedAvailableDebitUsd: number;
  availableAfterEstimate: number;
  hedgeRatioAfter: number;
  long: ScaleLegPreview;
  short: ScaleLegPreview;
  pairResultNote: string;
  generatedAt?: string;
};

type ScaleResult = {
  operationId: string;
  symbol: string;
  status: "SUCCEEDED" | "SUCCEEDED_PARTIAL";
  actualAddedQuantity: number;
  longQtyAfter: number;
  shortQtyAfter: number;
  longEntryAfter: number;
  shortEntryAfter: number;
  hedgeRatioAfter: number;
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
  return `${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: digits, maximumFractionDigits: 2 }).format(value)}`;
}

function pct1(value: number | null | undefined) {
  if (!Number.isFinite(Number(value))) return "–";
  const normalized = Math.abs(Number(value)) < 0.0000001 ? 0 : Number(value);
  return new Intl.NumberFormat("nl-NL", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(normalized);
}

function breakEvenMoveText(leg: ScaleLegPreview | undefined, phase: "before" | "after") {
  if (!leg) return "–";
  const reached = phase === "before" ? leg.breakEvenReachedBefore : leg.breakEvenReachedAfter;
  if (reached) return "Break-even bereikt";
  const distance = phase === "before" ? leg.breakEvenDistanceBeforePct : leg.breakEvenDistanceAfterPct;
  const direction = phase === "before" ? leg.breakEvenDirectionBefore : leg.breakEvenDirectionAfter;
  if (direction === "UP") return `+${pct1(distance)}% omhoog`;
  if (direction === "DOWN") return `−${pct1(distance)}% omlaag`;
  return "Break-even bereikt";
}

function distanceChangeText(leg: ScaleLegPreview | undefined) {
  if (!leg) return "–";
  if (leg.distanceChangeKind === "ALREADY_REACHED") return "Break-even al bereikt";
  if (leg.distanceChangeKind === "UNCHANGED") return "Ongewijzigd";
  const value = Math.max(0, Math.round(Number(leg.distanceChangePct || 0)));
  return leg.distanceChangeKind === "FARTHER"
    ? `${value}% verder weg`
    : `${value}% dichterbij`;
}

function distanceChangeClass(leg: ScaleLegPreview | undefined) {
  if (!leg) return "neutral";
  if (leg.distanceChangeKind === "CLOSER") return "closer";
  if (leg.distanceChangeKind === "FARTHER") return "farther";
  return "neutral";
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

function PairCard({ pair, saving, onRehedge, onScale }: {
  pair: PairState;
  saving: boolean;
  onRehedge: (pair: PairState, enabled: boolean) => void;
  onScale: (pair: PairState) => void;
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
            {status === "HEDGED" ? <button
              type="button"
              className="plah-scale-open"
              disabled={saving}
              onTouchEnd={(event) => event.stopPropagation()}
              onDoubleClick={(event) => {
                event.stopPropagation();
                onScale(pair);
              }}
              onClick={(event) => {
                event.stopPropagation();
                onScale(pair);
              }}
              aria-label={`Hedge-lock vergroten voor ${pair.symbol}`}
            ><span aria-hidden="true">+</span> VERHOOG</button> : null}
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
  const [scalePair, setScalePair] = useState<PairState | null>(null);
  const [scaleDraft, setScaleDraft] = useState("2");
  const [scalePreview, setScalePreview] = useState<ScalePreview | null>(null);
  const [scaleLoading, setScaleLoading] = useState(false);
  const [scaleSubmitting, setScaleSubmitting] = useState(false);
  const [scaleError, setScaleError] = useState("");
  const [scaleMessage, setScaleMessage] = useState("");
  const [scaleOperationId, setScaleOperationId] = useState("");
  const [scaleRefreshKey, setScaleRefreshKey] = useState(0);
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

  const persist = async (enabled: boolean, threshold: number, applyNow = false, source = "AUTO_HEDGE_SCREEN") => {
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
        body: JSON.stringify({ enabled, thresholdUsd: threshold, confirmDisable: state.enabled === true && enabled === false, clientBuild: WEBAPP_BUILD_NUMBER, clientSource: source }),
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

  const requestEnabledChange = async (nextEnabled: boolean, source: string) => {
    if (state.enabled === true && nextEnabled === false) {
      const confirmed = window.confirm(
        "Auto Hedge uitschakelen? Nieuwe verliesposities worden dan niet meer automatisch gehedged. Bestaande HEDGE_LOCKED-pairs blijven beschermd.",
      );
      if (!confirmed) {
        setMessage("Auto Hedge blijft AAN.");
        return false;
      }
    }
    return persist(nextEnabled, threshold, nextEnabled, source);
  };

  const openScale = (pair: PairState) => {
    if (String(pair.status || "").toUpperCase() !== "HEDGED") return;
    setScalePair(pair);
    setScaleDraft("2");
    setScalePreview(null);
    setScaleError("");
    setScaleMessage("");
    setScaleOperationId("");
  };

  const closeScale = () => {
    if (scaleSubmitting) return;
    setScalePair(null);
    setScalePreview(null);
    setScaleError("");
    setScaleMessage("");
    setScaleOperationId("");
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

  useEffect(() => {
    if (!scalePair) return;
    const refreshOnFocus = () => setScaleRefreshKey((value) => value + 1);
    const refreshOnVisibility = () => {
      if (document.visibilityState === "visible") refreshOnFocus();
    };
    window.addEventListener("focus", refreshOnFocus);
    document.addEventListener("visibilitychange", refreshOnVisibility);
    return () => {
      window.removeEventListener("focus", refreshOnFocus);
      document.removeEventListener("visibilitychange", refreshOnVisibility);
    };
  }, [scalePair]);

  useEffect(() => {
    if (!scalePair) return;
    const amount = Number(scaleDraft.replace(",", "."));
    if (!Number.isFinite(amount) || amount <= 0) {
      setScalePreview(null);
      setScaleError("Vul een bedrag per zijde groter dan $0 in.");
      return;
    }
    let active = true;
    const timer = window.setTimeout(async () => {
      setScaleLoading(true);
      setScaleError("");
      try {
        const preview = await authenticatedRequest(
          `/api/exchanges/aster/position-loss-auto-hedge/pairs/${encodeURIComponent(scalePair.symbol)}/scale/preview`,
          {
            method: "POST",
            body: JSON.stringify({ marginPerSideUsd: amount, clientBuild: WEBAPP_BUILD_NUMBER }),
            cache: "no-store",
          },
        ) as ScalePreview;
        if (active) setScalePreview(preview);
      } catch (reason) {
        if (active) {
          setScalePreview(null);
          setScaleError(reason instanceof Error ? reason.message : "Recovery-preview kon niet worden berekend.");
        }
      } finally {
        if (active) setScaleLoading(false);
      }
    }, 260);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [scalePair, scaleDraft, scaleRefreshKey]);

  const executeScale = async () => {
    if (!scalePair || !scalePreview || scaleSubmitting) return;
    const amount = Number(scaleDraft.replace(",", "."));
    if (!Number.isFinite(amount) || amount <= 0) return;
    const operationId = scaleOperationId || (
      globalThis.crypto?.randomUUID?.() || `lhs-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`
    );
    setScaleOperationId(operationId);
    setScaleSubmitting(true);
    setScaleError("");
    setScaleMessage("");
    try {
      const result = await authenticatedRequest(
        `/api/exchanges/aster/position-loss-auto-hedge/pairs/${encodeURIComponent(scalePair.symbol)}/scale`,
        {
          method: "POST",
          body: JSON.stringify({
            marginPerSideUsd: amount,
            operationId,
            confirm: true,
            clientBuild: WEBAPP_BUILD_NUMBER,
          }),
        },
      ) as ScaleResult;
      setScaleMessage(
        result.status === "SUCCEEDED"
          ? `Uitgevoerd · LONG en SHORT +${nlNumber(result.actualAddedQuantity)} · hedge 100% (1:1).`
          : `Gedeeltelijk gevuld maar veilig 1:1 · beide zijden +${nlNumber(result.actualAddedQuantity)}.`,
      );
      await load();
      setScalePreview(null);
    } catch (reason) {
      const rawMessage = reason instanceof Error ? reason.message : "Beide posities verhogen is niet uitgevoerd.";
      const replanRequired = rawMessage.includes("RECOVERY_REPLAN_REQUIRED");
      setScaleError(rawMessage.replace(/RECOVERY_REPLAN_REQUIRED:\s*/g, ""));
      if (replanRequired) {
        setScaleOperationId("");
        setScalePreview(null);
        setScaleRefreshKey((value) => value + 1);
      }
    } finally {
      setScaleSubmitting(false);
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
      <Toggle checked={state.enabled} disabled={saving || loading} onChange={() => void requestEnabledChange(!state.enabled, "SNAPSHOT_TILE")} compact label="Auto Hedge" />
    </div>,
    tileHost,
  ) : null;

  const screen = screenHost && available === true ? createPortal(
    <section
      className="plah-screen"
      data-reference={scalePair ? SCALE_REFERENCE : OVERVIEW_REFERENCE}
      data-parent-reference={SCREEN_REFERENCE}
      aria-label={scalePair ? "Hedge-lock vergroten" : "Auto Hedge"}
    >
      {scalePair ? <div className="plah-scale-screen">
        <div className="plah-scale-topline">
          <button type="button" className="plah-back-link" onClick={closeScale} disabled={scaleSubmitting}>
            <span aria-hidden="true">‹</span> Terug
          </button>
          <div className="plah-mini-brand"><span>{shieldIcon()}</span><b>LEGACY RECOVERY</b></div>
        </div>

        <header className="plah-scale-hero">
          <h3>Hedge-lock vergroten</h3>
          <p>Verhoog beide posities met exact dezelfde coin quantity.</p>
        </header>

        <section className="plah-scale-pair">
          <div className="plah-scale-pair-id">
            <CoinBadge symbol={scalePair.symbol} />
            <div>
              <div className="plah-scale-pair-title">
                <strong>{scalePair.symbol.replace(/USDT$/i, "")}</strong>
                <span className="plah-status-badge hedged">HEDGED</span>
              </div>
              <small>Verhoog LONG en SHORT met hetzelfde marginbudget per zijde.</small>
            </div>
          </div>
          <div className="plah-scale-ratio"><small>Hedge ratio</small><b>100% (1:1)</b></div>
        </section>

        <section className="plah-scale-form">
          <div className="plah-scale-available">
            <span className="plah-scale-wallet" aria-hidden="true">▣</span>
            <span><small>Beschikbaar saldo</small><b>{scalePreview ? money(scalePreview.availableBalance, false) : scaleLoading ? "Laden…" : "–"}</b></span>
          </div>

          <label className="plah-scale-label" htmlFor="plah-scale-margin">Bedrag per zijde (USDT)</label>
          <div className="plah-scale-input">
            <input
              id="plah-scale-margin"
              type="number"
              min="0.01"
              step="0.01"
              inputMode="decimal"
              value={scaleDraft}
              onChange={(event) => {
                setScaleDraft(event.target.value);
                setScaleMessage("");
                setScaleOperationId("");
              }}
              disabled={scaleSubmitting}
              aria-describedby="plah-scale-help"
            />
            <span><b>₮</b> USDT</span>
          </div>
          {scaleError ? <div className="plah-error" role="alert">{scaleError}</div> : null}
          {scaleMessage ? <div className="plah-success">{scaleMessage}</div> : null}

          <section className="plah-scale-preview plah-scale-preview-v2" aria-busy={scaleLoading}>
            <div className="plah-scale-preview-title">
              <span className="plah-scale-chart-icon" aria-hidden="true"><i /><i /><i /></span>
              <b>Preview (break-even afstand)</b>
              <span className="plah-scale-info-dot" aria-hidden="true">i</span>
              {scaleLoading ? <em>Actueel laden…</em> : null}
            </div>

            <div className="plah-scale-overview">
              <div className="plah-scale-preview-row total"><span>Totaal extra margin</span><b>{scalePreview ? money(scalePreview.estimatedTotalMarginUsd, false) : "–"}</b></div>
              <div className="plah-scale-preview-row"><span>Geschatte fees</span><b>{scalePreview ? money(scalePreview.estimatedFeesUsd, false) : "–"}</b></div>
              <div className="plah-scale-preview-row"><span>Extra quantity beide zijden</span><b>{scalePreview ? nlNumber(scalePreview.extraQuantity) : "–"}</b></div>
              <div className="plah-scale-preview-row"><span>Hedge ratio na uitvoering</span><b>{scalePreview ? "100% (1:1)" : "–"}</b></div>
            </div>

            <div className="plah-scale-break-grid">
              {(["long", "short"] as const).map((key) => {
                const leg = scalePreview?.[key];
                const side = key.toUpperCase();
                const direction = leg?.breakEvenDirectionBefore === "DOWN" ? "down" : "up";
                return <article className={`plah-scale-break-card ${key}`} key={key}>
                  <div className="plah-scale-break-head">
                    <span className={`plah-side-badge ${key}`}>{side}</span>
                    <span className={`plah-scale-direction ${key} ${direction}`} aria-hidden="true">{direction === "down" ? "↘" : "↗"}</span>
                  </div>

                  <div className="plah-scale-qty">Qty {leg ? `${nlNumber(leg.currentQuantity)} → ${nlNumber(leg.quantityAfter)}` : "–"}</div>

                  <small>Nu naar break-even</small>
                  <strong className={key}>{breakEvenMoveText(leg, "before")}</strong>

                  <small>Na verhogen</small>
                  <strong className={`after ${key}`}>{breakEvenMoveText(leg, "after")}</strong>

                  <div className={`plah-scale-distance-change ${distanceChangeClass(leg)}`}>
                    <span aria-hidden="true">◎</span>
                    <b>{distanceChangeText(leg)}</b>
                  </div>
                </article>;
              })}
            </div>

            <p className="plah-scale-break-note"><span>i</span>Break-even afstand is per zijde, niet voor het totale pair.</p>
          </section>

          <div className="plah-scale-actions">
            <button type="button" className="secondary" onClick={closeScale} disabled={scaleSubmitting}>Annuleren</button>
            <button type="button" className="primary" onClick={() => void executeScale()} disabled={!scalePreview || scaleLoading || scaleSubmitting}>
              {scaleSubmitting ? "Uitvoeren…" : "Beide posities verhogen"}
            </button>
          </div>
        </section>
      </div> : <div className="plah-screen-scroll">
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
          <Toggle checked={state.enabled} disabled={saving} onChange={() => void requestEnabledChange(!state.enabled, "AUTO_HEDGE_SCREEN")} label="Auto Hedge hoofdschakelaar" labelText />
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
              <h4>Gehedgede posities</h4>
              <p>Alleen coins die (in het verleden) door Auto Hedge zijn gehedged.</p>
            </div>
            <select value={coinFilter} onChange={(event) => setCoinFilter(event.target.value)} aria-label="Filter gehedgde coins">
              <option value="ALL">Alle coins</option>
              {coinOptions.map((symbol) => <option value={symbol} key={symbol}>{symbol.replace(/USDT$/i, "")}</option>)}
            </select>
          </div>

          <div className="plah-pair-list">
            {visiblePairs.length ? visiblePairs.map((pair) =>
              <PairCard
                key={pair.symbol}
                pair={pair}
                saving={saving || scaleSubmitting}
                onRehedge={(item, enabled) => void setRehedge(item, enabled)}
                onScale={openScale}
              />
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
          <button type="button" onClick={() => void persist(state.enabled, threshold, true, "AUTO_HEDGE_CHECK")} disabled={saving || loading}>
            {saving ? "Controleren…" : "Nu controleren"} <span>›</span>
          </button>
        </section>
      </div>}
    </section>,
    screenHost,
  ) : null;

  return <>{tile}{screen}</>;
}
