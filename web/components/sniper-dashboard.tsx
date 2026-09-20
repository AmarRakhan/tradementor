"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { authenticatedRequest } from "@/lib/cloud-client";

type SniperTab = "overview" | "trades" | "signals" | "performance" | "settings";

type SniperSettings = {
  enabled?: boolean;
  maxTradeSeconds: number;
  tpMinPercent: number;
  tpMaxPercent: number;
  maxLossUsd: number;
  maxConcurrent: number;
  marginPerTradeUsd: number;
  leverage: number;
  cooldownSeconds: number;
  attemptsPerCoin: number;
  maxDailyLossUsd: number;
  profitLockPercent: number;
  universeTopN: number;
};

type SniperTrade = {
  tradeId?: string;
  symbol?: string;
  side?: string;
  status?: string;
  entryPrice?: number;
  markPrice?: number;
  quantity?: number;
  notionalUsd?: number;
  marginUsd?: number;
  leverage?: number;
  unrealizedPnlUsd?: number;
  unrealizedPnlPercent?: number;
  realizedPnlUsd?: number;
  feesUsd?: number;
  fundingUsd?: number;
  netRealizedPnlUsd?: number;
  costEvidenceReliable?: boolean;
  accountingError?: string;
  tpPercent?: number;
  elapsedSeconds?: number;
  deadlineAtMs?: number;
  timeframe?: string;
  entryReason?: string;
  exitReason?: string;
  checks?: Array<{ name?: string; passed?: boolean }>;
};

type Signal = {
  symbol?: string;
  side?: string;
  timeframe?: string;
  score?: number;
  eligible?: boolean;
  reason?: string;
  tpPercent?: number;
  checks?: Array<{ name?: string; passed?: boolean }>;
};

type SniperPayload = {
  enabled?: boolean;
  monitor?: boolean;
  phase?: string;
  lastReason?: string;
  liveExecutionEnabled?: boolean;
  canaryValidated?: boolean;
  canaryStatus?: string;
  settings?: SniperSettings;
  activeTrades?: SniperTrade[];
  signals?: Signal[];
  history?: SniperTrade[];
  performance?: {
    realizedPnlUsd?: number;
    closedTrades?: number;
    wins?: number;
    winRate?: number | null;
    dayRealizedPnlUsd?: number;
  };
  sharedAccount?: {
    equity?: number;
    availableBalance?: number;
    unrealizedPnl?: number;
    maintenanceMargin?: number;
    marginRatio?: number | null;
  };
  ownership?: {
    activeSymbols?: string[];
    strategy2Symbols?: string[];
    overlap?: string[];
  };
};

const ENTRY_CHECKS = [
  "Bollinger Band locatie", "Momentum", "Trendfilter", "Volume bevestiging",
  "Orderflow", "Orderboek", "Liquiditeit", "Spread check", "Volatiliteit",
  "Kosten check", "Liquidatiebuffer", "Historische edge",
] as const;

const DEFAULT_SETTINGS: SniperSettings = {
  maxTradeSeconds: 180,
  tpMinPercent: 0.18,
  tpMaxPercent: 0.45,
  maxLossUsd: 0.10,
  maxConcurrent: 3,
  marginPerTradeUsd: 1,
  leverage: 20,
  cooldownSeconds: 60,
  attemptsPerCoin: 3,
  maxDailyLossUsd: 5,
  profitLockPercent: 0.10,
  universeTopN: 60,
};

function n(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function money(value: unknown) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(parsed);
}

function price(value: unknown) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) return "—";
  return parsed >= 1000 ? parsed.toLocaleString("en-US", { maximumFractionDigits: 2 }) : parsed.toLocaleString("en-US", { maximumFractionDigits: 8 });
}

