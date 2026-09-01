"use client";

import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useAuthSession } from "@/components/auth-provider";
import { AuthGate } from "@/components/auth-gate";
import { ConnectionManager } from "@/components/connection-manager";
import { ExchangeLiveControl } from "@/components/exchange-live-control";
import { HyperliquidStrategyControl } from "@/components/hyperliquid-strategy-control";
import { AsterStrategy2Maker } from "@/components/aster-strategy2-maker";
import { AsterPerformancePanel } from "@/components/aster-performance-panel";
import { AsterRecentTrades } from "@/components/aster-recent-trades";
import { PortfolioGrowthCard } from "@/components/portfolio-growth-card";
import { PositionCloseControl } from "@/components/position-close-control";
import { authenticatedRequest } from "@/lib/cloud-client";
import { useExchangeData, type ExchangeSnapshot, type ExchangeSnapshots } from "@/lib/use-exchange-data";
import { realizedCalendar } from "@/lib/realized-calendar";
import { RiskTimeline } from "@/components/risk-timeline";
import { TradeReportControl } from "@/components/trade-report-control";
import { SupportCenter } from "@/components/support-center";
import { SafeTradingChart, type TradeSelection } from "@/components/trading-chart";
import { BacktestComparison } from "@/components/backtest-comparison";
import { isCompletePortfolioSnapshot, sanitizePortfolioEquityRows, type PortfolioEquityRow } from "@/lib/portfolio-equity-history";
import { AdminPortal } from "@/components/admin-portal";
import { AdminMfaControl } from "@/components/admin-mfa-control";
import { ASTER_FINANCIAL_DATA_CONTRACT, optionalFinancialNumber, positionDisplayReturnPercent } from "@/lib/financial-data-contract";
import { AsterBotStatus } from "@/components/aster-bot-status";
import { BotHealthCard } from "@/components/bot-health-card";
import { JourneyView } from "@/components/journey-view";
import { deriveAsterAccountDisplay, type AsterAccountDisplay } from "@/lib/aster-account-display";

type Destination = "hyperliquid" | "aster" | "journey" | "positions" | "risk" | "wallet" | "admin";
type TradingExchange = "hyperliquid" | "aster";
type InterfaceMode = "legacy" | "premium";
type AppSkin = "original" | "suriname-heritage";
type ChartScope = TradingExchange | "portfolio";
type PremiumSection = "dashboard" | "screener" | "bots" | "risk" | "portfolio" | "exchanges" | "wallet" | "academy" | "settings";

const destinationIds = new Set<Destination>(["hyperliquid", "aster", "journey", "positions", "risk", "wallet", "admin"]);

