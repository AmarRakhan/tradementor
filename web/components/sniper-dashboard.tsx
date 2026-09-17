"use client";

import { useEffect, useMemo, useState } from "react";
import type { ExchangeSnapshots } from "@/lib/use-exchange-data";

type SniperTab = "overview" | "trades" | "signals" | "performance" | "settings";
type CheckState = "pass" | "watch" | "blocked";

type SniperSettings = {
  enabled: boolean;
  simulation: boolean;
  maxTradeSeconds: number;
  tpMinPercent: number;
  tpMaxPercent: number;
  maxLossUsd: number;
  maxConcurrent: number;
  marginPerTradeUsd: string;
  cooldownSeconds: string;
  attemptsPerCoin: string;
  maxDailyLossUsd: string;
  profitLockPercent: string;
};

const STORAGE_KEY = "aavansh.sniper.v1.settings";

const DEFAULT_SETTINGS: SniperSettings = {
  enabled: false,
  simulation: true,
  maxTradeSeconds: 180,
  tpMinPercent: 0.18,
  tpMaxPercent: 0.45,
  maxLossUsd: 0.10,
  maxConcurrent: 3,
  marginPerTradeUsd: "1.00",
  cooldownSeconds: "",
  attemptsPerCoin: "",
  maxDailyLossUsd: "",
  profitLockPercent: "",
};

const ENTRY_CHECKS = [
  "Bollinger Band locatie",
  "Momentum",
  "Trendfilter",
  "Volume bevestiging",
  "Orderflow",
  "Orderboek",
  "Liquiditeit",
  "Spread check",
  "Volatiliteit",
  "Kosten check",
  "Liquidatiebuffer",
  "Historische edge",
] as const;

const SAMPLE_SIGNALS = [
  { symbol: "BTCUSDT", side: "LONG", timeframe: "1m", score: 11, state: "watch" as CheckState, reason: "11/12 checks · wacht op orderflow" },
  { symbol: "ETHUSDT", side: "SHORT", timeframe: "3m", score: 12, state: "pass" as CheckState, reason: "12/12 checks · simulatie-entry gereed" },
  { symbol: "SOLUSDT", side: "LONG", timeframe: "15s", score: 9, state: "blocked" as CheckState, reason: "9/12 checks · spread/volume/liquiditeit blokkeren" },
  { symbol: "HYPEUSDT", side: "LONG", timeframe: "5m", score: 10, state: "watch" as CheckState, reason: "10/12 checks · trend en kosten nog niet bevestigd" },
];

function numericCandidate(source: unknown, keys: string[]): number | null {
  if (!source || typeof source !== "object") return null;
  const object = source as Record<string, unknown>;
  for (const key of keys) {
    const raw = object[key];
    const value = typeof raw === "number" ? raw : typeof raw === "string" ? Number(raw) : NaN;
    if (Number.isFinite(value)) return value;
  }
  for (const value of Object.values(object)) {
    if (!value || typeof value !== "object" || Array.isArray(value)) continue;
    const found = numericCandidate(value, keys);
    if (found !== null) return found;
  }
  return null;
}

function money(value: number | null) {
  if (value === null) return "—";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
}