function age(value: unknown) {
  const total = Math.max(0, Math.floor(n(value)));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export function SniperDashboard({ cloudReady }: { cloudReady: boolean }) {
  const [tab, setTab] = useState<SniperTab>("overview");
  const [data, setData] = useState<SniperPayload | null>(null);
  const [settings, setSettings] = useState<SniperSettings>(DEFAULT_SETTINGS);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [startConfirm, setStartConfirm] = useState(false);
  const [backtest, setBacktest] = useState<Record<string, unknown> | null>(null);

  const refresh = useCallback(async () => {
    if (!cloudReady) return;
    try {
      const payload = await authenticatedRequest("/api/exchanges/aster/sniper") as SniperPayload;
      setData(payload);
      if (payload.settings) setSettings({ ...DEFAULT_SETTINGS, ...payload.settings });
      setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Sniper-status kon niet worden geladen.");
    }
  }, [cloudReady]);

  useEffect(() => { void refresh(); }, [refresh]);

  useEffect(() => {
    if (!data?.enabled && !data?.monitor) return;
    const timer = window.setInterval(() => void refresh(), 4000);
    return () => window.clearInterval(timer);
  }, [data?.enabled, data?.monitor, refresh]);

  const act = async (name: string, request: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(name);
    setMessage("");
    try {
      await request();
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "De Sniper-opdracht is niet gelukt.");
    } finally {
      setBusy("");
    }
  };

  const save = () => act("save", () => authenticatedRequest("/api/exchanges/aster/sniper/settings", {
    method: "PUT", body: JSON.stringify({ settings }),
  }));

  const start = () => act("start", async () => {
    await authenticatedRequest("/api/exchanges/aster/sniper/start", {
      method: "POST", body: JSON.stringify({ confirm: true, settings }),
    });
    setStartConfirm(false);
  });

  const stop = () => act("stop", () => authenticatedRequest("/api/exchanges/aster/sniper/stop", {
    method: "POST", body: JSON.stringify({ confirm: true }),
  }));

  const closeTrade = (trade: SniperTrade) => {
    const tradeId = String(trade.tradeId || "");
    if (!tradeId || !window.confirm(`Sniper ${trade.symbol || ""} ${trade.side || ""} echt handmatig sluiten?`)) return;
    void act(`close-${tradeId}`, () => authenticatedRequest("/api/exchanges/aster/sniper/trades/close", {
      method: "POST", body: JSON.stringify({ confirm: true, trade_id: tradeId }),
    }));
  };

  const runBacktest = () => act("backtest", async () => {
    const result = await authenticatedRequest("/api/exchanges/aster/sniper/backtest", { method: "POST", body: "{}" }) as Record<string, unknown>;
    setBacktest(result);
  });

  const trades = data?.activeTrades || [];
  const signals = data?.signals || [];
  const history = data?.history || [];
  const strongest = useMemo(() => [...signals].sort((a, b) => n(b.score) - n(a.score))[0], [signals]);
  const overlap = data?.ownership?.overlap || [];
  const live = Boolean(data?.enabled);
  const liveGate = Boolean(data?.liveExecutionEnabled);

  return (
    <section className="sniper-shell" data-sniper-version="2" data-live={String(live)}>
      <header className="sniper-hero">
        <div className="sniper-title">
          <div className="sniper-eyebrow"><i /> AMAR CRYPTO BOT · SNIPER LIVE</div>
          <h1>SNIPER</h1>
          <p>Ultra-korte Aster USDT-perpetual trades. Eigen scanner, eigen posities en eigen exits — gedeelde accountwaarde en available margin.</p>
        </div>
        <div className="sniper-control">
          <span>LIVE STRATEGIE</span>
          <strong className={live ? "is-live" : ""}>{live ? "ACTIEF" : data?.monitor ? "AFBOUWEN" : "UIT"}</strong>
          {!live ? (
            <button type="button" className="primary" disabled={!liveGate || Boolean(busy)} onClick={() => setStartConfirm(true)}>
              {liveGate ? "Sniper aanzetten" : "Live execution niet gereed"}
            </button>
          ) : (
            <button type="button" className="danger" disabled={Boolean(busy)} onClick={() => void stop()}>Nieuwe entries stoppen</button>
          )}
          <small>{data?.lastReason || "Sniper-status wordt geladen…"}</small>
        </div>
      </header>

      {startConfirm && (
        <div className="sniper-live-confirm" role="alertdialog" aria-modal="true">
          <div>
            <span>LIVE BEVESTIGING</span>
            <strong>Sniper gaat echte Aster-orders plaatsen.</strong>
            <p>De strategie gebruikt dezelfde portfolio- en available margin als Aster, maar claimt uitsluitend vrije symbols. Aster en Sniper mogen nooit dezelfde munt beheren. ${!data?.canaryValidated ? "Bij de eerste activering voert Sniper eerst automatisch één zeer kleine echte Aster open/fill/close-canary uit. Alleen na volledige exchange-bevestiging wordt de scanner vrijgegeven." : "De live activation canary is al exchange-bevestigd."}</p>
          </div>
          <div className="confirm-actions">
            <button type="button" onClick={() => setStartConfirm(false)}>Annuleren</button>
            <button type="button" className="primary" disabled={Boolean(busy)} onClick={() => void start()}>BEVESTIG LIVE SNIPER</button>
          </div>
        </div>
      )}

      {message && <div className="sniper-alert">{message}</div>}
      {overlap.length > 0 && <div className="sniper-alert critical">OWNERSHIP-CONFLICT: {overlap.join(", ")} · nieuwe orders zijn geblokkeerd.</div>}

      <div className="sniper-metrics">
        <Metric label="GEDEELD PORTFOLIO" value={money(data?.sharedAccount?.equity)} detail="Aster-account equity" />
        <Metric label="AVAILABLE" value={money(data?.sharedAccount?.availableBalance)} detail="Gedeelde vrije margin" />
        <Metric label="SNIPER OPEN" value={String(trades.length)} detail={`max ${settings.maxConcurrent}`} />
        <Metric label="VANDAAG" value={money(data?.performance?.dayRealizedPnlUsd)} detail="Sniper gerealiseerd" />
        <Metric label="ACCOUNT RISK" value={data?.sharedAccount?.marginRatio == null ? "—" : `${(n(data.sharedAccount.marginRatio) * 100).toFixed(1)}%`} detail="Gedeeld liquidatierisico" />
        <Metric label="LIVE CANARY" value={data?.canaryValidated ? "BEVESTIGD" : String(data?.canaryStatus || "NIET GEDRAAID").replaceAll("_", " ")} detail={data?.canaryValidated ? "Aster open/fill/close bewezen" : "Eerste live start voert bounded canary uit"} />
      </div>

      <nav className="sniper-tabs" aria-label="Sniper onderdelen">
        {([
          ["overview", "Overzicht"], ["trades", "Trades"], ["signals", "Signalen"],
          ["performance", "Prestaties"], ["settings", "Instellingen"],
        ] as Array<[SniperTab, string]>).map(([id, label]) => (
          <button key={id} type="button" className={tab === id ? "active" : ""} onClick={() => setTab(id)}>{label}</button>
        ))}
      </nav>

      {tab === "overview" && (
        <div className="sniper-grid">
          <article className="sniper-card wide">
            <CardHead kicker="LIVE SCANNER" title={live ? "Scanner zoekt 12/12 setups" : "Scanner staat uit"} badge={live ? "ECHT GELD" : "GESTOPT"} />
            {strongest ? (
              <div className="scanner-focus">
                <div><span>STERKSTE KANDIDAAT</span><strong>{strongest.symbol || "—"}</strong><small>{strongest.side || "—"} · {strongest.timeframe || "—"}</small></div>
                <div className={`score-ring ${n(strongest.score) === 12 ? "pass" : "watch"}`}><strong>{n(strongest.score)}</strong><span>/ 12</span></div>
                <div><span>STATUS</span><strong>{strongest.eligible ? "ENTRY GEREED" : "WACHTEN"}</strong><small>{strongest.reason || "—"}</small></div>
              </div>
            ) : <Empty title="Nog geen scanresultaat" text="Zodra de live scanner draait verschijnen hier de meest recente kandidaten." />}
            <div className="check-grid">
              {(strongest?.checks?.length ? strongest.checks : ENTRY_CHECKS.map((name) => ({ name, passed: false }))).map((check) => (
                <div className={`check-chip ${check.passed ? "pass" : "wait"}`} key={String(check.name)}>
                  <i>{check.passed ? "✓" : "·"}</i><span>{check.name}</span>
                </div>
              ))}
            </div>
          </article>

          <article className="sniper-card">
            <CardHead kicker="POSITIONS" title="Sniper ownership" badge={overlap.length ? "CONFLICT" : "GEÏSOLEERD"} />
            <div className="big-value">{trades.length} / {settings.maxConcurrent}</div>
            <p className="muted">Sniper symbols: {(data?.ownership?.activeSymbols || []).join(", ") || "geen"}</p>
            <p className="muted">Aster symbols zijn voor Sniper automatisch geblokkeerd.</p>
          </article>

          <article className="sniper-card">
            <CardHead kicker="EXIT ENGINE" title="Harde grenzen" />
            <ul className="plain-list">
              <li><span>Max tradeduur</span><b>{settings.maxTradeSeconds}s</b></li>
              <li><span>TP-zone</span><b>{settings.tpMinPercent}–{settings.tpMaxPercent}%</b></li>
              <li><span>Max verlies</span><b>{money(settings.maxLossUsd)}</b></li>
              <li><span>Margin / trade</span><b>{money(settings.marginPerTradeUsd)}</b></li>
            </ul>
          </article>

          <article className="sniper-card wide">
            <CardHead kicker="ACTIEVE SNIPER TRADES" title={trades.length ? "Live op Aster" : "Geen open Sniper-posities"} />
            {trades.length ? <TradeTable trades={trades} busy={busy} onClose={closeTrade} /> :
              <Empty title="Sniper is flat" text="Aster-posities worden hier bewust niet getoond." />}
          </article>
        </div>
      )}

      {tab === "trades" && (
        <div className="sniper-grid">
          <article className="sniper-card wide">
            <CardHead kicker="OPEN" title="Eigen Sniper-posities" badge="LIVE ASTER" />
            {trades.length ? <TradeTable trades={trades} busy={busy} onClose={closeTrade} /> :
              <Empty title="Geen open Sniper-trades" text="Alleen posities met bewezen SNIPER ownership verschijnen hier." />}
          </article>
          <article className="sniper-card wide">
            <CardHead kicker="GESLOTEN" title="Sniper historie" />
            {history.length ? <HistoryTable rows={history} /> :
              <Empty title="Nog geen gesloten Sniper-trades" text="Aster tradehistorie blijft volledig buiten dit overzicht." />}
          </article>
        </div>
      )}

      {tab === "signals" && (
        <article className="sniper-card">
          <CardHead kicker="SIGNAL FEED" title="Laatste Sniper-kandidaten" badge="EIGEN SCANNER" />
          {signals.length ? <div className="signal-table">
            <div className="signal-head"><span>PAIR</span><span>RICHTING</span><span>TF</span><span>CHECKS</span><span>STATUS</span></div>
            {signals.map((signal, index) => (
              <div className="signal-row" key={`${signal.symbol}-${index}`}>
                <strong>{signal.symbol}</strong><span>{signal.side || "—"}</span><span>{signal.timeframe || "—"}</span>
                <span>{n(signal.score)}/12</span><span className={signal.eligible ? "signal-pass" : ""}>{signal.reason || "Wachten"}</span>
              </div>
            ))}
          </div> : <Empty title="Nog geen signalen" text="De Sniper scanner deelt geen triggers met Aster." />}
        </article>
      )}

      {tab === "performance" && (
        <div className="sniper-grid four">
          <article className="sniper-card"><CardHead kicker="TOTAAL" title="Netto gerealiseerd" /><div className="big-value">{money(data?.performance?.realizedPnlUsd)}</div></article>
          <article className="sniper-card"><CardHead kicker="TRADES" title="Gesloten" /><div className="big-value">{n(data?.performance?.closedTrades)}</div></article>
          <article className="sniper-card"><CardHead kicker="WINS" title="Winsttrades" /><div className="big-value">{n(data?.performance?.wins)}</div></article>
          <article className="sniper-card"><CardHead kicker="WINRATE" title="Bevestigd" /><div className="big-value">{data?.performance?.winRate == null ? "—" : `${n(data.performance.winRate).toFixed(1)}%`}</div></article>
          <article className="sniper-card wide"><CardHead kicker="HISTORIE" title="Alleen Sniper-resultaten" />{history.length ? <HistoryTable rows={history} /> : <Empty title="Nog geen resultaatdata" text="Performance wordt uitsluitend uit Sniper-trades opgebouwd." />}</article>
        </div>
      )}

      {tab === "settings" && (
        <div className="sniper-grid">
          <article className="sniper-card wide">
            <CardHead kicker="LIVE PARAMETERS" title="Sniper grenzen" badge={live ? "ACTIEF" : "BEWERKBAAR"} />
            <div className="settings-grid">
              <NumberField label="Margin / trade ($)" value={settings.marginPerTradeUsd} onChange={(value) => setSettings({ ...settings, marginPerTradeUsd: value })} />
              <NumberField label="Leverage" value={settings.leverage} onChange={(value) => setSettings({ ...settings, leverage: Math.round(value) })} />
              <NumberField label="Max concurrent" value={settings.maxConcurrent} onChange={(value) => setSettings({ ...settings, maxConcurrent: Math.round(value) })} />
              <NumberField label="Max tradeduur (sec)" value={settings.maxTradeSeconds} onChange={(value) => setSettings({ ...settings, maxTradeSeconds: Math.round(value) })} />
              <NumberField label="TP minimum (%)" value={settings.tpMinPercent} onChange={(value) => setSettings({ ...settings, tpMinPercent: value })} />
              <NumberField label="TP maximum (%)" value={settings.tpMaxPercent} onChange={(value) => setSettings({ ...settings, tpMaxPercent: value })} />
              <NumberField label="Max verlies / trade ($)" value={settings.maxLossUsd} onChange={(value) => setSettings({ ...settings, maxLossUsd: value })} />
              <NumberField label="Cooldown (sec)" value={settings.cooldownSeconds} onChange={(value) => setSettings({ ...settings, cooldownSeconds: Math.round(value) })} />
              <NumberField label="Pogingen / coin" value={settings.attemptsPerCoin} onChange={(value) => setSettings({ ...settings, attemptsPerCoin: Math.round(value) })} />
              <NumberField label="Max dagverlies ($)" value={settings.maxDailyLossUsd} onChange={(value) => setSettings({ ...settings, maxDailyLossUsd: value })} />
              <NumberField label="Profit lock (%)" value={settings.profitLockPercent} onChange={(value) => setSettings({ ...settings, profitLockPercent: value })} />
              <NumberField label="Universe Top-N" value={settings.universeTopN} onChange={(value) => setSettings({ ...settings, universeTopN: Math.round(value) })} />
            </div>
            <div className="settings-actions">
              <button type="button" className="primary" disabled={Boolean(busy)} onClick={() => void save()}>{busy === "save" ? "Opslaan…" : "Instellingen opslaan"}</button>
              <button type="button" disabled={Boolean(busy)} onClick={() => void runBacktest()}>{busy === "backtest" ? "Backtest draait…" : "Historische backtest uitvoeren"}</button>
            </div>
          </article>

          <article className="sniper-card wide">
            <CardHead kicker="ENTRY ENGINE" title="12 onafhankelijke checks" badge="12 / 12 VERPLICHT" />
            <div className="check-grid static">{ENTRY_CHECKS.map((name) => <div className="check-chip pass" key={name}><i>✓</i><span>{name}</span></div>)}</div>
          </article>

          {backtest && (
            <article className="sniper-card wide">
              <CardHead kicker="READ-ONLY TEST" title="Laatste backtest" badge="GEEN ORDERS" />
              <pre className="backtest-output">{JSON.stringify(backtest, null, 2)}</pre>
            </article>
          )}
        </div>
      )}
    </section>
  );
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="sniper-metric"><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>;
}

