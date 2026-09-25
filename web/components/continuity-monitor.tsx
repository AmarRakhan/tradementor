"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";

export type ContinuityService = {
  id: string;
  title: string;
  description: string;
  status: "ACTIVE" | "FREE" | "UPCOMING_PAYMENT" | "WARNING" | "CRITICAL" | "PLANNED" | "UNKNOWN";
  statusLabel?: string;
  dataSource?: "LIVE_API" | "MANUAL" | "CALCULATED" | "UNKNOWN";
  dependencyType?: string;
  isRuntimeCritical?: boolean;
  plan?: string | null;
  monthlyEstimate?: number | null;
  amountDue?: number | null;
  currency?: string;
  dueDate?: string | null;
  daysUntilDue?: number | null;
  note?: string;
  connected?: boolean;
  readOnly?: boolean;
  apiStatus?: string;
  assets?: Array<{ coin: string; walletBalance: number; transferBalance: number; bonus?: number; availableForReserve?: number }>;
  safetyBuffer?: number;
  upcomingPayments30d?: number;
  requiredReserve?: number;
  availableReserve?: number | null;
  reserveDifference?: number | null;
  lastSuccessfulSync?: string | null;
  billingEnabled?: boolean | null;
  billingSource?: string;
  runtimeOnline?: boolean;
  budgetStatus?: string;
  budgetCount?: number | null;
  project?: string;
  cloudRunService?: string;
  repository?: string;
  visibility?: string;
  latestWorkflowStatus?: string | null;
  latestWorkflowConclusion?: string | null;
  estimateComplete?: boolean;
  estimateScope?: string;
};

export type ContinuitySnapshot = {
  enabled: boolean;
  ownerOnly: boolean;
  summary: {
    activeServices: number;
    totalServices: number;
    upcomingPayments: number;
    upcomingAmount: number;
    knownMonthlyCost: number;
    currency: string;
    overallStatus: "SAFE" | "WARNING" | "CRITICAL";
    allCriticalOperational: boolean;
    paymentReserveSufficient: boolean | null;
  };
  services: ContinuityService[];
  settings: {
    safetyBufferAmount: number;
    safetyBufferCurrency: string;
    safetyBufferSource?: string;
    pushNotificationsEnabled: boolean;
  };
  alert?: {
    id: string;
    kind: string;
    title: string;
    message: string;
    showStartupAlert?: boolean;
    availableReserve?: number | null;
    requiredReserve?: number | null;
    reserveDifference?: number | null;
    currency?: string;
  } | null;
  lastUpdated: string;
};