export function SniperDashboard({ snapshots, cloudReady }: { snapshots: ExchangeSnapshots; cloudReady: boolean }) {
  const [tab, setTab] = useState<SniperTab>("overview");
  const [settings, setSettings] = useState<SniperSettings>(DEFAULT_SETTINGS);
  const [ready, setReady] = useState(false);
  const [scanTick, setScanTick] = useState(0);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored) setSettings({ ...DEFAULT_SETTINGS, ...JSON.parse(stored) });
    } catch { /* Invalid local state never enables trading. */ }
    setReady(true);
  }, []);

  useEffect(() => {
    if (!ready) return;
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  }, [settings, ready]);

  useEffect(() => {
    if (!settings.enabled || !settings.simulation) return;
    const timer = window.setInterval(() => setScanTick((value) => value + 1), 1600);
    return () => window.clearInterval(timer);
  }, [settings.enabled, settings.simulation]);

  const asterEquity = useMemo(() => numericCandidate(snapshots.aster.data, ["equity", "accountValue", "totalEquity", "portfolioValue", "balance"]), [snapshots.aster.data]);
  const hyperEquity = useMemo(() => numericCandidate(snapshots.hyperliquid.data, ["equity", "accountValue", "totalEquity", "portfolioValue", "balance"]), [snapshots.hyperliquid.data]);
  const asterAvailable = useMemo(() => numericCandidate(snapshots.aster.data, ["availableToTrade", "availableBalance", "available", "withdrawable"]), [snapshots.aster.data]);
  const totalEquity = (asterEquity ?? 0) + (hyperEquity ?? 0) || null;
  const activeSignal = SAMPLE_SIGNALS[scanTick % SAMPLE_SIGNALS.length];
  const configuredRisk = Boolean(settings.cooldownSeconds && settings.attemptsPerCoin && settings.maxDailyLossUsd && settings.profitLockPercent);
  const liveLocked = true;

  const update = <K extends keyof SniperSettings>(key: K, value: SniperSettings[K]) => setSettings((current) => ({ ...current, [key]: value }));

  return (
    <section className="sniper-shell" data-sniper-version="1" aria-label="SNIPER strategie">
      <div className="sniper-hero">
        <div>
          <div className="sniper-eyebrow"><span className="sniper-dot" /> AAVANSH TRADING · SNIPER V1</div>
          <h1>SNIPER</h1>
          <p>Ultra-korte USDT-perpetual strategie met maximaal 3 minuten per trade, continue validatie en twaalf onafhankelijke entry-checks.</p>
        </div>
        <div className="sniper-mode-card">
          <span>STRATEGIE</span>
          <strong>{settings.enabled ? "ACTIEF" : "UIT"}</strong>
          <button type="button" className={settings.enabled ? "on" : ""} onClick={() => update("enabled", !settings.enabled)} aria-pressed={settings.enabled}>
            <i /> {settings.enabled ? "Sniper aan" : "Sniper uit"}
          </button>
          <small>{settings.simulation ? "Alleen simulatie · geen echte orders" : "Live geblokkeerd totdat backend-gates zijn getest"}</small>
        </div>
      </div>

      <div className="sniper-metrics">
        <Metric label="GEDEELD PORTFOLIO" value={money(totalEquity)} detail="Alleen lezen uit gekoppelde accounts" />
        <Metric label="ASTER AVAILABLE" value={money(asterAvailable)} detail="Atomic reservation volgt in execution-laag" />
        <Metric label="MAX TRADEDUUR" value="03:00" detail="Harde timeout" />
        <Metric label="TP-ZONE" value="0,18–0,45%" detail="Dynamisch binnen ingestelde band" />
        <Metric label="MAX VERLIES / TRADE" value="$0,10" detail="Risicogate vóór iedere entry" />
      </div>

      <nav className="sniper-tabs" aria-label="SNIPER onderdelen">
        {([
          ["overview", "Overzicht"],
          ["trades", "Trades"],
          ["signals", "Signalen"],
          ["performance", "Prestaties"],
          ["settings", "Instellingen"],
        ] as Array<[SniperTab, string]>).map(([id, label]) => (
          <button key={id} type="button" className={tab === id ? "active" : ""} onClick={() => setTab(id)}>{label}</button>
        ))}
      </nav>

      {tab === "overview" && (
        <div className="sniper-grid">
          <article className="sniper-card wide">
            <CardHead kicker="LIVE SCANNER" title={settings.enabled ? "Scanner draait" : "Scanner gereed"} badge={settings.simulation ? "SIMULATIE" : "LIVE LOCKED"} />
            <div className="scanner-focus">
              <div><span>NU GESCAND</span><strong>{activeSignal.symbol}</strong><small>{activeSignal.side} · {activeSignal.timeframe}</small></div>
              <div className={`score-ring ${activeSignal.state}`}><strong>{activeSignal.score}</strong><span>/ 12</span></div>
              <div><span>STATUS</span><strong>{activeSignal.state === "pass" ? "ENTRY GEREED" : activeSignal.state === "blocked" ? "GEBLOKKEERD" : "WACHTEN"}</strong><small>{activeSignal.reason}</small></div>
            </div>
            <div className="check-grid">
              {ENTRY_CHECKS.map((name, index) => {
                const passed = index < activeSignal.score;
                return <div className={`check-chip ${passed ? "pass" : "wait"}`} key={name}><i>{passed ? "✓" : "·"}</i><span>{name}</span></div>;
              })}
            </div>
          </article>

          <article className="sniper-card">
            <CardHead kicker="ENTRY ENGINE" title="4 timeframes" />
            <div className="timeframes"><b>15s</b><b>1m</b><b>3m</b><b>5m</b></div>
            <p className="muted">Een entry mag pas door wanneer alle geactiveerde checks én de risk/capital/ownership-gates geldig zijn.</p>
          </article>

          <article className="sniper-card">
            <CardHead kicker="EXIT ENGINE" title="Continue validatie" />
            <ul className="plain-list">
              <li><span>Dynamic TP</span><b>0,18–0,45%</b></li>
              <li><span>Hard loss</span><b>max $0,10</b></li>
              <li><span>Timeout</span><b>180 sec</b></li>
              <li><span>Profit lock</span><b>{settings.profitLockPercent ? `${settings.profitLockPercent}%` : "Nog instellen"}</b></li>
            </ul>
          </article>

          <article className="sniper-card wide">
            <CardHead kicker="ISOLATIE" title="Sniper raakt Aster niet" badge={cloudReady ? "CLOUD ACTIEF" : "CLOUD CONTROLEREN"} />
            <div className="isolation-row"><span>✓ Eigen settings/state</span><span>✓ Eigen signalen</span><span>✓ Eigen trades</span><span>✓ Eigen performance</span><span>✓ Geen Aster close/manage</span></div>
          </article>
        </div>
      )}

      {tab === "trades" && (
        <div className="sniper-grid">
          <article className="sniper-card wide">
            <CardHead kicker="SNIPER TRADES" title="Simulatie-orders" badge="GEÏSOLEERD" />
            <div className="empty-trades"><strong>Nog geen Sniper-trades</strong><p>Zodra de simulatiescanner een geldige 12/12 setup uitvoert, verschijnt de trade hier. Echte orderuitvoering blijft in deze eerste testbuild geblokkeerd.</p></div>
          </article>
          <article className="sniper-card"><CardHead kicker="LIMIET" title="Concurrent" /><div className="big-value">{settings.maxConcurrent}</div><p className="muted">Maximaal gelijktijdige Sniper-trades.</p></article>
          <article className="sniper-card"><CardHead kicker="MARGIN" title="Per trade" /><div className="big-value">${settings.marginPerTradeUsd || "—"}</div><p className="muted">Echte available-margin; leverage bepaalt notional.</p></article>
        </div>
      )}

      {tab === "signals" && (
        <article className="sniper-card">
          <CardHead kicker="SIGNAL FEED" title="Kandidaten" badge="SIMULATIE" />
          <div className="signal-table">
            <div className="signal-head"><span>PAIR</span><span>RICHTING</span><span>TF</span><span>CHECKS</span><span>STATUS</span></div>
            {SAMPLE_SIGNALS.map((signal) => <div className="signal-row" key={signal.symbol}><strong>{signal.symbol}</strong><span>{signal.side}</span><span>{signal.timeframe}</span><span>{signal.score}/12</span><span className={`signal-state ${signal.state}`}>{signal.state === "pass" ? "Gereed" : signal.state === "blocked" ? "Geblokkeerd" : "Wachten"}</span></div>)}
          </div>
        </article>
      )}

      {tab === "performance" && (
        <div className="sniper-grid">
          <article className="sniper-card"><CardHead kicker="VANDAAG" title="Netto PnL" /><div className="big-value">$0,00</div><p className="muted">Alleen Sniper-resultaat; Aster-resultaten tellen hier niet mee.</p></article>
          <article className="sniper-card"><CardHead kicker="TRADES" title="Voltooid" /><div className="big-value">0</div><p className="muted">Simulatie- en live-resultaten blijven afzonderlijk gelabeld.</p></article>
          <article className="sniper-card"><CardHead kicker="WINRATE" title="Bevestigd" /><div className="big-value">—</div><p className="muted">Verschijnt zodra er voldoende eigen Sniper-data is.</p></article>
          <article className="sniper-card"><CardHead kicker="EDGE" title="Historische check" /><div className="big-value">12/12</div><p className="muted">Historische edge is één van de verplichte entry-checks.</p></article>
        </div>
      )}

      {tab === "settings" && (
        <div className="sniper-grid">
          <article className="sniper-card wide">
            <CardHead kicker="MODUS" title="Veilig testen" badge={settings.simulation ? "SIMULATIE ACTIEF" : "LIVE LOCKED"} />
            <div className="mode-select">
              <button className={settings.simulation ? "active" : ""} type="button" onClick={() => update("simulation", true)}><strong>Simulatie</strong><span>Scanner + entries zonder echte orders</span></button>
              <button disabled={liveLocked} type="button" title="Live wordt pas vrijgegeven nadat backend, ownership en risk-gates end-to-end zijn getest"><strong>Live</strong><span>Geblokkeerd in deze testbuild</span></button>
            </div>
          </article>

          <article className="sniper-card wide">
            <CardHead kicker="TRADE PARAMETERS" title="Sniper grenzen" />
            <div className="settings-grid">
              <Field label="Max tradeduur (sec)" value={String(settings.maxTradeSeconds)} disabled />
              <Field label="TP minimum (%)" value={String(settings.tpMinPercent)} disabled />
              <Field label="TP maximum (%)" value={String(settings.tpMaxPercent)} disabled />
              <Field label="Max verlies / trade ($)" value={String(settings.maxLossUsd)} disabled />
              <Field label="Max concurrent" value={String(settings.maxConcurrent)} disabled />
              <Field label="Margin / trade ($)" value={settings.marginPerTradeUsd} onChange={(value) => update("marginPerTradeUsd", value)} />
            </div>
          </article>

          <article className="sniper-card wide">
            <CardHead kicker="RISICO" title="Waarden die jij nog vastlegt" badge={configuredRisk ? "INGESTELD" : "NOG INSTELLEN"} />
            <div className="settings-grid">
              <Field label="Cooldown (sec)" value={settings.cooldownSeconds} placeholder="Nog niet afgesproken" onChange={(value) => update("cooldownSeconds", value)} />
              <Field label="Pogingen per coin" value={settings.attemptsPerCoin} placeholder="Vrij instelbaar" onChange={(value) => update("attemptsPerCoin", value)} />
              <Field label="Max dagverlies ($)" value={settings.maxDailyLossUsd} placeholder="Nog niet afgesproken" onChange={(value) => update("maxDailyLossUsd", value)} />
              <Field label="Profit lock (%)" value={settings.profitLockPercent} placeholder="Verplicht · waarde nog open" onChange={(value) => update("profitLockPercent", value)} />
            </div>
          </article>

          <article className="sniper-card wide">
            <CardHead kicker="ENTRY CHECKS" title="12 van 12 actief" />
            <div className="check-grid static">{ENTRY_CHECKS.map((name) => <div className="check-chip pass" key={name}><i>✓</i><span>{name}</span></div>)}</div>
          </article>
        </div>
      )}

      <style jsx>{`
        .sniper-shell{display:grid;gap:16px;padding:4px 0 28px;color:#eefbf3}.sniper-hero{display:grid;grid-template-columns:minmax(0,1fr) 250px;gap:18px;padding:26px;border:1px solid rgba(86,255,146,.2);border-radius:24px;background:radial-gradient(circle at 15% 0%,rgba(40,255,120,.12),transparent 34%),linear-gradient(145deg,rgba(8,22,16,.98),rgba(5,11,9,.98));box-shadow:0 24px 70px rgba(0,0,0,.25)}.sniper-eyebrow{display:flex;align-items:center;gap:8px;font-size:11px;font-weight:800;letter-spacing:.16em;color:#7cf7a8}.sniper-dot{width:8px;height:8px;border-radius:50%;background:#54f58e;box-shadow:0 0 15px #54f58e}.sniper-hero h1{margin:8px 0 4px;font-size:clamp(34px,5vw,62px);line-height:.95;letter-spacing:-.05em}.sniper-hero p{max-width:720px;margin:10px 0 0;color:#93aa9b;line-height:1.55}.sniper-mode-card{display:flex;flex-direction:column;gap:7px;padding:16px;border:1px solid rgba(255,255,255,.08);border-radius:18px;background:rgba(255,255,255,.03)}.sniper-mode-card>span,.scanner-focus span{font-size:10px;font-weight:800;letter-spacing:.14em;color:#769182}.sniper-mode-card>strong{font-size:24px}.sniper-mode-card button{height:42px;border:1px solid rgba(255,255,255,.12);border-radius:12px;background:#151d19;color:#9eb0a5;font-weight:800;cursor:pointer}.sniper-mode-card button.on{border-color:rgba(77,244,136,.5);background:rgba(42,220,107,.15);color:#6ef49e}.sniper-mode-card button i{display:inline-block;width:8px;height:8px;margin-right:7px;border-radius:50%;background:currentColor}.sniper-mode-card small{color:#73847a;line-height:1.35}.sniper-metrics{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px}.metric{min-width:0;padding:15px;border:1px solid rgba(255,255,255,.07);border-radius:16px;background:#0a120f}.metric span{display:block;font-size:9px;font-weight:800;letter-spacing:.12em;color:#70867a}.metric strong{display:block;margin-top:7px;font-size:18px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.metric small{display:block;margin-top:5px;color:#63766b;line-height:1.25}.sniper-tabs{display:grid;grid-template-columns:repeat(5,1fr);gap:6px;padding:6px;border:1px solid rgba(255,255,255,.07);border-radius:16px;background:#07100c}.sniper-tabs button{min-height:42px;border:0;border-radius:11px;background:transparent;color:#73877c;font-weight:800;cursor:pointer}.sniper-tabs button.active{background:rgba(55,236,119,.12);color:#70f79f;box-shadow:inset 0 0 0 1px rgba(73,242,132,.18)}.sniper-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.sniper-card{min-width:0;padding:19px;border:1px solid rgba(255,255,255,.07);border-radius:19px;background:linear-gradient(150deg,#0b1410,#08100d)}.sniper-card.wide{grid-column:1/-1}.card-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:16px}.card-head span{font-size:9px;font-weight:800;letter-spacing:.14em;color:#688175}.card-head h2{margin:4px 0 0;font-size:18px}.card-head b{padding:5px 8px;border-radius:8px;background:rgba(65,241,128,.09);color:#6bf49b;font-size:9px;letter-spacing:.1em}.scanner-focus{display:grid;grid-template-columns:1fr 110px 1.3fr;gap:18px;align-items:center;padding:18px;border:1px solid rgba(255,255,255,.06);border-radius:15px;background:rgba(0,0,0,.13)}.scanner-focus strong{display:block;margin-top:5px;font-size:20px}.scanner-focus small{display:block;margin-top:4px;color:#748b7e}.score-ring{width:84px;height:84px;margin:auto;border-radius:50%;display:grid;place-content:center;text-align:center;border:7px solid rgba(255,255,255,.08)}.score-ring.pass{border-color:#46ef83}.score-ring.watch{border-color:#d6b949}.score-ring.blocked{border-color:#e26060}.score-ring strong{font-size:25px;line-height:1}.score-ring span{margin-top:3px}.check-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin-top:12px}.check-chip{display:flex;align-items:center;gap:8px;min-height:38px;padding:8px 10px;border-radius:10px;background:rgba(255,255,255,.025);color:#7f9388;font-size:12px}.check-chip i{display:grid;place-content:center;width:18px;height:18px;border-radius:50%;font-style:normal;font-weight:900;background:rgba(255,255,255,.06)}.check-chip.pass{color:#94eeb1}.check-chip.pass i{background:rgba(55,235,118,.13);color:#55ee8c}.check-chip.wait{opacity:.55}.timeframes{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.timeframes b{display:grid;place-content:center;height:54px;border:1px solid rgba(75,241,133,.16);border-radius:12px;background:rgba(65,235,126,.05);color:#7bf5a6}.muted{color:#6f8177;line-height:1.5;font-size:13px}.plain-list{list-style:none;padding:0;margin:0;display:grid;gap:8px}.plain-list li{display:flex;justify-content:space-between;gap:12px;padding:10px 0;border-bottom:1px solid rgba(255,255,255,.05);color:#84978c}.plain-list b{color:#dff4e7}.isolation-row{display:flex;flex-wrap:wrap;gap:8px}.isolation-row span{padding:8px 10px;border-radius:10px;background:rgba(62,233,122,.07);color:#82dca0;font-size:12px}.empty-trades{padding:36px 20px;text-align:center;border:1px dashed rgba(255,255,255,.1);border-radius:14px;color:#778c80}.empty-trades strong{display:block;color:#dcebe1;font-size:18px}.empty-trades p{max-width:650px;margin:8px auto 0;line-height:1.5}.big-value{font-size:36px;font-weight:850;letter-spacing:-.04em}.signal-table{display:grid}.signal-head,.signal-row{display:grid;grid-template-columns:1.3fr 1fr .6fr .7fr 1fr;gap:10px;align-items:center;padding:11px 10px}.signal-head{font-size:9px;font-weight:800;letter-spacing:.12em;color:#63776b;border-bottom:1px solid rgba(255,255,255,.07)}.signal-row{border-bottom:1px solid rgba(255,255,255,.045);color:#8da096;font-size:13px}.signal-row strong{color:#e0f0e6}.signal-state{font-weight:800}.signal-state.pass{color:#5eec91}.signal-state.watch{color:#d6bd54}.signal-state.blocked{color:#e26b6b}.mode-select{display:grid;grid-template-columns:1fr 1fr;gap:10px}.mode-select button{display:flex;flex-direction:column;align-items:flex-start;gap:4px;padding:15px;border:1px solid rgba(255,255,255,.08);border-radius:13px;background:#0a120f;color:#83968b;text-align:left}.mode-select button.active{border-color:rgba(69,238,128,.35);background:rgba(53,223,114,.08);color:#8aeeac}.mode-select button:disabled{opacity:.42}.mode-select span{font-size:12px}.settings-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.field{display:grid;gap:6px}.field span{font-size:10px;font-weight:800;letter-spacing:.08em;color:#71857a}.field input{width:100%;box-sizing:border-box;height:42px;padding:0 11px;border:1px solid rgba(255,255,255,.08);border-radius:10px;background:#07100c;color:#dceee3;outline:none}.field input:focus{border-color:rgba(73,239,131,.35)}.field input:disabled{opacity:.65}.field input::placeholder{color:#47584e}@media(max-width:900px){.sniper-hero{grid-template-columns:1fr}.sniper-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.sniper-grid{grid-template-columns:1fr}.sniper-card.wide{grid-column:auto}.scanner-focus{grid-template-columns:1fr}.check-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.settings-grid{grid-template-columns:1fr 1fr}}@media(max-width:620px){.sniper-shell{gap:10px}.sniper-hero{padding:18px;border-radius:18px}.sniper-metrics{grid-template-columns:1fr 1fr}.sniper-tabs{grid-template-columns:repeat(5,minmax(72px,1fr));overflow-x:auto}.sniper-tabs button{font-size:11px}.check-grid,.settings-grid,.mode-select{grid-template-columns:1fr}.signal-table{overflow-x:auto}.signal-head,.signal-row{min-width:620px}.sniper-card{padding:15px}.scanner-focus{padding:14px}}
      `}</style>
    </section>
  );
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>;
}

function CardHead({ kicker, title, badge }: { kicker: string; title: string; badge?: string }) {
  return <div className="card-head"><div><span>{kicker}</span><h2>{title}</h2></div>{badge ? <b>{badge}</b> : null}</div>;
}

function Field({ label, value, placeholder, disabled, onChange }: { label: string; value: string; placeholder?: string; disabled?: boolean; onChange?: (value: string) => void }) {
  return <label className="field"><span>{label}</span><input value={value} placeholder={placeholder} disabled={disabled} inputMode="decimal" onChange={(event) => onChange?.(event.target.value)} /></label>;
}