function CardHead({ kicker, title, badge }: { kicker: string; title: string; badge?: string }) {
  return <div className="sniper-card-head"><div><span>{kicker}</span><h2>{title}</h2></div>{badge ? <b>{badge}</b> : null}</div>;
}

function Empty({ title, text }: { title: string; text: string }) {
  return <div className="sniper-empty"><strong>{title}</strong><p>{text}</p></div>;
}

function NumberField({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  return <label className="sniper-field"><span>{label}</span><input inputMode="decimal" type="number" value={value} onChange={(event) => onChange(Number(event.target.value))} /></label>;
}

function TradeTable({ trades, busy, onClose }: { trades: SniperTrade[]; busy: string; onClose: (trade: SniperTrade) => void }) {
  return <div className="trade-table">
    <div className="trade-head"><span>PAIR</span><span>RICHTING</span><span>ENTRY</span><span>MARK</span><span>PNL</span><span>TIJD</span><span /></div>
    {trades.map((trade) => <div className="trade-row" key={String(trade.tradeId)}>
      <strong>{trade.symbol || "—"}</strong><span>{trade.side || "—"}</span><span>{price(trade.entryPrice)}</span><span>{price(trade.markPrice)}</span>
      <span className={n(trade.unrealizedPnlUsd) >= 0 ? "pnl-positive" : "pnl-negative"}>{money(trade.unrealizedPnlUsd)}<small>{n(trade.unrealizedPnlPercent).toFixed(2)}%</small></span>
      <span>{age(trade.elapsedSeconds)}<small>{trade.timeframe || ""}</small></span>
      <button type="button" disabled={Boolean(busy)} onClick={() => onClose(trade)}>Sluit</button>
    </div>)}
  </div>;
}

function HistoryTable({ rows }: { rows: SniperTrade[] }) {
  return <div className="history-list">{rows.slice(0, 100).map((row, index) => (
    <div className="history-row" key={String(row.tradeId || index)}>
      <div><strong>{row.symbol || "—"}</strong><span>{row.side || "—"} · {row.timeframe || "—"}</span></div>
      <div>
        <span>{row.costEvidenceReliable === false ? "Accounting controleren" : `${row.exitReason || "Gesloten"} · fees ${money(row.feesUsd)}`}</span>
        <strong className={n(row.netRealizedPnlUsd ?? row.realizedPnlUsd) >= 0 ? "pnl-positive" : "pnl-negative"}>
          {row.costEvidenceReliable === false ? "—" : money(row.netRealizedPnlUsd ?? row.realizedPnlUsd)}
        </strong>
      </div>
    </div>
  ))}</div>;
}