function destinationFromLocation(): Destination | null {
  const route = window.location.hash.replace(/^#\/?/, "").split(/[/?]/, 1)[0];
  return destinationIds.has(route as Destination) ? route as Destination : null;
}

function destinationHref(destination: Destination): string {
  return `${window.location.pathname}${window.location.search}#/${destination}`;
}

function asterActionsAreFresh(snapshot: ExchangeSnapshot, cloudReady: boolean) {
  return Boolean(cloudReady && snapshot.serverConfirmed && snapshot.updatedAt && Date.now() - snapshot.updatedAt < 120_000 && !snapshot.error);
}

function asterEvidenceIsFresh(value: unknown, maximumAgeMs = 120_000) {
  if (value === null || value === undefined || value === "") return false;
  let timestamp = 0;
  if (typeof value === "number" && Number.isFinite(value)) timestamp = value < 10_000_000_000 ? value * 1000 : value;
  else if (typeof value === "string") timestamp = Date.parse(value);
  else if (value instanceof Date) timestamp = value.getTime();
  if (!Number.isFinite(timestamp) || timestamp <= 0) return false;
  const age = Date.now() - timestamp;
  return age >= 0 && age < maximumAgeMs;
}

const destinations: Array<{ id: Destination; label: string; glyph: string }> = [
  { id: "hyperliquid", label: "HYPERLIQUID", glyph: "HL" },
  { id: "aster", label: "ASTER", glyph: "AS" },
  { id: "journey", label: "JOURNEY", glyph: "J" },
  { id: "positions", label: "POSITIONS", glyph: "P" },
  { id: "risk", label: "RISICO", glyph: "R" },
  { id: "wallet", label: "WALLET", glyph: "W" },
  { id: "admin", label: "ADMIN", glyph: "A" },
];

const exchangeCopy: Record<TradingExchange, { eyebrow: string; title: string; strategy: string; note: string }> = {
  hyperliquid: {
    eyebrow: "HYPERLIQUID · MULTI-PAIR",
    title: "DCA Pulse",
    strategy: "DCA Strategy Settings",
    note: "Exchange-state blijft leidend. Een verschil tussen cloud, browser en exchange blokkeert automatisch iedere nieuwe aankoop.",
  },
  aster: {
    eyebrow: "ASTER FUTURES V3 · HEDGE MODE",
    title: "Aster Multi-Pair",
    strategy: "Veilige migratiemodus",
    note: "Aster staat standaard uit. LONG en SHORT blijven afzonderlijk en kunnen pas starten na credentials, Hedge Mode en riskcontrole.",
  },
};

export default function HomePage() {
  return <AuthGate><TradeMentorHome /></AuthGate>;
}

function TradeMentorHome() {
  const { user, cloudReady, signOut } = useAuthSession();
  const [active, setActive] = useState<Destination>("hyperliquid");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [premiumOpen, setPremiumOpen] = useState(false);
  const [sound, setSound] = useState(true);
  const [motion, setMotion] = useState(true);
  const [refreshedAt, setRefreshedAt] = useState("Nog niet gesynchroniseerd");
  const [interfaceMode, setInterfaceMode] = useState<InterfaceMode>("legacy");
  const [interfacePreferenceReady, setInterfacePreferenceReady] = useState(false);
  const [interfacePreferenceMessage, setInterfacePreferenceMessage] = useState("");
  const [showHyperliquidTab, setShowHyperliquidTab] = useState(true);
  const [appSkin, setAppSkin] = useState<AppSkin>("original");
  const adminAccount = String(user?.email || "").toLowerCase() === "amar_rakhan@hotmail.com";
  const [adminDeviceAllowed, setAdminDeviceAllowed] = useState(false);
  const [adminDeviceEnrolled, setAdminDeviceEnrolled] = useState(false);
  const { snapshots, refresh, refreshAll, confirmAsterStrategy2 } = useExchangeData(cloudReady, user?.uid || "");

  useEffect(() => {
    const hyperliquid = exchangeView("hyperliquid", snapshots.hyperliquid).equityNumber;
    const aster = exchangeView("aster", snapshots.aster).equityNumber;
    const total = (hyperliquid ?? 0) + (aster ?? 0);
    if (total <= 0 || (!snapshots.hyperliquid.updatedAt && !snapshots.aster.updatedAt)) return;
    try {
      const key = `tradementor.portfolioEquity.v2.${encodeURIComponent(user?.uid || "")}`;
      const rows = JSON.parse(window.localStorage.getItem(key) || "[]");
      const history = sanitizePortfolioEquityRows(Array.isArray(rows) ? rows : []);
      const latest = history[history.length - 1];
      const now = Date.now();
      if (latest && now - Number(latest.at) < 10_000) return;
      const next: PortfolioEquityRow = { at: now, total, hyperliquid, aster };
      const persistHistory = () => {
        const overflow = history.length - 20_000;
        if (overflow > 0) history.splice(0, overflow);
        window.localStorage.setItem(key, JSON.stringify(history));
      };
      if (!isCompletePortfolioSnapshot(latest, next)) {
        persistHistory();
        return;
      }
      history.push(next);
      persistHistory();
    } catch { /* Een beschadigde lokale historie mag actuele exchange-data nooit blokkeren. */ }
  }, [snapshots.hyperliquid.updatedAt, snapshots.aster.updatedAt, user?.uid]);

  useEffect(() => {
    const saved = window.localStorage.getItem("tradementor.activeDestination");
    const route = destinationFromLocation();
    const savedInterface = window.localStorage.getItem("tradementor.interfaceMode");
    if (savedInterface === "premium" || savedInterface === "legacy") setInterfaceMode(savedInterface);
    const savedHyperliquidVisibility = window.localStorage.getItem("tradementor.navigation.hyperliquid.visible");
    let initial = route || (destinationIds.has(saved as Destination) ? saved as Destination : "hyperliquid");
    if (savedHyperliquidVisibility === "false") {
      setShowHyperliquidTab(false);
      if (initial === "hyperliquid") initial = "aster";
    }
    setActive(initial);
    window.localStorage.setItem("tradementor.activeDestination", initial);
    if (route !== initial) window.history.replaceState({ destination: initial }, "", destinationHref(initial));
    const savedSkin = window.localStorage.getItem("tradementor.appSkin");
    const skin = savedSkin === "suriname-heritage" ? "suriname-heritage" : "original";
    setAppSkin(skin);
    document.documentElement.dataset.appSkin = skin;
  }, []);

  useEffect(() => {
    const restoreDestination = () => {
      const destination = destinationFromLocation();
      if (!destination) return;
      setActive(destination);
      window.localStorage.setItem("tradementor.activeDestination", destination);
    };
    window.addEventListener("popstate", restoreDestination);
    window.addEventListener("hashchange", restoreDestination);
    return () => {
      window.removeEventListener("popstate", restoreDestination);
      window.removeEventListener("hashchange", restoreDestination);
    };
  }, []);

  const changeAppSkin = (skin: AppSkin) => {
    setAppSkin(skin);
    window.localStorage.setItem("tradementor.appSkin", skin);
    document.documentElement.dataset.appSkin = skin;
    window.dispatchEvent(new CustomEvent("tradementor:skin-change", { detail: skin }));
  };

  const changeHyperliquidTabVisibility = (visible: boolean) => {
    setShowHyperliquidTab(visible);
    window.localStorage.setItem("tradementor.navigation.hyperliquid.visible", String(visible));
    if (!visible && active === "hyperliquid") {
      setActive("aster");
      window.localStorage.setItem("tradementor.activeDestination", "aster");
      window.history.replaceState({ destination: "aster" }, "", destinationHref("aster"));
    }
  };

  const visibleDestinations = useMemo(
    () => destinations.filter((item) => (item.id !== "hyperliquid" || showHyperliquidTab) && (item.id !== "admin" || adminDeviceAllowed)),
    [showHyperliquidTab, adminDeviceAllowed],
  );

  useEffect(() => {
    if (!cloudReady || !adminAccount) { setAdminDeviceAllowed(false); return; }
    authenticatedRequest("/api/admin/device").then((value) => { setAdminDeviceAllowed(Boolean(value.allowed)); setAdminDeviceEnrolled(Boolean(value.enrolled)); }).catch(() => setAdminDeviceAllowed(false));
  }, [cloudReady, adminAccount]);

  useEffect(() => {
    if (active === "admin" && !adminDeviceAllowed) {
      setActive("wallet");
      window.localStorage.setItem("tradementor.activeDestination", "wallet");
      window.history.replaceState({ destination: "wallet" }, "", destinationHref("wallet"));
    }
  }, [active, adminDeviceAllowed]);

  useEffect(() => {
    if (!cloudReady) return;
    authenticatedRequest("/api/preferences/interface")
      .then((value) => {
        const mode = value.mode === "premium" ? "premium" : "legacy";
        setInterfaceMode(mode);
        window.localStorage.setItem("tradementor.interfaceMode", mode);
      })
      .catch(() => setInterfacePreferenceMessage("De keuze is veilig op dit apparaat opgeslagen; cloudsynchronisatie volgt."))
      .finally(() => setInterfacePreferenceReady(true));
  }, [cloudReady]);

  const changeInterfaceMode = async (mode: InterfaceMode) => {
    if (mode === interfaceMode) return;
    setInterfaceMode(mode);
    window.localStorage.setItem("tradementor.interfaceMode", mode);
    setInterfacePreferenceMessage("Weergave wordt veilig opgeslagen...");
    try {
      await authenticatedRequest("/api/preferences/interface", { method: "PUT", body: JSON.stringify({ mode }) });
      setInterfacePreferenceMessage(mode === "premium" ? "Premium-weergave actief. Tradinginstellingen zijn niet gewijzigd." : "Vertrouwde weergave actief. Tradinginstellingen zijn niet gewijzigd.");
    } catch (reason) {
      setInterfacePreferenceMessage(reason instanceof Error ? `Weergave actief op dit apparaat. Cloudsync volgt: ${reason.message}` : "Weergave actief op dit apparaat; cloudsynchronisatie volgt.");
    }
  };

  const selectDestination = (destination: Destination) => {
    if (destination === active && destinationFromLocation() === destination) return;
    setActive(destination);
    window.localStorage.setItem("tradementor.activeDestination", destination);
    window.history.pushState({ destination }, "", destinationHref(destination));
  };

  const activeLabel = useMemo(
    () => destinations.find((item) => item.id === active)?.label ?? "HYPERLIQUID",
    [active],
  );
  const initials = (user?.displayName || user?.email || "TM").split(/[\s@._-]+/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("");

  if (interfaceMode === "premium") {
    return <PremiumExperience
      cloudReady={cloudReady}
      initials={initials || "TM"}
      snapshots={snapshots}
      refreshedAt={refreshedAt}
      onRefresh={(exchange) => refresh(exchange)}
      onStrategy2Confirmed={confirmAsterStrategy2}
      onRefreshAll={() => { refreshAll(); setRefreshedAt(new Date().toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit" })); }}
      onUseLegacy={() => changeInterfaceMode("legacy")}
      preferenceReady={interfacePreferenceReady}
      preferenceMessage={interfacePreferenceMessage}
      appSkin={appSkin}
      onAppSkinChange={changeAppSkin}
    />;
  }

  return (
    <main className={`app-shell ${active === "journey" ? "journey-active" : ""}`}>
      <aside className="rail" aria-label="Hoofdnavigatie">
        <Brand compact />
        <nav className="rail-nav">
          {visibleDestinations.map((item) => (
            <NavButton key={item.id} item={item} active={active === item.id} onClick={() => selectDestination(item.id)} />
          ))}
        </nav>
        <button className="icon-button" type="button" aria-label="Instellingen openen" onClick={() => setSettingsOpen(true)}>
          <span aria-hidden="true">⚙</span>
        </button>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <Brand />
          <div className="topbar-actions">
            <span className={`environment ${cloudReady ? "connected" : ""}`}><i /> {cloudReady ? "CLOUDSESSIE ACTIEF" : "CLOUDSESSIE CONTROLEREN"}</span>
            <button className="refresh-button" type="button" onClick={() => { refreshAll(); setRefreshedAt(new Date().toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit" })); }}>
              Vernieuwen
            </button>
            <button className="avatar-button" type="button" aria-label="Instellingen openen" onClick={() => setSettingsOpen(true)}>{initials || "TM"}</button>
          </div>
        </header>

        <div className="mobile-context">
          <span>{activeLabel}</span>
          <span className="safe-label">PERSOONLIJK ACCOUNT</span>
        </div>

        <div className="content">
          {active === "admin" && adminDeviceAllowed ? <AdminPortal /> : active === "journey" ? <JourneyView snapshots={snapshots} /> : active === "wallet" ? <WalletView refreshedAt={refreshedAt} snapshots={snapshots} interfaceMode={interfaceMode} preferenceReady={interfacePreferenceReady} preferenceMessage={interfacePreferenceMessage} onInterfaceModeChange={changeInterfaceMode} showHyperliquidTab={showHyperliquidTab} onShowHyperliquidTabChange={changeHyperliquidTabVisibility} appSkin={appSkin} onAppSkinChange={changeAppSkin} /> : active === "risk" ? <RiskTimeline snapshots={snapshots} /> : active === "positions" ? <PositionsPage snapshots={snapshots} refreshedAt={refreshedAt} cloudReady={cloudReady} onRefresh={refresh} /> : <ExchangeView destination={active as TradingExchange} refreshedAt={refreshedAt} snapshot={snapshots[active as TradingExchange]} cloudReady={cloudReady} onRefresh={() => refresh(active as TradingExchange)} onStrategy2Confirmed={confirmAsterStrategy2} />}
        </div>
      </section>

      <nav className="bottom-nav" aria-label="Mobiele hoofdnavigatie" style={{ "--mobile-nav-count": visibleDestinations.length } as CSSProperties}>
        {visibleDestinations.map((item) => (
          <NavButton key={item.id} item={item} active={active === item.id} onClick={() => selectDestination(item.id)} />
        ))}
      </nav>

      {settingsOpen && (
        <div className="drawer-layer" role="presentation" onMouseDown={() => setSettingsOpen(false)}>
          <aside className="settings-drawer" role="dialog" aria-modal="true" aria-labelledby="settings-title" onMouseDown={(event) => event.stopPropagation()}>
            <div className="drawer-heading">
              <div><span className="kicker">WEBINSTELLINGEN</span><h2 id="settings-title">TradeMentor</h2></div>
              <button className="close-button" type="button" aria-label="Instellingen sluiten" onClick={() => setSettingsOpen(false)}>×</button>
            </div>
            <section className="plan-summary" aria-label="Huidig abonnement">
              <div><span className="kicker">HUIDIG PLAN</span><strong>Free</strong><small>Premium-betalingen zijn nog niet geactiveerd.</small></div>
              <button type="button" onClick={() => { setSettingsOpen(false); setPremiumOpen(true); }}>Bekijk Premium</button>
            </section>
            <section className="account-summary">
              <img src="/tradementor-logo.png?v=redgreen-1" alt="" />
              <div><span className="kicker">INGELOGD ALS</span><strong>{user?.displayName || "TradeMentor gebruiker"}</strong><small>{user?.email}</small></div>
              <button type="button" onClick={() => signOut()}>Uitloggen</button>
            </section>
            <ConnectionManager snapshots={snapshots} onChanged={() => refreshAll()} />
            <SettingToggle label="Profitgeluid" description="Speel een melding af bij een bevestigde winstgevende sluiting." checked={sound} onChange={setSound} />
            <SettingToggle label="Interface-animaties" description="Gebruik subtiele beweging en diepte in de trade floor." checked={motion} onChange={setMotion} />
            {adminAccount && <AdminMfaControl allowed={adminDeviceAllowed} configured={adminDeviceEnrolled} onAllowed={(allowed,configured)=>{setAdminDeviceAllowed(allowed);setAdminDeviceEnrolled(configured)}} />}
            <div className="drawer-note">
              <strong>Bewuste activering</strong>
              <p>De persoonlijke live-schakelaar werkt na preflight en dubbele bevestiging. Nieuwe orderknoppen worden pas zichtbaar zodra de betreffende strategie volledig naar web is overgezet.</p>
            </div>
            <a className="legal-link" href="/legal" target="_blank" rel="noreferrer">Privacy, voorwaarden en risicowaarschuwing</a>
          </aside>
        </div>
      )}

      {premiumOpen && (
        <div className="premium-layer" role="presentation" onMouseDown={() => setPremiumOpen(false)}>
          <section className="premium-dialog" role="dialog" aria-modal="true" aria-labelledby="premium-title" onMouseDown={(event) => event.stopPropagation()}>
            <div className="drawer-heading">
              <div><span className="kicker">ABONNEMENT</span><h2 id="premium-title">Kies wat bij je past</h2></div>
              <button className="close-button" type="button" aria-label="Premium sluiten" onClick={() => setPremiumOpen(false)}>×</button>
            </div>
            <p className="premium-intro">Dit is het veilige planvoorstel. Prijzen, voorwaarden en echte betaling worden pas geactiveerd nadat ze expliciet zijn goedgekeurd.</p>
            <div className="plan-grid">
              <PlanCard
                name="Free"
                price="€0"
                description="Kennismaken met je portefeuille zonder automatische uitvoering."
                features={["Persoonlijk account", "Basis portfolio-overzicht", "Paper-trading voorbereiden"]}
                action="Nu actief"
                active
              />
              <PlanCard
                name="Premium"
                price="Prijs volgt"
                description="Voor actieve TradeMentor-gebruikers die alle exchanges en strategie-inzichten willen gebruiken."
                features={["Hyperliquid en Aster", "Geavanceerd risico- en profitoverzicht", "Achtergrondmonitoring en automatisering", "Prioriteit bij nieuwe strategieën"]}
                action="Nog niet beschikbaar"
              />
            </div>
            <div className="billing-safety"><strong>Betaalveiligheid</strong><span>Abonnementstatus komt straks alleen van de beveiligde server. Geen betaalgegevens of geheime sleutels worden in de browser opgeslagen.</span></div>
          </section>
        </div>
      )}
    </main>
  );
}

function ExchangeView({ destination, refreshedAt, snapshot, cloudReady, onRefresh, onStrategy2Confirmed = () => {}, positionsOnly = false, selectedPositionId = "", onSelectPosition }: { destination: TradingExchange; refreshedAt: string; snapshot: ExchangeSnapshot; cloudReady: boolean; onRefresh: () => void; onStrategy2Confirmed?: (strategy2: Record<string, unknown>) => void; positionsOnly?: boolean; selectedPositionId?: string; onSelectPosition?: (selection: TradeSelection) => void }) {
  const [positionTab, setPositionTab] = useState<"active" | "closed">("active");
  const [positionFilter, setPositionFilter] = useState("largest");
  const [positionLayout, setPositionLayout] = useState<"cards" | "list">("list");
  const [filterOpen, setFilterOpen] = useState(false);
  const copy = exchangeCopy[destination];
  const isHyperliquid = destination === "hyperliquid";
  const view = exchangeView(destination, snapshot);
  const longPositions = view.positions.filter((position) => position.side.toLowerCase() === "long");
  const shortPositions = view.positions.filter((position) => position.side.toLowerCase() === "short");
  const longPnl = longPositions.reduce((total, position) => total + position.pnl, 0);
  const shortPnl = shortPositions.reduce((total, position) => total + position.pnl, 0);
  const netOpenPnl = longPnl + shortPnl;
  const displayedPositions = sortPositions(view.positions, positionFilter);
  const realizedEvents = Array.isArray(snapshot.data?.realizedEvents) ? snapshot.data.realizedEvents as Array<Record<string, unknown>> : [];
  const asterActionsEnabled = destination !== "aster" || asterActionsAreFresh(snapshot, cloudReady);
  const strategy2Snapshot = destination === "aster" && snapshot.data?.strategy2 && typeof snapshot.data.strategy2 === "object"
    ? snapshot.data.strategy2 as Record<string, unknown> : null;
  const asterExecutionConfirmed = destination !== "aster" || Boolean(
    asterActionsEnabled && (
      asterEvidenceIsFresh(snapshot.data?.snapshotAt) ||
      (view.tradingEnabled && asterEvidenceIsFresh(strategy2Snapshot?.lastTickAt))
    )
  );
  const snapshotStatus = destination !== "aster" ? refreshedAt : snapshot.loading
    ? "Vernieuwen…"
    : snapshot.error && snapshot.data
      ? "Tijdelijk geen nieuwe gegevens; laatst bekende gegevens worden getoond"
      : snapshot.updatedAt
        ? `Laatst bijgewerkt om ${new Date(snapshot.updatedAt).toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`
        : "Nog geen Aster-gegevens ontvangen";
  useEffect(() => {
    const saved = window.localStorage.getItem(`tradementor.positionLayout.${destination}`);
    if (saved === "cards" || saved === "list") setPositionLayout(saved);
  }, [destination]);
  useEffect(() => {
    if (!filterOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") setFilterOpen(false); };
    window.addEventListener("keydown", close);
    return () => { document.body.style.overflow = previous; window.removeEventListener("keydown", close); };
  }, [filterOpen]);
  const changeLayout = (layout: "cards" | "list") => {
    setPositionLayout(layout);
    window.localStorage.setItem(`tradementor.positionLayout.${destination}`, layout);
  };
  return (
    <>
      {!positionsOnly && <section className="hero-panel">
        {destination === "aster" ? <AsterBotStatus snapshot={snapshot.data} /> : <div className="hero-copy">
          <span className="kicker">{copy.eyebrow}</span>
          <h1>{copy.title}</h1>
          <p>{copy.note}</p>
          <div className="status-row">
            <span className={`status-chip ${view.tradingEnabled ? "" : "warning"}`}><i /> {view.tradingEnabled ? "Live handel aan" : "Live handel uit"}</span>
            <span className={`status-chip ${view.connected ? "" : "muted"}`}><i /> {view.statusText}</span>
            <button className="status-chip refresh-chip" type="button" onClick={onRefresh} disabled={snapshot.loading}><i /> {snapshotStatus}</button>
          </div>
        </div>}
        {destination === "aster" ? <div className="risk-orbits liquidation-only"><LiquidationRiskOrbit display={view.asterAccountDisplay} /></div> : <div><div className={`risk-orbit risk-${view.riskTone}`} aria-label={view.riskLabel}><div className="orbit-lines" /><div className="risk-core"><span>{view.riskLabel}</span><strong>{view.riskValue}</strong><small>{view.riskDetail}</small></div></div></div>}
      </section>}

      {!positionsOnly && destination === "aster" && <BotHealthCard />}

      {!positionsOnly && <section className="metric-strip" aria-label="Portefeuilleoverzicht">
        <Metric label="PORTFOLIOWAARDE" value={view.equity} detail={view.metricDetail} />
        <Metric label="AVAILABLE TO TRADE" value={view.available} detail="Direct van de exchange" />
        <Metric label="ACTIVE TRADE CAPITAL" value={view.activeTradeCapital} detail="Werkelijke margin in live posities" />
        <Metric label="ACTIEVE POSITIES" value={view.accountDataAvailable ? String(view.positions.length || view.activeCount) : "—"} detail={isHyperliquid ? "Hyperliquid exchange-truth" : "Actuele accountcontrole"} />
        {isHyperliquid && <Metric label="MAINTENANCE MARGIN" value={view.maintenanceMargin} detail="Perps maintenance margin" />}
        {destination === "aster" && <TodayRealizedMetric onChanged={onRefresh} available={snapshot.data?.historyAvailable === true} positions={view.positions} equity={view.equity} availableToTrade={view.available} openPnl={netOpenPnl} trades={realizedEvents.length ? realizedEvents.map((event) => ({ symbol: String(event.symbol ?? ""), side: "", size: 0, entry: 0, exit: 0, pnl: asNumber(event.realizedPnlUsd), openedAt: "", closedAt: String(event.closedAt ?? ""), strategy: "", dcaCount: 0 })) : view.closedTrades} />}
        {isHyperliquid && <Metric label="ACCOUNT LEVERAGE" value={view.accountLeverage} detail="Unified Account leverage" />}
      </section>}

      {!positionsOnly && <section className="direction-balance" aria-label="Long en short balans">
        <DirectionBalanceCell label="LONG" count={view.accountDataAvailable ? longPositions.length : null} value={view.accountDataAvailable ? longPnl : null} />
        <DirectionBalanceCell label="NETTO OPEN PNL" value={view.accountDataAvailable ? netOpenPnl : null} center />
        <DirectionBalanceCell label="SHORT" count={view.accountDataAvailable ? shortPositions.length : null} value={view.accountDataAvailable ? shortPnl : null} />
      </section>}
      {!positionsOnly && destination === "aster" && <AsterRecentTrades snapshot={snapshot} onRetry={onRefresh} />}
      {!positionsOnly && destination === "aster" && <fieldset className="aster-action-gate" disabled={!asterActionsEnabled}><AsterPerformancePanel snapshot={snapshot.data} onChanged={onRefresh} /></fieldset>}

      <section className="dashboard-grid">
        {positionsOnly && <article className="primary-card position-card">
          <div className="card-heading">
            <div><span className="kicker">POSITIEOVERZICHT</span><h2>{positionTab === "active" ? `${view.positions.length} actieve posities` : `${view.closedTrades.length} afgesloten trades`}</h2></div>
            <div className="position-tools"><button type="button" className={positionTab === "active" ? "active" : ""} onClick={() => setPositionTab("active")}>Actief</button><button type="button" className={positionTab === "closed" ? "active" : ""} onClick={() => setPositionTab("closed")}>Afgesloten</button></div>
          </div>
          <div className="position-view-toolbar">
            <div className="position-layout-choice" role="group" aria-label="Positieweergave kiezen"><button type="button" className={positionLayout === "list" ? "active" : ""} aria-pressed={positionLayout === "list"} title="Compact overzicht waarmee je meer posities tegelijk ziet" onClick={() => changeLayout("list")}><i>☷</i><span>Lijst</span></button><button type="button" className={positionLayout === "cards" ? "active" : ""} aria-pressed={positionLayout === "cards"} title="Ruime kaarten met visuele resultaatmeter" onClick={() => changeLayout("cards")}><i>▦</i><span>Kaarten</span></button></div>
            {positionTab === "active" && <button className="position-filter-trigger" type="button" aria-haspopup="dialog" aria-expanded={filterOpen} onClick={() => setFilterOpen(true)}><span>{positionFilterLabel(positionFilter)}</span><i>⌄</i></button>}
          </div>
          {positionTab === "active" && displayedPositions.length ? <div className={positionLayout === "list" ? "compact-position-list" : "position-list"}>{displayedPositions.map((position) => { const id=`${destination}:active:${position.symbol}:${position.side}`; return positionLayout === "list" ? <CompactPositionRow key={id} position={position} exchange={destination} onChanged={onRefresh} selected={selectedPositionId===id} onSelect={onSelectPosition} /> : <PositionRow key={id} position={position} exchange={destination} onChanged={onRefresh} selected={selectedPositionId===id} onSelect={onSelectPosition} />; })}</div> : positionTab === "closed" && view.closedTrades.length ? <div className={positionLayout === "list" ? "compact-position-list" : "position-list"}>{view.closedTrades.map((trade, index) => { const id=`${destination}:closed:${trade.symbol}:${trade.closedAt}:${index}`; return positionLayout === "list" ? <CompactClosedTradeRow key={id} trade={trade} exchange={destination} selected={selectedPositionId===id} positionId={id} onSelect={onSelectPosition} /> : <ClosedTradeRow key={id} trade={trade} exchange={destination} selected={selectedPositionId===id} positionId={id} onSelect={onSelectPosition} />; })}</div> : <div className="empty-stage">
            <div className="radar"><i /><i /><i /></div>
            <h3>{snapshot.error ? "Exchangecontrole niet voltooid" : snapshot.loading ? "Posities worden opgehaald" : positionTab === "closed" ? "Nog geen bevestigde sluitingen" : "Geen positie voor dit filter"}</h3>
            <p>{snapshot.error || "TradeMentor toont alleen gegevens die centraal of door de exchange zijn bevestigd."}</p>
          </div>}
          {filterOpen && <PositionFilterSheet value={positionFilter} onChange={setPositionFilter} onClose={() => setFilterOpen(false)} />}
        </article>}

        {!positionsOnly && <aside className="side-stack">
          {destination === "hyperliquid" ? <HyperliquidStrategyControl cloudReady={cloudReady} onChanged={onRefresh} /> : <fieldset className="aster-action-gate" disabled={!asterActionsEnabled}>{!asterActionsEnabled && <p className="aster-stale-lock">Acties zijn tijdelijk vergrendeld totdat de server een verse Aster-status heeft bevestigd.</p>}<AsterStrategy2Maker snapshot={snapshot.data} serverConfirmed={snapshot.serverConfirmed} onConfirmed={onStrategy2Confirmed} onChanged={onRefresh} /></fieldset>}
          {destination !== "aster" && <ExchangeLiveControl exchange={destination} cloudReady={cloudReady} snapshot={snapshot.data} onChanged={onRefresh} />}
          <article className={`safety-card ${view.tradingEnabled && asterExecutionConfirmed ? "live" : ""}`}>
            <div className="shield-mark">TM</div>
            <div><span className="kicker">ORDER COORDINATOR</span><h3>{!asterExecutionConfirmed ? "Aster-uitvoering niet bevestigd" : view.tradingEnabled ? "Persoonlijke livepoort actief" : "Nieuwe exposure geblokkeerd"}</h3><p>{!asterExecutionConfirmed ? "Nieuwe instappen zijn geblokkeerd. Positiebeheer staat ingeschakeld, maar actuele uitvoering kon door Aster niet worden bevestigd." : view.tradingEnabled ? "De actieve strategie beslist pas na iedere server-side risicocontrole." : "Nieuwe instappen blijven uit; positiebeheer wordt alleen als beschikbaar getoond met actuele serverbevestiging."}</p></div>
          </article>
        </aside>}
      </section>
    </>
  );
}

function PositionsPage({ snapshots, refreshedAt, cloudReady, onRefresh }: { snapshots: ExchangeSnapshots; refreshedAt: string; cloudReady: boolean; onRefresh: (exchange: TradingExchange) => void }) {
  const [mode, setMode] = useState<"live"|"backtest">("live");
  const [exchange, setExchange] = useState<TradingExchange>("aster");
  const [chartScope, setChartScope] = useState<ChartScope>("aster");
  const [selection, setSelection] = useState<TradeSelection>({ id: "default:aster:BTC", symbol: "BTCUSDT", exchange: "aster", side: "" });
  useEffect(() => {
    const saved = window.localStorage.getItem("tradementor.positions.exchange");
    if (saved === "aster" || saved === "hyperliquid") setExchange(saved);
  }, []);
  const changeExchange = (value: TradingExchange) => {
    setExchange(value);
    setChartScope(value);
    window.localStorage.setItem("tradementor.positions.exchange", value);
    setSelection({ id: `default:${value}:BTC`, symbol: "BTCUSDT", exchange: value, side: "" });
  };
  const selectPortfolio = () => {
    setChartScope("portfolio");
    setSelection({ id: "portfolio:total", symbol: "PORTFOLIO", exchange: "portfolio", side: "" });
  };
  const selectPosition = (value: TradeSelection) => {
    const selectedExchange = value.exchange === "hyperliquid" ? "hyperliquid" : "aster";
    setExchange(selectedExchange);
    setChartScope(selectedExchange);
    setSelection(value);
  };
  return <div className="positions-page">
    <header className="positions-page-heading"><div><span className="kicker">PROFESSIONELE TRADE-ANALYSE</span><h1>Positions</h1><p>Selecteer een marktpositie of analyseer je eigen portfoliowaarde met dezelfde professionele indicatoren.</p></div><div className="positions-exchange-switch" role="group" aria-label="Grafiek kiezen"><button className={chartScope === "hyperliquid" ? "active" : ""} onClick={() => changeExchange("hyperliquid")}>Hyperliquid</button><button className={chartScope === "portfolio" ? "active portfolio" : "portfolio"} onClick={selectPortfolio}>Portfolio</button><button className={chartScope === "aster" ? "active" : ""} onClick={() => changeExchange("aster")}>Aster</button></div></header>
    <div className="positions-mode-switch" role="group" aria-label="Positions modus"><button className={mode==="live"?"active":""} onClick={()=>setMode("live")}>Live trading</button><button className={mode==="backtest"?"active":""} onClick={()=>setMode("backtest")}>Backtest A/B</button></div>
    {mode==="live" ? (
      <><SafeTradingChart selection={selection} /><ExchangeView destination={exchange} refreshedAt={refreshedAt} snapshot={snapshots[exchange]} cloudReady={cloudReady} onRefresh={() => onRefresh(exchange)} positionsOnly selectedPositionId={selection.id} onSelectPosition={selectPosition} /></>
    ) : <BacktestComparison snapshot={snapshots.aster} />}
  </div>;
}

function DirectionBalanceCell({ label, count, value, center = false }: { label: string; count?: number | null; value: number | null; center?: boolean }) {
  const tone = value === null ? "unknown" : value > 0 ? "positive" : value < 0 ? "negative" : "neutral";
  return <div className={`direction-balance-cell ${center ? "center" : ""} ${tone}`}><span>{count === undefined ? label : `${count === null ? "—" : count} ${label}`}</span><strong>{value === null ? "—" : formatSignedUsd(value)}</strong></div>;
}

function WalletView({ refreshedAt, snapshots, interfaceMode, preferenceReady, preferenceMessage, onInterfaceModeChange, showHyperliquidTab = true, onShowHyperliquidTabChange = () => {}, appSkin = "original", onAppSkinChange = () => {} }: { refreshedAt: string; snapshots: ExchangeSnapshots; interfaceMode: InterfaceMode; preferenceReady: boolean; preferenceMessage: string; onInterfaceModeChange: (mode: InterfaceMode) => void; showHyperliquidTab?: boolean; onShowHyperliquidTabChange?: (visible: boolean) => void; appSkin?: AppSkin; onAppSkinChange?: (skin: AppSkin) => void }) {
  const exchanges = (["hyperliquid", "aster"] as const).map((id) => ({ id, name: id === "hyperliquid" ? "HYPERLIQUID" : "ASTER", view: exchangeView(id, snapshots[id]), snapshot: snapshots[id], tone: id === "hyperliquid" ? "blue" : "purple" }));
  const connected = exchanges.filter((item) => item.view.connected && item.view.equityNumber !== null);
  const total = connected.reduce((sum, item) => sum + (item.view.equityNumber ?? 0), 0);
  return (
    <>
      <section className="wallet-hero">
        <div><span className="kicker">CENTRALE WALLET</span><h1>Alle exchanges. Eén waarheid.</h1><p>TradeMentor telt open PnL nooit dubbel en toont ontbrekende exchange-data niet alsof het nul is.</p></div>
        <span className="status-chip muted"><i /> {refreshedAt}</span>
      </section>
      <section className="wallet-total">
        <div><span>TOTALE PORTFOLIOWAARDE</span><strong>{connected.length ? formatUsd(total) : "—"}</strong><small>{connected.length === 2 ? "Hyperliquid en Aster zijn actueel." : connected.length ? `Gedeeltelijk totaal van ${connected.length} gekoppelde exchange.` : "Nog geen actuele exchange-snapshot beschikbaar."}</small></div>
        <div className="wallet-ring"><span>{connected.length}</span><small>VAN 2 VERBONDEN</small></div>
      </section>
      <section className="exchange-grid">
        {exchanges.map((exchange) => (
          <article className={`exchange-card ${exchange.tone}`} key={exchange.name}>
            <div className="exchange-card-head"><span className="exchange-glyph">{exchange.name.slice(0, 2)}</span><span className={`connection-dot ${exchange.view.connected ? "connected" : ""}`} /></div>
            <h2>{exchange.name}</h2><p>{exchange.snapshot.error || exchange.view.statusText}</p>
            <dl><div><dt>Equity</dt><dd>{exchange.view.equity}</dd></div><div><dt>Available</dt><dd>{exchange.view.available}</dd></div><div><dt>Open PnL</dt><dd>{exchange.view.openPnl}</dd></div></dl>
          </article>
        ))}
      </section>
      <SupportCenter />
      <section className="wallet-navigation-settings" aria-labelledby="wallet-navigation-title">
        <div><span className="kicker">NAVIGATIE</span><h2 id="wallet-navigation-title">Zichtbare tabbladen</h2><p>Dit verandert alleen de navigatie. Je Hyperliquid-koppeling, gegevens, posities en strategieën blijven ongewijzigd.</p></div>
        <SettingToggle label="Hyperliquid-tab tonen" description="Schakel dit uit om Hyperliquid uit de hoofdnav te verbergen. Je kunt het hier altijd weer aanzetten." checked={showHyperliquidTab} onChange={onShowHyperliquidTabChange} />
      </section>
      <AppSkinSelector skin={appSkin} onChange={onAppSkinChange} />
      <InterfaceModeSelector mode={interfaceMode} ready={preferenceReady} message={preferenceMessage} onChange={onInterfaceModeChange} />
    </>
  );
}

function InterfaceModeSelector({ mode, ready, message, onChange }: { mode: InterfaceMode; ready: boolean; message: string; onChange: (mode: InterfaceMode) => void }) {
  return <section className="interface-mode-card" aria-labelledby="interface-mode-title">
    <div className="interface-mode-heading"><div><span className="kicker">INTERFACEWEERGAVE</span><h2 id="interface-mode-title">Kies jouw TradeMentor-ervaring</h2></div><span className="interface-safe-badge">Alleen weergave</span></div>
    <p>Wisselen verandert geen strategie, scanner, bot, order of actieve positie. Je kunt altijd veilig terug.</p>
    <div className="interface-mode-options">
      <button type="button" className={mode === "legacy" ? "active" : ""} aria-pressed={mode === "legacy"} disabled={!ready} onClick={() => onChange("legacy")}><span>Vertrouwde weergave</span><small>De huidige stabiele TradeMentor-interface.</small></button>
      <button type="button" className={mode === "premium" ? "active" : ""} aria-pressed={mode === "premium"} disabled={!ready} onClick={() => onChange("premium")}><span>Premium-weergave</span><small>De nieuwe ervaring met dezelfde gegevens en verbindingen.</small></button>
    </div>
    <small className="interface-mode-message">{!ready ? "Persoonlijke voorkeur wordt geladen..." : message || "Deze keuze wordt persoonlijk in TradeMentor Cloud opgeslagen."}</small>
  </section>;
}

const premiumNavigation: Array<{ id: PremiumSection; label: string; glyph: string }> = [
  { id: "dashboard", label: "Dashboard", glyph: "⌂" },
  { id: "screener", label: "Market Screener", glyph: "⌕" },
  { id: "bots", label: "Bot Creator", glyph: "◆" },
  { id: "risk", label: "Risico", glyph: "R" },
  { id: "portfolio", label: "Portfolio", glyph: "◫" },
  { id: "exchanges", label: "Exchanges", glyph: "⇄" },
  { id: "wallet", label: "Wallet", glyph: "W" },
  { id: "academy", label: "Academy", glyph: "A" },
  { id: "settings", label: "Instellingen", glyph: "⚙" },
];

function PremiumExperience({ cloudReady, initials, snapshots, refreshedAt, onRefresh, onStrategy2Confirmed, onRefreshAll, onUseLegacy, preferenceReady, preferenceMessage, appSkin, onAppSkinChange }: { cloudReady: boolean; initials: string; snapshots: ExchangeSnapshots; refreshedAt: string; onRefresh: (exchange: TradingExchange) => void; onStrategy2Confirmed: (strategy2: Record<string, unknown>) => void; onRefreshAll: () => void; onUseLegacy: () => void; preferenceReady: boolean; preferenceMessage: string; appSkin: AppSkin; onAppSkinChange: (skin: AppSkin) => void }) {
  const [section, setSection] = useState<PremiumSection>("dashboard");
  const [portfolioExchange, setPortfolioExchange] = useState<TradingExchange>("hyperliquid");
  const [scanner, setScanner] = useState<Record<string, unknown> | null>(null);
  const [scannerError, setScannerError] = useState("");

  useEffect(() => {
    if (!cloudReady || section !== "screener") return;
    authenticatedRequest("/api/exchanges/hyperliquid/scanner/status").then(setScanner).catch((reason) => setScannerError(reason instanceof Error ? reason.message : "De screenerstatus is niet beschikbaar."));
  }, [cloudReady, section]);

  const hyperliquid = exchangeView("hyperliquid", snapshots.hyperliquid);
  const aster = exchangeView("aster", snapshots.aster);
  const connectedViews = [hyperliquid, aster].filter((view) => view.connected && view.equityNumber !== null);
  const totalEquity = connectedViews.length ? connectedViews.reduce((sum, view) => sum + (view.equityNumber ?? 0), 0) : null;
  const allPositions = [...hyperliquid.positions, ...aster.positions];
  const totalPnl = connectedViews.length ? allPositions.reduce((sum, position) => sum + position.pnl, 0) : null;
  const runningBots = hyperliquid.connected && aster.connected ? Number(Boolean(hyperliquid.tradingEnabled)) + Number(Boolean(aster.tradingEnabled)) : null;

  return <main className="premium-app-shell">
    <aside className="premium-sidebar" aria-label="Premium hoofdnavigatie">
      <div className="premium-brand"><img src="/tradementor-logo.png?v=redgreen-1" alt="TradeMentor rood-groen logo" /><strong>Trade<span>Mentor</span></strong></div>
      <nav>{premiumNavigation.map((item) => <button type="button" key={item.id} className={section === item.id ? "active" : ""} aria-pressed={section === item.id} onClick={() => setSection(item.id)}><i>{item.glyph}</i><span>{item.label}</span>{(item.id === "academy" || item.id === "settings") && <small>Binnenkort</small>}</button>)}</nav>
      <div className="premium-account"><span>{initials}</span><div><strong>Persoonlijk account</strong><small>{cloudReady ? "Cloud verbonden" : "Cloud controleren"}</small></div></div>
    </aside>
    <section className="premium-workspace">
      <header className="premium-topbar"><div><span className="premium-breadcrumb">TRADEMENTOR · PREMIUM</span><strong>{premiumNavigation.find((item) => item.id === section)?.label}</strong></div><div><span className={`premium-cloud ${cloudReady ? "connected" : ""}`}><i />{cloudReady ? "CLOUDSESSIE" : "CONTROLEREN"}</span><button type="button" onClick={onRefreshAll}>Vernieuwen</button><button className="premium-interface-switch" type="button" onClick={onUseLegacy} aria-label="Terug naar de vertrouwde webapp"><span className="desktop-label">Vertrouwde weergave</span><span className="mobile-label">Terug</span></button><span className="premium-avatar">{initials}</span></div></header>
      <div className="premium-page">
        {section === "dashboard" && <PremiumDashboard totalEquity={totalEquity} totalPnl={totalPnl} positions={allPositions} runningBots={runningBots} hyperliquid={hyperliquid} aster={aster} refreshedAt={refreshedAt} />}
        {section === "screener" && <PremiumScreener scanner={scanner} error={scannerError} />}
        {section === "bots" && <PremiumBotCreator cloudReady={cloudReady} snapshots={snapshots} onRefresh={onRefresh} onStrategy2Confirmed={onStrategy2Confirmed} />}
        {section === "risk" && <RiskTimeline snapshots={snapshots} />}
        {section === "portfolio" && <><PremiumPageHeading eyebrow="ECHTE EXCHANGE-STATE" title="Portfolio & posities" detail="Dezelfde positie-, filter- en sluitfuncties als in de vertrouwde weergave." /><div className="premium-segmented"><button className={portfolioExchange === "hyperliquid" ? "active" : ""} type="button" onClick={() => setPortfolioExchange("hyperliquid")}>Hyperliquid</button><button className={portfolioExchange === "aster" ? "active" : ""} type="button" onClick={() => setPortfolioExchange("aster")}>Aster</button></div><ExchangeView destination={portfolioExchange} refreshedAt={refreshedAt} snapshot={snapshots[portfolioExchange]} cloudReady={cloudReady} onRefresh={() => onRefresh(portfolioExchange)} onStrategy2Confirmed={onStrategy2Confirmed} /></>}
        {section === "exchanges" && <PremiumExchanges snapshots={snapshots} onRefresh={(exchange) => onRefresh(exchange as TradingExchange)} />}
        {section === "wallet" && <><PremiumPageHeading eyebrow="CENTRALE WALLET" title="Wallet & interface" detail="Alle exchangegegevens en jouw persoonlijke interfacekeuze op één plek." /><WalletView refreshedAt={refreshedAt} snapshots={snapshots} interfaceMode="premium" preferenceReady={preferenceReady} preferenceMessage={preferenceMessage} onInterfaceModeChange={(mode) => { if (mode === "legacy") onUseLegacy(); }} appSkin={appSkin} onAppSkinChange={onAppSkinChange} /></>}
        {(section === "academy" || section === "settings") && <PremiumUnavailable title={section === "academy" ? "Academy" : "Uitgebreide instellingen"} />}
      </div>
    </section>
    <nav className="premium-bottom-nav" aria-label="Premium mobiele navigatie">
      {premiumNavigation.filter((item) => ["dashboard", "screener", "bots", "risk"].includes(item.id)).map((item) => <button type="button" key={item.id} className={section === item.id ? "active" : ""} onClick={() => setSection(item.id)}><i>{item.glyph}</i><span>{item.label.replace("Market ", "")}</span></button>)}
      <button type="button" onClick={onUseLegacy} aria-label="Terug naar de oude vertrouwde weergave"><i>↩</i><span>Oude weergave</span></button>
    </nav>
  </main>;
}

function PremiumPageHeading({ eyebrow, title, detail }: { eyebrow: string; title: string; detail: string }) {
  return <header className="premium-page-heading"><span>{eyebrow}</span><h1>{title}</h1><p>{detail}</p></header>;
}

function PremiumDashboard({ totalEquity, totalPnl, positions, runningBots, hyperliquid, aster, refreshedAt }: { totalEquity: number | null; totalPnl: number | null; positions: PositionView[]; runningBots: number | null; hyperliquid: ReturnType<typeof exchangeView>; aster: ReturnType<typeof exchangeView>; refreshedAt: string }) {
  const longs = positions.filter((position) => position.side.toLowerCase() === "long");
  const shorts = positions.filter((position) => position.side.toLowerCase() === "short");
  const accountDataAvailable = hyperliquid.accountDataAvailable || aster.accountDataAvailable;
  return <>
    <PremiumPageHeading eyebrow="PORTFOLIO COMMAND CENTER" title="Goed overzicht. Rustige beslissingen." detail="Actuele waarden komen rechtstreeks uit jouw gekoppelde exchanges." />
    <section className="command-hero"><div className="command-value"><span>Portfolio Value</span><strong>{totalEquity === null ? "Geen betrouwbare waarde" : formatUsd(totalEquity)}</strong><small className={totalPnl === null ? "" : totalPnl >= 0 ? "profit" : "loss"}>Open resultaat {totalPnl === null ? "—" : formatSignedUsd(totalPnl)}</small></div><div className="period-tabs"><button className="active" type="button">Actueel</button><button type="button" disabled>Vandaag</button><button type="button" disabled>Deze week</button><button type="button" disabled>Deze maand</button></div><div className="equity-unavailable"><i /><div><strong>Performancegrafiek</strong><span>Binnenkort beschikbaar zodra betrouwbare historische equity-snapshots zijn opgeslagen.</span></div></div></section>
    <section className="premium-metric-grid"><PremiumStat label="ACTIEVE POSITIES" value={accountDataAvailable ? String(positions.length) : "—"} detail={accountDataAvailable ? `${longs.length} Long · ${shorts.length} Short` : "Geen betrouwbare account-snapshot"} /><PremiumStat label="BOTS ACTIEF" value={runningBots === null ? "—" : String(runningBots)} detail={runningBots === null ? "Niet voor beide exchanges bevestigd" : runningBots ? "Live status uit exchange-controls" : "Geen actieve uitvoering"} /><PremiumStat label="OPEN PNL" value={totalPnl === null ? "—" : formatSignedUsd(totalPnl)} detail={totalPnl === null ? "Geen betrouwbare account-snapshot" : "Niet dubbel opgeteld"} tone={totalPnl === null ? "" : totalPnl >= 0 ? "profit" : "loss"} /><PremiumStat label="LAATSTE SYNC" value={refreshedAt} detail="Persoonlijke cloudcontrole" /></section>
    <section className="premium-dashboard-lower"><article className="health-panel"><div><span>MARGIN HEALTH</span><strong>{hyperliquid.riskValue}</strong><small>Hyperliquid</small></div><div><span>ASTER RISK</span><strong>{aster.riskValue}</strong><small>{aster.riskDetail}</small></div></article><article className="exchange-status-panel"><div className="panel-title"><h2>Connected Exchanges</h2><span>{[hyperliquid, aster].filter((view) => view.connected).length}/2 verbonden</span></div><PremiumExchangeLine name="Hyperliquid" view={hyperliquid} /><PremiumExchangeLine name="Aster" view={aster} /></article><article className="bot-status-panel"><div className="panel-title"><h2>Bots actief</h2><span>Exchange-truth</span></div><PremiumBotLine name="DCA Pulse" active={hyperliquid.tradingEnabled} known={hyperliquid.connected} exchange="Hyperliquid" /><PremiumBotLine name="Dual Profit Harvest" active={aster.tradingEnabled} known={aster.connected} exchange="Aster" /></article></section>
  </>;
}

function PremiumStat({ label, value, detail, tone = "" }: { label: string; value: string; detail: string; tone?: string }) { return <article className={`premium-stat ${tone}`}><span>{label}</span><strong>{value}</strong><small>{detail}</small></article>; }
function PremiumExchangeLine({ name, view }: { name: string; view: ReturnType<typeof exchangeView> }) { return <div className="premium-list-line"><span className="exchange-mini">{name.slice(0, 2).toUpperCase()}</span><div><strong>{name}</strong><small>{view.connected ? view.equity : view.statusText}</small></div><em className={view.connected ? "online" : ""}>{view.connected ? "Verbonden" : "Controle nodig"}</em></div>; }
function PremiumBotLine({ name, active, known, exchange }: { name: string; active: boolean; known: boolean; exchange: string }) { return <div className="premium-list-line"><span className="bot-mini">◆</span><div><strong>{name}</strong><small>{exchange}</small></div><em className={known && active ? "online" : ""}>{!known ? "Onbekend" : active ? "Actief" : "Gestopt"}</em></div>; }

function PremiumScreener({ scanner, error }: { scanner: Record<string, unknown> | null; error: string }) {
  const settings = asRecord(scanner?.scannerSettings);
  return <>
    <PremiumPageHeading eyebrow="MARKET SCREENER" title="Vind kansen zonder ruis" detail="De screener toont uitsluitend wat de bestaande Hyperliquid-scanner werkelijk heeft bevestigd." />
    <section className="screener-toolbar"><div className="premium-search">Zoek markt... <span>⌕</span></div><div className="premium-select">Top {String(settings.top_universe_size ?? 50)} <span>⌄</span></div><div className="premium-select">Hyperliquid <span>⌄</span></div><button type="button" disabled>Filters</button></section>
    <section className="screener-summary"><PremiumStat label="GESCANDE MARKTEN" value={scanner ? String(scanner.scannerScannedMarkets ?? 0) : "—"} detail="Laatste cloudscan" /><PremiumStat label="KANDIDATEN" value={scanner ? String(scanner.scannerCandidateCount ?? 0) : "—"} detail="Door eerste selectie" /><PremiumStat label="AFGEWEZEN" value={scanner ? String(scanner.scannerRejectedCount ?? 0) : "—"} detail="Veiligheidscontrole" /><PremiumStat label="STATUS" value={scanner?.scannerEnabled ? "Running" : "Paused"} detail={String(scanner?.scannerReason ?? (error || "Status wordt geladen"))} /></section>
    <article className="screener-table"><header><span>#</span><span>Markt</span><span>Momentum</span><span>24H</span><span>Volatiliteit</span><span>Risico</span><span>Setup</span></header><div className="screener-empty"><span className="maintenance-pill">ONVOLDOENDE GEGEVENS</span><h2>Resultatenlijst wordt nog niet door de bestaande API geleverd</h2><p>Scan-aantallen en veiligheidsstatus zijn beschikbaar. Pair-ranking, momentum en uitleg worden pas getoond nadat de cloudscanner deze velden betrouwbaar retourneert.</p></div></article>
  </>;
}

function PremiumBotCreator({ cloudReady, snapshots, onRefresh, onStrategy2Confirmed }: { cloudReady: boolean; snapshots: ExchangeSnapshots; onRefresh: (exchange: TradingExchange) => void; onStrategy2Confirmed: (strategy2: Record<string, unknown>) => void }) {
  const [creatorExchange, setCreatorExchange] = useState<TradingExchange>("aster");
  const asterActionsEnabled = asterActionsAreFresh(snapshots.aster, cloudReady);
  return <>
    <PremiumPageHeading eyebrow="BOT CREATOR" title="Een krachtige bot, stap voor stap" detail="Bestaande strategie-instellingen blijven volledig beschikbaar; ingewikkelde keuzes krijgen uitleg op het moment dat je ze nodig hebt." />
    <div className="creator-progress"><span>1</span><i className="active" /><span>2</span><i /><span>3</span><i /><span>4</span><i /><span>5</span><small>Exchange en strategie kiezen</small></div>
    <section className="creator-layout"><article className="creator-question"><span className="creator-step">STAP 1 VAN 5</span><h2>Welke bot wil je instellen?</h2><p>Kies eerst de exchange. Daarna gebruikt TradeMentor exact de bestaande veilige Strategy Maker.</p><div className="creator-choices"><button type="button" className={creatorExchange === "aster" ? "active" : ""} onClick={() => setCreatorExchange("aster")}><strong>Aster</strong><small>Dual Profit Harvest & Strategy Maker</small></button><button type="button" className={creatorExchange === "hyperliquid" ? "active" : ""} onClick={() => setCreatorExchange("hyperliquid")}><strong>Hyperliquid</strong><small>DCA Pulse multipair scanner</small></button></div><div className="creator-help"><strong>Waarom deze keuze?</strong><span>Iedere exchange gebruikt zijn eigen bestaande instellingen en veiligheidscontroles. Er wordt geen nieuwe trading-engine gemaakt.</span></div></article><aside className="creator-live-summary"><span>JOUW STRATEGIE</span><h3>{creatorExchange === "aster" ? "Aster Strategy Maker" : "DCA Pulse"}</h3><dl><div><dt>Exchange</dt><dd>{creatorExchange === "aster" ? "Aster" : "Hyperliquid"}</dd></div><div><dt>Data</dt><dd>Live gekoppeld</dd></div><div><dt>Uitvoering</dt><dd>Huidige veilige flow</dd></div><div><dt>Instellingen</dt><dd>Volledig behouden</dd></div></dl></aside></section>
    <section className="creator-existing-engine">{creatorExchange === "aster" ? <fieldset className="aster-action-gate" disabled={!asterActionsEnabled}>{!asterActionsEnabled && <p className="aster-stale-lock">Acties zijn tijdelijk vergrendeld totdat de server een verse Aster-status heeft bevestigd.</p>}<AsterStrategy2Maker snapshot={snapshots.aster.data} serverConfirmed={snapshots.aster.serverConfirmed} onConfirmed={onStrategy2Confirmed} onChanged={() => onRefresh("aster")} /></fieldset> : <HyperliquidStrategyControl cloudReady={cloudReady} onChanged={() => onRefresh("hyperliquid")} />}</section>
  </>;
}

function PremiumExchanges({ snapshots, onRefresh }: { snapshots: ExchangeSnapshots; onRefresh: (exchange: Exclude<Destination, "wallet">) => void }) { return <><PremiumPageHeading eyebrow="EXCHANGES" title="Eén interface. Twee bronnen van waarheid." detail="Verbindingen en accountstatus komen uit dezelfde bestaande koppelingen." /><section className="premium-exchange-grid">{(["hyperliquid", "aster"] as const).map((id) => { const view = exchangeView(id, snapshots[id]); return <article key={id}><div className="premium-exchange-head"><span>{id.slice(0, 2).toUpperCase()}</span><em className={view.connected ? "online" : ""}>{view.statusText}</em></div><h2>{id === "hyperliquid" ? "Hyperliquid" : "Aster"}</h2><dl><div><dt>Equity</dt><dd>{view.equity}</dd></div><div><dt>Available</dt><dd>{view.available}</dd></div><div><dt>Open PnL</dt><dd>{view.openPnl}</dd></div><div><dt>Posities</dt><dd>{view.accountDataAvailable ? view.positions.length : "—"}</dd></div></dl><button type="button" onClick={() => onRefresh(id)}>Exchange vernieuwen</button></article>; })}</section></>; }

function PremiumUnavailable({ title }: { title: string }) { return <><PremiumPageHeading eyebrow="BINNENKORT BESCHIKBAAR" title={title} detail="Dit onderdeel zat nog niet als werkende functie in de huidige webapp." /><section className="premium-unavailable"><span>Binnenkort beschikbaar</span><h2>Geen nepknoppen of verzonnen gegevens</h2><p>De plaats in de navigatie is alvast zichtbaar. De functie wordt pas interactief wanneer de echte databron en veilige gebruikersflow beschikbaar zijn.</p></section></>; }

type StrategyTpView = { netProfitUsd: number | null; takeProfitTargetUsd: number | null; takeProfitPercent: number | null; progressPercent: number | null; status: "TP bereikt" | "TP nog niet bereikt" | "Niet betrouwbaar te bepalen"; evaluatedAt: string | null; blockReason: string; paidFeesUsd: number | null; fundingUsd: number | null; estimatedCloseFeeUsd: number | null; ownershipProven: boolean; decision: string; phase: string; protection: { role: string | null; active: boolean }; trailing: { enabled: boolean; active: boolean; peakReturnPercent: number | null }; scheduler: { status: string; lastTickAt: unknown; ageSeconds: number | null; warning: string } };
type PositionView = { symbol: string; side: string; size: number; entry: number; mark: number; liquidationPrice: number; pnl: number; leverage: number; dcaCount: number; lastOrderAt: number; openedAt: number; strategy: string; strategy2Tp: StrategyTpView | null };
type ClosedTradeView = { symbol: string; side: string; size: number; entry: number; exit: number; pnl: number; openedAt: string; closedAt: string; strategy: string; dcaCount: number };

const positionFilterOptions = [
  ["latest", "Laatst aangekocht"], ["largest", "Grootste positie"], ["smallest", "Kleinste positie"], ["dca", "Vaakst bijgekocht"],
  ["profit", "Hoogste profit"], ["loss", "Grootste verlies"], ["leverage", "Hoogste leverage"],
  ["alphabetical", "Pair A–Z"], ["long", "Alleen Long"], ["short", "Alleen Short"], ["top10", "Top 10 grootste"],
] as const;

function positionFilterLabel(value: string) { return positionFilterOptions.find(([id]) => id === value)?.[1] ?? "Sorteren en filteren"; }

function PositionFilterSheet({ value, onChange, onClose }: { value: string; onChange: (value: string) => void; onClose: () => void }) {
  const [draft, setDraft] = useState(value);
  return <div className="position-filter-layer" role="presentation" onMouseDown={onClose}>
    <section className="position-filter-sheet" role="dialog" aria-modal="true" aria-labelledby="position-filter-title" onMouseDown={(event) => event.stopPropagation()}>
      <header><div><span>SORTEER POSITIES</span><h3 id="position-filter-title">Sorteren en filteren</h3></div><button type="button" aria-label="Menu sluiten" onClick={onClose}>×</button></header>
      <div className="filter-sheet-options" role="radiogroup" aria-label="Kies sortering of filter">{positionFilterOptions.map(([id, label]) => <button type="button" role="radio" aria-checked={draft === id} className={draft === id ? "selected" : ""} key={id} onClick={() => setDraft(id)}><i aria-hidden="true"/><span>{label}</span>{draft === id && <b>Gekozen</b>}</button>)}</div>
      <footer><button type="button" className="filter-cancel" onClick={onClose}>Annuleren</button><button type="button" className="filter-apply" onClick={() => { onChange(draft); onClose(); }}>Toepassen</button></footer>
    </section>
  </div>;
}

function AppSkinSelector({ skin, onChange }: { skin: AppSkin; onChange: (skin: AppSkin) => void }) {
  return <section className="app-skin-card" aria-labelledby="app-skin-title">
    <div className="interface-mode-heading"><div><span className="kicker">APPEARANCE · APP SKIN</span><h2 id="app-skin-title">Kies jouw uitstraling</h2></div><span className="interface-safe-badge">Alleen visueel</span></div>
    <p>De skin verandert uitsluitend kleuren, achtergronden en afwerking. Posities, bots, berekeningen en exchangegegevens blijven exact hetzelfde.</p>
    <div className="app-skin-options">
      <button type="button" className={skin === "original" ? "active" : ""} aria-pressed={skin === "original"} onClick={() => onChange("original")}><span className="skin-preview original" /><strong>TradeMentor Original</strong><small>De vertrouwde blauw-donkere stijl.</small></button>
      <button type="button" className={skin === "suriname-heritage" ? "active" : ""} aria-pressed={skin === "suriname-heritage"} onClick={() => onChange("suriname-heritage")}><span className="skin-preview heritage" /><strong>Suriname Heritage</strong><small>Diep groen, warm goud en tropische diepte.</small></button>
    </div>
    <small className="interface-mode-message">De keuze wordt direct toegepast en op dit apparaat onthouden.</small>
  </section>;
}

function CompactPositionRow({ position, exchange, onChanged, selected = false, onSelect }: { position: PositionView; exchange: TradingExchange; onChanged: () => void; selected?: boolean; onSelect?: (selection: TradeSelection) => void }) {
  const positive = position.pnl >= 0;
  const resultPercent = positionDisplayReturnPercent(position.pnl, position.size);
  const id = `${exchange}:active:${position.symbol}:${position.side}`;
  return <article className={`compact-position-row ${positive ? "positive" : "negative"} ${selected ? "selected-position" : ""}`} onClick={(event) => { if ((event.target as HTMLElement).closest("button")) return; onSelect?.({ id, symbol: position.symbol, exchange, side: position.side, entry: position.entry, mark: position.mark, dcaCount: position.dcaCount }); }}>
    <header><div className="compact-symbol"><strong>{position.symbol}</strong><span className={`side-badge ${position.side.toLowerCase()}`}>{position.side.toUpperCase()}</span><span>Cross</span>{position.leverage > 0 && <span>{position.leverage}×</span>}</div><div className="compact-row-action"><span className="compact-status"><i/>Actief</span><TradeReportControl trade={{exchange,symbol:position.symbol,side:position.side,size:position.size,entry:position.entry,mark:position.mark,pnl:position.pnl,leverage:position.leverage,dcaCount:position.dcaCount,status:"active"}}/><PositionCloseControl symbol={position.symbol} exchange={exchange} onClosed={onChanged} /></div></header>
    <div className="compact-financial-grid">
      <dl><div><dt>Grootte</dt><dd>{formatUsd(position.size)}</dd></div><div><dt>Instapprijs</dt><dd>{formatPrice(position.entry)}</dd></div><div><dt>Instaptijd</dt><dd>{formatDateTime(position.openedAt)}</dd></div><div><dt>Strategie</dt><dd>{position.strategy || "—"}</dd></div><div><dt>DCA-status</dt><dd>{position.dcaCount}× bijgekocht</dd></div></dl>
      <dl><div className="compact-result"><dt>Open PnL <DataOrigin origin="direct" /></dt><dd>{formatSignedUsd(position.pnl)}</dd></div><div className="compact-result"><dt>Bruto PnL / positie <DataOrigin origin="calculated" /></dt><dd>{formatOptionalSignedPercent(resultPercent)}</dd></div><div><dt>Actuele prijs <DataOrigin origin="direct" /></dt><dd>{formatPrice(position.mark)}</dd></div></dl>
    </div>
    {isManagedStrategyPosition(position) && <StrategyTpPanel value={positionTp(position)} strategy={strategyTpLabel(position)} />}
  </article>;
}

function CompactClosedTradeRow({ trade, exchange, selected = false, positionId, onSelect }: { trade: ClosedTradeView; exchange: TradingExchange; selected?: boolean; positionId: string; onSelect?: (selection: TradeSelection) => void }) {
  const resultPercent = trade.size > 0 ? trade.pnl / trade.size * 100 : 0;
  const closedAt = formatDateTime(trade.closedAt);
  return <article className={`compact-position-row compact-closed-row ${trade.pnl >= 0 ? "positive" : "negative"} ${selected ? "selected-position" : ""}`} onClick={(event) => { if ((event.target as HTMLElement).closest("button")) return; onSelect?.({ id: positionId, symbol: trade.symbol, exchange, side: trade.side, exit: trade.exit, closedAt: trade.closedAt }); }}>
    <header><div className="compact-symbol"><strong>{trade.symbol}</strong>{trade.side && <span className={`side-badge ${trade.side.toLowerCase()}`}>{trade.side.toUpperCase()}</span>}</div><div className="compact-row-action"><TradeReportControl trade={{exchange,symbol:trade.symbol,side:trade.side,size:trade.size,entry:0,mark:trade.exit,pnl:trade.pnl,leverage:0,dcaCount:0,status:"closed"}}/><span className="compact-closed-badge">Gesloten</span></div></header>
    <div className="compact-financial-grid"><dl><div className="compact-result"><dt>Gerealiseerde PnL</dt><dd>{formatSignedUsd(trade.pnl)}</dd></div><div><dt>Maximaal aangehouden</dt><dd>{trade.size ? formatUsd(trade.size) : "—"}</dd></div><div><dt>Instapprijs</dt><dd>{formatPrice(trade.entry)}</dd></div><div><dt>Instaptijd</dt><dd>{formatDateTime(trade.openedAt)}</dd></div></dl><dl><div className="compact-result"><dt>Resultaat</dt><dd>{formatSignedPercent(resultPercent)}</dd></div><div><dt>Gemiddelde sluitprijs</dt><dd>{formatPrice(trade.exit)}</dd></div><div><dt>Uitstaptijd</dt><dd>{closedAt}</dd></div><div><dt>Strategie</dt><dd>{trade.strategy || "—"}</dd></div></dl></div>
  </article>;
}

function PositionRow({ position, exchange, onChanged, selected = false, onSelect }: { position: PositionView; exchange: TradingExchange; onChanged: () => void; selected?: boolean; onSelect?: (selection: TradeSelection) => void }) {
  const positive = position.pnl >= 0;
  const resultPercent = positionDisplayReturnPercent(position.pnl, position.size);
  const id = `${exchange}:active:${position.symbol}:${position.side}`;
  return <article className={`position-row premium-position-row ${positive ? "positive" : "negative"} ${selected ? "selected-position" : ""}`} onClick={(event) => { if ((event.target as HTMLElement).closest("button")) return; onSelect?.({ id, symbol: position.symbol, exchange, side: position.side, entry: position.entry, mark: position.mark, dcaCount: position.dcaCount }); }}>
    <header className="position-row-head">
      <div className="position-symbol"><span>{position.symbol}</span><small>{position.side.toUpperCase()}{position.leverage > 0 ? ` · ${position.leverage}×` : ""} · {position.dcaCount}× bijgekocht</small></div>
      <div className="position-head-actions"><TradeReportControl trade={{exchange,symbol:position.symbol,side:position.side,size:position.size,entry:position.entry,mark:position.mark,pnl:position.pnl,leverage:position.leverage,dcaCount:position.dcaCount,status:"active"}}/><span className="position-live-status"><i /> Position active</span></div>
    </header>
    <div className="position-financial-grid">
      <dl className="position-data position-data-left"><div><dt>Grootte</dt><dd>{formatUsd(position.size)}</dd></div><div><dt>Instap</dt><dd>{formatPrice(position.entry)}</dd></div></dl>
      <PositionResultMeter value={resultPercent} tp={positionTp(position)} managed={isManagedStrategyPosition(position)} strategy={strategyTpLabel(position)} />
      <dl className="position-data position-data-right"><div className="result-metric"><dt>Open PnL <DataOrigin origin="direct" /></dt><dd>{formatUsd(position.pnl)}</dd></div><div><dt>Actueel <DataOrigin origin="direct" /></dt><dd>{formatPrice(position.mark)}</dd></div></dl>
    </div>
    <footer className="position-row-foot"><div className="position-dca"><span>DCA-status</span><strong>{position.dcaCount}× bijgekocht</strong><small>Instap: {formatDateTime(position.openedAt)} · {position.strategy || "Strategie —"}</small></div><PositionCloseControl symbol={position.symbol} exchange={exchange} onClosed={onChanged} /></footer>
  </article>;
}

function ClosedTradeRow({ trade, exchange, selected = false, positionId, onSelect }: { trade: ClosedTradeView; exchange: TradingExchange; selected?: boolean; positionId: string; onSelect?: (selection: TradeSelection) => void }) {
  const resultPercent = trade.size > 0 ? trade.pnl / trade.size * 100 : 0;
  return <article className={`position-row premium-position-row closed-position-row ${trade.pnl >= 0 ? "positive" : "negative"} ${selected ? "selected-position" : ""}`} onClick={(event) => { if ((event.target as HTMLElement).closest("button")) return; onSelect?.({ id: positionId, symbol: trade.symbol, exchange, side: trade.side, exit: trade.exit, closedAt: trade.closedAt }); }}>
    <header className="position-row-head"><div className="position-symbol"><span>{trade.symbol}</span><small>{trade.side} · {new Date(trade.closedAt).toLocaleString("nl-NL")}</small></div><div className="position-head-actions"><TradeReportControl trade={{exchange,symbol:trade.symbol,side:trade.side,size:trade.size,entry:0,mark:trade.exit,pnl:trade.pnl,leverage:0,dcaCount:0,status:"closed"}}/><span className="position-live-status closed">Afgesloten</span></div></header>
    <div className="position-financial-grid">
      <dl className="position-data position-data-left"><div><dt>Gesloten bedrag</dt><dd>{formatUsd(trade.size)}</dd></div><div><dt>Sluitprijs</dt><dd>{formatPrice(trade.exit)}</dd></div></dl>
      <PositionResultMeter value={resultPercent} tp={null} managed={false} strategy="" />
      <dl className="position-data position-data-right"><div className="result-metric"><dt>Gerealiseerd</dt><dd>{formatUsd(trade.pnl)}</dd></div><div><dt>Resultaat</dt><dd>{formatSignedPercent(resultPercent)}</dd></div></dl>
    </div>
    <footer className="position-row-foot"><div className="position-dca"><span>Tradeverloop</span><strong>{formatDateTime(trade.openedAt)} → {formatDateTime(trade.closedAt)}</strong><small>{trade.strategy || "Strategie —"}</small></div></footer>
  </article>;
}

function PositionResultMeter({ value, tp, managed, strategy }: { value: number | null; tp: StrategyTpView | null; managed: boolean; strategy: string }) {
  const numericValue = value ?? 0;
  const bounded = Math.max(-20, Math.min(20, numericValue));
  const fill = Math.max(7, Math.abs(bounded) / 20 * 72);
  const meterStyle = { "--meter-fill": `${fill}%` } as CSSProperties;
  return <div className={`position-result-meter ${numericValue >= 0 ? "positive" : "negative"}`} style={meterStyle} aria-label={`Berekend bruto positie-resultaat ${formatOptionalSignedPercent(value)}`}>
    <div className="position-result-ring"><span>Bruto PnL / positie</span><strong>{formatOptionalSignedPercent(value)}</strong></div>
    <small><DataOrigin origin="calculated" /> Bruto resultaat; TP komt alleen uit serverbewijs</small>
    {managed && <StrategyTpPanel value={tp} strategy={strategy} />}
  </div>;
}

function isStrategy2Position(position: PositionView) {
  return position.strategy2Tp !== null || /Strategy\s*2/i.test(position.strategy);
}

function isManagedStrategyPosition(position: PositionView) { return isStrategy2Position(position); }
function positionTp(position: PositionView) { return position.strategy2Tp; }
function strategyTpLabel(_position: PositionView) { return "Strategy 2"; }

function StrategyTpPanel({ value, strategy }: { value: StrategyTpView | null; strategy: string }) {
  if (!value) return <section className="strategy2-tp-panel unknown" aria-label={`${strategy} netto TP: Niet betrouwbaar te bepalen`}><strong>Niet betrouwbaar te bepalen</strong><span>De server heeft geen volledig, bewezen netto TP-contract geleverd.</span></section>;
  const tone = value.status === "TP bereikt" ? "reached" : value.status === "TP nog niet bereikt" ? "pending" : "unknown";
  const net = value.netProfitUsd === null ? "—" : formatSignedUsd(value.netProfitUsd);
  const progress = value.progressPercent === null ? "—" : `${value.progressPercent.toFixed(1)}%`;
  const assessed = value.evaluatedAt ? formatDateTime(value.evaluatedAt) : "Geen betrouwbare beoordeling";
  const target = value.takeProfitTargetUsd === null || value.takeProfitPercent === null ? "—" : `${formatUsd(value.takeProfitTargetUsd)} (${value.takeProfitPercent.toFixed(2)}%)`;
  return <section className={`strategy2-tp-panel ${tone}`} aria-label={`${strategy} netto TP: ${value.status}`}>
    <strong>{value.status}</strong>
    <span>Netto {net} · doel {target} · voortgang {progress}</span>
    <small>Fees {value.paidFeesUsd === null ? "—" : formatUsd(value.paidFeesUsd)} · funding {value.fundingUsd === null ? "—" : formatSignedUsd(value.fundingUsd)} · geschatte sluitfee {value.estimatedCloseFeeUsd === null ? "—" : formatUsd(value.estimatedCloseFeeUsd)}</small>
    <small>Fase {value.phase || "—"} · beslissing {value.decision || "HOLD"} · protection {value.protection.active ? value.protection.role : "niet actief"} · trailing {value.trailing.active ? "actief" : value.trailing.enabled ? "stand-by" : "uit"}</small>
    <small>Laatste serverbeoordeling: {assessed}</small>
    {value.blockReason && <small className="strategy2-tp-block">Reden: {value.blockReason}</small>}
    {value.scheduler.warning && <small className="strategy2-tp-warning">Waarschuwing: {value.scheduler.warning}</small>}
  </section>;
}

function DataOrigin({ origin }: { origin: "direct" | "calculated" | "aggregate" }) {
  const label = origin === "direct" ? "Aster" : origin === "aggregate" ? "Som Aster" : "Berekend";
  const title = origin === "direct"
    ? "Deze waarde komt rechtstreeks uit de actuele Aster API-snapshot."
    : origin === "aggregate"
      ? "Deze waarde is uitsluitend samengesteld uit officiële Aster-velden."
      : `TradeMentor-berekening: ${ASTER_FINANCIAL_DATA_CONTRACT.positionDisplayReturn.formula}. Netto TP wordt uitsluitend uit afzonderlijk serverbewijs getoond.`;
  return <abbr className={`data-origin ${origin}`} title={title}>{label}</abbr>;
}
function sortPositions(values: PositionView[], filter: string): PositionView[] {
  let rows = [...values];
  if (filter === "long" || filter === "short") rows = rows.filter((row) => row.side.toLowerCase() === filter);
  else if (filter === "smallest") rows.sort((a, b) => a.size - b.size);
  else if (filter === "dca") rows.sort((a, b) => b.dcaCount - a.dcaCount || b.size - a.size);
  else if (filter === "latest") rows.sort((a, b) => b.lastOrderAt - a.lastOrderAt || b.size - a.size);
  else if (filter === "profit") rows.sort((a, b) => b.pnl - a.pnl);
  else if (filter === "loss") rows.sort((a, b) => a.pnl - b.pnl);
  else if (filter === "leverage") rows.sort((a, b) => b.leverage - a.leverage);
  else if (filter === "alphabetical") rows.sort((a, b) => a.symbol.localeCompare(b.symbol));
  else rows.sort((a, b) => b.size - a.size);
  return filter === "top10" ? rows.slice(0, 10) : rows;
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function asNumber(value: unknown): number {
  const result = typeof value === "number" ? value : Number(value);
  return Number.isFinite(result) ? result : 0;
}

function parseStrategyTp(value: unknown): StrategyTpView | null {
  const row=asRecord(value);const status=String(row.status??"");
  if (!(["TP bereikt","TP nog niet bereikt","Niet betrouwbaar te bepalen"] as string[]).includes(status)) return null;
  const scheduler=asRecord(row.scheduler);
  const protection=asRecord(row.protection);const trailing=asRecord(row.trailing);
  return {netProfitUsd:optionalFinancialNumber(row.netProfitUsd),takeProfitTargetUsd:optionalFinancialNumber(row.takeProfitTargetUsd),
    takeProfitPercent:optionalFinancialNumber(row.takeProfitPercent),progressPercent:optionalFinancialNumber(row.progressPercent),
    status:status as StrategyTpView["status"],evaluatedAt:row.evaluatedAt?String(row.evaluatedAt):null,
    blockReason:String(row.blockReason??""),paidFeesUsd:optionalFinancialNumber(row.paidFeesUsd),
    fundingUsd:optionalFinancialNumber(row.fundingUsd),estimatedCloseFeeUsd:optionalFinancialNumber(row.estimatedCloseFeeUsd),
    ownershipProven:row.ownershipProven===true,decision:String(row.decision??"HOLD"),phase:String(row.phase??""),
    protection:{role:protection.role?String(protection.role):null,active:protection.active===true},
    trailing:{enabled:trailing.enabled===true,active:trailing.active===true,peakReturnPercent:optionalFinancialNumber(trailing.peakReturnPercent)},
    scheduler:{status:String(scheduler.status??"STALE"),lastTickAt:scheduler.lastTickAt,
      ageSeconds:optionalFinancialNumber(scheduler.ageSeconds),warning:String(scheduler.warning??"")}};
}

function parseStrategy2Tp(value: unknown): StrategyTpView | null { return parseStrategyTp(value); }

function asTimestamp(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value < 10_000_000_000 ? value * 1000 : value;
  if (typeof value === "string") { const numeric=Number(value); if(Number.isFinite(numeric)&&numeric>0)return numeric<10_000_000_000?numeric*1000:numeric; const parsed=Date.parse(value); return Number.isFinite(parsed)?parsed:0; }
  if (value && typeof value === "object") { const row=asRecord(value); return asNumber(row.seconds)*1000+Math.floor(asNumber(row.nanoseconds)/1_000_000); }
  return 0;
}

function formatDateTime(value: unknown): string {
  const timestamp = asTimestamp(value);
  return timestamp > 0 ? new Date(timestamp).toLocaleString("nl-NL", { dateStyle: "short", timeStyle: "medium" }) : "—";
}

function formatUsd(value: number): string {
  return new Intl.NumberFormat("nl-NL", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
}

function formatSignedPercent(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${new Intl.NumberFormat("nl-NL", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value)}%`;
}

function formatOptionalSignedPercent(value: number | null): string {
  return value === null ? "—" : formatSignedPercent(value);
}
function formatSignedUsd(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatUsd(value)}`;
}

function formatPrice(value: number): string {
  if (!value) return "—";
  return new Intl.NumberFormat("nl-NL", { minimumFractionDigits: value < 1 ? 4 : 2, maximumFractionDigits: value < 1 ? 6 : 2 }).format(value);
}

function exchangeView(exchange: TradingExchange, snapshot: ExchangeSnapshot) {
  const data = snapshot.data ?? {};
  const asterAccountDisplay = exchange === "aster" ? deriveAsterAccountDisplay({ data: snapshot.data, serverConfirmed: snapshot.serverConfirmed, error: snapshot.error, updatedAt: snapshot.updatedAt }) : null;
  let equity = 0;
  let available = 0;
  let openPnl = 0;
  let activeCount = 0;
  let positions: PositionView[] = [];
  let closedTrades: ClosedTradeView[] = [];
  let connected = Boolean(snapshot.data) && !snapshot.error;
  let accountDataAvailable = connected;
  let tradingEnabled = false;
  let riskLabel = "MARGIN RATIO";
  let riskNumber: number | null = null;

  if (exchange === "hyperliquid") {
    equity = asNumber(data.portfolioValue);
    available = asNumber(data.availableToTrade);
    const dealMeta = new Map((Array.isArray(data.deals) ? data.deals : []).map((row) => { const item = asRecord(row); return [String(item.symbol ?? "").toUpperCase(), {dcaCount:asNumber(item.safetyOrdersCompleted),lastOrderAt:asTimestamp(item.lastOrderAt??item.updatedAt??item.createdAt)}]; }));
    positions = (Array.isArray(data.assetPositions) ? data.assetPositions : []).map((row) => asRecord(asRecord(row).position)).filter((row) => Math.abs(asNumber(row.szi)) > 0).map((row) => {
      const size = asNumber(row.szi);
      const symbol = String(row.coin ?? "—");
      const metadata=dealMeta.get(symbol.toUpperCase());
      return { symbol, side: size >= 0 ? "long" : "short", size: Math.abs(asNumber(row.positionValue) || size * asNumber(row.entryPx)), entry: asNumber(row.entryPx), mark: asNumber(row.markPx), liquidationPrice: 0, pnl: asNumber(row.unrealizedPnl), leverage: asNumber(asRecord(row.leverage).value), dcaCount: metadata?.dcaCount ?? 0, lastOrderAt:metadata?.lastOrderAt ?? asTimestamp(row.openedAt), openedAt: asTimestamp(row.openedAt), strategy: String(row.strategyName ?? row.strategyId ?? ""), strategy2Tp:null };
    });
    openPnl = asNumber(data.unrealizedPnl);
    activeCount = asNumber(data.activePositionCount);
    tradingEnabled = Boolean(data.tradingEnabled);
    const maintenance = asNumber(data.maintenanceMargin);
    riskLabel = "MAINTENANCE";
    riskNumber = equity > 0 ? maintenance / equity * 100 : null;
  } else {
    const configured = data.configured === true;
    const walletRecognized = data.walletRecognized === true;
    connected = connected && (configured || walletRecognized);
    accountDataAvailable = connected && configured;
    equity = asterAccountDisplay?.equityNumber ?? asNumber(data.equity);
    available = asterAccountDisplay?.availableNumber ?? asNumber(data.availableBalance);
    openPnl = asNumber(data.unrealizedPnl);
    positions = (Array.isArray(data.positions) ? data.positions : []).map((row) => asRecord(row)).map((row) => ({
      symbol: String(row.symbol ?? "—"),
      side: String(row.side ?? "—").toLowerCase(),
      size: asNumber(row.notionalUsd),
      entry: asNumber(row.entryPrice),
      mark: asNumber(row.markPrice),
      liquidationPrice: asNumber(row.liquidationPrice),
      pnl: asNumber(row.unrealizedPnl),
      leverage: asNumber(row.leverage),
      dcaCount: asNumber(row.dcaCount),
      lastOrderAt: asTimestamp(row.lastOrderAt ?? row.updatedAt ?? row.openedAt),
      openedAt: asTimestamp(row.openedAt),
      strategy: String(row.strategyName ?? row.strategyId ?? ""),
      strategy2Tp: parseStrategy2Tp(row.strategy2Tp),
    }));
    activeCount = asNumber(data.activePositions);
    tradingEnabled = Boolean(data.liveEnabled);
    riskLabel = "MAINTENANCE MARGIN";
    riskNumber = accountDataAvailable ? (asterAccountDisplay?.maintenanceMarginPercent ?? null) : null;
  }
  closedTrades = (Array.isArray(data.closedTrades) ? data.closedTrades : []).map((raw) => asRecord(raw)).map((row) => ({ symbol: String(row.symbol ?? "—"), side: String(row.side ?? "—"), size: asNumber(row.notionalUsd), entry: asNumber(row.entryPrice), exit: asNumber(row.exitPrice), pnl: asNumber(row.realizedPnlUsd), openedAt: String(row.openedAt ?? ""), closedAt: String(row.closedAt ?? ""), strategy: String(row.strategyName ?? row.strategyId ?? ""), dcaCount: asNumber(row.dcaCount) }));

  const reportedTradeCapital = optionalFinancialNumber(data.activeTradeCapital)
    ?? (exchange === "hyperliquid" ? optionalFinancialNumber(data.totalMarginUsed) : null);
  const derivedTradeCapital = positions.reduce((total, position) => total + (position.leverage > 0 ? Math.abs(position.size) / position.leverage : 0), 0);
  const activeTradeCapital = exchange === "aster" ? reportedTradeCapital : reportedTradeCapital ?? derivedTradeCapital;
  const readOnlyRecognized = exchange === "aster" && data.walletRecognized === true && data.configured !== true;
  const statusText = snapshot.loading && !snapshot.data ? "Gegevens laden" : snapshot.error ? "Controle nodig" : readOnlyRecognized ? "Wallet herkend · alleen-lezen" : connected ? "Exchange verbonden" : "Niet gekoppeld";
  const metricDetail = snapshot.error || (snapshot.loading ? (snapshot.source === "cache" ? "Laatste bekende waarde · actuele data wordt opgehaald" : "Exchange wordt vernieuwd") : snapshot.source === "cache" ? "Laatste bekende waarde · actuele data wordt opgehaald" : readOnlyRecognized ? "Trading en automatische orders staan uit" : connected ? "Actuele exchange-snapshot" : "Nog niet gekoppeld");
  return {
    connected,
    accountDataAvailable,
    tradingEnabled,
    statusText,
    metricDetail,
    equity: exchange === "aster" ? (asterAccountDisplay?.equity ?? "—") : accountDataAvailable ? formatUsd(equity) : "—",
    equityNumber: exchange === "aster" ? (asterAccountDisplay?.equityNumber ?? null) : accountDataAvailable ? equity : null,
    available: exchange === "aster" ? (asterAccountDisplay?.available ?? "—") : accountDataAvailable ? formatUsd(available) : "—",
    openPnl: accountDataAvailable ? formatUsd(openPnl) : "—",
    activeTradeCapital: accountDataAvailable && activeTradeCapital !== null ? formatUsd(activeTradeCapital) : "\u2014",
    activeCount,
    positions,
    closedTrades,
    riskLabel,
    riskTone: riskNumber === null ? "unknown" : riskNumber < 30 ? "safe" : riskNumber < 50 ? "caution" : riskNumber < 70 ? "high" : "critical",
    riskValue: riskNumber === null ? "—" : `${riskNumber.toFixed(2)}%`,
    riskDetail: riskNumber === null ? "Nog geen betrouwbare waarde" : exchange === "aster" ? (asterAccountDisplay?.maintenanceDetail ?? "Gewogen Aster maintenance-rate") : "Rechtstreeks uit account- en positiedata",
    asterAccountDisplay,
    maintenanceMargin: (exchange === "hyperliquid" || exchange === "aster") && accountDataAvailable ? formatUsd(asNumber(data.maintenanceMargin)) : "—",
    accountLeverage: exchange === "hyperliquid" && connected ? `${asNumber(data.unifiedAccountLeverage).toFixed(2)}×` : "—",
  };
}

function Brand({ compact = false }: { compact?: boolean }) {
  return <div className={`brand ${compact ? "compact" : ""}`}><span className="brand-mark"><img src="/tradementor-logo.png?v=redgreen-1" alt="TradeMentor rood-groen logo" /></span><div><strong>TRADEMENTOR</strong><small>PORTFOLIO INTELLIGENCE</small></div></div>;
}

function NavButton({ item, active, onClick }: { item: { id: Destination; label: string; glyph: string }; active: boolean; onClick: () => void }) {
  return <button className={`nav-button ${active ? "active" : ""}`} data-destination={item.id} type="button" aria-pressed={active} onClick={onClick}><span>{item.glyph}</span><small>{item.label}</small></button>;
}

function LiquidationRiskOrbit({ display }: { display: AsterAccountDisplay | null }) {
  const tone = display?.liquidationTone ?? "unknown";
  const available = display?.liquidationRiskPercent !== null && display?.liquidationRiskPercent !== undefined;
  const health = tone === "safe" ? "VEILIG" : tone === "caution" ? "VERHOOGD" : tone === "high" ? "HOOG" : tone === "critical" ? "KRITIEK" : "GEEN DATA";
  return <div className={`risk-orbit liquidation-risk risk-${tone}`} aria-label={`LIQUIDATIERISICO ${display?.liquidationValue ?? "onbekend"}`} title={display?.liquidationDetail ?? "Geen bevestigde cross-account liquidatieratio"}><div className="orbit-lines" /><div className="risk-core"><span>LIQUIDATIERISICO</span><strong className={available ? "" : "unavailable"}>{display?.liquidationValue ?? "—"}</strong><small>{health}</small></div></div>;
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <article className="metric"><span>{label}</span><strong>{value}</strong><small>{detail}</small></article>;
}


type IndexPoint={t:number;v:number};
type IndexRow={symbol:string;side:string;returnPct:number;weight:number;contribution:number;pnl:number;dcaCount:number};

function ActiveTradesIndex({positions,equity,availableToTrade,openPnl}:{positions:PositionView[];equity:string;availableToTrade:string;openPnl:number}){
  const [open,setOpen]=useState(false),[range,setRange]=useState("24u"),[series,setSeries]=useState<IndexPoint[]>([]);
  const lastSample=useRef(0);
  const rows=useMemo<IndexRow[]>(()=>{
    const prepared=positions.filter(p=>p.entry>0&&p.mark>0&&p.size>0).map(p=>{
      const direction=p.side.toLowerCase()==="short"?-1:1;
      const returnPct=((p.mark/p.entry)-1)*direction*100;
      const margin=p.leverage>0?p.size/p.leverage:p.size;
      return {symbol:p.symbol,side:p.side,returnPct,weight:Math.max(.000001,margin),contribution:0,pnl:p.pnl,dcaCount:p.dcaCount};
    });
    const total=prepared.reduce((a,b)=>a+b.weight,0)||1;
    return prepared.map(r=>({...r,weight:r.weight/total,contribution:r.returnPct*(r.weight/total)}));
  },[positions]);
  const weightedReturn=rows.reduce((a,b)=>a+b.contribution,0);
  const indexValue=100+weightedReturn;
  useEffect(()=>{
    if(!rows.length||!Number.isFinite(indexValue))return;
    const now=Date.now();
    if(now-lastSample.current<8000)return;
    lastSample.current=now;
    setSeries(prev=>[...prev.filter(x=>now-x.t<7*86400000),{t:now,v:indexValue}].slice(-1200));
  },[indexValue,rows.length]);
  useEffect(()=>{if(!open)return;const prev=document.body.style.overflow;document.body.style.overflow="hidden";const esc=(e:KeyboardEvent)=>{if(e.key==="Escape")setOpen(false)};window.addEventListener("keydown",esc);return()=>{document.body.style.overflow=prev;window.removeEventListener("keydown",esc)}},[open]);
  const rangeMs:Record<string,number>={"15m":900000,"1u":3600000,"4u":14400000,"12u":43200000,"24u":86400000,"7d":604800000};
  const filtered=series.filter(x=>Date.now()-x.t<rangeMs[range]);
  const chart=filtered.length>1?filtered:[{t:Date.now()-60000,v:100},{t:Date.now(),v:indexValue}];
  const values=chart.map(x=>x.v),lo=Math.min(...values,99.5),hi=Math.max(...values,100.5),span=Math.max(.1,hi-lo);
  const points=chart.map((x,i)=>`${(i/Math.max(1,chart.length-1))*100},${44-((x.v-lo)/span)*40}`).join(" ");
  const totalDca=rows.reduce((a,b)=>a+b.dcaCount,0),winners=rows.filter(x=>x.returnPct>0).length,losers=rows.filter(x=>x.returnPct<0).length;
  const longs=rows.filter(x=>x.side.toLowerCase()==="long").length,shorts=rows.filter(x=>x.side.toLowerCase()==="short").length;
  const breadth=rows.length?winners/rows.length*100:0,activeCapital=positions.reduce((a,p)=>a+(p.leverage>0?p.size/p.leverage:0),0);
  const top=[...rows].sort((a,b)=>b.contribution-a.contribution).slice(0,5),bottom=[...rows].sort((a,b)=>a.contribution-b.contribution).slice(0,5);
  const change=chart.length>1?indexValue-chart[0].v:weightedReturn;
  const tone=indexValue>=100?"positive":"negative";
  return <>
    <button type="button" className={`active-trades-index ${tone}`} onClick={()=>setOpen(true)} aria-label="Open Actieve Trades Index fullscreen">
      <span className="ati-head"><b>ACTIEVE TRADES INDEX</b><i>↗</i></span>
      <strong>{rows.length?indexValue.toFixed(2):"—"}</strong>
      <em>{rows.length?`${change>=0?"+":""}${change.toFixed(2)}% · live`:`Geen actieve trades`}</em>
      <svg viewBox="0 0 100 46" preserveAspectRatio="none" aria-hidden="true"><polyline points={points}/></svg>
      <small>{rows.length} posities · {longs}L/{shorts}S · {totalDca} DCA</small>
    </button>
    {open&&<div className="ati-modal" role="dialog" aria-modal="true" aria-label="Actieve Trades Index fullscreen">
      <section>
        <header><div><span>ACTIEVE TRADES INDEX</span><h2>{indexValue.toFixed(2)} <small className={tone}>{weightedReturn>=0?"+":""}{weightedReturn.toFixed(2)}%</small></h2><p>Gewogen op werkelijke margin per actieve positie. LONG omhoog en SHORT omlaag tellen positief.</p></div><button type="button" onClick={()=>setOpen(false)}>×</button></header>
        <div className="ati-chart"><svg viewBox="0 0 100 46" preserveAspectRatio="none"><line x1="0" x2="100" y1="23" y2="23"/><polyline points={points}/></svg><div className="ati-ranges">{Object.keys(rangeMs).map(r=><button key={r} className={range===r?"active":""} onClick={()=>setRange(r)}>{r}</button>)}</div><small>{filtered.length<2?"Geschiedenis wordt vanaf gebruik van deze functie opgebouwd; de actuele index is wel volledig berekend.":`${filtered.length} indexmetingen in deze periode`}</small></div>
        <div className="ati-kpis">
          <div><span>PORTFOLIOWAARDE</span><b>{equity}</b></div><div><span>AVAILABLE</span><b>{availableToTrade}</b></div><div><span>ACTIEVE POSITIES</span><b>{rows.length}</b></div>
          <div><span>LONG / SHORT</span><b>{longs} / {shorts}</b></div><div><span>ACTIVE TRADE CAPITAL</span><b>{formatUsd(activeCapital)}</b></div><div><span>NETTO OPEN PNL</span><b className={openPnl>=0?"positive":"negative"}>{formatSignedUsd(openPnl)}</b></div>
          <div><span>TOTAAL DCA</span><b>{totalDca}</b></div><div><span>GEM. DCA / POSITIE</span><b>{rows.length?(totalDca/rows.length).toFixed(2):"0.00"}</b></div><div><span>BREADTH</span><b>{breadth.toFixed(1)}%</b></div>
          <div><span>WINNAARS</span><b className="positive">{winners}</b></div><div><span>VERLIEZERS</span><b className="negative">{losers}</b></div><div><span>GEM. OPEN PNL</span><b>{rows.length?formatSignedUsd(openPnl/rows.length):formatUsd(0)}</b></div>
        </div>
        <div className="ati-contributors"><ContributorList title="TOP POSITIEVE BIJDRAGERS" rows={top}/><ContributorList title="TOP NEGATIEVE BIJDRAGERS" rows={bottom}/></div>
      </section>
    </div>}
  </>;
}

function ContributorList({title,rows}:{title:string;rows:IndexRow[]}){return <article><h3>{title}</h3>{rows.map((r,i)=><div key={`${title}-${r.symbol}-${r.side}`}><span>{i+1}. {r.symbol} <small>{r.side.toUpperCase()}</small></span><b className={r.contribution>=0?"positive":"negative"}>{r.contribution>=0?"+":""}{r.contribution.toFixed(3)}</b><em>{r.returnPct>=0?"+":""}{r.returnPct.toFixed(2)}%</em></div>)}</article>}

function TodayRealizedMetric({ trades, available, onChanged, positions, equity, availableToTrade, openPnl }: { trades: ClosedTradeView[]; available: boolean; onChanged:()=>void; positions:PositionView[]; equity:string; availableToTrade:string; openPnl:number }) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    let timer = 0;
    const scheduleNextDay = () => {
      window.clearTimeout(timer);
      const current = new Date();
      const nextDay = new Date(current);
      nextDay.setHours(24, 0, 0, 50);
      timer = window.setTimeout(() => { setNow(new Date()); scheduleNextDay(); }, Math.max(1000, nextDay.getTime() - Date.now()));
    };
    const refreshAfterResume = () => {
      if (document.visibilityState === "visible") { setNow(new Date()); scheduleNextDay(); }
    };
    scheduleNextDay();
    document.addEventListener("visibilitychange", refreshAfterResume);
    return () => { window.clearTimeout(timer); document.removeEventListener("visibilitychange", refreshAfterResume); };
  }, []);
  const { today } = realizedCalendar(trades.map((trade) => ({ closedAt: trade.closedAt, realizedPnlUsd: trade.pnl })), now);
  return <>
    <article className={`metric realized-today ${available && today.total > 0 ? "positive" : available && today.total < 0 ? "negative" : ""}`}><span>GESLOTEN RESULTAAT VANDAAG</span><strong className="realized-amount">{available ? formatSignedUsd(today.total) : "—"}</strong><small>{available ? "Lokale dag 00:00–23:59" : "Aster-geschiedenis tijdelijk niet bevestigd"}</small></article>
    <PortfolioGrowthCard onChanged={onChanged} />
    <article className="metric realized-trades"><div className="realized-trades-count"><span>TRADES GESLOTEN</span><strong>{available ? today.trades : "—"}</strong><small>{available ? "Vandaag bevestigd door Aster" : "Aster-geschiedenis tijdelijk niet bevestigd"}</small></div><ActiveTradesIndex positions={positions} equity={equity} availableToTrade={availableToTrade} openPnl={openPnl}/></article>
  </>;
}

function SettingToggle({ label, description, checked, onChange }: { label: string; description: string; checked: boolean; onChange: (value: boolean) => void }) {
  return <label className="setting-row"><span><strong>{label}</strong><small>{description}</small></span><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} /><i aria-hidden="true" /></label>;
}

function PlanCard({ name, price, description, features, action, active = false }: { name: string; price: string; description: string; features: string[]; action: string; active?: boolean }) {
  return <article className={`plan-card ${active ? "active" : "premium"}`}><span className="kicker">{active ? "BASIS" : "VOLLEDIG"}</span><h3>{name}</h3><strong className="plan-price">{price}</strong><p>{description}</p><ul>{features.map((feature) => <li key={feature}>{feature}</li>)}</ul><button type="button" disabled>{action}</button></article>;
}