function money(value: number | null | undefined, currency = "EUR") {
  if (typeof value !== "number" || !Number.isFinite(value)) return "Niet beschikbaar";
  return new Intl.NumberFormat("nl-NL", {
    style: "currency",
    currency: currency === "USD" ? "USD" : "EUR",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

function shortTime(value?: string | null) {
  if (!value) return "Nog niet";
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.getTime())) return "Onbekend";
  return parsed.toLocaleString("nl-NL", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function service(snapshot: ContinuitySnapshot | null, id: string) {
  return snapshot?.services.find((item) => item.id === id);
}

function tone(status?: ContinuityService["status"] | ContinuitySnapshot["summary"]["overallStatus"]) {
  if (status === "CRITICAL") return "critical";
  if (status === "WARNING" || status === "UPCOMING_PAYMENT") return "warning";
  if (status === "ACTIVE" || status === "FREE" || status === "SAFE") return "safe";
  if (status === "PLANNED") return "planned";
  return "unknown";
}

function statusLabel(item?: ContinuityService) {
  if (!item) return "Controleren";
  return item.statusLabel || ({
    ACTIVE: "Actief", FREE: "Gratis", UPCOMING_PAYMENT: "Binnenkort",
    WARNING: "Let op", CRITICAL: "Kritiek", PLANNED: "Gepland", UNKNOWN: "Onbekend",
  }[item.status] || item.status);
}

function iconFor(id: string) {
  if (id === "chatgpt") return "AI";
  if (id === "github") return "GH";
  if (id === "google_cloud") return "GC";
  if (id === "bybit") return "BY";
  return "◇";
}

function daysLabel(item?: ContinuityService) {
  if (!item || item.daysUntilDue === null || item.daysUntilDue === undefined) return "n.v.t.";
  if (item.daysUntilDue < 0) return "Verlopen";
  if (item.daysUntilDue === 0) return "Vandaag";
  return `Nog ${item.daysUntilDue} dag${item.daysUntilDue === 1 ? "" : "en"}`;
}

export function ContinuityHomeCard({
  snapshot,
  loading,
  onOpen,
}: {
  snapshot: ContinuitySnapshot | null;
  loading: boolean;
  onOpen: () => void;
}) {
  const providers = ["chatgpt", "github", "google_cloud"].map((id) => service(snapshot, id));
  const overall = snapshot?.summary.overallStatus;
  return <button className={`tm-continuity-home-card ${tone(overall)}`} type="button" onClick={onOpen}>
    <div className="tm-continuity-home-title">
      <span className="tm-continuity-home-icon">▣</span>
      <span><strong>App kosten &amp; betalingen</strong><small>Overzicht van alles wat betaald moet worden om de app live te houden.</small></span>
      <b>›</b>
    </div>
    <div className="tm-continuity-home-providers">
      {providers.map((item, index) => <span key={item?.id || index}>
        <i>{iconFor(item?.id || "")}</i>{item?.title?.replace(" / Agent", "").replace("Google Cloud", "Google Cloud") || ["ChatGPT","GitHub","Google Cloud"][index]}
        <em className={tone(item?.status)} />
      </span>)}
    </div>
    <div className="tm-continuity-home-foot">
      <span>▣</span>
      <strong>{loading && !snapshot ? "Continuïteit wordt gecontroleerd…" : snapshot ? `${snapshot.summary.upcomingPayments} betaling${snapshot.summary.upcomingPayments === 1 ? "" : "en"} binnenkort · ${snapshot.services.filter((item) => item.status !== "PLANNED").length} diensten in beeld` : "Open continuïteitsoverzicht"}</strong>
      <b>›</b>
    </div>
  </button>;
}

export function ContinuityAlertModal({
  alert,
  onAcknowledge,
  onOpen,
}: {
  alert: NonNullable<ContinuitySnapshot["alert"]>;
  onAcknowledge: () => Promise<void>;
  onOpen: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const bybit = alert.kind === "BYBIT_LOW_RESERVE";
  const acknowledge = async () => {
    setBusy(true);
    try { await onAcknowledge(); } finally { setBusy(false); }
  };
  return <div className="tm-continuity-alert-layer" role="dialog" aria-modal="true" aria-labelledby="continuity-alert-title">
    <div className="tm-continuity-alert">
      <button className="tm-continuity-alert-close" type="button" aria-label="Melding sluiten" onClick={() => void acknowledge()}>×</button>
      <div className="tm-continuity-warning-mark">!</div>
      <h2 id="continuity-alert-title">{alert.title}</h2>
      <p>{alert.message}</p>
      {bybit && <div className="tm-continuity-alert-reserve">
        <span className="tm-bybit-mark">BYBIT</span>
        <dl>
          <div><dt>Huidige betaalreserve</dt><dd>{money(alert.availableReserve, alert.currency)}</dd></div>
          <div><dt>Benodigde reserve</dt><dd>{money(alert.requiredReserve, alert.currency)}</dd></div>
          <div><dt>Verschil</dt><dd className={(alert.reserveDifference || 0) < 0 ? "negative" : "positive"}>{money(alert.reserveDifference, alert.currency)}</dd></div>
        </dl>
      </div>}
      <button className="tm-continuity-ack" type="button" disabled={busy} onClick={() => void acknowledge()}>{busy ? "Opslaan…" : "Begrepen"}</button>
      <button className="tm-continuity-alert-link" type="button" onClick={onOpen}>Naar App kosten &amp; betalingen</button>
    </div>
  </div>;
}

export function ContinuityDashboard({
  snapshot,
  loading,
  error,
  onBack,
  onRefresh,
  onSnapshot,
}: {
  snapshot: ContinuitySnapshot | null;
  loading: boolean;
  error: string;
  onBack: () => void;
  onRefresh: () => Promise<void>;
  onSnapshot: (snapshot: ContinuitySnapshot) => void;
}) {
  const [connectOpen, setConnectOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const currency = snapshot?.summary.currency || "EUR";
  const critical = snapshot?.summary.overallStatus === "CRITICAL";
  const warning = snapshot?.summary.overallStatus === "WARNING";

  return <section className="tm-continuity-page" aria-label="App kosten en betalingen">
    <header className="tm-continuity-page-header">
      <button type="button" onClick={onBack} aria-label="Terug">‹</button>
      <div className="tm-continuity-brand"><img src="/tradementor-logo.png?v=redgreen-1" alt="" /><strong>Aster</strong></div>
      <button className="tm-continuity-refresh" type="button" disabled={loading} onClick={() => void onRefresh()} aria-label="Vernieuwen">↻</button>
    </header>

    <div className="tm-continuity-title-row">
      <div><h1>App kosten &amp; betalingen</h1><p>Overzicht van alles wat nodig is om de app live te houden.</p></div>
      <span className={`tm-continuity-overall ${critical ? "critical" : warning ? "warning" : "safe"}`}>
        {critical ? "ACTIE NODIG" : warning ? "CONTROLEREN" : "VEILIG"}
      </span>
    </div>

    {error && <div className="tm-continuity-error">{error}</div>}

    <div className="tm-continuity-summary-grid">
      <SummaryCard glyph="▱" label="Actieve diensten" value={snapshot ? `${snapshot.summary.activeServices} / ${snapshot.summary.totalServices}` : "—"} detail={loading ? "Controleren…" : "Live status"} />
      <SummaryCard glyph="▤" label="Openstaande betaling" value={snapshot ? money(snapshot.summary.upcomingAmount, currency) : "—"} detail={snapshot ? `${snapshot.summary.upcomingPayments} bekende betaling${snapshot.summary.upcomingPayments === 1 ? "" : "en"} · 30 dagen` : "binnen 30 dagen"} />
      <SummaryCard glyph="▥" label="Bekende maandkosten" value={snapshot ? money(snapshot.summary.knownMonthlyCost, currency) : "—"} detail="excl. onbekend verbruik" />
    </div>

    <div className="tm-continuity-info">ⓘ <span>Geen waarde wordt gegokt. Niet beschikbare billingdata wordt expliciet als onbekend getoond.</span></div>

    <section className="tm-continuity-services">
      <h2>Diensten</h2>
      {(snapshot?.services || []).map((item) => <ServiceCard key={item.id} item={item} onConnectBybit={() => setConnectOpen(true)} />)}
      {!snapshot && loading && <div className="tm-continuity-skeleton">Diensten worden veilig gecontroleerd…</div>}
    </section>

    {snapshot && <section className="tm-continuity-dependencies">
      <h2>Afhankelijkheden app</h2>
      <p>Deze diensten werken samen om Aster draaiende te houden.</p>
      <div className="tm-continuity-flow">
        <FlowNode id="chatgpt" label="ChatGPT" sub="Agent & AI" />
        <b>→</b>
        <FlowNode id="github" label="GitHub" sub="Code & Deploy" />
        <b>→</b>
        <FlowNode id="google_cloud" label="Google Cloud" sub="Hosting & Runtime" />
        <b>→</b>
        <FlowNode id="aster" label="Aster" sub="Live App" />
      </div>
    </section>}

    {snapshot && <div className={`tm-continuity-final ${critical ? "critical" : warning ? "warning" : "safe"}`}>
      <span>{critical ? "!" : warning ? "!" : "✓"}</span>
      <div>
        <strong>{critical ? "Een kritieke dienst vraagt aandacht." : warning ? "Niet alles kan volledig worden geverifieerd." : "Alle kritieke diensten zijn momenteel operationeel."}</strong>
        <small>{snapshot.summary.paymentReserveSufficient === true ? "Betaalreserve voldoende voor bekende verplichtingen." : snapshot.summary.paymentReserveSufficient === false ? "Betaalreserve is onvoldoende voor bekende verplichtingen." : "Bybit betaalreserve is nog niet volledig gekoppeld of vergelijkbaar."}</small>
      </div>
    </div>}

    <div className="tm-continuity-actions">
      <button type="button" onClick={() => setSettingsOpen(true)}>Continuïteitsinstellingen</button>
      <small>Laatste controle: {shortTime(snapshot?.lastUpdated)}</small>
    </div>

    {connectOpen && <BybitConnectModal onClose={() => setConnectOpen(false)} onSnapshot={(next) => { onSnapshot(next); setConnectOpen(false); }} />}
    {settingsOpen && snapshot && <ContinuitySettingsModal snapshot={snapshot} onClose={() => setSettingsOpen(false)} onSnapshot={(next) => { onSnapshot(next); setSettingsOpen(false); }} />}
  </section>;
}

function SummaryCard({ glyph, label, value, detail }: { glyph: string; label: string; value: string; detail: string }) {
  return <article><i>{glyph}</i><span>{label}</span><strong>{value}</strong><small>{detail}</small></article>;
}

function FlowNode({ id, label, sub }: { id: string; label: string; sub: string }) {
  return <span><i>{iconFor(id)}</i><strong>{label}</strong><small>{sub}</small></span>;
}

function ServiceCard({ item, onConnectBybit }: { item: ContinuityService; onConnectBybit: () => void }) {
  const isBybit = item.id === "bybit";
  const planned = item.id === "future";
  const [expanded, setExpanded] = useState(false);
  return <article className={`tm-continuity-service ${tone(item.status)}`}>
    <div className="tm-continuity-service-icon">{iconFor(item.id)}</div>
    <div className="tm-continuity-service-main">
      <div className="tm-continuity-service-heading">
        <span><strong>{item.title}</strong><small>{item.description}</small></span>
        <em className={tone(item.status)}>{statusLabel(item)}</em>
      </div>
      {item.id === "chatgpt" && <p>{item.plan ? `Plan: ${item.plan}` : "Plan: nog niet ingesteld"} <b>·</b> {item.monthlyEstimate != null ? `${money(item.monthlyEstimate, item.currency)} / maand` : "bedrag onbekend"} <b>·</b> {item.dueDate ? `volgende betaling: ${new Date(item.dueDate).toLocaleDateString("nl-NL")}` : "betaaldatum onbekend"}</p>}
      {item.id === "github" && <p>{item.repository || "Repository onbekend"} <b>·</b> {item.visibility || "zichtbaarheid onbekend"} <b>·</b> plan/billing: niet beschikbaar</p>}
      {item.id === "google_cloud" && <p>Billing: <strong>{item.billingEnabled === true ? "Actief" : item.billingEnabled === false ? "Niet actief" : "Niet geverifieerd"}</strong> <b>·</b> Cloud Run: {item.runtimeOnline ? "Online" : "Onbekend"} <b>·</b> Budget: {item.budgetStatus === "CONFIGURED" ? `${item.budgetCount ?? 0} actief` : item.budgetStatus === "NONE" ? "geen budget gevonden" : "niet geverifieerd"} <b>·</b> {item.project}</p>}
      {isBybit && <BybitServiceDetails item={item} onConnect={onConnectBybit} />}
      {planned && <div className="tm-future-tags">{["Domeinnaam","E-mailservice","Monitoring","Back-ups","Analytics","Stripe"].map((tag) => <span key={tag}>{tag}</span>)}</div>}
      {item.note && !isBybit && !planned && <small className="tm-continuity-note">{item.note}</small>}
      {expanded && <div className="tm-continuity-provider-details">
        <span>Bron <strong>{item.dataSource || "UNKNOWN"}</strong></span>
        <span>Afhankelijkheid <strong>{item.dependencyType || "onbekend"}</strong></span>
        <span>Runtime-kritiek <strong>{item.isRuntimeCritical ? "Ja" : "Nee"}</strong></span>
        <span>Bedrag <strong>{item.amountDue != null ? money(item.amountDue, item.currency) : "Niet beschikbaar"}</strong></span>
      </div>}
    </div>
    <div className="tm-continuity-service-side">
      {!planned && !isBybit && <span className={`tm-continuity-due ${tone(item.status)}`}>{daysLabel(item)}</span>}
      <button type="button" aria-label={`Details ${item.title}`} aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>›</button>
    </div>
  </article>;
}

function BybitServiceDetails({ item, onConnect }: { item: ContinuityService; onConnect: () => void }) {
  if (!item.connected) return <div className="tm-bybit-disconnected">
    <p>Nog geen aparte read-only Funding-walletkoppeling.</p>
    <button type="button" onClick={onConnect}>Wallet verbinden</button>
  </div>;
  return <div className="tm-bybit-details">
    <div className="tm-bybit-numbers">
      <span><small>Beschikbare reserve</small><strong>{money(item.availableReserve, item.currency)}</strong></span>
      <span><small>Benodigd</small><strong>{money(item.requiredReserve, item.currency)}</strong></span>
      <span><small>Verschil</small><strong className={(item.reserveDifference || 0) < 0 ? "negative" : "positive"}>{money(item.reserveDifference, item.currency)}</strong></span>
    </div>
    <div className="tm-bybit-assets">{(item.assets || []).map((asset) => <span key={asset.coin}>{asset.coin} <strong>{(asset.availableForReserve ?? asset.walletBalance).toLocaleString("nl-NL", { maximumFractionDigits: 8 })}</strong></span>)}</div>
    <p>Read-only: {item.readOnly ? "bevestigd" : "niet bevestigd"} · API: {item.apiStatus || "onbekend"} · Sync: {shortTime(item.lastSuccessfulSync)}</p>
    {item.estimateComplete === false && <small className="tm-continuity-note">De reservevergelijking telt alleen direct vergelijkbare {item.currency}-assets mee. Andere Funding-assets blijven zichtbaar maar worden niet gegokt of omgerekend.</small>}
  </div>;
}

function BybitConnectModal({ onClose, onSnapshot }: { onClose: () => void; onSnapshot: (snapshot: ContinuitySnapshot) => void }) {
  const keyRef = useRef<HTMLInputElement>(null);
  const secretRef = useRef<HTMLInputElement>(null);
  const confirmRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [verified, setVerified] = useState(false);
  const [message, setMessage] = useState("");
  const payload = () => ({
    api_key: keyRef.current?.value.trim() || "",
    api_secret: secretRef.current?.value || "",
    read_only_confirmed: Boolean(confirmRef.current?.checked),
  });
  const test = async () => {
    setBusy(true); setVerified(false); setMessage("");
    try {
      const result = await authenticatedRequest("/api/continuity/bybit/test", { method: "POST", body: JSON.stringify(payload()) });
      setVerified(Boolean(result.verified && result.readOnly));
      setMessage(result.verified ? "Bybit succesvol gecontroleerd · read-only bevestigd · Funding wallet bereikbaar." : "Verbinding kon niet worden bevestigd.");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Bybit kon niet worden gecontroleerd.");
    } finally { setBusy(false); }
  };
  const save = async () => {
    setBusy(true); setMessage("");
    try {
      const result = await authenticatedRequest("/api/continuity/bybit", { method: "PUT", body: JSON.stringify(payload()) });
      if (!result?.snapshot) throw new Error("De nieuwe continuiteitsstatus ontbreekt.");
      if (keyRef.current) keyRef.current.value = "";
      if (secretRef.current) secretRef.current.value = "";
      onSnapshot(result.snapshot as ContinuitySnapshot);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Bybit kon niet veilig worden opgeslagen.");
    } finally { setBusy(false); }
  };
  return <div className="tm-continuity-modal-layer" onMouseDown={onClose}>
    <div className="tm-continuity-modal" onMouseDown={(event) => event.stopPropagation()}>
      <div className="tm-continuity-modal-head"><div><span>BYBIT · READ-ONLY</span><h3>Bybit verbinden</h3></div><button type="button" onClick={onClose}>×</button></div>
      <p>Maak een aparte read-only API-sleutel aan. Hiermee kan Amar alleen je betaalreserve controleren.</p>
      <div className="tm-bybit-security-note"><strong>Veiligheidsgrens</strong><span>Schrijfrechten, orders, transfers en withdrawals worden geweigerd. Gebruik niet je trading-key.</span></div>
      <ol className="tm-bybit-connect-steps">
        <li>Open Bybit in je browser en ga via je profiel naar <strong>API Management</strong>.</li>
        <li>Kies <strong>Create New Key</strong> en maak een aparte sleutel voor deze continuïteitsmonitor.</li>
        <li>Zet de sleutel op <strong>Read-Only</strong>. Geef geen Trade-, Transfer- of Withdrawal-rechten.</li>
        <li>Kopieer de API Key en het API Secret hieronder. Het secret blijft alleen lang genoeg in dit formulier om de verbinding te testen en veilig op te slaan.</li>
      </ol>
      <label>API Key<input ref={keyRef} autoComplete="off" autoCapitalize="none" spellCheck={false} /></label>
      <label>API Secret<input ref={secretRef} type="password" autoComplete="new-password" autoCapitalize="none" spellCheck={false} /></label>
      <label className="tm-continuity-checkbox"><input ref={confirmRef} type="checkbox" /><span>Ik heb uitsluitend read-only rechten ingesteld.</span></label>
      {message && <div className={verified ? "tm-connect-success" : "tm-connect-message"}>{verified ? "✓ " : ""}{message}</div>}
      <button className="tm-continuity-test-button" type="button" disabled={busy} onClick={() => void test()}>{busy ? "Controleren…" : "Verbinding testen"}</button>
      <button className="tm-continuity-save-button" type="button" disabled={busy || !verified} onClick={() => void save()}>{busy ? "Opslaan…" : "Opslaan"}</button>
      <small>API Secret wordt nooit in localStorage opgeslagen en wordt na opslaan niet opnieuw naar je browser teruggestuurd.</small>
    </div>
  </div>;
}

function ContinuitySettingsModal({ snapshot, onClose, onSnapshot }: { snapshot: ContinuitySnapshot; onClose: () => void; onSnapshot: (snapshot: ContinuitySnapshot) => void }) {
  const chatgpt = service(snapshot, "chatgpt");
  const [buffer, setBuffer] = useState(String(snapshot.settings.safetyBufferAmount ?? 50));
  const bufferRef = useRef<HTMLInputElement>(null);
  const presetBuffer = [25, 50, 100].includes(Number(buffer)) ? Number(buffer) : null;
  const [currency, setCurrency] = useState(snapshot.settings.safetyBufferCurrency || "EUR");
  const [plan, setPlan] = useState(chatgpt?.plan || "");
  const [monthly, setMonthly] = useState(chatgpt?.monthlyEstimate != null ? String(chatgpt.monthlyEstimate) : "");
  const [due, setDue] = useState(chatgpt?.dueDate ? String(chatgpt.dueDate).slice(0,10) : "");
  const [push, setPush] = useState(Boolean(snapshot.settings.pushNotificationsEnabled));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const save = async () => {
    setBusy(true); setMessage("");
    try {
      let pushEnabled = push;
      if (push && "Notification" in window && Notification.permission !== "granted") {
        const permission = await Notification.requestPermission();
        pushEnabled = permission === "granted";
        setPush(pushEnabled);
      }
      const result = await authenticatedRequest("/api/continuity/settings", {
        method: "PUT",
        body: JSON.stringify({
          safety_buffer_amount: Number(buffer || 0),
          safety_buffer_currency: currency,
          push_notifications_enabled: pushEnabled,
          chatgpt_plan: plan,
          chatgpt_monthly_amount: monthly === "" ? undefined : Number(monthly),
          chatgpt_currency: currency,
          chatgpt_next_payment_date: due,
        }),
      });
      if (!result?.snapshot) throw new Error("Nieuwe instellingen konden niet worden bevestigd.");
      onSnapshot(result.snapshot as ContinuitySnapshot);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Instellingen konden niet worden opgeslagen.");
    } finally { setBusy(false); }
  };
  return <div className="tm-continuity-modal-layer" onMouseDown={onClose}>
    <div className="tm-continuity-modal settings" onMouseDown={(event) => event.stopPropagation()}>
      <div className="tm-continuity-modal-head"><div><span>CONTINUÏTEIT</span><h3>Instellingen</h3></div><button type="button" onClick={onClose}>×</button></div>
      <label>Extra veiligheidsbuffer
        <div className="tm-buffer-presets" aria-label="Veiligheidsbuffer kiezen">
          {[25, 50, 100].map((value) => <button key={value} type="button" className={presetBuffer === value ? "active" : ""} onClick={() => setBuffer(String(value))}>{currency === "EUR" ? "€" : "$"}{value}</button>)}
          <button type="button" className={presetBuffer === null ? "active" : ""} onClick={() => { if (presetBuffer !== null) setBuffer(""); requestAnimationFrame(() => bufferRef.current?.focus()); }}>Aangepast</button>
        </div>
        <div className="tm-inline-field"><input ref={bufferRef} inputMode="decimal" value={buffer} onChange={(e) => setBuffer(e.target.value.replace(",", ".").replace(/[^0-9.]/g, ""))} placeholder="Eigen buffer" /><select value={currency} onChange={(e) => setCurrency(e.target.value)}><option>EUR</option><option>USD</option></select></div>
      </label>
      <div className="tm-settings-divider"><strong>ChatGPT handmatig</strong><small>Alleen totdat ondersteunde live billingdata beschikbaar is.</small></div>
      <label>Plan<input value={plan} onChange={(e) => setPlan(e.target.value)} placeholder="Bijv. Plus / Pro" /></label>
      <label>Maandbedrag<input inputMode="decimal" value={monthly} onChange={(e) => setMonthly(e.target.value.replace(",", ".").replace(/[^0-9.]/g, ""))} placeholder="Niet ingesteld" /></label>
      <label>Volgende betaling<input type="date" value={due} onChange={(e) => setDue(e.target.value)} /></label>
      <label className="tm-continuity-checkbox"><input type="checkbox" checked={push} onChange={(e) => setPush(e.target.checked)} /><span>Continuïteitsmeldingen op dit apparaat toestaan.</span></label>
      {message && <div className="tm-connect-message">{message}</div>}
      <button className="tm-continuity-save-button" type="button" disabled={busy} onClick={() => void save()}>{busy ? "Opslaan…" : "Instellingen opslaan"}</button>
    </div>
  </div>;
}

export function ContinuityStartupGuard({ enabled, onOpen }: { enabled: boolean; onOpen: () => void }) {
  const continuity = useContinuityMonitor(enabled);
  const alert = continuity.snapshot?.alert;
  if (!alert?.showStartupAlert) return null;
  return <ContinuityAlertModal alert={alert} onAcknowledge={continuity.acknowledge} onOpen={onOpen} />;
}

export function useContinuityMonitor(enabled: boolean) {
  const [snapshot, setSnapshot] = useState<ContinuitySnapshot | null>(null);
  const [available, setAvailable] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const refresh = async (force = false) => {
    if (!enabled) return;
    setLoading(true);
    if (force) setError("");
    try {
      const result = await authenticatedRequest(force ? "/api/continuity/refresh" : "/api/continuity", force ? { method: "POST", body: "{}" } : undefined);
      setSnapshot(result as ContinuitySnapshot);
      setAvailable(true);
      setError("");
    } catch (reason) {
      if (snapshot || force) setError(reason instanceof Error ? reason.message : "Continuïteitsstatus kon niet worden opgehaald.");
      if (!snapshot) setAvailable(false);
    } finally { setLoading(false); }
  };

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setLoading(true);
    authenticatedRequest("/api/continuity")
      .then((result) => {
        if (cancelled) return;
        const next = result as ContinuitySnapshot;
        setSnapshot(next); setAvailable(true); setError("");
        window.setTimeout(() => {
          if (!cancelled) void authenticatedRequest("/api/continuity/refresh", { method: "POST", body: "{}" })
            .then((fresh) => { if (!cancelled) setSnapshot(fresh as ContinuitySnapshot); })
            .catch(() => undefined);
        }, 250);
      })
      .catch(() => { if (!cancelled) setAvailable(false); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [enabled]);

  useEffect(() => {
    const alert = snapshot?.alert;
    if (!alert?.showStartupAlert || !snapshot?.settings.pushNotificationsEnabled || !("Notification" in window) || Notification.permission !== "granted") return;
    const key = `tradementor.continuity.notified.${alert.id}`;
    if (window.sessionStorage.getItem(key)) return;
    window.sessionStorage.setItem(key, "1");
    const show = async () => {
      try {
        const registration = await navigator.serviceWorker?.ready;
        if (registration) await registration.showNotification(alert.title, { body: alert.message, tag: alert.id });
        else new Notification(alert.title, { body: alert.message, tag: alert.id });
      } catch { /* Notification support is best effort; the in-app alert remains authoritative. */ }
    };
    void show();
  }, [snapshot?.alert?.id, snapshot?.alert?.showStartupAlert, snapshot?.settings.pushNotificationsEnabled]);

  const acknowledge = async () => {
    const alert = snapshot?.alert;
    if (!alert) return;
    await authenticatedRequest("/api/continuity/alerts/ack", { method: "POST", body: JSON.stringify({ alert_id: alert.id }) });
    setSnapshot((current) => current ? { ...current, alert: current.alert ? { ...current.alert, showStartupAlert: false } : current.alert } : current);
  };

  return useMemo(() => ({ snapshot, setSnapshot, available, loading, error, refresh, acknowledge }), [snapshot, available, loading, error]);
}
